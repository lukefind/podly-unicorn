"""Outbound URL policy tests use fake DNS and sockets; no network is contacted."""

import io
import socket
from collections import namedtuple
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from flask import Flask

from app.feeds import fetch_feed, refresh_feed
from app.models import Feed, Post
from app.routes.feed_routes import feed_bp
from podcast_processor.podcast_downloader import DownloadError, PodcastDownloader


class FakeSocket:
    def __init__(self, network, family):
        self.network = network
        self.family = family
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def gettimeout(self):
        return self.timeout

    def setsockopt(self, *_args):
        pass

    def connect(self, address):
        self.network.connected.append(address)

    def sendall(self, data):
        self.network.sent.append(data)

    def makefile(self, *_args, **_kwargs):
        return io.BytesIO(self.network.responses.pop(0))

    def close(self):
        self.closed = True


@pytest.fixture
def network(monkeypatch):
    net = SimpleNamespace(
        answers=["93.184.216.34"],
        connected=[],
        sent=[],
        queries=[],
        sockets=[],
        responses=[
            b"HTTP/1.1 200 OK\r\nContent-Length: 31\r\n\r\n<rss><channel /></rss>          "
        ],
    )

    def resolve(host, port, *_args, **_kwargs):
        net.queries.append((host, port))
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (ip, port, 0, 0) if ":" in ip else (ip, port),
            )
            for ip in net.answers
        ]

    def make_socket(family, *_args, **_kwargs):
        sock = FakeSocket(net, family)
        net.sockets.append(sock)
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", make_socket)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    return net


def test_feed_fetch_rejects_private_dns_before_connect(network):
    network.answers = ["127.0.0.1"]
    with pytest.raises(requests.RequestException, match="public HTTP"):
        fetch_feed("http://podcast.example/rss")
    assert network.connected == []


def test_feed_refresh_rechecks_stored_url(network, app):
    network.answers = ["169.254.169.254"]
    with app.app_context():
        feed = Feed(rss_url="http://old-podcast.example/rss", title="Example")
        with pytest.raises(requests.RequestException, match="public HTTP"):
            refresh_feed(feed)
    assert network.connected == []


def test_enclosure_download_rejects_private_dns_and_removes_partial(network, tmp_path):
    network.answers = ["10.0.0.1"]
    destination = tmp_path / "episode.mp3"
    post = Post(
        id=1,
        guid="episode",
        title="Episode",
        download_url="http://podcast.example/audio.mp3",
    )
    with pytest.raises(DownloadError, match="public HTTP"):
        PodcastDownloader().download_episode(post, str(destination))
    assert network.connected == []
    assert not destination.exists()
    assert not destination.with_suffix(".mp3.part").exists()


def test_add_feed_returns_400_for_unsafe_destination_without_leaking_credentials(
    network,
):
    app = Flask(__name__)
    app.register_blueprint(feed_bp)
    with app.test_client() as client:
        response = client.post(
            "/feed",
            data={"url": "http://user:secret@127.0.0.1/rss"},
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 400
    assert "secret" not in response.get_data(as_text=True)
    assert network.connected == []


@pytest.fixture
def public_get():
    from shared.http_client import public_get

    return public_get


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://podcast.example/file",
        "gopher://podcast.example/",
        "http://user:secret@podcast.example/rss",
        "http://podcast.example:invalid/rss",
        "http://127.0.0.1/rss",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.0.1/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://100.64.0.1/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[ff02::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://[::]/",
        "http://2130706433/",
        "http://0177.0.0.1/",
        "http://127.1/",
        "http://0x7f000001/",
        "http://0x7f.0.0.1/",
        "http://127.0.0.1./",
        "http://podcast.example\\@127.0.0.1/",
        "http://podcast.example%00/",
        "http://podcast.example/\n",
        "http://[fe80::1%25eth0]/",
    ],
)
def test_rejects_unsafe_urls_without_network(url, public_get, network):
    with pytest.raises(requests.RequestException, match="public HTTP"):
        with public_get(url):
            pytest.fail("unsafe URL accepted")
    assert network.connected == []
    assert network.queries == []


