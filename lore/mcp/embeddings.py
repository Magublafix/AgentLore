"""Embedding pipeline for the Lore MCP server.

Wraps ``sentence-transformers`` so that the rest of the codebase never imports
it directly.  The model is loaded once at construction time and reused for all
subsequent calls.

The embedding target for every :class:`~lore.mcp.models.Concept` is::

    when_to_use + " " + name

This is the primary retrieval surface.  ``content`` is deliberately *not*
embedded — it is too long and too domain-specific to produce clean
nearest-neighbour results.

Model: ``all-MiniLM-L6-v2`` (384-dimensional cosine-space vectors).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only imported for type-checking so that the ImportError guard below is
    # exercised at runtime rather than at import time.
    from sentence_transformers import SentenceTransformer  # noqa: F401

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class EmbeddingModel:
    """Thin wrapper around a sentence-transformers model.

    Attributes:
        _model: The underlying :class:`~sentence_transformers.SentenceTransformer`
            instance, loaded at construction time.
        _model_name: Name of the model that was loaded.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        """Load the sentence-transformers model.

        Args:
            model_name: HuggingFace model identifier.  Defaults to
                ``"all-MiniLM-L6-v2"`` which produces 384-dimensional vectors.

        Raises:
            ImportError: If the ``sentence-transformers`` package is not
                installed.  Install it with::

                    pip install sentence-transformers
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for the embedding pipeline. "
                "Install it with: pip install sentence-transformers"
            ) from exc

        self._model_name = model_name
        self._model: SentenceTransformer = SentenceTransformer(model_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Compute a 384-dimensional vector for a single text string.

        Args:
            text: The input string to embed.

        Returns:
            A plain ``list[float]`` of length 384.
        """
        vector = self._model.encode(text, convert_to_numpy=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute vectors for multiple texts in one forward pass.

        Args:
            texts: List of strings to embed.

        Returns:
            A list of ``list[float]``, one per input string, each of length 384.
            Order matches the input order.
        """
        if not texts:
            return []
        vectors = self._model.encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]

    @property
    def dimension(self) -> int:
        """Embedding dimension.  Always 384 for ``all-MiniLM-L6-v2``."""
        return _EMBEDDING_DIM
