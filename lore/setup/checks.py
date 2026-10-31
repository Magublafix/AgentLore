"""Prerequisite checks for ``mcp-server-lore init`` (LORE-043).

Every check is a pure function of injected environment facts (``which``,
``version_info``) so it can be tested without touching the real machine. A
failed :class:`Check` always carries a ``fix`` string telling the user exactly
what to do.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import Callable, Optional

MIN_PYTHON = (3, 11)

Which = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class Check:
    """Outcome of one prerequisite check."""

    name: str
    ok: bool
    detail: str
    fix: str = ""


def check_python(version_info: tuple = tuple(sys.version_info[:3])) -> Check:
    """Require Python >= 3.11."""
    found = ".".join(str(p) for p in version_info[:3])
    if tuple(version_info[:2]) >= MIN_PYTHON:
        return Check("python", True, f"Python {found}")
    return Check(
        "python",
        False,
        f"Python {found} is too old (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
        f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ from https://www.python.org/downloads/",
    )


def check_claude_cli(which: Which = shutil.which) -> Check:
    """Require the ``claude`` CLI (used to register the MCP server)."""
    path = which("claude")
    if path:
        return Check("claude", True, f"Claude Code CLI found at {path}")
    return Check(
        "claude",
        False,
        "Claude Code CLI ('claude') not found on PATH",
        "Install Claude Code from https://claude.ai/code, then re-run this command",
    )


def check_uvx(which: Which = shutil.which) -> Check:
    """Require ``uvx`` — the registered server command is ``uvx mcp-server-lore``."""
    path = which("uvx")
    if path:
        return Check("uvx", True, f"uvx found at {path}")
    return Check(
        "uvx",
        False,
        "'uvx' not found on PATH (needed to launch mcp-server-lore)",
        "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
    )


def check_docker(which: Which = shutil.which) -> Check:
    """Require Docker — only needed for the optional semantic-search stack."""
    path = which("docker")
    if path:
        return Check("docker", True, f"Docker found at {path}")
    return Check(
        "docker",
        False,
        "Docker not found on PATH (needed for the semantic search stack)",
        "Install Docker from https://docs.docker.com/get-docker/ or omit --semantic",
    )


def run_checks(
    semantic: bool = False,
    which: Which = shutil.which,
    version_info: tuple = tuple(sys.version_info[:3]),
    local: bool = False,
) -> list[Check]:
    """Run all prerequisite checks.

    Docker is checked only when ``semantic``; ``uvx`` is skipped when ``local``
    (``init --local`` registers this interpreter instead of ``uvx``).
    """
    checks = [check_python(version_info), check_claude_cli(which)]
    if not local:
        checks.append(check_uvx(which))
    if semantic:
        checks.append(check_docker(which))
    return checks