@pytest.mark.parametrize(
    "answers",
    [
        ["10.1.2.3"],
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["100.64.0.1"],
        ["::1"],
        ["fc00::1"],
        ["fe80::1"],
        ["ff02::1"],
        ["::ffff:192.168.1.1"],
        ["93.184.216.34", "127.0.0.1"],
        ["2606:4700:4700::1111", "fc00::1"],
        [],
    ],
)
def test_rejects_any_non_public_dns_answer(answers, public_get, network):
    network.answers = answers
    with pytest.raises(requests.RequestException, match="public HTTP"):
        with public_get("http://podcast.example/rss"):
            pytest.fail("unsafe DNS accepted")
    assert network.connected == []


def test_connect_uses_only_validated_dns_result(public_get, network, monkeypatch):
    original_resolver = socket.getaddrinfo

    def rebound_dns(*args, **kwargs):
        result = original_resolver(*args, **kwargs)
        network.answers = ["127.0.0.1"]
        return result

    monkeypatch.setattr(socket, "getaddrinfo", rebound_dns)
    with public_get("http://podcast.example/rss", timeout=(10, 30)) as response:
        assert response.status_code == 200
        assert response.content.startswith(b"<rss>")
        assert network.connected == [("93.184.216.34", 80)]
        assert len(network.queries) == 1
        assert not network.sockets[0].closed
    assert all(sock.closed for sock in network.sockets)
    assert b"Host: podcast.example" in network.sent[0]


def test_https_keeps_hostname_for_tls_verification(public_get, network, monkeypatch):
    tls_calls = []

    def fake_tls(**kwargs):
        tls_calls.append(kwargs)
        wrapped_socket = namedtuple("WrappedSocket", ["socket", "is_verified"])
        return wrapped_socket(socket=kwargs["sock"], is_verified=True)

    monkeypatch.setattr(
        "urllib3.connection._ssl_wrap_socket_and_match_hostname", fake_tls
    )
    with public_get("https://podcast.example/rss") as response:
        assert response.status_code == 200
    assert network.connected == [("93.184.216.34", 443)]
    assert tls_calls[0]["server_hostname"] == "podcast.example"
    assert tls_calls[0]["cert_reqs"] == "CERT_REQUIRED"
    assert tls_calls[0]["assert_hostname"] is None
    assert b"Host: podcast.example" in network.sent[0]


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/secret",
        "http://[::1]/",
        "file:///etc/passwd",
        "http://user:secret@podcast.example/",
    ],
)
def test_redirect_target_is_validated(location, public_get, network):
    network.responses = [
        f"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nLocation: {location}\r\n\r\n".encode()
    ]
    with pytest.raises(requests.RequestException, match="public HTTP"):
        with public_get("http://podcast.example/rss"):
            pytest.fail("unsafe redirect accepted")
    assert len(network.connected) == 1
    assert all(sock.closed for sock in network.sockets)


def test_redirect_revalidates_dns_even_for_same_host(public_get, network, monkeypatch):
    original_resolver = socket.getaddrinfo

    def rebound_dns(*args, **kwargs):
        result = original_resolver(*args, **kwargs)
        network.answers = ["10.0.0.1"]
        return result

    monkeypatch.setattr(socket, "getaddrinfo", rebound_dns)
    network.responses = [
        b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nConnection: close\r\nLocation: /second\r\n\r\n"
    ]
    with pytest.raises(requests.RequestException, match="public HTTP"):
        with public_get("http://podcast.example/rss"):
            pytest.fail("rebound redirect accepted")
    assert network.connected == [("93.184.216.34", 80)]


def test_relative_redirect_and_redirect_limit(public_get, network):
    redirect = b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nConnection: close\r\nLocation: /next\r\n\r\n"
    network.responses = [redirect] * 8
    with pytest.raises(requests.TooManyRedirects):
        with public_get("http://podcast.example/rss", max_redirects=3):
            pytest.fail("redirect limit ignored")
    assert len(network.connected) == 4
    assert all(sock.closed for sock in network.sockets)


def test_default_limit_allows_long_public_podcast_tracking_chains(public_get, network):
    redirect = b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nConnection: close\r\nLocation: /next\r\n\r\n"
    final_response = network.responses[0]
    network.responses = [redirect] * 6 + [final_response]

    with public_get("http://podcast.example/audio", stream=True) as response:
        assert response.status_code == 200
        assert response.content.startswith(b"<rss>")

    assert len(network.connected) == 7
    assert all(sock.closed for sock in network.sockets)


