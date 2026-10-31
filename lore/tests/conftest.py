# Lore test suite — shared pytest configuration.

import os
import shutil
import tempfile

import pytest

_REAL_HOME = os.environ.get("HOME")
_TEST_HOME: str | None = None


def pytest_configure(config):
    """Register markers and isolate the whole run from the real home directory.

    Several modules compute paths such as ``~/.lore/session.json`` or
    ``~/.lore/watcher_cursor.json`` at import time (``Path("~/...").expanduser()``),
    so a per-test fixture is too late. Pointing ``HOME`` at a throwaway directory
    before collection guarantees no test can read or write the developer's real
    ``~/.lore`` or agent config. Live tests (``LORE_LIVE_TESTS=1``) keep the real
    home because they need the real Claude Code installation.
    """
    global _TEST_HOME
    config.addinivalue_line(
        "markers",
        "live: mark test as requiring a live Claude Code installation "
        "(skipped unless LORE_LIVE_TESTS=1).",
    )
    if os.environ.get("LORE_LIVE_TESTS") != "1":
        _TEST_HOME = tempfile.mkdtemp(prefix="lore-test-home-")
        os.environ["HOME"] = _TEST_HOME
        os.environ.pop("LORE_SESSION_FILE", None)
        os.environ.pop("LORE_DB_PATH", None)


def pytest_unconfigure(config):
    """Remove the throwaway home and restore ``HOME``."""
    global _TEST_HOME
    if _TEST_HOME is not None:
        if _REAL_HOME is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = _REAL_HOME
        shutil.rmtree(_TEST_HOME, ignore_errors=True)
        _TEST_HOME = None


@pytest.fixture(scope="session", autouse=True)
def _assert_home_is_isolated():
    """Fail loudly if the suite ever runs against the real home directory."""
    if os.environ.get("LORE_LIVE_TESTS") != "1":
        assert _TEST_HOME is not None and os.environ["HOME"] == _TEST_HOME
    yield
