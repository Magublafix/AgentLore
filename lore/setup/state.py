"""Local state initialisation for ``mcp-server-lore init`` (LORE-044).

Creates ``~/.lore/`` and an empty ``session.json`` only when absent. Anything
that already exists is left exactly as it is. Symlink policy: a ``~/.lore``
symlink that resolves to an existing directory is used as-is (dotfile managers
do this); ``session.json`` is only created when nothing — not even a symlink —
exists at that path, and is never written through a symlink; a dangling or
non-directory ``~/.lore`` is left alone with a warning.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional


def ensure_state(
    home: Optional[Path] = None, warn: Optional[Callable[[str], None]] = None
) -> list[Path]:
    """Create ``<home>/.lore`` (0700) and ``session.json`` (``[]``, 0600) if absent.

    Args:
        home: Home directory (defaults to ``Path.home()``).
        warn: Called with a message when ``~/.lore`` exists but is unusable
            (dangling symlink or not a directory); nothing is created then.

    Returns:
        The paths that were created; empty when everything already existed.
    """
    home = Path.home() if home is None else Path(home)
    created: list[Path] = []
    state_dir = home / ".lore"
    if not os.path.lexists(state_dir):
        os.mkdir(state_dir, 0o700)
        created.append(state_dir)
    elif not state_dir.is_dir():
        if warn:
            warn(f"{state_dir} exists but is not a usable directory (dangling symlink or file); "
                 "left untouched, so no session state was created")
        return created
    session = state_dir / "session.json"
    if not os.path.lexists(session):
        try:
            # O_EXCL also refuses to follow a symlink planted at this path.
            fd = os.open(session, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # created concurrently: leave it alone
            return created
        with os.fdopen(fd, "w") as fh:
            fh.write("[]")
        created.append(session)
    return created
