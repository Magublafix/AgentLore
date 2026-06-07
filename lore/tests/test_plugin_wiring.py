"""Layer 1 — Static plugin wiring checks.

Mandatory quality gate. No external process calls, no network, no mocking.
These tests run entirely against the filesystem and stdlib and must pass in CI
with a plain ``pytest lore/tests/`` invocation.

Checks:
1. Skill frontmatter — every ``skills/*/SKILL.md`` has a non-empty description.
2. hooks/hooks.json validity — correct structure with at least one Stop command.
3. Stop hook script exists and is executable.
4. Plugin manifest (.claude-plugin/plugin.json) is valid JSON with required fields.
5. No orphan skill directories — every skills/ subdirectory name is valid
   (alphanumeric + hyphens) and contains a SKILL.md.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Project root resolution — anchored at this file's location.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent  # lore/tests/ -> lore/ -> root
_SKILLS_DIR = _PROJECT_ROOT / "skills"
_HOOKS_JSON = _PROJECT_ROOT / "hooks" / "hooks.json"
_PLUGIN_MANIFEST = _PROJECT_ROOT / ".claude-plugin" / "plugin.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict[str, str]:
    """Return key/value pairs from the first YAML frontmatter block.

    Returns an empty dict when no frontmatter is found.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}
    block = lines[1:end]
    result: dict[str, str] = {}
    for line in block:
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _skill_dirs() -> list[Path]:
    """Return all immediate subdirectories of the skills/ directory."""
    if not _SKILLS_DIR.is_dir():
        return []
    return [p for p in _SKILLS_DIR.iterdir() if p.is_dir()]


# ---------------------------------------------------------------------------
# 1. Skill frontmatter
# ---------------------------------------------------------------------------

class TestSkillFrontmatter:
    """Every skills/*/SKILL.md must have a non-empty description: field."""

    def test_skills_directory_exists(self):
        """The skills/ directory must exist at the project root."""
        assert _SKILLS_DIR.is_dir(), (
            f"skills/ directory not found at {_SKILLS_DIR}. "
            "Expected project structure: <root>/skills/<skill-name>/SKILL.md"
        )

    @pytest.mark.parametrize("skill_dir", _skill_dirs())
    def test_skill_has_skill_md(self, skill_dir: Path):
        """Each skills/<name>/ directory must contain a SKILL.md file."""
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.is_file(), (
            f"Missing SKILL.md in skill directory: {skill_dir}"
        )

    @pytest.mark.parametrize("skill_dir", _skill_dirs())
    def test_skill_has_frontmatter_block(self, skill_dir: Path):
        """SKILL.md must open with a YAML frontmatter block (lines enclosed in ---)."""
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            pytest.skip(f"SKILL.md missing in {skill_dir} — covered by test_skill_has_skill_md")
        text = skill_md.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines and lines[0].strip() == "---", (
            f"{skill_md}: frontmatter block must start on line 1 with '---'. "
            f"First line found: {lines[0]!r}"
        )
        # Closing --- must exist somewhere after line 1.
        assert any(line.strip() == "---" for line in lines[1:]), (
            f"{skill_md}: frontmatter block is never closed with a second '---' line."
        )

    @pytest.mark.parametrize("skill_dir", _skill_dirs())
    def test_skill_frontmatter_has_nonempty_description(self, skill_dir: Path):
        """The frontmatter block must contain a non-empty 'description:' field."""
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            pytest.skip(f"SKILL.md missing in {skill_dir} — covered by test_skill_has_skill_md")
        text = skill_md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert "description" in fm, (
            f"{skill_md}: frontmatter is missing a 'description:' key. "
            f"Parsed frontmatter keys: {list(fm.keys())}"
        )
        assert fm["description"].strip(), (
            f"{skill_md}: 'description:' field is present but empty."
        )


# ---------------------------------------------------------------------------
# 2. hooks/hooks.json validity
# ---------------------------------------------------------------------------

