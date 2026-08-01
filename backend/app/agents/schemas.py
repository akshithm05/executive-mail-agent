"""Structured JSON output schemas for each LLM-calling graph node.

Every model that a node asks Claude to produce includes a ``confidence``
field (0.0-1.0) -- the model's own self-assessed certainty, used downstream
to decide whether to act automatically (e.g. auto-send a draft) or defer to
the user. These are passed as the Pydantic ``response_model`` to
:meth:`~app.agents.claude_client.StructuredLLMClient.complete`, which uses
the Anthropic SDK's ``messages.parse()`` (JSON-schema-constrained, validated
client-side against the model) rather than free-text parsing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "action_required",
    "meeting_request",
    "fyi",
    "newsletter",
    "personal",
    "spam",
    "other",
]
TaskPriority = Literal["low", "medium", "high", "urgent"]
ReplyTone = Literal[
    "professional",
    "friendly",
    "formal",
    "executive",
    "short",
    "detailed",
    "apology",
    "thank_you",
    "follow_up",
    "negotiation",
    "clarification",
]
MemoryCategory = Literal[
    "fact",
    "preference_inference",
    "relationship",
    "context",
    "important_sender",
    "favorite_label",
    "archive_behavior",
    "reply_style",
    "priority_rule",
    "typical_deadline",
    "communication_preference",
]


class CategorizationResult(BaseModel):
    """Output of the categorize node."""

    category: Category
    reasoning: str = Field(description="One-sentence justification.")
    confidence: float = Field(ge=0.0, le=1.0)


class PriorityScoreResult(BaseModel):
    """Output of the priority_score node."""

    priority_score: float = Field(
        ge=0.0, le=1.0, description="0 = no urgency, 1 = extremely urgent."
    )
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


class DeadlineDetectionResult(BaseModel):
    """Output of the deadline_detection node."""

    has_deadline: bool
    deadline_at: datetime | None = Field(
        default=None, description="ISO 8601 UTC datetime, or null if no deadline."
    )
    deadline_description: str = Field(
        default="",
        description="The literal deadline phrase found in the email, if any.",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedTask(BaseModel):
    """One task extracted from the email.

    ``depends_on_index`` references another task *within this same
    extraction batch* by its position in ``TaskExtractionResult.tasks``
    (0-based) -- there are no database ids yet at extraction time. The
    graph resolves it to a real ``Task.depends_on_task_id`` foreign key
    after all tasks in the batch have been persisted (see
    ``app/agents/graph.py::database_update``).
    """

    title: str = Field(max_length=500)
    description: str = ""
    priority: TaskPriority = "medium"
    due_at: datetime | None = Field(
        default=None,
        description=(
            "ISO 8601 UTC datetime this task is due, if the email implies "
            "one. Null if no deadline is implied for this specific task."
        ),
    )
    depends_on_index: int | None = Field(
        default=None,
        description=(
            "0-based index of another task in this same list that must be "
            "done first, if this task is explicitly blocked by it. Null if "
            "this task has no dependency within this batch."
        ),
    )


class TaskExtractionResult(BaseModel):
    """Output of the task_extraction node."""

    tasks: list[ExtractedTask] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ReplyDecisionResult(BaseModel):
    """Output of the reply_decision node."""

    should_reply: bool
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


class ReplyDraftResult(BaseModel):
    """Output of the reply_draft node.

    This is the sole shape the Draft Reply Engine produces -- whether called
    from the email-triage graph or the on-demand regenerate endpoint (see
    ``app/api/v1/routes/draft_replies.py``). ``tone`` is always one of the
    fixed, supported descriptors (never free text), so the API and UI can
    treat it as an enum rather than parsing prose.
    """

    subject: str = Field(max_length=998)
    body_text: str
    tone: ReplyTone
    reasoning: str = Field(description="Why this tone/approach was chosen.")
    confidence: float = Field(ge=0.0, le=1.0)


class CalendarSuggestionResult(BaseModel):
    """Output of the calendar_suggestion node."""

    should_create_event: bool
    title: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None
    location: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryCandidate(BaseModel):
    """One durable fact or preference worth persisting long-term.

    ``memory_key`` is a short, stable, machine-usable identifier for facts
    that can recur and should be *reinforced* rather than duplicated the
    next time they're observed -- e.g. a sender's email address for
    ``important_sender``, or a label name for ``favorite_label``. Left null
    for one-off facts with nothing to key on (most ``fact``/``context``
    memories).
    """

    memory_type: MemoryCategory
    memory_key: str | None = Field(
        default=None,
        description=(
            "Stable lookup key for reinforceable memories, e.g. a sender's "
            "email address or a label name. Null for one-off facts."
        ),
    )
    content: str = Field(description="The durable fact or preference itself.")
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryUpdateResult(BaseModel):
    """Output of the memory_update node.

    A list, not a single memory: one email can reveal several independent
    durable facts at once (e.g. both that the sender is a VIP client *and*
    that they always give a one-week deadline).
    """

    memories: list[MemoryCandidate] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class SearchQueryParseResult(BaseModel):
    """Output of parsing a free-text AI-powered search query.

    Splits a natural-language query (e.g. "unread invoices from last month")
    into the part that maps cleanly to a SQL filter (``category``,
    ``is_read``, ``days_back``, ``keyword``) and the residual part that
    only a semantic/embedding comparison can resolve (``semantic_query`` --
    e.g. "recruiter emails" or "internship offers" have no literal keyword
    to filter on). See ``app/services/email_search.py`` for how both halves
    are combined into one ranked result set.
    """

    semantic_query: str = Field(
        description=(
            "The query, or the part of it with no literal filter meaning, "
            "to embed for semantic similarity ranking. Never empty -- if "
            "the whole query was consumed by filters, repeat the original "
            "query text here so ranking still has something to compare "
            "against."
        )
    )
    category: Category | None = Field(
        default=None,
        description="Set only if the query clearly names one of the fixed categories.",
    )
    is_read: bool | None = Field(
        default=None,
        description="True/false if the query explicitly says read/unread, else null.",
    )
    has_deadline: bool | None = Field(default=None)
    days_back: int | None = Field(
        default=None,
        description=(
            "If the query references a relative time window (e.g. 'last "
            "month', 'this week', 'yesterday'), the number of days back "
            "from now to search from. Null if no time constraint is implied."
        ),
    )
    keyword: str | None = Field(
        default=None,
        description=(
            "A literal word or phrase (e.g. a company name like 'Deloitte') "
            "that must appear verbatim in the email, if the query names one. "
            "Null if the query is purely conceptual with nothing literal to "
            "match."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0)


class MemorySummaryResult(BaseModel):
    """Output of the memory-summarization maintenance task.

    Not part of the per-email graph -- produced by
    ``MemoryService.maybe_summarize`` when a user has accumulated many
    low-signal memories of the same type, consolidating them into one
    higher-confidence memory.
    """

    summary: str = Field(description="One consolidated statement of the pattern.")
    confidence: float = Field(ge=0.0, le=1.0)
