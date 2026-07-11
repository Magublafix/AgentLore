"""Lore self-hosted API — re-export shim.

The canonical implementation has moved to :mod:`lore.server.api`.
This module re-exports ``app`` and ``COLLECTION_NAME`` so that existing import
paths do not hard-break during the transition period.

.. deprecated::
    Import from :mod:`lore.server.api` directly.
"""

from lore.server.api import app  # noqa: F401
from lore.server.storage.sqlite_qdrant import COLLECTION_NAME  # noqa: F401

# Re-export legacy symbols that tests import directly.
from lore.server.api import (  # noqa: F401
    ConceptSubmitRequest,
    SearchRequest,
    LinkRequest,
    RateRequest,
    VALID_CONCEPT_TYPES,
    VALID_LINK_RELS,
    lifespan,
)

# Re-export patched module-level names that test_api.py patches by dotted path.
# These must resolve to the same objects that the server uses.
from lore.core.scanner import scan_content  # noqa: F401
from lore.selfhosted.indexer import index_concept, search_concepts  # noqa: F401