class TestHooksJson:
    """hooks/hooks.json must be valid JSON with the expected structure."""

    def test_hooks_json_exists(self):
        assert _HOOKS_JSON.is_file(), f"hooks/hooks.json not found at {_HOOKS_JSON}"

    def test_hooks_json_is_valid_json(self):
        try:
            json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            pytest.fail(f"hooks/hooks.json is not valid JSON: {exc}")

    def test_hooks_json_has_hooks_key(self):
        data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
        assert "hooks" in data, (
            f"hooks/hooks.json is missing the top-level 'hooks' key. "
            f"Top-level keys present: {list(data.keys())}"
        )

    def test_hooks_json_has_stop_array(self):
        data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
        hooks = data.get("hooks", {})
        assert "Stop" in hooks, (
            f"hooks/hooks.json 'hooks' object is missing a 'Stop' key. "
            f"Keys present: {list(hooks.keys())}"
        )
        assert isinstance(hooks["Stop"], list), (
            f"hooks/hooks.json hooks.Stop must be a JSON array, "
            f"got: {type(hooks['Stop']).__name__}"
        )
        assert len(hooks["Stop"]) > 0, (
            "hooks/hooks.json hooks.Stop array is empty — at least one entry required."
        )

    def test_stop_entries_have_hooks_array(self):
        data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
        stop_entries = data["hooks"]["Stop"]
        for idx, entry in enumerate(stop_entries):
            assert "hooks" in entry, (
                f"hooks/hooks.json hooks.Stop[{idx}] is missing a nested 'hooks' array. "
                f"Entry: {entry!r}"
            )
            nested = entry["hooks"]
            assert isinstance(nested, list) and len(nested) > 0, (
                f"hooks/hooks.json hooks.Stop[{idx}].hooks must be a non-empty array. "
                f"Got: {nested!r}"
            )

    def test_stop_hook_entries_have_nonempty_command(self):
        data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
        stop_entries = data["hooks"]["Stop"]
        for outer_idx, entry in enumerate(stop_entries):
            nested = entry.get("hooks", [])
            for inner_idx, item in enumerate(nested):
                assert "command" in item, (
                    f"hooks/hooks.json hooks.Stop[{outer_idx}].hooks[{inner_idx}] "
                    f"is missing the 'command' field. Item: {item!r}"
                )
                assert isinstance(item["command"], str) and item["command"].strip(), (
                    f"hooks/hooks.json hooks.Stop[{outer_idx}].hooks[{inner_idx}].command "
                    f"is empty or not a string. Value: {item['command']!r}"
                )


# ---------------------------------------------------------------------------
# 3. Stop hook script exists and is executable
# ---------------------------------------------------------------------------

class TestStopHookScript:
    """The script referenced in the Stop hook command must exist and be executable."""

    @staticmethod
    def _resolve_command_path() -> Path:
        """Parse the command from hooks.json and resolve ${CLAUDE_PLUGIN_ROOT}."""
        data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
        # Grab the command from the first Stop entry's first nested hook.
        command = data["hooks"]["Stop"][0]["hooks"][0]["command"]
        # Replace ${CLAUDE_PLUGIN_ROOT} with the project root.
        resolved_command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(_PROJECT_ROOT))
        # Extract the path from e.g. "bash '<path>'" — pull the quoted token.
        # Pattern: any token surrounded by single quotes.
        match = re.search(r"'([^']+)'", resolved_command)
        if match:
            return Path(match.group(1))
        # Fall back: the command might be a bare path.
        tokens = resolved_command.split()
        # Skip the interpreter name (bash/sh) if present.
        for token in tokens:
            candidate = Path(token)
            if candidate.suffix in (".sh", ".py", ".bash") or "/" in token:
                return candidate
        pytest.fail(
            f"Could not extract script path from Stop hook command: {command!r}"
        )

    def test_stop_hook_hooks_json_parseable(self):
        """Precondition: hooks.json is parseable enough to extract a command."""
        if not _HOOKS_JSON.is_file():
            pytest.skip("hooks.json missing — covered by TestHooksJson")
        data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
        try:
            data["hooks"]["Stop"][0]["hooks"][0]["command"]
        except (KeyError, IndexError, TypeError):
            pytest.skip("hooks.json structure incomplete — covered by TestHooksJson")

    def test_stop_hook_script_exists(self):
        """The resolved script path must point to an existing file."""
        if not _HOOKS_JSON.is_file():
            pytest.skip("hooks.json missing")
        script = self._resolve_command_path()
        assert script.is_file(), (
            f"Stop hook script does not exist: {script}\n"
            f"Resolved from CLAUDE_PLUGIN_ROOT={_PROJECT_ROOT}"
        )

    def test_stop_hook_script_is_executable(self):
        """The resolved script must have the executable bit set (os.X_OK)."""
        if not _HOOKS_JSON.is_file():
            pytest.skip("hooks.json missing")
        script = self._resolve_command_path()
        if not script.is_file():
            pytest.skip("script file missing — covered by test_stop_hook_script_exists")
        assert os.access(script, os.X_OK), (
            f"Stop hook script exists but is not executable: {script}\n"
            f"Run: chmod +x {script}"
        )


