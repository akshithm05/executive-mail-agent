"""Composite importance scoring and decay for long-term memories.

A memory's ``importance_score`` is not a single AI-reported number -- it is
recomputed from four independent signals every time a memory is written or
decayed, so that memories which are old-but-frequently-useful outrank
memories which are new-but-fabricated-once:

* **Base weight** -- how durable this *category* of memory tends to be. A
  ``communication_preference`` ("always CC my assistant") is durable; a
  ``context`` note ("mentioned they're traveling this week") is not.
* **Confidence** -- the AI's own self-assessed certainty when the memory was
  last written or reinforced (see ``app/agents/schemas.py``).
* **Recency decay** -- an exponential half-life applied to the time since
  the memory was last *accessed* (read back into a prompt) or, if never
  accessed, last updated. Memories nobody has needed in a while fade.
* **Reinforcement** -- how many times this fact has been independently
  observed again (``Memory.reinforcement_count``, bumped by
  ``MemoryService.upsert`` when a keyed memory recurs). Diminishing returns
  via a log curve so the 20th confirmation barely moves the needle over the
  10th.

``is_pinned`` memories (explicit, user-confirmed preferences) bypass all of
this and always score 1.0 -- they should never decay out of relevance.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.infra.models.memory import Memory

DEFAULT_HALF_LIFE_DAYS = 30.0

# How durable each memory category tends to be, independent of any single
# observation's confidence. Deliberately not uniform: an explicit stated
# preference is worth remembering far longer than a one-off contextual note.
_BASE_WEIGHT_BY_TYPE: dict[str, float] = {
    "communication_preference": 0.9,
    "priority_rule": 0.85,
    "important_sender": 0.8,
    "reply_style": 0.75,
    "archive_behavior": 0.7,
    "typical_deadline": 0.65,
    "favorite_label": 0.6,
    "relationship": 0.6,
    "preference_inference": 0.55,
    "fact": 0.5,
    "context": 0.4,
}
_DEFAULT_BASE_WEIGHT = 0.5

_WEIGHT_BASE = 0.30
_WEIGHT_CONFIDENCE = 0.30
_WEIGHT_RECENCY = 0.25
_WEIGHT_REINFORCEMENT = 0.15


def base_weight(memory_type: str) -> float:
    """Return the durability weight for a memory category."""
    return _BASE_WEIGHT_BY_TYPE.get(memory_type, _DEFAULT_BASE_WEIGHT)


def decay_factor(
    elapsed_days: float, half_life_days: float = DEFAULT_HALF_LIFE_DAYS
) -> float:
    """Exponential decay: 1.0 at zero elapsed time, 0.5 at one half-life."""
    if elapsed_days <= 0:
        return 1.0
    if half_life_days <= 0:
        return 0.0
    return math.pow(0.5, elapsed_days / half_life_days)


def reinforcement_boost(reinforcement_count: int, saturation_count: int = 10) -> float:
    """Diminishing-returns boost from repeated confirmation of the same fact."""
    if reinforcement_count <= 1:
        return 0.0
    return min(1.0, math.log1p(reinforcement_count - 1) / math.log1p(saturation_count))


def compute_importance_score(
    memory: Memory,
    *,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Recompute a memory's composite importance score.

    Does not mutate or persist ``memory`` -- callers (``MemoryService``)
    decide when to write the result back.
    """
    if memory.is_pinned:
        return 1.0

    now = now or datetime.now(UTC)
    # A brand-new, not-yet-flushed row has no `updated_at` yet (it is a
    # server-side default populated on insert) -- treat it as scored "now",
    # i.e. zero elapsed time, rather than crashing on a None anchor.
    anchor = memory.last_accessed_at or memory.updated_at or now
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    elapsed_days = max((now - anchor).total_seconds() / 86400.0, 0.0)

    # Column defaults (e.g. `reinforcement_count`'s default of 1) are applied
    # by SQLAlchemy at flush/insert time, not on plain construction -- a
    # not-yet-flushed row can still read back as None here.
    reinforcement_count = memory.reinforcement_count or 1
    confidence = memory.confidence if memory.confidence is not None else 0.5

    score = (
        _WEIGHT_BASE * base_weight(memory.memory_type)
        + _WEIGHT_CONFIDENCE * confidence
        + _WEIGHT_RECENCY * decay_factor(elapsed_days, half_life_days)
        + _WEIGHT_REINFORCEMENT * reinforcement_boost(reinforcement_count)
    )
    return max(0.0, min(1.0, score))