def test_long_tracking_chain_still_rejects_private_redirects(public_get, network):
    redirect = b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nConnection: close\r\nLocation: /next\r\n\r\n"
    private_redirect = b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nConnection: close\r\nLocation: http://127.0.0.1/private\r\n\r\n"
    network.responses = [redirect] * 6 + [private_redirect]

    with pytest.raises(requests.RequestException, match="public HTTP"):
        with public_get("http://podcast.example/audio"):
            pytest.fail("private destination after tracking chain accepted")

    assert len(network.connected) == 7
    assert all(address[0] == "93.184.216.34" for address in network.connected)
    assert all(sock.closed for sock in network.sockets)


def test_default_redirect_limit_matches_requests_and_remains_bounded(
    public_get, network
):
    redirect = b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nConnection: close\r\nLocation: /next\r\n\r\n"
    network.responses = [redirect] * 31

    with pytest.raises(requests.TooManyRedirects):
        with public_get("http://podcast.example/audio"):
            pytest.fail("default redirect limit ignored")

    assert len(network.connected) == 31
    assert all(sock.closed for sock in network.sockets)


def test_environment_proxy_is_ignored(public_get, network, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret@127.0.0.1:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8080")
    with public_get("http://podcast.example/rss") as response:
        assert response.status_code == 200
    assert network.queries == [("podcast.example", 80)]
    assert network.connected == [("93.184.216.34", 80)]


def test_stream_keeps_socket_open_until_context_closes(public_get, network):
    with public_get("http://podcast.example/audio", stream=True) as response:
        assert not network.sockets[0].closed
        assert next(response.iter_content(chunk_size=4)) == b"<rss"
    assert all(sock.closed for sock in network.sockets)


def test_response_closes_when_consumer_raises(public_get, network):
    with pytest.raises(ValueError, match="consumer"):
        with public_get("http://podcast.example/audio", stream=True):
            raise ValueError("consumer")
    assert all(sock.closed for sock in network.sockets)


@pytest.mark.parametrize("url", ["http://[4000::1]/", "http://[64:ff9b::7f00:1]/"])
def test_rejects_reserved_and_private_ipv4_translation(url, public_get, network):
    with pytest.raises(requests.RequestException, match="public HTTP"):
        with public_get(url):
            pytest.fail("reserved or translated private destination accepted")
    assert network.connected == []


@pytest.mark.parametrize("ip", ["8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_ip_literals_connect_without_dns(ip, public_get, network):
    host = f"[{ip}]" if ":" in ip else ip
    with public_get(f"http://{host}/rss") as response:
        assert response.status_code == 200
    assert network.connected[0][0] == ip
    assert network.queries == []


def test_public_ipv6_dns_connects(public_get, network):
    network.answers = ["2606:4700:4700::1111"]
    with public_get("http://podcast.example/rss") as response:
        assert response.status_code == 200
    assert network.connected == [("2606:4700:4700::1111", 80, 0, 0)]


def test_public_dns_fallback_uses_only_validated_addresses(
    public_get, network, monkeypatch
):
    network.answers = ["93.184.216.34", "8.8.8.8"]
    original_connect = FakeSocket.connect

    def fail_first(sock, address):
        original_connect(sock, address)
        if len(network.connected) == 1:
            raise ConnectionRefusedError("test refusal")

    monkeypatch.setattr(FakeSocket, "connect", fail_first)
    with public_get("http://podcast.example/rss") as response:
        assert response.status_code == 200
    assert network.connected == [("93.184.216.34", 80), ("8.8.8.8", 80)]
    assert len(network.queries) == 1
    assert all(sock.closed for sock in network.sockets)


def test_relative_redirect_rechecks_closed_connection_after_rebind(
    public_get, network, monkeypatch
):
    monkeypatch.setattr(
        "urllib3.connectionpool.is_connection_dropped", lambda _conn: False
    )
    original_send = FakeSocket.sendall

    def send_and_rebind(sock, data):
        original_send(sock, data)
        network.answers = ["127.0.0.1"]

    monkeypatch.setattr(FakeSocket, "sendall", send_and_rebind)
    network.responses.insert(
        0, b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nLocation: /next\r\n\r\n"
    )
    with pytest.raises(requests.RequestException, match="public HTTP"):
        with public_get("http://podcast.example/rss"):
            pytest.fail("rebound connection accepted")
    assert network.connected == [("93.184.216.34", 80)]
    assert len(network.queries) == 2
    assert len(network.sent) == 1
    assert all(sock.closed for sock in network.sockets)


def test_add_feed_private_dns_returns_400(network):
    network.answers = ["10.0.0.1"]
    app = Flask(__name__)
    app.register_blueprint(feed_bp)
    with app.test_client() as client:
        response = client.post(
            "/feed",
            data={"url": "http://podcast.example/rss"},
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 400
    assert "public HTTP" in response.json["error"]
    assert network.connected == []


def test_feed_fetch_public_success_preserves_headers_timeout_and_final_url(network):
    feed = fetch_feed("http://podcast.example/rss")
    assert feed.href == "http://podcast.example/rss"
    assert b"User-Agent: feedparser/" in network.sent[0]
    assert network.sockets[0].timeout == 30
    assert all(sock.closed for sock in network.sockets)


def test_enclosure_public_success_streams_audio(network, tmp_path):
    destination = tmp_path / "episode.mp3"
    network.responses = [b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\naudio"]
    post = Post(
        id=1,
        guid="episode",
        title="Episode",
        download_url="http://podcast.example/audio.mp3",
    )
    result = PodcastDownloader().download_episode(post, str(destination))
    assert result == str(destination)
    assert destination.read_bytes() == b"audio"
    assert network.sockets[0].timeout == 60
    assert all(sock.closed for sock in network.sockets)


def test_enclosure_socket_timeout_keeps_retry_behavior(network, tmp_path, monkeypatch):
    original_connect = FakeSocket.connect

    def timeout_once(sock, address):
        original_connect(sock, address)
        if len(network.connected) == 1:
            raise socket.timeout("test timeout")

    monkeypatch.setattr(FakeSocket, "connect", timeout_once)
    sleep = mock.Mock()
    monkeypatch.setattr("podcast_processor.podcast_downloader.time.sleep", sleep)
    network.responses = [b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\naudio"]
    destination = tmp_path / "episode.mp3"
    post = Post(
        id=1,
        guid="episode",
        title="Episode",
        download_url="http://podcast.example/audio.mp3",
    )
    PodcastDownloader().download_episode(post, str(destination))
    assert destination.read_bytes() == b"audio"
    assert len(network.connected) == 2
    sleep.assert_called_once_with(1)
    assert all(sock.closed for sock in network.sockets)


@pytest.mark.parametrize(
    "location",
    [
        b"http://[invalid]/path",
        b"http://[::1/path",
        b"http://podcast.example:bad-port/path",
        b"http://podcast.example:65536/path",
        b"http://podcast.example/\xff",
        "http://podcast.example\uff1a80/path".encode("utf8"),
        "http://\u2603.example/path".encode("utf8"),
    ],
)
def test_malformed_redirect_is_a_safe_policy_error(location, public_get, network):
    from shared.http_client import UnsafeURLError

    network.responses = [
        b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nLocation: "
        + location
        + b"\r\n\r\n"
    ]
    with pytest.raises(UnsafeURLError, match="public HTTP"):
        with public_get("http://podcast.example/rss"):
            pytest.fail("malformed redirect accepted")
    assert len(network.connected) == 1
    assert all(sock.closed for sock in network.sockets)


@pytest.mark.parametrize(
    "location",
    [
        b"http://[invalid]/path",
        b"http://podcast.example/\xff",
        "http://\u2603.example/path".encode("utf8"),
    ],
)
def test_add_feed_malformed_redirect_returns_400(location, network):
    network.responses = [
        b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nLocation: "
        + location
        + b"\r\n\r\n"
    ]
    app = Flask(__name__)
    app.register_blueprint(feed_bp)
    with app.test_client() as client:
        response = client.post(
            "/feed",
            data={"url": "http://podcast.example/rss"},
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 400
    assert response.json["error"] == "Only public HTTP(S) podcast URLs are allowed."
    assert all(sock.closed for sock in network.sockets)


def test_relative_redirect_success_keeps_final_url(public_get, network):
    network.responses.insert(
        0, b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nLocation: /next\r\n\r\n"
    )
    with public_get("http://podcast.example/rss") as response:
        assert response.url == "http://podcast.example/next"
        assert response.content.startswith(b"<rss>")
    assert len(network.sent) == 2
    assert all(sock.closed for sock in network.sockets)


def test_unrelated_network_value_error_is_not_a_policy_rejection(
    public_get, network, monkeypatch
):
    def fail_send(_sock, _data):
        raise ValueError("unrelated network bug")

    monkeypatch.setattr(FakeSocket, "sendall", fail_send)
    with pytest.raises(ValueError, match="unrelated network bug"):
        with public_get("http://podcast.example/rss"):
            pytest.fail("network failure ignored")
    assert all(sock.closed for sock in network.sockets)
