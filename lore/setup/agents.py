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

from lore.core.auth import redact

SERVER_NAME = "lore"


@dataclass(frozen=True)
class ServerSpec:
    """The MCP server registration Lore wants to exist."""

    name: str = SERVER_NAME
    command: str = "uvx"
    args: tuple[str, ...] = ("mcp-server-lore",)
    env: dict[str, str] = field(default_factory=lambda: {"LORE_BACKEND": "gists"})
    # Values stored in the agent config (only with --store-token). Kept apart so
    # they never take part in matching or repr, and can be redacted from output.
    secrets: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def secret_values(self) -> list[str]:
        """All secret values, for redaction."""
        return [v for v in self.secrets.values() if v]


@dataclass(frozen=True)
class Registration:
    """An MCP server registration that already exists in the agent."""

    transport: str
    command: str
    args: tuple[str, ...]
    env: dict[str, str] = field(repr=False)
    scope: str

    def __repr__(self) -> str:
        """Show env keys only — values may be secrets."""
        return (
            f"Registration(transport={self.transport!r}, command={self.command!r}, "
            f"args={self.args!r}, env_keys={sorted(self.env)!r}, scope={self.scope!r})"
        )

    def mismatch_reason(self, spec: ServerSpec) -> Optional[str]:
        """Why this registration does not satisfy ``spec``; ``None`` when it does.

        Extra environment variables do not count as a conflict; a different
        command, args or env value does. ``LORE_READ_ONLY`` must agree in both
        directions. When ``spec`` asks to store a token, the stored value is
        compared with the registered ``LORE_GITHUB_TOKEN`` (neither is ever
        shown); without a stored token in ``spec`` secrets are ignored.
        """
        ro_here = self.env.get("LORE_READ_ONLY") == "1"
        ro_spec = spec.env.get("LORE_READ_ONLY") == "1"
        if ro_here and not ro_spec:
            return "registered in read-only mode, but a token is now available"
        if ro_spec and not ro_here:
            return "registered with a token, but no token is available now (read-only mode)"
        if self.transport != "stdio":
            return f"registered as a {self.transport} server, not a local stdio command"
        if self.command != spec.command or self.args != spec.args:
            return "different command or arguments"
        if any(self.env.get(k) != v for k, v in spec.env.items()):
            return "different settings (environment variables)"
        for key, value in spec.secrets.items():
            if self.env.get(key) != value:
                return f"the stored {key} differs from the current one"
        return None

    def matches(self, spec: ServerSpec) -> bool:
        """True when this registration already satisfies ``spec`` (see :meth:`mismatch_reason`)."""
        return self.mismatch_reason(spec) is None


class AgentError(RuntimeError):
    """An agent CLI call failed; the message is safe to show the user."""


class AgentAdapter(ABC):
    """Reads and writes MCP server registrations for one coding agent."""

    name: str
    secrets: list[str]  # values to redact from CLI error text (set by init)

    def __init__(self) -> None:
        self.secrets = []

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
        super().__init__()
        self._run = runner

    def get_registration(self, server: str) -> Optional[Registration]:
        result = self._run(["claude", "mcp", "get", server])
        output = result.stdout + result.stderr
        if "No MCP server named" in output:
            return None
        if result.returncode != 0:
            detail = redact(output.strip(), self.secrets) or "no output"
            raise AgentError(f"'claude mcp get' failed: {detail}")
        return parse_claude_get(output)

    def register(self, spec: ServerSpec, scope: str) -> None:
        cmd = ["claude", "mcp", "add", spec.name, "-s", scope]
        for key, value in {**spec.env, **spec.secrets}.items():
            # NOTE: a stored secret is visible in this process's argv while it runs.
            cmd += ["-e", f"{key}={value}"]
        cmd += ["--", spec.command, *spec.args]
        self._check(self._run(cmd), "register", [*spec.secret_values(), *self.secrets])

    def remove(self, server: str, scope: str) -> None:
        self._check(self._run(["claude", "mcp", "remove", server, "-s", scope]), "remove", self.secrets)

    @staticmethod
    def _check(
        result: "subprocess.CompletedProcess[str]", action: str, secrets: list[str] | None = None
    ) -> None:
        if result.returncode != 0:
            detail = redact((result.stderr or result.stdout).strip(), secrets or []) or "no output"
            raise AgentError(f"'claude mcp {action}' failed: {detail}")


ADAPTERS: dict[str, Callable[[], AgentAdapter]] = {"claude": ClaudeCodeAdapter}
