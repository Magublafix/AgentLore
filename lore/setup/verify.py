"""End-to-end install verification for ``mcp-server-lore init`` (LORE-044).

Starts the registered MCP server over stdio with ``fastmcp.Client``, checks the
five tools are listed and runs exactly one ``search_concepts`` call. The write
tools (``submit_concept``, ``link_concepts``, ``rate_concept``) are never
called. The server's stderr is captured, redacted and only shown on failure;
the environment is never printed.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from lore.core.auth import redact

EXPECTED_TOOLS = frozenset(
    {"search_concepts", "get_concept", "submit_concept", "link_concepts", "rate_concept"}
)
VERIFY_QUERY = "REST CLI around a REST API"
TIMEOUT_SECONDS = 30.0

ClientFactory = Callable[[str, Sequence[str], Mapping[str, str], Path], Any]


@dataclass
class VerifyResult:
    """Outcome of :func:`verify_install`."""

    ok: bool
    message: str
    tools: list[str] = field(default_factory=list)
    result_count: int = 0
    warnings: list[str] = field(default_factory=list)
    first_result: Optional[str] = None


def default_client_factory(
    command: str, args: Sequence[str], env: Mapping[str, str], log_path: Path
) -> Any:
    """Build a ``fastmcp.Client`` that spawns ``command args`` with ``env`` over stdio."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=command,
        args=list(args),
        env=dict(env),
        keep_alive=False,
        log_file=log_path,
    )
    return Client(transport)


def _payload(result: Any) -> dict:
    """Extract the dict returned by a tool call."""
    data = getattr(result, "structured_content", None)
    if isinstance(data, dict) and data:
        return data
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


async def _run(
    factory: ClientFactory,
    command: str,
    args: Sequence[str],
    env: Mapping[str, str],
    log_path: Path,
) -> VerifyResult:
    client = factory(command, args, env, log_path)
    async with client:
        tools = sorted(t.name for t in await client.list_tools())
        missing = sorted(EXPECTED_TOOLS - set(tools))
        if missing:
            return VerifyResult(False, f"server is missing tools: {', '.join(missing)}", tools)
        # Exactly one real call, and only to the read-only search tool.
        raw = await client.call_tool("search_concepts", {"problem": VERIFY_QUERY, "limit": 3})
    payload = _payload(raw)
    results = payload.get("results")
    if not isinstance(results, list):
        err = payload.get("error") or "unexpected response shape"
        return VerifyResult(False, f"search_concepts returned an error: {err}", tools)
    warnings = []
    if payload.get("fallback"):
        warnings.append(
            "search used the fallback backend: the semantic server was unreachable "
            "(check LORE_SEMANTIC_URL)"
        )
    first = results[0].get("name") if results and isinstance(results[0], dict) else None
    return VerifyResult(
        True, "search_concepts works", tools, len(results), warnings, first
    )


def verify_install(
    command: str,
    args: Sequence[str],
    env: Mapping[str, str],
    *,
    secrets: Sequence[str] = (),
    client_factory: ClientFactory = default_client_factory,
    timeout: float = TIMEOUT_SECONDS,
) -> VerifyResult:
    """Spawn the registered server, list its tools and run one ``search_concepts``.

    Args:
        command, args: The registered launch command.
        env: The registration environment, plus the resolved token (in memory only).
        secrets: Values to redact from any message.
        client_factory: Injectable ``fastmcp.Client`` factory (for tests).
        timeout: Overall deadline in seconds.

    Returns:
        A :class:`VerifyResult`; never raises for server/transport failures.
    """
    with tempfile.TemporaryDirectory(prefix="lore-verify-") as tmp:
        log_path = Path(tmp) / "server-stderr.log"
        try:
            result = asyncio.run(
                asyncio.wait_for(_run(client_factory, command, args, env, log_path), timeout)
            )
        except asyncio.TimeoutError:
            reason = f"timed out after {timeout:g}s"
            result = VerifyResult(False, reason)
        except Exception as exc:  # noqa: BLE001 — any spawn/protocol failure is a verify failure
            result = VerifyResult(False, f"{type(exc).__name__}: {exc}")
        if not result.ok:
            try:
                tail = log_path.read_text(errors="replace").strip().splitlines()[-8:]
            except OSError:
                tail = []
            if tail:
                result.message += "\nserver stderr (last lines):\n  " + "\n  ".join(tail)
    result.message = redact(result.message, secrets)
    result.warnings = [redact(w, secrets) for w in result.warnings]
    return result
