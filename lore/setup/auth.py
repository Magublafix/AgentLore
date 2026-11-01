"""GitHub authentication for ``mcp-server-lore init`` (LORE-044).

Token resolution order: ``LORE_GITHUB_TOKEN`` -> ``gh auth token`` -> an
interactive hidden prompt (only on a TTY and without ``--yes``). The token is
validated with a read-only ``GET /user``. It is never printed or logged.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

import requests

from lore.core.auth import gh_auth_token
from lore.core.endpoints import github_api_url

TOKEN_URL = "https://github.com/settings/tokens/new?scopes=gist&description=AgentLore"

SOURCE_ENV = "env"
SOURCE_GH = "gh"
SOURCE_PROMPT = "prompt"

Http = Callable[..., "requests.Response"]


@dataclass(frozen=True)
class TokenResult:
    """A resolved token and where it came from; ``repr`` never shows the token."""

    token: Optional[str] = field(default=None, repr=False)
    source: Optional[str] = None


class AuthError(RuntimeError):
    """Token validation failed; the message is safe to show (contains no token)."""


def resolve_token(
    *,
    env: Optional[Mapping[str, str]] = None,
    allow_prompt: bool = True,
    interactive: Optional[bool] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    prompt: Callable[[str], str] = getpass.getpass,
    out: Callable[[str], None] = print,
) -> TokenResult:
    """Find a GitHub token: env, then ``gh``, then (if allowed and on a TTY) a prompt.

    Args:
        env: Environment mapping (defaults to ``os.environ``).
        allow_prompt: ``False`` for ``--yes`` / dry runs — never prompts.
        interactive: Whether stdin is a TTY (defaults to ``sys.stdin.isatty()``).
        which, run: Injectable for ``gh`` lookup.
        prompt: Hidden-input function (``getpass.getpass``); input is not echoed.
        out: Output sink for the instructions shown before prompting.
    """
    env = os.environ if env is None else env
    token = (env.get("LORE_GITHUB_TOKEN") or "").strip()
    if token:
        return TokenResult(token, SOURCE_ENV)
    token = gh_auth_token(which, run)
    if token:
        return TokenResult(token, SOURCE_GH)
    if interactive is None:
        import sys

        interactive = sys.stdin.isatty()
    if allow_prompt and interactive:
        out("No GitHub token found. Create one with the 'gist' scope at:\n  " + TOKEN_URL)
        out("Press Enter without typing anything to continue in read-only demo mode.")
        entered = (prompt("GitHub token (input hidden): ") or "").strip()
        if entered:
            return TokenResult(entered, SOURCE_PROMPT)
    return TokenResult()


def validate_token(token: str, http: Optional[Http] = None) -> Optional[str]:
    """Check ``token`` with ``GET https://api.github.com/user`` (read-only).

    Returns the GitHub login. Raises :class:`AuthError` on a 401, a missing
    ``gist`` scope (only checked when GitHub sends ``X-OAuth-Scopes``), any other
    error status, or a network failure.
    """
    http = http or requests.get
    try:
        resp = http(
            github_api_url() + "/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise AuthError(
            f"could not reach GitHub to validate the token ({type(exc).__name__}). "
            "Check your network, or re-run without a token for read-only demo mode."
        ) from None
    if resp.status_code == 401:
        raise AuthError(
            "GitHub rejected the token (401 Bad credentials). It may be expired or revoked; "
            f"create a new one with the 'gist' scope at {TOKEN_URL}"
        )
    if resp.status_code != 200:
        raise AuthError(f"GitHub returned HTTP {resp.status_code} while validating the token")
    scopes_header = resp.headers.get("X-OAuth-Scopes")
    if scopes_header is not None:
        scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
        if "gist" not in scopes:
            raise AuthError(
                "the token does not have the 'gist' scope (found: "
                f"{', '.join(sorted(scopes)) or 'none'}). Create one with it at {TOKEN_URL}"
            )
    try:
        return str(resp.json().get("login", ""))
    except (ValueError, AttributeError):
        raise AuthError("GitHub returned an unreadable response while validating the token") from None
