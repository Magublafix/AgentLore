"""Lore semantic server API — re-export shim.

The canonical implementation has moved to :mod:`lore.server.api`.
This module re-exports ``app`` and ``COLLECTION_NAME`` so that existing import
paths do not hard-break during the transition period.

.. deprecated::
    Import from :mod:`lore.server.api` directly.
"""

from lore.server.api import app  # noqa: F401
from lore.server.storage.gist_qdrant import COLLECTION_NAME  # noqa: F401

# Re-export legacy symbols that tests import directly.
from lore.server.api import lifespan  # noqa: F401
