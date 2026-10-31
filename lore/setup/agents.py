"""Coding-agent adapters for ``mcp-server-lore init`` (LORE-043).

An :class:`AgentAdapter` knows how to read, create and remove one MCP server
registration in one coding agent. Claude Code is the only adapter shipped; a
new agent is added by implementing the interface and listing it in
:data:`ADAPTERS`.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

SERVER_NAME = "lore"


@dataclass(frozen=True)
class ServerSpec:
    """The MCP server registration Lore wants to exist."""

    name: str = SERVER_NAME
    command: str = "uvx"
    args: tuple[str, ...] = ("mcp-server-lore",)
    env: dict[str, str] = field(default_factory=lambda: {"LORE_BACKEND": "gists"})


@dataclass(frozen=True)
class Registration:
    """An MCP server registration that already exists in the agent."""

    transport: str
    command: str
    args: tuple[str, ...]
    env: dict[str, str]
    scope: str

    def matches(self, spec: ServerSpec) -> bool:
        """True when this registration already satisfies ``spec``.

        Extra environment variables (e.g. a token added later) do not count
        as a conflict; a different command, args or env value does.
        """
        return (
            self.transport == "stdio"
            and self.command == spec.command
            and self.args == spec.args
            and all(self.env.get(k) == v for k, v in spec.env.items())
        )


class AgentError(RuntimeError):
    """An agent CLI call failed; the message is safe to show the user."""


class AgentAdapter(ABC):
    """Reads and writes MCP server registrations for one coding agent."""

    name: str

    @abstractmethod
    def get_registration(self, server: str) -> Optional[Registration]:
        """Return the existing registration, or ``None`` when absent."""

    @abstractmethod
    def register(self, spec: ServerSpec, scope: str) -> None:
        """Create the registration."""

    @abstractmethod
    def remove(self, server: str, scope: str) -> None:
        """Delete the registration."""


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _run(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


_SCOPES = {"user": "user", "local": "local", "project": "project"}
UNKNOWN_SCOPE = "unknown"


def parse_claude_get(output: str) -> Optional[Registration]:
    """Parse ``claude mcp get <name>`` output.

    Returns ``None`` only when the CLI says no such server exists. Output that
    is neither that message nor a recognisable registration raises
    :class:`AgentError` — it must never be mistaken for "absent". Non-stdio
    servers (http/sse) are returned with an empty ``command`` so they register
    as a conflict. An unrecognised scope is reported as ``"unknown"``.
    """
    if "No MCP server named" in output:
        return None
    fields: dict[str, str] = {}
    env: dict[str, str] = {}
    in_env = False
    for raw in output.splitlines():
        line = raw.strip()
        if in_env and "=" in line and not line.endswith(":"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
            continue
        in_env = False
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key == "Environment":
            in_env = True
        elif key in ("Scope", "Type", "Command", "Args", "URL"):
            fields[key] = value.strip()
    if "Command" not in fields and "Type" not in fields:
        raise AgentError(
            "could not understand the output of 'claude mcp get' — "
            "is your Claude Code CLI up to date?"
        )
    scope_text = fields.get("Scope", "").lower()
    scope = next((v for k, v in _SCOPES.items() if scope_text.startswith(k)), UNKNOWN_SCOPE)
    return Registration(
        transport=fields.get("Type", "stdio"),
        command=fields.get("Command", ""),
        args=tuple(fields.get("Args", "").split()),
        env=env,
        scope=scope,
    )


class ClaudeCodeAdapter(AgentAdapter):
    """Claude Code, driven through its own ``claude mcp`` CLI."""

    name = "Claude Code"

    def __init__(self, runner: Runner = _run) -> None:
        self._run = runner

    def get_registration(self, server: str) -> Optional[Registration]:
        result = self._run(["claude", "mcp", "get", server])
        output = result.stdout + result.stderr
        if "No MCP server named" in output:
            return None
        if result.returncode != 0:
            detail = output.strip() or "no output"
            raise AgentError(f"'claude mcp get' failed: {detail}")
        return parse_claude_get(output)

    def register(self, spec: ServerSpec, scope: str) -> None:
        cmd = ["claude", "mcp", "add", spec.name, "-s", scope]
        for key, value in spec.env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += ["--", spec.command, *spec.args]
        self._check(self._run(cmd), "register")

    def remove(self, server: str, scope: str) -> None:
        self._check(self._run(["claude", "mcp", "remove", server, "-s", scope]), "remove")

    @staticmethod
    def _check(result: "subprocess.CompletedProcess[str]", action: str) -> None:
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "no output"
            raise AgentError(f"'claude mcp {action}' failed: {detail}")


ADAPTERS: dict[str, Callable[[], AgentAdapter]] = {"claude": ClaudeCodeAdapter}