# ---------------------------------------------------------------------------
# 4. Plugin manifest
# ---------------------------------------------------------------------------

class TestPluginManifest:
    """The .claude-plugin/plugin.json manifest must exist with required fields."""

    def test_plugin_manifest_exists(self):
        assert _PLUGIN_MANIFEST.is_file(), (
            f"Plugin manifest not found at {_PLUGIN_MANIFEST}. "
            "Expected: <project-root>/.claude-plugin/plugin.json"
        )

    def test_plugin_manifest_is_valid_json(self):
        if not _PLUGIN_MANIFEST.is_file():
            pytest.skip("Manifest missing — covered by test_plugin_manifest_exists")
        try:
            json.loads(_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            pytest.fail(f".claude-plugin/plugin.json is not valid JSON: {exc}")

    def test_plugin_manifest_has_nonempty_name(self):
        if not _PLUGIN_MANIFEST.is_file():
            pytest.skip("Manifest missing — covered by test_plugin_manifest_exists")
        data = json.loads(_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        assert "name" in data, (
            f".claude-plugin/plugin.json is missing a 'name' field. "
            f"Keys present: {list(data.keys())}"
        )
        assert isinstance(data["name"], str) and data["name"].strip(), (
            f".claude-plugin/plugin.json 'name' field is empty or not a string. "
            f"Value: {data['name']!r}"
        )

    def test_plugin_manifest_has_nonempty_version(self):
        if not _PLUGIN_MANIFEST.is_file():
            pytest.skip("Manifest missing — covered by test_plugin_manifest_exists")
        data = json.loads(_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        assert "version" in data, (
            f".claude-plugin/plugin.json is missing a 'version' field. "
            f"Keys present: {list(data.keys())}"
        )
        assert isinstance(data["version"], str) and data["version"].strip(), (
            f".claude-plugin/plugin.json 'version' field is empty or not a string. "
            f"Value: {data['version']!r}"
        )

    def test_plugin_manifest_version_is_semver_like(self):
        """Version should look like MAJOR.MINOR.PATCH (strict semver not enforced)."""
        if not _PLUGIN_MANIFEST.is_file():
            pytest.skip("Manifest missing — covered by test_plugin_manifest_exists")
        data = json.loads(_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        version = data.get("version", "")
        assert re.match(r"^\d+\.\d+", version), (
            f".claude-plugin/plugin.json version does not look like a semver string. "
            f"Value: {version!r}"
        )


# ---------------------------------------------------------------------------
# 5. No orphan skill directories
# ---------------------------------------------------------------------------

class TestSkillDirectoryConventions:
    """Every directory under skills/ must be a valid skill name and contain SKILL.md."""

    _VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$")

    @pytest.mark.parametrize("skill_dir", _skill_dirs())
    def test_skill_dir_name_is_valid(self, skill_dir: Path):
        """Skill directory name must contain only alphanumerics and hyphens."""
        name = skill_dir.name
        assert self._VALID_NAME_RE.match(name), (
            f"Skill directory name is invalid: {name!r}. "
            "Names must match [a-zA-Z0-9][a-zA-Z0-9-]* (alphanumeric + hyphens only, "
            "must not start with a hyphen)."
        )

    @pytest.mark.parametrize("skill_dir", _skill_dirs())
    def test_skill_dir_contains_skill_md(self, skill_dir: Path):
        """No SKILL.md-less skill directory should exist — it would be an orphan."""
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.is_file(), (
            f"Orphan skill directory found: {skill_dir}. "
            f"It contains no SKILL.md. Either add a SKILL.md or remove the directory."
        )

    def test_no_skill_md_outside_subdirectory(self):
        """A SKILL.md placed directly under skills/ (not in a subdirectory) is invalid."""
        if not _SKILLS_DIR.is_dir():
            pytest.skip("skills/ directory does not exist")
        top_level_skill_md = _SKILLS_DIR / "SKILL.md"
        assert not top_level_skill_md.exists(), (
            "Found SKILL.md directly under skills/ (not in a subdirectory). "
            "Each skill must live in its own subdirectory: skills/<name>/SKILL.md"
        )
