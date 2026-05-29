"""Unit tests for lore.mcp.embeddings.EmbeddingModel.

These tests use the *real* model (all-MiniLM-L6-v2) — no mocking.  The model
is downloaded once and cached by sentence-transformers; subsequent runs are
fast.  The tests verify correctness of the embedding API, not the model's
semantic quality.
"""

from __future__ import annotations

import pytest

from lore.mcp.embeddings import EmbeddingModel


# ---------------------------------------------------------------------------
# Module-level fixture — load the model once for all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def model() -> EmbeddingModel:
    """Return a module-scoped EmbeddingModel so the model is loaded once."""
    return EmbeddingModel()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmbedDimension:
    def test_embed_returns_correct_dimension(self, model: EmbeddingModel) -> None:
        """embed() must return a list of exactly 384 floats."""
        result = model.embed("use this when building a REST API")
        assert isinstance(result, list)
        assert len(result) == 384
        assert all(isinstance(v, float) for v in result)

    def test_dimension_property(self, model: EmbeddingModel) -> None:
        """model.dimension must equal 384."""
        assert model.dimension == 384


class TestEmbedBatch:
    def test_embed_batch_returns_correct_shape(self, model: EmbeddingModel) -> None:
        """embed_batch(['a', 'b']) must return 2 vectors each of length 384."""
        results = model.embed_batch(["a", "b"])
        assert isinstance(results, list)
        assert len(results) == 2
        for vec in results:
            assert isinstance(vec, list)
            assert len(vec) == 384
            assert all(isinstance(v, float) for v in vec)

    def test_embed_batch_single_text(self, model: EmbeddingModel) -> None:
        """embed_batch with a single text must return a list of one vector."""
        results = model.embed_batch(["only one text here"])
        assert len(results) == 1
        assert len(results[0]) == 384

    def test_embed_batch_empty_input(self, model: EmbeddingModel) -> None:
        """embed_batch with an empty list must return an empty list."""
        results = model.embed_batch([])
        assert results == []


class TestEmbedDeterminism:
    def test_embed_is_deterministic(self, model: EmbeddingModel) -> None:
        """Same input text must produce bit-identical output on repeated calls."""
        text = "use when you need semantic search over structured data"
        v1 = model.embed(text)
        v2 = model.embed(text)
        assert v1 == v2

    def test_embed_batch_is_deterministic(self, model: EmbeddingModel) -> None:
        """embed_batch must produce the same vectors on repeated calls."""
        texts = ["tool for database migrations", "pattern for retry logic"]
        r1 = model.embed_batch(texts)
        r2 = model.embed_batch(texts)
        assert r1 == r2


class TestEmbedDistinctness:
    def test_embed_different_texts_differ(self, model: EmbeddingModel) -> None:
        """Two semantically different texts must produce different vectors."""
        v1 = model.embed("use when building a REST API")
        v2 = model.embed("use when writing database migrations")
        assert v1 != v2

    def test_embed_batch_different_texts_differ(self, model: EmbeddingModel) -> None:
        """Each text in embed_batch must produce a distinct vector."""
        results = model.embed_batch([
            "retry pattern for transient failures",
            "circuit breaker for cascading fault prevention",
        ])
        assert results[0] != results[1]


class TestImportGuard:
    def test_missing_sentence_transformers_raises_import_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EmbeddingModel.__init__ must raise ImportError if sentence-transformers
        is not importable, with a helpful install hint in the message."""
        import builtins
        original_import = builtins.__import__

        def _patched_import(name: str, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("no module named sentence_transformers")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _patched_import)

        with pytest.raises(ImportError, match="pip install sentence-transformers"):
            EmbeddingModel()
