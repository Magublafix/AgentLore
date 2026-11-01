"""Minimal stdlib MCP stdio client used to spawn the REGISTERED server command.

Deliberately independent of ``fastmcp`` / ``lore`` so the test runner needs only pytest and
the black-box artifacts (wheel, ``uvx``, ``claude``) are what get exercised.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence


class McpError(RuntimeError):
    pass


class McpStdioSession:
    def __init__(self, command: str, args: Sequence[str], env: Mapping[str, str], cwd: str,
                 timeout: float = 120.0) -> None:
        self.timeout = timeout
        self._next_id = 0
        self._lines: "queue.Queue[str | None]" = queue.Queue()
        self.proc = subprocess.Popen(
            [command, *args], env=dict(env), cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self.stderr_chunks: list[str] = []
        threading.Thread(target=self._pump_out, daemon=True).start()
        threading.Thread(target=self._pump_err, daemon=True).start()

    def _pump_out(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _pump_err(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self.stderr_chunks.append(line)

    @property
    def stderr(self) -> str:
        return "".join(self.stderr_chunks)

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> Any:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError(f"timeout waiting for {method}")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise McpError(f"timeout waiting for {method}") from None
            if line is None:
                raise McpError(f"server exited before answering {method}: {self.stderr[-500:]}")
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # non-protocol noise on stdout
            if msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(f"{method} failed: {msg['error']}")
                return msg["result"]

    def initialize(self) -> dict:
        result = self.request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "lore-e2e", "version": "0"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def list_tools(self) -> list[dict]:
        return self.request("tools/list")["tools"]

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Return the tool's JSON payload (structuredContent, else parsed text content)."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        sc = result.get("structuredContent")
        if isinstance(sc, dict) and sc:
            return sc
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    parsed = json.loads(block["text"])
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return {"_raw": result}

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            self.proc.wait(timeout=5)

    def __enter__(self) -> "McpStdioSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def spawn_env_without_inherit(base: Mapping[str, str], registered: Mapping[str, str]) -> dict[str, str]:
    """Registered env layered over the sandbox base env (never ``os.environ``)."""
    return {**base, **registered}


_ = os  # keep import for callers extending this module
