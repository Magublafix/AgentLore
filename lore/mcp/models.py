"""Shared dataclasses for Lore concepts, links, and ratings.

These are the canonical in-memory representations used throughout the MCP
server and selfhosted backend.  They are deliberately backend-agnostic — no
SQLite or Qdrant imports here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Concept:
    """A typed node in the Lore knowledge graph.

    Attributes:
        concept_id: UUID primary key (str form).
        name: Short human-readable name for the concept.
        type: One of project | pattern | tool | testing | architecture.
        content: Markdown body — the blueprint, pattern description, or
            strategy text.
        language: Programming language context (e.g. "python", "typescript",
            "generic"). May be None for language-agnostic concepts.
        when_to_use: Natural-language description of the ideal use context.
            This field (concatenated with ``name``) is the embedding target.
        dont_use_when: Known anti-cases / counter-indications.  May be None.
        tags: Deserialized list of tag strings (stored as JSON text in SQLite).
        source_url: Origin URL — GitHub, docs page, prior agent session, etc.
        author: Free-text author identifier.
        avg_rating: Rolling average of all ``outcome`` values from ratings.
        usage_count: Total number of times the concept has been retrieved.
        time_saved_avg_hours: Rolling average of ``hours_saved`` values
            reported by raters.  None until at least one rating provides a
            value.
        created_at: ISO-8601 UTC timestamp string.
        embedding: Raw float32 BLOB from sqlite-vec, or None before the
            embedding pipeline has run.
    """

    concept_id: str
    name: str
    type: str
    content: str
    language: str | None
    when_to_use: str
    dont_use_when: str | None
    tags: list[str] = field(default_factory=list)
    source_url: str | None = None
    author: str | None = None
    avg_rating: float = 0.0
    usage_count: int = 0
    time_saved_avg_hours: float | None = None
    created_at: str = ""
    embedding: bytes | None = None


@dataclass
class Link:
    """A directed, typed edge between two Concept nodes.

    Attributes:
        link_id: UUID primary key (str form).
        from_id: concept_id of the source concept.
        to_id: concept_id of the target concept.
        rel: Relationship type — one of uses | tested_by | extends |
            alternative_to | requires.
        label: Optional human-readable edge description.
    """

    link_id: str
    from_id: str
    to_id: str
    rel: str
    label: str | None = None


@dataclass
class Rating:
    """A single agent rating event for a concept.

    Attributes:
        rating_id: UUID primary key (str form).
        concept_id: The concept being rated.
        session_id: The agent session that produced this rating.  May be None
            if the caller did not provide a session identifier.
        outcome: Integer score 1–5.
        hours_saved: Estimated hours saved versus solving from scratch.
            This is the primary signal; ``outcome`` is secondary.
        notes: Free-text notes from the rater.
        rated_at: ISO-8601 UTC timestamp string.
    """

    rating_id: str
    concept_id: str
    session_id: str | None
    outcome: int
    hours_saved: float | None = None
    notes: str | None = None
    rated_at: str = ""
