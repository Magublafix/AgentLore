"""Tests for lore.core.scanner (LORE-005).

Covers:
- Credential pattern detection (labelled and unlabelled)
- Internal URL detection (localhost, .internal, .corp, .local)
- Custom blocklist via LORE_BLOCK_PATTERNS env var
- Clean content passes through unchanged
- Structured output format
- Edge cases: None values, non-string values, empty input
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from lore.core.scanner import scan_content, reload_custom_patterns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan(fields: dict) -> list[dict]:
    """Thin wrapper so tests remain readable."""
    return scan_content(fields)


# ---------------------------------------------------------------------------
# Credential detection
# ---------------------------------------------------------------------------


class TestCredentialPatterns:
    """Credential label + value patterns."""

    def test_api_key_colon(self):
        result = _scan({"content": "api_key: abcdef1234567890"})
        assert len(result) == 1
        assert result[0]["field"] == "content"
        assert "credential" in result[0]["reason"]
        assert "api_key" in result[0]["match"].lower() or "abcdef" in result[0]["match"]

    def test_api_key_equals(self):
        result = _scan({"content": "api-key=MYSECRETTOKEN123"})
        assert len(result) == 1
        assert "credential" in result[0]["reason"]

    def test_token_label(self):
        result = _scan({"content": "token: ghp_abc123def456ghi789"})
        assert len(result) == 1
        assert "credential" in result[0]["reason"]

    def test_bearer_label(self):
        result = _scan({"content": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdefgh"})
        assert len(result) == 1
        assert "credential" in result[0]["reason"]

    def test_secret_label(self):
        result = _scan({"content": "secret=supersecretkeyvalue"})
        assert len(result) == 1

    def test_case_insensitive_label(self):
        result = _scan({"content": "API_KEY=ABCDEFGHIJKLMNOP"})
        assert len(result) == 1

    def test_short_value_not_flagged(self):
        """Values shorter than 8 chars after the label are not flagged."""
        result = _scan({"content": "token: abc"})
        assert len(result) == 0

    def test_multiple_fields_multiple_violations(self):
        """Each field is checked independently."""
        result = _scan({
            "name": "api_key: abcdef1234567890",
            "content": "token: ghp_abc123def456",
        })
        # Both fields should produce violations
        assert len(result) == 2
        fields = {v["field"] for v in result}
        assert "name" in fields
        assert "content" in fields


# ---------------------------------------------------------------------------
# Long hex / base64 detection
# ---------------------------------------------------------------------------


class TestRawSecretPatterns:
    """Unlabelled hex and base64 strings that may be raw secrets."""

    def test_long_hex_flagged(self):
        """32+ character hex string is flagged."""
        result = _scan({"content": "deadbeefcafebabe0102030405060708"})
        assert len(result) == 1
        assert "hex" in result[0]["reason"].lower()

    def test_short_hex_not_flagged(self):
        """31-char hex is not flagged (below threshold)."""
        result = _scan({"content": "deadbeefcafebabe010203040506070"})
        assert len(result) == 0

    def test_long_base64_flagged(self):
        """40+ character base64-looking string is flagged."""
        b64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn=="
        result = _scan({"content": b64})
        assert len(result) == 1
        assert "base64" in result[0]["reason"].lower()

    def test_short_base64_not_flagged(self):
        """39-char base64 string is not flagged."""
        result = _scan({"content": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm"})
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Internal URL detection
# ---------------------------------------------------------------------------


class TestInternalUrlPatterns:
    """localhost, .internal, .corp, .local host detection."""

    def test_localhost_bare_flagged(self):
        result = _scan({"content": "connecting to http://localhost:8080/api"})
        assert len(result) == 1
        assert "internal" in result[0]["reason"].lower()

    def test_internal_domain_flagged(self):
        result = _scan({"content": "POST https://payments.internal/v1/charge"})
        assert len(result) == 1

    def test_corp_domain_flagged(self):
        result = _scan({"content": "see docs at https://wiki.corp/engineering"})
        assert len(result) == 1

    def test_local_domain_flagged(self):
        result = _scan({"content": "http://myapp.local/api"})
        assert len(result) == 1

    def test_localhost_in_quotes_not_flagged(self):
        """'localhost' inside quotes is treated as an example and not flagged."""
        result = _scan({"content": "set LORE_URL to 'localhost' for dev"})
        assert len(result) == 0

    def test_localhost_in_double_quotes_not_flagged(self):
        result = _scan({"content": 'default value is "localhost"'})
        assert len(result) == 0

    def test_example_domain_not_flagged(self):
        """example.com, test.com etc. are fine."""
        result = _scan({"content": "see https://example.com for docs"})
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Custom blocklist
# ---------------------------------------------------------------------------


class TestCustomBlocklist:
    """LORE_BLOCK_PATTERNS semicolon-separated custom patterns."""

    def test_custom_pattern_blocks(self):
        with patch.dict(os.environ, {"LORE_BLOCK_PATTERNS": "secret-project"}):
            reload_custom_patterns()
            result = _scan({"content": "this is for secret-project only"})
        reload_custom_patterns()  # reset
        assert len(result) == 1
        assert "custom pattern" in result[0]["reason"]
        assert "secret-project" in result[0]["reason"]

    def test_multiple_custom_patterns(self):
        with patch.dict(os.environ, {"LORE_BLOCK_PATTERNS": "acme-internal;top-secret"}):
            reload_custom_patterns()
            result1 = _scan({"content": "acme-internal service"})
            result2 = _scan({"content": "this is top-secret"})
        reload_custom_patterns()
        assert len(result1) == 1
        assert len(result2) == 1

    def test_invalid_pattern_skipped(self):
        """A malformed regex in LORE_BLOCK_PATTERNS is skipped, not fatal."""
        with patch.dict(os.environ, {"LORE_BLOCK_PATTERNS": "[invalid(;valid-word"}):
            reload_custom_patterns()
            # The valid pattern should still work
            result = _scan({"content": "contains valid-word here"})
        reload_custom_patterns()
        assert len(result) == 1

    def test_empty_blocklist_no_violations(self):
        with patch.dict(os.environ, {"LORE_BLOCK_PATTERNS": ""}):
            reload_custom_patterns()
            result = _scan({"content": "completely harmless content"})
        reload_custom_patterns()
        assert len(result) == 0

    def test_env_var_absent_returns_empty(self, monkeypatch):
        """reload_custom_patterns() returns empty list without error when LORE_BLOCK_PATTERNS is absent."""
        monkeypatch.delenv("LORE_BLOCK_PATTERNS", raising=False)
        reload_custom_patterns()
        result = _scan({"content": "completely harmless content"})
        assert result == []


# ---------------------------------------------------------------------------
# Clean content
# ---------------------------------------------------------------------------


class TestCleanContent:
    """Content that should pass through without violations."""

    def test_plain_description_is_clean(self):
        result = _scan({
            "name": "SQLite WAL Mode",
            "content": "Enable WAL mode with PRAGMA journal_mode=WAL for concurrent writes.",
            "when_to_use": "Use when you need crash-safe concurrent SQLite access.",
        })
        assert result == []

    def test_code_snippet_without_secrets_is_clean(self):
        result = _scan({"content": "```python\nimport sqlite3\nconn = sqlite3.connect(':memory:')\n```"})
        assert result == []

    def test_empty_dict_is_clean(self):
        assert _scan({}) == []

    def test_none_values_skipped(self):
        result = _scan({"name": "Safe Name", "dont_use_when": None})
        assert result == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary and unusual input conditions."""

    def test_non_string_value_coerced(self):
        """Non-string values are coerced to str before scanning."""
        # An integer field should not raise
        result = _scan({"count": 12345})
        assert isinstance(result, list)

    def test_match_truncated_to_80_chars(self):
        """Match snippets in violation dicts are capped at 80 characters."""
        long_value = "api_key: " + "x" * 200
        result = _scan({"content": long_value})
        assert len(result) == 1
        assert len(result[0]["match"]) <= 80

    def test_first_violation_per_field_only(self):
        """Only one violation is reported per field even if multiple patterns match."""
        # api_key triggers credential; also has localhost — only credential fires
        result = _scan({"content": "api_key: secret123 — endpoint at localhost/api"})
        matching_fields = [v for v in result if v["field"] == "content"]
        assert len(matching_fields) == 1
        # Credential check must fire before internal URL check.
        assert "credential" in result[0]["reason"]

    def test_violation_dict_has_required_keys(self):
        result = _scan({"content": "api_key: abcdefghijklmnop"})
        assert len(result) == 1
        viol = result[0]
        assert "field" in viol
        assert "reason" in viol
        assert "match" in viol
