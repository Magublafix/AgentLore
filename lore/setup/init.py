"""``mcp-server-lore init`` — prerequisite checks and MCP registration (LORE-043).

Safe by default: ``init`` never publishes or rates a concept. Re-running is
idempotent; an existing different registration is reported, not overwritten,
unless ``--force`` is given. ``--dry-run`` changes nothing.
"""

from __future__ import annotations

import argparse
import subprocess
from typing import Callable, Optional, Sequence

from lore.setup.agents import (
    ADAPTERS,
    SERVER_NAME,
    AgentAdapter,
    AgentError,
    UNKNOWN_SCOPE,
    ServerSpec,
)
from lore.setup.checks import Check, run_checks

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


def run_init(
    argv: Sequence[str],
    *,
    adapters: Optional[dict[str, AdapterFactory]] = None,
    checks_fn: Optional[Callable[..., list[Check]]] = None,
    out: Callable[[str], None] = print,
    spec: Optional[ServerSpec] = None,
) -> int:
    """Run ``init``; returns the process exit code (0 ok, 1 failure/conflict)."""
    args = build_parser().parse_args(list(argv))
    spec = spec or ServerSpec()
    adapter = (adapters or ADAPTERS)[args.agent]()
    prefix = "[dry-run] " if args.dry_run else ""

    out("Checking prerequisites")
    if not _print_checks((checks_fn or run_checks)(semantic=args.semantic), out):
        out("\nSetup stopped: fix the issues above and re-run.")
        return 1

    out(f"\nConfiguring {adapter.name}")
    try:
        existing = adapter.get_registration(spec.name)
        if existing is not None and existing.matches(spec):
            out(f"  ✓ '{spec.name}' already configured ({existing.scope} scope) — nothing to do")
            return 0

        if existing is not None:
            out(f"  ✗ '{spec.name}' is already registered with different settings "
                f"({existing.scope} scope): {existing.command or existing.transport} {' '.join(existing.args)}".rstrip())
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

    out("\nDone." if not args.dry_run else "\nDry run complete — nothing was changed.")
    return 0
