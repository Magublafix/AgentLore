"""API key store and GitHub token verification for the Lore semantic server.

Provides SQLite-backed key issuance (one key per GitHub user) and a
verify_github_token helper that calls the GitHub REST API to confirm token
validity before issuing a key.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx


class KeyStore:
    """SQLite-backed API key store for the Lore semantic server.

    Stores one API key per GitHub user in ~/.lore/semantic-keys.db.
    Keys are 64-character hex strings (secrets.token_hex(32)).

    Args:
        db_path: Path to the SQLite database file.
            Defaults to ~/.lore/semantic-keys.db.
    """

    _DEFAULT_PATH = Path("~/.lore/semantic-keys.db")

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Open (or create) the key store database.

        Creates the ~/.lore/ directory if it does not exist.
        Enables WAL mode and foreign key enforcement on every connection.

        Args:
            db_path: Override path for the SQLite database. Used in tests.
        """
        resolved = Path(db_path).expanduser() if db_path else self._DEFAULT_PATH.expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(resolved), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                github_user_id TEXT PRIMARY KEY,
                github_login   TEXT NOT NULL,
                api_key        TEXT NOT NULL UNIQUE,
                created_at     TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get_or_create(self, github_user_id: str, github_login: str) -> str:
        """Return the existing API key for this GitHub user, or create a new one.

        Idempotent: calling with the same github_user_id always returns the
        same key. Uses INSERT OR IGNORE + SELECT to be safe under concurrent
        writers.

        Args:
            github_user_id: GitHub numeric user ID as a string.
            github_login: GitHub username (login handle).

        Returns:
            The 64-character hex API key for this user.
        """
        new_key = secrets.token_hex(32)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO api_keys (github_user_id, github_login, api_key, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (github_user_id, github_login, new_key, now),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT api_key FROM api_keys WHERE github_user_id = ?",
            (github_user_id,),
        ).fetchone()
        return row[0]

    def validate(self, api_key: str) -> bool:
        """Return True if api_key exists in the key store.

        Args:
            api_key: The bearer token to validate.

        Returns:
            True if the key exists, False otherwise (including empty string).
        """
        if not api_key:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM api_keys WHERE api_key = ?",
            (api_key,),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()


def verify_github_token(github_token: str) -> dict:
    """Call the GitHub REST API to verify a personal access token.

    Args:
        github_token: A GitHub personal access token or OAuth token.

    Returns:
        A dict with ``{"id": int, "login": str}`` on success.

    Raises:
        httpx.HTTPStatusError: If GitHub returns 401 or 403.
        httpx.HTTPError: On network failure or timeout.
    """
    response = httpx.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    return {"id": data["id"], "login": data["login"]}
