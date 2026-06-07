"""Layer 2 — Live registration checks.

Skipped unless the environment variable ``LORE_LIVE_TESTS=1`` is set.
Requires a working Claude Code installation with the Lore plugin registered.

Run:
    LORE_LIVE_TESTS=1 pytest lore/tests/test_live_registration.py -v

Tests:
1. Plugin appears in ``claude plugins list``.
2. Lore skills appear in a fresh Claude session.
"""

from __future__ import annotations

import os
import subprocess

import pytest

# ---------------------------------------------------------------------------
# Module-level skip guard — applied to every test in this module.
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    os.environ.get("LORE_LIVE_TESTS") != "1",
    reason="Set LORE_LIVE_TESTS=1 to run live registration tests.",
)

# Mark every test in this module with the 'live' marker as well so they can be
# selected/excluded independently with ``pytest -m live``.
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("LORE_LIVE_TESTS") != "1",
        reason="Set LORE_LIVE_TESTS=1 to run live registration tests.",
    ),
]

_REQUIRED_SKILLS = [
    "lore:wrapup",
    "lore:search-concepts",
    "lore:capture-concept",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    """The Lore plugin must be visible in claude plugins list."""

    def test_lore_appears_in_plugins_list(self):
        """``claude plugins list`` must include 'lore' in its output."""
        result = subprocess.run(
            ["claude", "plugins", "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        assert "lore" in output.lower(), (
            "The Lore plugin does not appear in 'claude plugins list'.\n"
            f"Exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
            "Ensure the plugin is registered: "
            "claude plugins add /path/to/AgentLore/.claude-plugin"
        )


class TestSkillRegistration:
    """All three Lore skills must be visible in a fresh Claude session."""

    def test_skills_appear_in_session(self):
        """``claude --print`` must report lore:wrapup, lore:search-concepts,
        and lore:capture-concept as available skills."""
        result = subprocess.run(
            [
                "claude",
                "--print",
                "List your currently available skills. Output only the skill names,"
                " one per line.",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        missing = [skill for skill in _REQUIRED_SKILLS if skill not in output]
        assert not missing, (
            f"The following Lore skills were not found in the session output: {missing}\n"
            f"Exit code: {result.returncode}\n"
            f"Full output:\n{output}\n"
            "Ensure the Lore plugin is registered and all SKILL.md files are present."
        )
