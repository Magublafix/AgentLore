"""``mcp-server-lore init`` — prerequisites, GitHub auth, registration, state, verification.

Safe by default: ``init`` never publishes or rates a concept (verification runs
one ``search_concepts`` call only). Re-running is idempotent; an existing
different registration is reported, not overwritten, unless ``--force`` is
given. ``--dry-run`` changes nothing. Tokens are never printed, and are only
written to the agent config with an explicit ``--store-token``.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from lore.core.auth import redact
from lore.setup import auth as auth_mod
from lore.setup import verify as verify_mod
from lore.setup.agents import (
    ADAPTERS,
    SERVER_NAME,
    AgentAdapter,
    AgentError,
    UNKNOWN_SCOPE,
    ServerSpec,
)
from lore.setup.checks import Check, run_checks
from lore.setup.state import ensure_state

AdapterFactory = Callable[[], AgentAdapter]

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-server-lore init",
        description="Check prerequisites and register the Lore MCP server with your coding agent.",
    )
    parser.add_argument("--agent", choices=sorted(ADAPTERS), default="claude")
    parser.add_argument(
        "--scope",
        choices=["user", "local", "project"],
        default="user",
        help="where to register the server (default: user — all projects)",
    )
    parser.add_argument("--force", action="store_true", help="replace a conflicting registration")
    parser.add_argument("--dry-run", action="store_true", help="print planned actions, change nothing")
    parser.add_argument("--semantic", action="store_true", help="also check Docker for the semantic search stack")
    parser.add_argument("--semantic-url", help="URL of a semantic search server to register (LORE_SEMANTIC_URL)")
    parser.add_argument("--yes", "-y", action="store_true", help="never prompt (non-interactive)")
    parser.add_argument(
        "--store-token",
        action="store_true",
        help="write an env/prompt-sourced token into the agent config in plain text (off by default)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="register this Python interpreter (python -m lore.mcp.server) instead of 'uvx mcp-server-lore'",
    )
    parser.add_argument("--no-verify", action="store_true", help="skip the end-to-end search check")
    return parser


def _print_checks(checks: Sequence[Check], out: Callable[[str], None]) -> bool:
    ok = True
    for check in checks:
        if check.ok:
            out(f"  ✓ {check.detail}")
        else:
            ok = False
            out(f"  ✗ {check.detail}")
            out(f"      fix: {check.fix}")
    return ok


def build_spec(
    token: auth_mod.TokenResult,
    store_token: bool,
    semantic_url: Optional[str],
    local: bool = False,
    uvx_from: Optional[str] = None,
) -> ServerSpec:
    """Choose the registration for the token situation.

    ``gh`` token -> ``LORE_TOKEN_FROM_GH=1`` (not stored); env/prompt token ->
    stored only with ``store_token``; no token -> read-only demo mode.
    """
    env = {"LORE_BACKEND": "gists"}
    secrets: dict[str, str] = {}
    if token.token is None:
        env["LORE_READ_ONLY"] = "1"
    elif token.source == auth_mod.SOURCE_GH:
        env["LORE_TOKEN_FROM_GH"] = "1"
    elif store_token:
        secrets["LORE_GITHUB_TOKEN"] = token.token
    if semantic_url:
        env["LORE_SEMANTIC_URL"] = semantic_url
    if local:
        return ServerSpec(
            command=sys.executable, args=("-m", "lore.mcp.server"), env=env, secrets=secrets
        )
    if uvx_from:
        return ServerSpec(args=("--from", uvx_from, "mcp-server-lore"), env=env, secrets=secrets)
    return ServerSpec(env=env, secrets=secrets)


_FORWARDED_TEST_ENV = ("LORE_ALLOW_INSECURE_TEST_URLS", "LORE_GITHUB_API_URL", "LORE_GIST_WEB_URL")
UVX_FROM_ENV = "LORE_INIT_UVX_FROM"  # test-only hook, deliberately undocumented outside ADR-016


def resolve_uvx_from(value: str) -> str:
    """Validate ``LORE_INIT_UVX_FROM``: an existing local ``.whl`` / ``.tar.gz`` file.

    Returns the absolute path. Raises :class:`ValueError` (message safe to show)
    for URLs, directories, missing files or any other file type.
    """
    if "://" in value:
        raise ValueError(f"{UVX_FROM_ENV} must be a local file path, not a URL")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.abspath(path))
    if not path.name.endswith((".whl", ".tar.gz")):
        raise ValueError(f"{UVX_FROM_ENV} must name a .whl or .tar.gz file")
    if not path.is_file():
        raise ValueError(f"{UVX_FROM_ENV} does not point to an existing file: {path}")
    return str(path)


def run_init(
    argv: Sequence[str],
    *,
    adapters: Optional[dict[str, AdapterFactory]] = None,
    checks_fn: Optional[Callable[..., list[Check]]] = None,
    out: Callable[[str], None] = print,
    spec: Optional[ServerSpec] = None,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
    token_fn: Optional[Callable[..., auth_mod.TokenResult]] = None,
    validate_fn: Optional[Callable[[str], Optional[str]]] = None,
    verify_fn: Optional[Callable[..., verify_mod.VerifyResult]] = None,
    interactive: Optional[bool] = None,
) -> int:
    """Run ``init``; returns the process exit code (0 ok, 1 failure/conflict)."""
    args = build_parser().parse_args(list(argv))
    env = os.environ if env is None else env
    adapter = (adapters or ADAPTERS)[args.agent]()
    prefix = "[dry-run] " if args.dry_run else ""
    secrets: list[str] = []
    raw_out = out

    def out(msg: str) -> None:  # noqa: F811 — every line is redacted before it is shown
        raw_out(redact(msg, secrets))

    if args.store_token and args.scope == "project":
        out(_PROJECT_TOKEN_REFUSAL)
        return 1

    semantic_url = args.semantic_url or env.get("LORE_SEMANTIC_URL") or None
    if args.scope == "project" and semantic_url and _url_is_credentialed(semantic_url):
        out(_PROJECT_URL_REFUSAL)
        return 1

    uvx_from: Optional[str] = None
    if env.get(UVX_FROM_ENV) and not args.local:
        try:
            uvx_from = resolve_uvx_from(env[UVX_FROM_ENV])
        except ValueError as exc:
            out(f"  ✗ {exc}")
            return 1
        out(f"  ! TEST-ONLY: {UVX_FROM_ENV} is set; registering 'uvx --from {uvx_from} mcp-server-lore' "
            "instead of the published package")

    out("Checking prerequisites")
    if not _print_checks((checks_fn or run_checks)(semantic=args.semantic, **({"local": True} if args.local else {})), out):
        out("\nSetup stopped: fix the issues above and re-run.")
        return 1

    # --- GitHub authentication -------------------------------------------
    out("\nGitHub authentication")
    can_prompt = not args.yes and not args.dry_run
    token = (token_fn or auth_mod.resolve_token)(
        env=env, allow_prompt=can_prompt, interactive=interactive, out=out
    )
    if token.token:
        secrets.append(token.token)
    if token.token is None and args.store_token:
        out("  ✗ --store-token needs a token: set LORE_GITHUB_TOKEN, log in with "
            "`gh auth login`, or drop --store-token for the read-only demo")
        return 1
    if token.token is None:
        out("  - no GitHub token found: continuing in READ-ONLY DEMO mode")
    elif args.dry_run:
        out(f"  {prefix}token found via {token.source}; skipping validation")
    else:
        try:
            login = (validate_fn or auth_mod.validate_token)(token.token)
        except auth_mod.AuthError as exc:
            out(f"  ✗ {exc}")
            return 1
        out(f"  ✓ token from {_SOURCE_LABEL[token.source]} is valid"
            + (f" (GitHub user {login})" if login else ""))

    spec = spec or build_spec(token, args.store_token, semantic_url, args.local, uvx_from)
    secrets.extend(spec.secret_values())
    if spec.secrets and args.scope == "project":
        out(_PROJECT_TOKEN_REFUSAL)
        return 1
    adapter.secrets = secrets  # shared list: CLI error text is redacted too
    _explain_token_handling(token, args.store_token, out)

    # --- registration -----------------------------------------------------
    out(f"\nConfiguring {adapter.name}")
    run_env = dict(spec.env)
    try:
        existing = adapter.get_registration(spec.name)
        if existing is not None and existing.scope == "project" and spec.secrets:
            out(_PROJECT_EXISTING_REFUSAL)
            return 1
        if existing is not None and existing.env.get("LORE_GITHUB_TOKEN"):
            secrets.append(existing.env["LORE_GITHUB_TOKEN"])  # legacy stored token: redact too
        if existing is not None and existing.matches(spec):
            out(f"  ✓ '{spec.name}' already configured ({existing.scope} scope) — nothing to do")
            run_env = {**existing.env, **spec.env}
        else:
            if existing is not None:
                out(f"  ✗ '{spec.name}' is already registered with different settings "
                    f"({existing.scope} scope): {existing.mismatch_reason(spec) or 'different command or arguments'}")
                if not args.force:
                    out("      fix: re-run with --force to replace it, or remove it with "
                        f"'claude mcp remove {spec.name} -s "
                        f"{'<scope>' if existing.scope == UNKNOWN_SCOPE else existing.scope}'")
                    return 1
                if existing.scope == UNKNOWN_SCOPE:
                    out("      cannot tell which scope holds it, so --force will not guess; "
                        f"run 'claude mcp get {spec.name}' and remove it manually")
                    return 1
                out(f"  {prefix}removing existing '{spec.name}' ({existing.scope} scope)")
                if not args.dry_run:
                    adapter.remove(spec.name, existing.scope)

            out(f"  {prefix}registering '{spec.name}': {spec.command} {' '.join(spec.args)} ({args.scope} scope)")
            out(f"      settings: {_describe_env(spec)}")
            if not args.dry_run:
                try:
                    adapter.register(spec, args.scope)
                except AgentError:
                    if existing is not None:
                        out(f"  ! the previous '{spec.name}' registration was already removed")
                    raise
    except AgentError as exc:
        out(f"  ✗ {exc}")
        return 1
    except (OSError, subprocess.SubprocessError) as exc:  # missing binary or CLI timeout
        out(f"  ✗ could not run the agent CLI: {exc}")
        return 1

    # --- local state (after the conflict check, so a refused init creates nothing) ---
    out("\nLocal state")
    if args.dry_run:
        out(f"  {prefix}would create ~/.lore/ and session.json if absent")
    else:
        try:
            created = ensure_state(home, warn=lambda m: out(f"  ! {m}"))
        except OSError as exc:
            out(f"  ✗ could not create ~/.lore: {exc}")
            return 1
        if created:
            out("  ✓ created " + ", ".join(p.name for p in created))
        else:
            out("  ✓ ~/.lore already exists — left untouched")

    # --- verification -----------------------------------------------------
    if args.dry_run:
        out("\nDry run complete — nothing was changed.")
        return 0
    if args.no_verify:
        out("\nSkipped verification (--no-verify). Done.")
        return 0

    out("\nVerifying the install (starting the server and running one search)")
    # Exactly the registered environment. A gh-sourced token is NOT injected (the server
    # resolves it itself via LORE_TOKEN_FROM_GH); a shell/prompt token that is not stored
    # is injected in memory only, and we say so.
    child_env = {**run_env, **spec.secrets}
    if token.token and token.source != auth_mod.SOURCE_GH and "LORE_GITHUB_TOKEN" not in child_env:
        child_env["LORE_GITHUB_TOKEN"] = token.token  # in memory only
        out("  ! verification used the token from your shell/prompt, which is not in the agent "
            "config: the agent needs LORE_GITHUB_TOKEN in its environment, or re-run with --store-token")
    # Test-only endpoint overrides reach the verification child only, never the registration.
    for key in _FORWARDED_TEST_ENV:
        if env.get(key):
            child_env[key] = env[key]
    result = (verify_fn or verify_mod.verify_install)(
        spec.command, list(spec.args), child_env, secrets=secrets
    )
    if not result.ok:
        out(f"  ✗ verification failed: {result.message}")
        out("      fix: run 'uvx mcp-server-lore' by hand to see the error, or re-run with --no-verify")
        return 1
    out(f"  ✓ server started, all {len(result.tools)} tools listed, search_concepts returned "
        f"{result.result_count} result(s)" + (f" (top: {result.first_result})" if result.first_result else ""))
    for warning in result.warnings:
        out(f"  ! warning: {warning}")
    if token.token is None:
        out("\nDone — READ-ONLY DEMO mode.")
        out("  - publishing and rating are disabled (submit/link/rate return a 'read_only' error)")
        out("  - search covers the bundled curated examples only")
        out("  - community-wide search needs a semantic server: re-run with --semantic-url <url>")
        out(f"  - to enable publishing, create a token with the 'gist' scope ({auth_mod.TOKEN_URL}),")
        out("    or run 'gh auth login', then re-run with --force")
    else:
        out("\nDone.")
    return 0


_SOURCE_LABEL = {
    auth_mod.SOURCE_ENV: "LORE_GITHUB_TOKEN",
    auth_mod.SOURCE_GH: "'gh auth token'",
    auth_mod.SOURCE_PROMPT: "the prompt",
}


_PROJECT_TOKEN_REFUSAL = (
    "  ✗ refusing to store a token with project scope: it would be written in plain text to "
    ".mcp.json, which is usually committed to version control.\n"
    "      fix: use --scope user or --scope local with --store-token, or drop --store-token and "
    "put LORE_GITHUB_TOKEN in the environment Claude Code starts from"
)
_PROJECT_EXISTING_REFUSAL = (
    "  ✗ refusing to store a token: a project-scope 'lore' registration already exists, and "
    "project scope writes .mcp.json, which is usually committed to version control.\n"
    "      fix: remove it with 'claude mcp remove lore -s project' and re-run, or drop "
    "--store-token and put LORE_GITHUB_TOKEN in the environment Claude Code starts from"
)
_PROJECT_URL_REFUSAL = (
    "  ✗ refusing to register this semantic URL with project scope: it may contain credentials "
    "(an '@'), a query string or a fragment, or lacks a scheme, and project scope writes it verbatim to "
    ".mcp.json, which is usually committed.\n"
    "      fix: use a plain URL like https://host, or use --scope user or --scope local"
)


def _url_is_credentialed(url: str) -> bool:
    """True when ``url`` might carry secrets: any ``@``, no ``://`` scheme, a query or a fragment."""
    from urllib.parse import urlsplit

    if "@" in url or "://" not in url:
        return True
    try:
        parts = urlsplit(url)
    except ValueError:
        return True
    return bool(parts.query or parts.fragment or parts.username or parts.password)


_USERINFO = re.compile(r"(://)[^/@\s]*@")


def _describe_env(spec: ServerSpec) -> str:
    items = [k + "=" + _USERINFO.sub("://***@", v) for k, v in spec.env.items()]
    items += [f"{k}=<hidden, stored>" for k in spec.secrets]
    return ", ".join(items)


def _explain_token_handling(token: auth_mod.TokenResult, store_token: bool, out: Callable[[str], None]) -> None:
    """Say plainly where the token will (not) be kept."""
    if token.token is None:
        return
    if token.source == auth_mod.SOURCE_GH:
        out("  - the token is NOT copied into your agent config; the server asks 'gh' for it at runtime")
    elif store_token:
        out("  ! --store-token: the token will be written in PLAIN TEXT to your agent config "
            "(and is briefly visible in this process's argument list)")
    else:
        out("  - the token is NOT stored in your agent config. Make sure LORE_GITHUB_TOKEN is "
            "set in the environment your agent starts from, or re-run with --store-token "
            "to write it in plain text into the agent config")
