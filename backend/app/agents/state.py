"""LangGraph state for the email-triage pipeline.

A single mutable dict threaded through every node. Each node reads what it
needs and returns a partial update (LangGraph merges it into the running
state) -- the standard LangGraph pattern. ``errors`` accumulates
per-node failures so one node's failure degrades gracefully (default values,
zero confidence) instead of crashing the whole run -- see the module
docstring on :mod:`app.agents.graph` for how that's wired.
"""

from __future__ import annotations

from typing import Any, TypedDict


class EmailTriageState(TypedDict, total=False):
    """Graph state.

    All keys are optional (``total=False``): each node fills in more of the
    state as the pipeline progresses.
    """

    # -- Identity (set once, at entry) --------------------------------------
    tenant_id: str
    user_id: str
    email_id: str
    gmail_message_id: str
    thread_id: str
    ai_history_id: str

    # -- Raw email (set at entry) --------------------------------------------
    subject: str
    from_address: str
    to_address: str
    raw_body_text: str | None
    raw_body_html: str | None
    received_at: str

    # -- preprocess -----------------------------------------------------------
    clean_body_text: str

    # -- recall_memory ----------------------------------------------------------
    memory_context: str
    recalled_memory_ids: list[str]

    # -- categorize -----------------------------------------------------------
    category: str
    category_reasoning: str
    category_confidence: float

    # -- priority_score ---------------------------------------------------------
    priority_score: float
    priority_reasoning: str
    priority_confidence: float

    # -- deadline_detection -----------------------------------------------------
    has_deadline: bool
    deadline_at: str | None
    deadline_description: str
    deadline_confidence: float

    # -- task_extraction --------------------------------------------------------
    extracted_tasks: list[dict[str, Any]]
    task_confidence: float

    # -- reply_decision ---------------------------------------------------------
    should_reply: bool
    reply_reasoning: str
    reply_confidence: float

    # -- reply_draft ------------------------------------------------------------
    draft_subject: str
    draft_body: str
    draft_tone: str
    draft_reasoning: str
    draft_confidence: float

    # -- calendar_suggestion ------------------------------------------------------
    should_create_event: bool
    event_title: str
    event_start_at: str | None
    event_end_at: str | None
    event_location: str
    event_confidence: float

    # -- memory_update ----------------------------------------------------------
    extracted_memories: list[dict[str, Any]]
    memory_extraction_confidence: float

    # -- database_update --------------------------------------------------------
    created_task_ids: list[str]
    created_calendar_event_id: str | None
    created_draft_reply_id: str | None
    created_memory_ids: list[str]

    # -- notification -----------------------------------------------------------
    created_notification_ids: list[str]

    # -- bookkeeping ----------------------------------------------------------
    errors: list[dict[str, str]]
