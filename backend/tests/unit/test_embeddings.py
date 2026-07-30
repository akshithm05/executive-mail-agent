"""Unit tests for the local hashing-trick embedding provider."""

from __future__ import annotations

import math

from app.agents.embeddings import HashingEmbeddingProvider, cosine_similarity


def test_embed_is_deterministic() -> None:
    provider = HashingEmbeddingProvider(dimensions=64)
    first = provider.embed("Alice is a VIP client who always needs fast replies")
    second = provider.embed("Alice is a VIP client who always needs fast replies")
    assert first == second


def test_embed_has_configured_dimensions() -> None:
    provider = HashingEmbeddingProvider(dimensions=128)
    vector = provider.embed("some email content")
    assert len(vector) == 128


def test_embed_is_l2_normalized() -> None:
    provider = HashingEmbeddingProvider(dimensions=64)
    vector = provider.embed("normalize this please, it has several distinct words")
    norm = math.sqrt(sum(v * v for v in vector))
    assert norm == 0.0 or abs(norm - 1.0) < 1e-9


def test_empty_text_yields_zero_vector() -> None:
    provider = HashingEmbeddingProvider(dimensions=32)
    vector = provider.embed("")
    assert vector == [0.0] * 32


def test_model_name_reflects_dimensions() -> None:
    provider = HashingEmbeddingProvider(dimensions=256)
    assert "256" in provider.model_name
    assert provider.dimensions == 256


def test_embed_batch_matches_individual_embed() -> None:
    provider = HashingEmbeddingProvider(dimensions=64)
    texts = ["first email about contracts", "second email about scheduling"]
    batch = provider.embed_batch(texts)
    individual = [provider.embed(t) for t in texts]
    assert batch == individual


def test_identical_text_has_similarity_one() -> None:
    provider = HashingEmbeddingProvider(dimensions=128)
    vector = provider.embed("please sign the contract by Friday")
    assert math.isclose(cosine_similarity(vector, vector), 1.0, abs_tol=1e-9)


def test_similar_text_scores_higher_than_unrelated_text() -> None:
    provider = HashingEmbeddingProvider(dimensions=256)
    base = provider.embed("please sign and return the attached contract")
    similar = provider.embed("please sign and return the attached agreement")
    unrelated = provider.embed(
        "join us for the quarterly all-hands potluck lunch next Tuesday"
    )

    similar_score = cosine_similarity(base, similar)
    unrelated_score = cosine_similarity(base, unrelated)
    assert similar_score > unrelated_score


def test_cosine_similarity_handles_mismatched_or_empty_vectors() -> None:
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0
