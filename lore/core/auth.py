"""GitHub token resolution and secret redaction (LORE-044).

The MCP side resolves its GitHub token through :func:`resolve_github_token`:
``LORE_GITHUB_TOKEN`` first, then ``gh auth token`` — but only when the
registration opted in with ``LORE_TOKEN_FROM_GH=1``. This keeps a ``gh``-sourced
token out of the agent's config file while leaving behaviour unchanged for
everyone who did not opt in.

Only the standard library is used so this module is safe to import in the
lightweight ``uvx mcp-server-lore`` install.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Callable, Iterable, Mapping, Optional

GH_TIMEOUT_SECONDS = 5
REDACTED = "[REDACTED]"

# Well-known GitHub token shapes, redacted even when not passed explicitly.
_TOKEN_PATTERN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


def gh_auth_token(
    which: Callable[[str], Optional[str]] = shutil.which,
    run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
) -> Optional[str]:
    """Return the token from ``gh auth token``, or ``None`` if unavailable.

    ``None`` is returned when ``gh`` is not installed, exits non-zero, times
    out (~5 s) or prints nothing. The token is never logged.
    """
    if not which("gh"):
        return None
    try:
        result = run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    token = (result.stdout or "").strip()
    return token or None


def resolve_github_token(
    env: Optional[Mapping[str, str]] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
) -> Optional[str]:
    """Resolve the GitHub token for the MCP server.

    Order: ``LORE_GITHUB_TOKEN`` from ``env``; otherwise ``gh auth token``,
    consulted only when ``env['LORE_TOKEN_FROM_GH'] == '1'``. Returns ``None``
    when no token can be found.

    Args:
        env: Environment mapping (defaults to ``os.environ``).
        which: ``shutil.which`` replacement (injectable for tests).
        run: ``subprocess.run`` replacement (injectable for tests).
    """
    env = os.environ if env is None else env
    token = (env.get("LORE_GITHUB_TOKEN") or "").strip()
    if token:
        return token
    if env.get("LORE_TOKEN_FROM_GH") == "1":
        return gh_auth_token(which, run)
    return None


def redact(text: str, secrets: Iterable[Optional[str]] = ()) -> str:
    """Replace every secret (and any GitHub-token-shaped string) in ``text``.

    Args:
        text: Text that may contain secrets.
        secrets: Exact secret values to mask; empty/``None`` values are ignored.
    """
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return _TOKEN_PATTERN.sub(REDACTED, text)
