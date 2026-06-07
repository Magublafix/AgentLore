# Lore test suite — shared pytest configuration.

import pytest


def pytest_configure(config):
    """Register custom markers so pytest does not warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "live: mark test as requiring a live Claude Code installation "
        "(skipped unless LORE_LIVE_TESTS=1).",
    )
