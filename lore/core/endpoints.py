"""Test-only GitHub endpoint overrides (ADR-016).

``LORE_GITHUB_API_URL`` / ``LORE_GIST_WEB_URL`` replace the GitHub API and gist
web bases so black-box tests can point Lore at a local stub server. An override
is honoured only when ``LORE_ALLOW_INSECURE_TEST_URLS=1`` is also set and the URL
is http(s) with a loopback host and no userinfo, query or fragment. Otherwise
the default is used and a WARNING is logged. Resolution happens at call time.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_GIST_WEB_URL = "https://gist.github.com"

ALLOW_ENV = "LORE_ALLOW_INSECURE_TEST_URLS"
API_ENV = "LORE_GITHUB_API_URL"
WEB_ENV = "LORE_GIST_WEB_URL"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_honoured_logged: set[tuple[str, str]] = set()


def _validate(raw: str) -> str | None:
    """Return the normalised override URL (no trailing slash) or None if unsafe."""
    try:
        parts = urlsplit(raw.strip())
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or host is None:
        return None
    if host.lower() not in _LOOPBACK_HOSTS:
        return None
    if "@" in parts.netloc or parts.query or parts.fragment or "?" in raw or "#" in raw:
        return None
    return raw.strip().rstrip("/")


def _resolve(env_name: str, default: str) -> str:
    raw = os.environ.get(env_name)
    if not raw:
        return default
    if os.environ.get(ALLOW_ENV) != "1":
        logger.warning(
            "Ignoring %s: %s=1 is not set (test-only override).", env_name, ALLOW_ENV
        )
        return default
    url = _validate(raw)
    if url is None:
        logger.warning(
            "Ignoring %s: value must be an http(s) loopback URL "
            "(127.0.0.1, localhost, ::1) without userinfo, query or fragment.",
            env_name,
        )
        return default
    if (env_name, url) not in _honoured_logged:
        _honoured_logged.add((env_name, url))
        logger.warning(
            "TEST-ONLY endpoint override active: %s -> %s. Tokens will be sent there.",
            env_name,
            url,
        )
    return url


def github_api_url() -> str:
    """Base URL of the GitHub REST API (default ``https://api.github.com``)."""
    return _resolve(API_ENV, DEFAULT_GITHUB_API_URL)


def gist_web_url() -> str:
    """Base URL of the gist website (default ``https://gist.github.com``)."""
    return _resolve(WEB_ENV, DEFAULT_GIST_WEB_URL)


def same_origin(url: str, base: str) -> bool:
    """True when ``url`` has the same scheme, host and port as ``base``."""
    try:
        a, b = urlsplit(url), urlsplit(base)
        defaults = {"http": 80, "https": 443}
        return (
            a.scheme in defaults
            and a.scheme == b.scheme
            and a.hostname is not None
            and a.hostname.lower() == (b.hostname or "").lower()
            and (a.port or defaults[a.scheme]) == (b.port or defaults[b.scheme])
        )
    except ValueError:
        return False
