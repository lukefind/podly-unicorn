"""HTTP transport for untrusted podcast URLs.

The connection classes resolve once, reject the entire DNS answer if any address
is non-public, and connect the validated sockaddr directly. Keeping the original
hostname on the urllib3 connection preserves HTTP Host, TLS SNI and certificate
verification without a second DNS lookup (and its DNS rebinding window).
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from requests.models import DEFAULT_REDIRECT_LIMIT
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import (
    ConnectTimeoutError,
    NameResolutionError,
    NewConnectionError,
)


class UnsafeURLError(requests.RequestException):
    """A URL or resolved destination violates the outbound network policy."""

    def __init__(self) -> None:
        # Never echo user-controlled URLs: they may contain credentials.
        super().__init__("Only public HTTP(S) podcast URLs are allowed.")


class _UnsafeDestinationError(Exception):
    """Internal policy rejection that urllib3 must not wrap as an OSError."""


def _public_ip(address: str) -> bool:
    try:
        if "%" in address:
            return False
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    )


def validate_public_url(url: str) -> None:
    """Reject ambiguous URLs and non-public literals before requests normalizes them.

    Domain DNS validation happens at socket creation, including reconnects.
    """
    try:
        if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise UnsafeURLError()
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            raise UnsafeURLError()
        if (
            parsed.username is not None
            or parsed.password is not None
            or "\\" in parsed.netloc
            or "%" in parsed.netloc
        ):
            raise UnsafeURLError()
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise UnsafeURLError()
        host = host.rstrip(".")
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            # inet_aton/getaddrinfo also accept abbreviated, octal, hexadecimal
            # and integer IPv4 forms that ipaddress intentionally rejects.
            if all(
                re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part, re.I)
                for part in host.split(".")
            ):
                raise UnsafeURLError() from exc
        else:
            if not _public_ip(host):
                raise UnsafeURLError()
        # Validate requests' URL normalization/IDNA parsing without performing
        # network I/O. Scope parsing errors here instead of catching ValueError
        # around session.get(), where an unrelated failure could be hidden.
        requests.PreparedRequest().prepare_url(url, None)
    except (ValueError, UnicodeError) as exc:
        raise UnsafeURLError() from exc


def _public_addresses(host: str, port: int) -> list[Any]:
    addresses: list[Any]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        addresses = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    else:
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        literal_sockaddr = (host, port, 0, 0) if ip.version == 6 else (host, port)
        addresses = [
            (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", literal_sockaddr)
        ]
    if not addresses or any(
        family not in {socket.AF_INET, socket.AF_INET6}
        or not isinstance(sockaddr[0], str)
        or not _public_ip(sockaddr[0])
        for family, _kind, _proto, _canon, sockaddr in addresses
    ):
        raise _UnsafeDestinationError()
    return addresses


class _PublicHTTPConnection(HTTPConnection):
    def _new_conn(self) -> socket.socket:
        try:
            addresses = _public_addresses(self._dns_host, self.port)
        except socket.gaierror as exc:
            raise NameResolutionError(self.host, self, exc) from exc

        last_error: OSError | None = None
        for family, kind, proto, _canon, sockaddr in addresses:
            sock = None
            try:
                sock = socket.socket(family, kind, proto)
                for option in self.socket_options or ():
                    sock.setsockopt(*option)
                if self.timeout is None or isinstance(self.timeout, (int, float)):
                    sock.settimeout(self.timeout)
                if self.source_address:
                    sock.bind(self.source_address)
                # sockaddr is numeric and already validated. Do not call a
                # hostname-based connection helper here.
                sock.connect(sockaddr)
                return sock
            except OSError as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
        if isinstance(last_error, socket.timeout):
            raise ConnectTimeoutError(
                self, "Connection to podcast host timed out."
            ) from last_error
        raise NewConnectionError(
            self, "Could not connect to podcast host."
        ) from last_error


class _PublicHTTPSConnection(HTTPSConnection, _PublicHTTPConnection):
    pass


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicAdapter(HTTPAdapter):
    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        super().init_poolmanager(*args, **kwargs)
        # Do not mutate urllib3's global pool-class registry.
        self.poolmanager.pools.dispose_func = lambda pool: pool.close()
        self.poolmanager.pool_classes_by_scheme = {
            "http": _PublicHTTPPool,
            "https": _PublicHTTPSPool,
        }

    def send(self, *args: Any, **kwargs: Any) -> requests.Response:
        try:
            return super().send(*args, **kwargs)
        except _UnsafeDestinationError as exc:
            raise UnsafeURLError() from exc


class _PublicSession(requests.Session):
    def resolve_redirects(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        # Session.send otherwise prepares Response.next even when redirects are
        # disabled. Leave decoding and parsing to our response-owned context.
        return iter(())


@contextmanager
def public_get(
    url: str,
    *,
    headers: dict[str, str | None] | None = None,
    timeout: tuple[int, int] | int = (10, 30),
    stream: bool = False,
    max_redirects: int = DEFAULT_REDIRECT_LIMIT,
) -> Iterator[requests.Response]:
    """GET an untrusted URL with bounded, validated redirects and owned lifetime.

    Use the response inside the context, especially when streaming audio. Proxy
    environment variables and .netrc credentials are deliberately disabled.
    Requests' standard redirect bound accommodates podcast tracking chains.
    """
    validate_public_url(url)
    with _PublicSession() as session:
        session.trust_env = False
        session.mount("http://", _PublicAdapter())
        session.mount("https://", _PublicAdapter())
        for redirect_count in range(max_redirects + 1):
            validate_public_url(url)
            with session.get(
                url,
                headers=headers,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            ) as response:
                if not response.is_redirect:
                    if not stream:
                        _ = response.content
                    yield response
                    return
                if redirect_count == max_redirects:
                    raise requests.TooManyRedirects(
                        "Podcast URL exceeded the redirect limit."
                    )
                try:
                    location = session.get_redirect_target(response)
                    url = urljoin(response.url, location)
                except (ValueError, UnicodeError) as exc:
                    raise UnsafeURLError() from exc
                validate_public_url(url)
