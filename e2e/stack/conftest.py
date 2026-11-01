"""Hooks and fixtures for the semantic-server stack E2E (see harness.py for the knobs)."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from harness import OUT, REPO, base_env


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e_stack: semantic-server stack E2E (stub GitHub, in-memory Qdrant)")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.e2e_stack)


@pytest.fixture(scope="session", autouse=True)
def _installed_code_check() -> None:
    python = os.environ.get("LORE_STACK_PYTHON", sys.executable)
    env = base_env(Path("/nonexistent"), os.environ.get("LORE_STACK_PYTHONPATH") or None)
    out = subprocess.run([python, "-c", "import lore, sys; print(lore.__file__)"], env=env,
                         cwd=str(Path(__file__).parent), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    where = Path(out.stdout.strip()).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lore-origin.txt").write_text(f"{where}\n")
    if os.environ.get("LORE_STACK_REQUIRE_INSTALLED") == "1":
        assert REPO.resolve() not in where.parents, f"lore imported from the checkout: {where}"


@pytest.fixture
def fake_token() -> str:
    return "ghp_E2ESTACK" + secrets.token_hex(12)


