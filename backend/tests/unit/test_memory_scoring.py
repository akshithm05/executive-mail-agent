"""Unit tests for long-term memory importance scoring and decay."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.agents.memory_scoring import (
    base_weight,
    compute_importance_score,
    decay_factor,
    reinforcement_boost,
)
from app.infra.models.memory import Memory


def _memory(**overrides: object) -> Memory:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "memory_type": "fact",
        "content": "some fact",
        "confidence": 0.5,
        "reinforcement_count": 1,
        "is_pinned": False,
        "last_accessed_at": None,
    }
    defaults.update(overrides)
    memory = Memory(**defaults)  # type: ignore[arg-type]
    memory.updated_at = defaults.get("updated_at", datetime.now(UTC))  # type: ignore[assignment]
    return memory


def test_decay_factor_is_one_at_zero_elapsed_time() -> None:
    assert decay_factor(0.0, half_life_days=30.0) == 1.0


def test_decay_factor_is_half_at_one_half_life() -> None:
    assert abs(decay_factor(30.0, half_life_days=30.0) - 0.5) < 1e-9


def test_decay_factor_approaches_zero_for_long_elapsed_time() -> None:
    assert decay_factor(365.0, half_life_days=30.0) < 0.01


def test_decay_factor_handles_non_positive_half_life() -> None:
    assert decay_factor(10.0, half_life_days=0.0) == 0.0


def test_reinforcement_boost_is_zero_for_unreinforced_memory() -> None:
    assert reinforcement_boost(1) == 0.0
    assert reinforcement_boost(0) == 0.0


def test_reinforcement_boost_increases_with_diminishing_returns() -> None:
    boost_at_2 = reinforcement_boost(2)
    boost_at_5 = reinforcement_boost(5)
    boost_at_10 = reinforcement_boost(10)
    boost_at_20 = reinforcement_boost(20)

    assert 0.0 < boost_at_2 < boost_at_5 < boost_at_10
    # Saturates: the jump from 10 to 20 reinforcements is much smaller than
    # the jump from 2 to 5.
    assert (boost_at_20 - boost_at_10) < (boost_at_5 - boost_at_2)


def test_base_weight_ranks_communication_preference_above_context() -> None:
    assert base_weight("communication_preference") > base_weight("context")


def test_base_weight_falls_back_for_unknown_type() -> None:
    assert base_weight("some_unrecognized_type") == 0.5


def test_pinned_memory_always_scores_maximum() -> None:
    old_anchor = datetime.now(UTC) - timedelta(days=3650)
    memory = _memory(is_pinned=True, confidence=0.01, reinforcement_count=1)
    memory.updated_at = old_anchor
    assert compute_importance_score(memory) == 1.0


def test_fresh_high_confidence_memory_scores_higher_than_stale_low_confidence() -> None:
    now = datetime.now(UTC)
    fresh = _memory(confidence=0.9, memory_type="important_sender")
    fresh.updated_at = now

    stale = _memory(confidence=0.2, memory_type="context")
    stale.updated_at = now - timedelta(days=180)

    assert compute_importance_score(fresh, now=now) > compute_importance_score(
        stale, now=now
    )


def test_reinforced_memory_scores_higher_than_single_observation() -> None:
    now = datetime.now(UTC)
    once = _memory(reinforcement_count=1)
    once.updated_at = now
    many = _memory(reinforcement_count=8)
    many.updated_at = now

    assert compute_importance_score(many, now=now) > compute_importance_score(
        once, now=now
    )


def test_score_is_clamped_between_zero_and_one() -> None:
    now = datetime.now(UTC)
    memory = _memory(confidence=1.0, memory_type="communication_preference")
    memory.updated_at = now
    score = compute_importance_score(memory, now=now)
    assert 0.0 <= score <= 1.0


def test_not_yet_flushed_memory_does_not_crash_on_none_fields() -> None:
    """A transient (unflushed) row can have None reinforcement_count/updated_at."""
    memory = Memory(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        memory_type="fact",
        content="brand new",
        confidence=0.6,
    )
    score = compute_importance_score(memory)
    assert 0.0 <= score <= 1.0
