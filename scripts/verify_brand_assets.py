#!/usr/bin/env python3
"""Verify the committed Podly Unicorn web/PWA branding contract."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend" / "public"
LOGOS = PUBLIC / "images" / "logos"

FAVICON_HASHES = {
    "favicon.svg": "f3f78a10fc7ad0cc9d197668d37a0d2a584f654dfce82cb9215c08cdf5c429ba",
    "favicon-96x96.png": "08afef87a7679554f7e85bc8fa70a67fc82c1d2c91c189326fb9332c6f8b6422",
    "favicon.ico": "f2f6f220a2c21a0a4da07c63bce605c88b5d035b713911c8a902d732d92d470f",
    "apple-touch-icon.png": "08edb85ef549cf6c312fa90d21841949a7e62455f156b24b6e375edf8eeec3f4",
}

PNG_DIMENSIONS = {
    "images/logos/favicon-96x96.png": (96, 96),
    "images/logos/apple-touch-icon.png": (180, 180),
    "images/logos/original-logo.png": (192, 192),
    "images/logos/unicorn-logo.png": (1024, 1024),
    "images/logos/pwa-icon-source.png": (512, 512),
    "images/logos/web-app-manifest-192x192.png": (192, 192),
    "images/logos/web-app-manifest-512x512.png": (512, 512),
    "images/logos/manifest-icon-192.maskable.png": (192, 192),
    "images/logos/manifest-icon-512.maskable.png": (512, 512),
    # The pre-Blue historical artwork keeps its original 3:2 pixel dimensions.
    "images/social-card1200x630.png": (1536, 1024),
    "images/screenshots/dashboard-desktop.png": (3450, 1828),
    "images/screenshots/podcasts-desktop.png": (3436, 1814),
    "images/screenshots/podcasts-mobile.png": (1036, 1834),
    "images/screenshots/processed mobile.png": (1044, 1820),
}

PLAIN_PODLY_SOURCE_ALLOWLIST = {
    "frontend/src/theme.ts": {
        "return theme === 'original' ? 'Podly' : 'Podly Unicorn';",
    },
    "src/app/routes/post_routes.py": {
        'message="This episode is not enabled for processing. Enable it in the Podly web interface first.",',
        '<a href="/" class="btn btn-primary">Go to Podly</a>',
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    require(data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} has an invalid PNG signature")
    require(data[12:16] == b"IHDR", f"{path} has no leading IHDR chunk")
    return struct.unpack(">II", data[16:24])


def verify_document_metadata() -> None:
    document = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    require(
        "<title>Podly Unicorn</title>" in document,
        "document title is not Podly Unicorn",
    )
    for name in ("apple-mobile-web-app-title", "twitter:title"):
        require(
            re.search(
                rf'<meta name="{re.escape(name)}" content="Podly Unicorn"\s*/?>',
                document,
            )
            is not None,
            f"{name} is not Podly Unicorn",
        )
    require(
        '<meta property="og:title" content="Podly Unicorn" />' in document,
        "Open Graph title is not Podly Unicorn",
    )
    require(
        '<meta name="theme-color" content="#7c3aed" />' in document,
        "document theme color is wrong",
    )
    require('href="/manifest.json?v=8"' in document, "manifest cache query is not v8")
    icon_links = re.findall(
        r'href="(/images/logos/(?:favicon[^"?]*|apple-touch-icon\.png)\?v=(\d+))"',
        document,
    )
    require(len(icon_links) == 4, "expected four versioned favicon/Apple icon links")
    require(
        all(version == "3" for _, version in icon_links),
        "favicon/Apple icon query is not v3",
    )


def verify_manifest() -> None:
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["name"] == "Podly Unicorn", "manifest name is wrong")
    require(manifest["short_name"] == "Podly Unicorn", "manifest short_name is wrong")
    require(
        manifest["background_color"] == "#1e1b4b", "manifest background color is wrong"
    )
    require(manifest["theme_color"] == "#7c3aed", "manifest theme color is wrong")

    expected = {
        ("/images/logos/web-app-manifest-192x192.png", "192x192", "any"),
        ("/images/logos/web-app-manifest-512x512.png", "512x512", "any"),
        ("/images/logos/manifest-icon-192.maskable.png", "192x192", "maskable"),
        ("/images/logos/manifest-icon-512.maskable.png", "512x512", "maskable"),
    }
    actual = {
        (icon["src"], icon["sizes"], icon["purpose"]) for icon in manifest["icons"]
    }
    require(actual == expected, "manifest icon dimensions/purposes are wrong")


def verify_service_worker() -> None:
    worker = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    require("const CACHE_VERSION = 'v6';" in worker, "service-worker cache is not v6")


def verify_icon_generator() -> None:
    generator = (ROOT / "scripts" / "generate_pwa_icons.py").read_text(encoding="utf-8")
    require(
        'SOURCE = LOGOS_DIR / "pwa-icon-source.png"' in generator,
        "generator does not use the flat Unicorn source",
    )
    require(
        "BG_COLOR = (30, 27, 75)" in generator, "generator background is not #1e1b4b"
    )
    for entry in (
        "(192, OUTPUT_192, 1.0)",
        "(512, OUTPUT_512, 1.0)",
        "(192, MASKABLE_192, 0.75)",
        "(512, MASKABLE_512, 0.75)",
    ):
        require(entry in generator, f"generator is missing icon rule {entry}")


def verify_asset_formats() -> None:
    for relative, dimensions in PNG_DIMENSIONS.items():
        path = PUBLIC / relative
        require(path.is_file(), f"missing required asset: {path}")
        require(
            png_dimensions(path) == dimensions,
            f"{path} is not {dimensions[0]}x{dimensions[1]}",
        )

    ico = (LOGOS / "favicon.ico").read_bytes()
    require(
        len(ico) >= 6 and ico[:4] == b"\x00\x00\x01\x00",
        "favicon.ico has an invalid ICO header",
    )
    require(int.from_bytes(ico[4:6], "little") > 0, "favicon.ico contains no images")

    svg = ElementTree.parse(LOGOS / "favicon.svg").getroot()
    require(svg.tag.rsplit("}", 1)[-1] == "svg", "favicon.svg root is not <svg>")

    for name, expected in FAVICON_HASHES.items():
        actual = hashlib.sha256((LOGOS / name).read_bytes()).hexdigest()
        require(
            actual == expected,
            f"{name} no longer matches the verified historical favicon",
        )


def verify_readme() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    requirements = {
        "Podly Unicorn heading": "<h1>Podly Unicorn</h1>",
        "Unicorn logo hero": 'src="frontend/public/images/logos/unicorn-logo.png" alt="Podly Unicorn"',
        "fork badge": "img.shields.io/badge/GitHub-podly--unicorn-purple?logo=github",
        "fork repository": "https://github.com/lukefind/podly-unicorn",
        "fork issues": "https://github.com/lukefind/podly-unicorn/issues",
        "upstream credit": "[Podly Pure Podcasts](https://github.com/jdrbc/podly_pure_podcasts)",
        "Unicorn dashboard alt text": 'alt="Podly Unicorn Dashboard"',
        "Unicorn mobile screenshot": "frontend/public/images/screenshots/podcasts-mobile.png",
        "Unicorn processed screenshot": "frontend/public/images/screenshots/processed mobile.png",
    }
    for label, needle in requirements.items():
        require(needle in readme, f"README is missing {label}")


def verify_source_branding() -> None:
    """Reject plain Podly product identity while preserving intentional feature copy."""
    for relative, allowed_lines in PLAIN_PODLY_SOURCE_ALLOWLIST.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        plain_podly_lines = {
            line.strip()
            for line in source.splitlines()
            if "Podly" in line
            and "Podly Unicorn" not in line
            and "Podly RSS" not in line
        }
        unexpected = plain_podly_lines - allowed_lines
        require(
            not unexpected,
            f"{relative} has unapproved plain Podly identity: {sorted(unexpected)}",
        )

    route_source = (ROOT / "src" / "app" / "routes" / "post_routes.py").read_text(
        encoding="utf-8"
    )
    expected_identity = {
        "trigger titles": ("<title>{title} - Podly Unicorn</title>", 2),
        "trigger headers": ("<h1>Podly Unicorn</h1>", 2),
        "trigger footers": ('<a href="/">Podly Unicorn</a>', 2),
    }
    for label, (needle, count) in expected_identity.items():
        require(
            route_source.count(needle) == count,
            f"expected {count} Unicorn-branded {label}",
        )

    auth_source = (ROOT / "src" / "app" / "routes" / "auth_routes.py").read_text(
        encoding="utf-8"
    )
    expected_email_subjects = (
        'subject="Podly Unicorn: Signup received"',
        'subject="Podly Unicorn: New signup pending approval"',
        'subject="Podly Unicorn: Password reset"',
        'subject="Podly Unicorn: Account approved"',
    )
    for subject in expected_email_subjects:
        require(
            auth_source.count(subject) == 1,
            f"auth email subject is missing or duplicated: {subject}",
        )
    require(
        'subject="Podly:' not in auth_source,
        "auth email subjects contain the plain Podly product identity",
    )


def main() -> int:
    checks = (
        verify_document_metadata,
        verify_manifest,
        verify_service_worker,
        verify_icon_generator,
        verify_asset_formats,
        verify_readme,
        verify_source_branding,
    )
    failures: list[str] = []
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except (
            AssertionError,
            FileNotFoundError,
            json.JSONDecodeError,
            ElementTree.ParseError,
        ) as error:
            failures.append(f"FAIL {check.__name__}: {error}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Podly Unicorn branding assets verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
