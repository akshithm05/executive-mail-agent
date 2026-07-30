"""The email-triage LangGraph pipeline.

    receive_email -> preprocess -> recall_memory -> categorize ->
    priority_score -> deadline_detection -> task_extraction -> reply_decision
    -- [should_reply?] --> reply_draft --+
    -- [no]             ------------------+--> calendar_suggestion
    -> memory_update -> database_update -> notification -> END

Every LLM-calling node is wrapped by :func:`_call_llm`, which catches any
exception the :class:`~app.agents.claude_client.StructuredLLMClient` raises
after exhausting its own retries, records it in ``state["errors"]``, and
returns a safe, zero-confidence default -- one node failing (a bad Claude
response, a persistent rate limit) degrades that node's output rather than
crashing the whole run. This is the "error recovery" behavior described in
the Phase 5 requirements, implemented once and reused by every node instead
of duplicated per node.

``recall_memory`` is the read side of the long-term memory loop (see
``app/agents/memory_retrieval.py``): it fetches this user's relevant
memories -- important senders, priority rules, reply style, and more --
before triage begins, and every node from ``categorize`` onward
(``_email_context``) has that context available in its prompt.
``memory_update`` is the write side: it extracts new/reinforcing memories
from this email, and ``database_update`` persists them via
``MemoryService.upsert`` (dedupe-by-key, confidence blending, importance
scoring) rather than raw inserts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from anthropic import AsyncAnthropic
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from app.agents import prompts
from app.agents.claude_client import StructuredLLMClient
from app.agents.deadline_parser import format_hint, parse_deadline
from app.agents.embeddings import EmbeddingProvider
from app.agents.memory_retrieval import MemoryRetrievalService
from app.agents.schemas import (
    CalendarSuggestionResult,
    CategorizationResult,
    DeadlineDetectionResult,
    MemoryUpdateResult,
    PriorityScoreResult,
    ReplyDecisionResult,
    ReplyDraftResult,
    TaskExtractionResult,
)
from app.agents.state import EmailTriageState
from app.agents.tools import fetch_existing_task_context
from app.config.logging import get_logger
from app.config.settings import AISettings
from app.infra.google.html_text import html_to_text
from app.infra.models.ai_history import AIHistory
from app.infra.models.calendar_event import CalendarEvent
from app.infra.models.draft_reply import DraftReply
from app.infra.models.notification import Notification
from app.infra.models.task import Task
from app.infra.repositories.ai_history import AIHistoryRepository
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.task import TaskRepository
from app.services.memory import MemoryService
from app.services.reminder import ReminderService

_HIGH_PRIORITY_THRESHOLD = 0.7
# How far ahead of a deadline to remind the user -- a task reminder fires
# well before its due_at; a calendar event reminder fires shortly before it
# starts, matching how most calendar apps default their own reminders.
_TASK_REMINDER_LEAD_TIME = timedelta(hours=2)
_EVENT_REMINDER_LEAD_TIME = timedelta(minutes=30)

logger = get_logger(__name__)

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


@dataclass
class GraphDependencies:
    """External collaborators every node closure needs.

    Built once per triage run (see ``app/agents/email_agent.py``) and closed
    over by every node function -- the standard way to inject dependencies
    into a LangGraph graph, since node functions only receive the state dict.
    """

    claude_client: StructuredLLMClient
    raw_anthropic_client: AsyncAnthropic
    settings: AISettings
    task_repo: TaskRepository
    ai_history_repo: AIHistoryRepository
    calendar_event_repo: CalendarEventRepository
    draft_reply_repo: DraftReplyRepository
    notification_repo: NotificationRepository
    memory_service: MemoryService
    memory_retrieval: MemoryRetrievalService
    embedding_provider: EmbeddingProvider
    reminder_service: ReminderService


async def _call_llm(
    deps: GraphDependencies,
    state: EmailTriageState,
    *,
    node_name: str,
    system: str,
    user_message: str,
    response_model: type[ResponseModelT],
    default: ResponseModelT,
) -> tuple[ResponseModelT, list[dict[str, str]]]:
    """Call Claude for one node, degrading to ``default`` on failure.

    Returns the result *and* the errors list to include in the node's own
    returned update -- LangGraph only merges a node's *returned* dict into
    the running state, so mutating the ``state`` parameter in place (the
    dict handed to this call) would be silently discarded. Every node must
    include the returned errors list verbatim in its own return value.
    """
    errors = list(state.get("errors", []))
    try:
        result = await deps.claude_client.complete(
            system=system,
            user_message=user_message,
            response_model=response_model,
            tenant_id=uuid.UUID(state["tenant_id"]),
            user_id=uuid.UUID(state["user_id"]),
            ai_history_id=uuid.UUID(state["ai_history_id"])
            if state.get("ai_history_id")
            else None,
            node_name=node_name,
        )
        return result, errors
    except Exception as exc:
        logger.warning("graph_node_degraded", node=node_name, error=str(exc))
        errors.append({"node": node_name, "error": str(exc)})
        return default, errors


def _ensure_aware(value: datetime) -> datetime:
    """Normalize to an aware (UTC) datetime.

    A round trip through the database can come back naive even when an
    aware value was written -- SQLite's plain ``DateTime`` type (no
    ``timezone=True``) has no native timezone storage, so a value reloaded
    via ``session.refresh()`` (e.g. after ``update_fields`` -- see
    ``app/infra/repositories/base.py``) loses its ``tzinfo`` even though the
    original insert was timezone-aware. Comparing against another aware
    datetime (e.g. "now") without this normalization raises ``TypeError``.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _parse_received_at(state: EmailTriageState) -> datetime:
    raw = state.get("received_at")
    if not raw:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _email_context(state: EmailTriageState) -> str:
    context = prompts.email_context(
        subject=state.get("subject", ""),
        from_address=state.get("from_address", ""),
        to_address=state.get("to_address", ""),
        body=state.get("clean_body_text", ""),
    )
    memory_context = state.get("memory_context", "")
    if memory_context:
        context = f"{context}\n\n{memory_context}"
    return context


async def preprocess(state: EmailTriageState) -> dict[str, Any]:
    """Derive clean plain text from whichever body the email has."""
    raw_text = state.get("raw_body_text")
    raw_html = state.get("raw_body_html")
    if raw_text:
        text = raw_text
    elif raw_html:
        text = html_to_text(raw_html)
    else:
        text = ""

    # Strip a common quoted-reply marker so the model triages the new
    # content, not the entire quoted thread beneath it.
    for marker in ("\nOn ", "\n-----Original Message-----", "\n> "):
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
            break

    return {"clean_body_text": text.strip()}


def build_graph(deps: GraphDependencies) -> Any:
    """Compile the email-triage StateGraph bound to ``deps``."""

    async def recall_memory(state: EmailTriageState) -> dict[str, Any]:
        """Fetch this user's relevant long-term memories before triaging.

        This is the read side of the memory loop: every downstream prompt
        (via ``_email_context``) gets a "known context about this user"
        block built from what earlier emails taught the ``memory_update``
        node -- important senders, priority rules, reply style, etc.
        """
        query_text = f"{state.get('subject', '')}\n{state.get('clean_body_text', '')}"
        try:
            memories = await deps.memory_retrieval.retrieve(
                user_id=uuid.UUID(state["user_id"]),
                from_address=state.get("from_address", ""),
                query_text=query_text,
            )
        except Exception as exc:
            logger.warning("memory_recall_failed", error=str(exc))
            errors = [
                *state.get("errors", []),
                {"node": "recall_memory", "error": str(exc)},
            ]
            return {"memory_context": "", "recalled_memory_ids": [], "errors": errors}

        return {
            "memory_context": deps.memory_retrieval.format_for_prompt(memories),
            "recalled_memory_ids": [str(m.id) for m in memories],
        }

    async def categorize(state: EmailTriageState) -> dict[str, Any]:
        result, errors = await _call_llm(
            deps,
            state,
            node_name="categorize",
            system=prompts.CATEGORIZE_SYSTEM,
            user_message=_email_context(state),
            response_model=CategorizationResult,
            default=CategorizationResult(
                category="other", reasoning="categorization failed", confidence=0.0
            ),
        )
        return {
            "category": result.category,
            "category_reasoning": result.reasoning,
            "category_confidence": result.confidence,
            "errors": errors,
        }

    async def priority_score(state: EmailTriageState) -> dict[str, Any]:
        result, errors = await _call_llm(
            deps,
            state,
            node_name="priority_score",
            system=prompts.PRIORITY_SYSTEM,
            user_message=_email_context(state),
            response_model=PriorityScoreResult,
            default=PriorityScoreResult(
                priority_score=0.5, reasoning="scoring failed", confidence=0.0
            ),
        )
        return {
            "priority_score": result.priority_score,
            "priority_reasoning": result.reasoning,
            "priority_confidence": result.confidence,
            "errors": errors,
        }

    async def deadline_detection(state: EmailTriageState) -> dict[str, Any]:
        received_at = state.get("received_at", datetime.now().isoformat())
        reference = _parse_received_at(state)
        scan_text = f"{state.get('subject', '')}\n{state.get('clean_body_text', '')}"
        rule_based_match = parse_deadline(scan_text, reference=reference)
        hint = f"\n\n{format_hint(rule_based_match)}" if rule_based_match else ""

        result, errors = await _call_llm(
            deps,
            state,
            node_name="deadline_detection",
            system=prompts.DEADLINE_SYSTEM,
            user_message=(
                f"Email received at: {received_at}\n\n{_email_context(state)}{hint}"
            ),
            response_model=DeadlineDetectionResult,
            default=DeadlineDetectionResult(has_deadline=False, confidence=0.0),
        )
        if rule_based_match is not None and not result.has_deadline:
            logger.info(
                "deadline_hint_overridden",
                phrase=rule_based_match.phrase,
                rule_based_at=rule_based_match.deadline_at.isoformat(),
            )
        return {
            "has_deadline": result.has_deadline,
            "deadline_at": result.deadline_at.isoformat()
            if result.deadline_at
            else None,
            "deadline_description": result.deadline_description,
            "deadline_confidence": result.confidence,
            "errors": errors,
        }

    async def task_extraction(state: EmailTriageState) -> dict[str, Any]:
        extra_context = await fetch_existing_task_context(
            raw_client=deps.raw_anthropic_client,
            model=deps.settings.model,
            task_repo=deps.task_repo,
            user_id=uuid.UUID(state["user_id"]),
            subject=state.get("subject", ""),
            body=state.get("clean_body_text", ""),
        )
        user_message = _email_context(state)
        if extra_context:
            user_message = f"{user_message}\n\n{extra_context}"

        result, errors = await _call_llm(
            deps,
            state,
            node_name="task_extraction",
            system=prompts.TASK_EXTRACTION_SYSTEM,
            user_message=user_message,
            response_model=TaskExtractionResult,
            default=TaskExtractionResult(tasks=[], confidence=0.0),
        )
        return {
            "extracted_tasks": [
                {**t.model_dump(), "due_at": t.due_at.isoformat() if t.due_at else None}
                for t in result.tasks
            ],
            "task_confidence": result.confidence,
            "errors": errors,
        }

    async def reply_decision(state: EmailTriageState) -> dict[str, Any]:
        result, errors = await _call_llm(
            deps,
            state,
            node_name="reply_decision",
            system=prompts.REPLY_DECISION_SYSTEM,
            user_message=_email_context(state),
            response_model=ReplyDecisionResult,
            default=ReplyDecisionResult(
                should_reply=False, reasoning="decision failed", confidence=0.0
            ),
        )
        return {
            "should_reply": result.should_reply,
            "reply_reasoning": result.reasoning,
            "reply_confidence": result.confidence,
            "errors": errors,
        }

    async def reply_draft(state: EmailTriageState) -> dict[str, Any]:
        result, errors = await _call_llm(
            deps,
            state,
            node_name="reply_draft",
            system=prompts.REPLY_DRAFT_SYSTEM,
            user_message=_email_context(state),
            response_model=ReplyDraftResult,
            default=ReplyDraftResult(
                subject="",
                body_text="",
                tone="professional",
                reasoning="draft generation failed",
                confidence=0.0,
            ),
        )
        return {
            "draft_subject": result.subject,
            "draft_body": result.body_text,
            "draft_tone": result.tone,
            "draft_reasoning": result.reasoning,
            "draft_confidence": result.confidence,
            "errors": errors,
        }

    async def calendar_suggestion(state: EmailTriageState) -> dict[str, Any]:
        # Skip the LLM call outright when neither signal (a meeting-shaped
        # category or a detected deadline) suggests a schedulable event --
        # most emails have neither, and this avoids a wasted API call.
        if state.get("category") != "meeting_request" and not state.get("has_deadline"):
            return {"should_create_event": False, "event_confidence": 1.0}

        received_at = state.get("received_at", datetime.now().isoformat())
        result, errors = await _call_llm(
            deps,
            state,
            node_name="calendar_suggestion",
            system=prompts.CALENDAR_SUGGESTION_SYSTEM,
            user_message=f"Email received at: {received_at}\n\n{_email_context(state)}",
            response_model=CalendarSuggestionResult,
            default=CalendarSuggestionResult(should_create_event=False, confidence=0.0),
        )
        return {
            "should_create_event": result.should_create_event,
            "event_title": result.title,
            "event_start_at": result.start_at.isoformat() if result.start_at else None,
            "event_end_at": result.end_at.isoformat() if result.end_at else None,
            "event_location": result.location,
            "event_confidence": result.confidence,
            "errors": errors,
        }

    async def memory_update(state: EmailTriageState) -> dict[str, Any]:
        result, errors = await _call_llm(
            deps,
            state,
            node_name="memory_update",
            system=prompts.MEMORY_UPDATE_SYSTEM,
            user_message=_email_context(state),
            response_model=MemoryUpdateResult,
            default=MemoryUpdateResult(memories=[], confidence=0.0),
        )
        return {
            "extracted_memories": [m.model_dump() for m in result.memories],
            "memory_extraction_confidence": result.confidence,
            "errors": errors,
        }

    async def receive_email(state: EmailTriageState) -> dict[str, Any]:
        """Entry point: open the AIHistory record every later node logs against."""
        history = await deps.ai_history_repo.add(
            AIHistory(
                tenant_id=uuid.UUID(state["tenant_id"]),
                user_id=uuid.UUID(state["user_id"]),
                email_id=uuid.UUID(state["email_id"]),
                action_type="email_triage",
                model_name=deps.settings.model,
            )
        )
        return {"ai_history_id": str(history.id), "errors": []}

    async def database_update(state: EmailTriageState) -> dict[str, Any]:
        """Persist every node's output: tasks, calendar event, draft, memory."""
        tenant_id = uuid.UUID(state["tenant_id"])
        user_id = uuid.UUID(state["user_id"])
        email_id = uuid.UUID(state["email_id"])

        now = datetime.now(UTC)
        extracted_tasks = state.get("extracted_tasks", [])
        created_tasks: list[Task] = []
        for extracted in extracted_tasks:
            due_raw = extracted.get("due_at")
            task = await deps.task_repo.add(
                Task(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    email_id=email_id,
                    title=extracted["title"],
                    description=extracted.get("description", ""),
                    priority=extracted.get("priority", "medium"),
                    due_at=datetime.fromisoformat(due_raw) if due_raw else None,
                    created_by="ai",
                )
            )
            created_tasks.append(task)

        # Second pass: resolve depends_on_index (a position in this same
        # batch, the only reference the LLM can give -- there were no
        # database ids yet at extraction time) into a real FK now that
        # every task in the batch has one.
        for i, (extracted, task) in enumerate(
            zip(extracted_tasks, created_tasks, strict=True)
        ):
            dep_index = extracted.get("depends_on_index")
            if dep_index is None or not (0 <= dep_index < len(created_tasks)):
                continue
            if dep_index == i:
                continue  # a task cannot depend on itself
            await deps.task_repo.update_fields(
                task.id, depends_on_task_id=created_tasks[dep_index].id
            )

        for task in created_tasks:
            if task.due_at is None:
                continue
            due_at = _ensure_aware(task.due_at)
            remind_at = due_at - _TASK_REMINDER_LEAD_TIME
            if remind_at <= now:
                remind_at = due_at
            await deps.reminder_service.schedule(
                tenant_id=tenant_id,
                user_id=user_id,
                task_id=task.id,
                remind_at=remind_at,
                message=f'Task due soon: "{task.title}"',
            )

        task_ids = [str(task.id) for task in created_tasks]

        calendar_event_id: str | None = None
        event_start_raw = state.get("event_start_at")
        if state.get("should_create_event") and event_start_raw:
            start_at = datetime.fromisoformat(event_start_raw)
            event_end_raw = state.get("event_end_at")
            end_at = (
                datetime.fromisoformat(event_end_raw) if event_end_raw else start_at
            )
            event = await deps.calendar_event_repo.add(
                CalendarEvent(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    email_id=email_id,
                    title=state.get("event_title", ""),
                    location=state.get("event_location", ""),
                    start_at=start_at,
                    end_at=end_at,
                    status="tentative",
                )
            )
            calendar_event_id = str(event.id)

            event_remind_at = start_at - _EVENT_REMINDER_LEAD_TIME
            if event_remind_at <= now:
                event_remind_at = start_at
            await deps.reminder_service.schedule(
                tenant_id=tenant_id,
                user_id=user_id,
                calendar_event_id=event.id,
                remind_at=event_remind_at,
                message=f'Upcoming: "{event.title}"',
            )

        draft_reply_id: str | None = None
        if state.get("should_reply") and state.get("draft_body"):
            draft = await deps.draft_reply_repo.add(
                DraftReply(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    email_id=email_id,
                    subject=state.get("draft_subject", ""),
                    body_text=state["draft_body"],
                    tone=state.get("draft_tone"),
                    reasoning=state.get("draft_reasoning"),
                    confidence=state.get("draft_confidence"),
                    status="draft",
                    generated_by="ai",
                )
            )
            draft_reply_id = str(draft.id)

        memory_ids: list[str] = []
        touched_memory_types: set[str] = set()
        for candidate in state.get("extracted_memories", []):
            memory = await deps.memory_service.upsert(
                tenant_id=tenant_id,
                user_id=user_id,
                memory_type=candidate.get("memory_type", "fact"),
                content=candidate["content"],
                memory_key=candidate.get("memory_key"),
                confidence=candidate.get("confidence", 0.5),
                source_email_id=email_id,
                embedding_provider=deps.embedding_provider,
            )
            memory_ids.append(str(memory.id))
            touched_memory_types.add(memory.memory_type)

        for memory_type in touched_memory_types:
            try:
                await deps.memory_service.maybe_summarize(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    memory_type=memory_type,
                    claude_client=deps.claude_client,
                    embedding_provider=deps.embedding_provider,
                )
            except Exception as exc:
                logger.warning(
                    "memory_summarization_failed",
                    memory_type=memory_type,
                    error=str(exc),
                )

        ai_history_id = state.get("ai_history_id")
        if ai_history_id:
            history = await deps.ai_history_repo.get(uuid.UUID(ai_history_id))
            if history is not None:
                history.output_summary = (
                    f"category={state.get('category')} "
                    f"priority={state.get('priority_score')} "
                    f"tasks={len(task_ids)} "
                    f"replied={bool(draft_reply_id)}"
                )
                history.extra_metadata = {
                    "category": state.get("category"),
                    "priority_score": state.get("priority_score"),
                    "has_deadline": state.get("has_deadline"),
                    "task_count": len(task_ids),
                    "should_reply": state.get("should_reply"),
                    "draft_tone": state.get("draft_tone"),
                    "should_create_event": state.get("should_create_event"),
                    "memory_count": len(memory_ids),
                    "recalled_memory_ids": state.get("recalled_memory_ids", []),
                    "errors": state.get("errors", []),
                }

        return {
            "created_task_ids": task_ids,
            "created_calendar_event_id": calendar_event_id,
            "created_draft_reply_id": draft_reply_id,
            "created_memory_ids": memory_ids,
        }

    async def notification(state: EmailTriageState) -> dict[str, Any]:
        """Notify the user when the triage produced something needing attention."""
        tenant_id = uuid.UUID(state["tenant_id"])
        user_id = uuid.UUID(state["user_id"])
        notification_ids: list[str] = []

        if state.get("created_draft_reply_id"):
            note = await deps.notification_repo.add(
                Notification(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    type="draft_ready",
                    title="A draft reply is ready for your review",
                    body=state.get("subject", ""),
                    related_entity_type="draft_reply",
                    related_entity_id=uuid.UUID(state["created_draft_reply_id"]),
                )
            )
            notification_ids.append(str(note.id))
        elif (state.get("priority_score") or 0.0) >= _HIGH_PRIORITY_THRESHOLD:
            note = await deps.notification_repo.add(
                Notification(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    type="high_priority_email",
                    title="A high-priority email needs your attention",
                    body=state.get("subject", ""),
                    related_entity_type="email",
                    related_entity_id=uuid.UUID(state["email_id"]),
                )
            )
            notification_ids.append(str(note.id))

        return {"created_notification_ids": notification_ids}

    graph: StateGraph[EmailTriageState] = StateGraph(EmailTriageState)
    graph.add_node("receive_email", receive_email)
    graph.add_node("preprocess", preprocess)
    graph.add_node("recall_memory", recall_memory)
    graph.add_node("categorize", categorize)
    graph.add_node("priority_score", priority_score)
    graph.add_node("deadline_detection", deadline_detection)
    graph.add_node("task_extraction", task_extraction)
    graph.add_node("reply_decision", reply_decision)
    graph.add_node("reply_draft", reply_draft)
    graph.add_node("calendar_suggestion", calendar_suggestion)
    graph.add_node("memory_update", memory_update)
    graph.add_node("database_update", database_update)
    graph.add_node("notification", notification)

    graph.set_entry_point("receive_email")
    graph.add_edge("receive_email", "preprocess")
    graph.add_edge("preprocess", "recall_memory")
    graph.add_edge("recall_memory", "categorize")
    graph.add_edge("categorize", "priority_score")
    graph.add_edge("priority_score", "deadline_detection")
    graph.add_edge("deadline_detection", "task_extraction")
    graph.add_edge("task_extraction", "reply_decision")
    graph.add_conditional_edges(
        "reply_decision",
        lambda state: "reply_draft"
        if state.get("should_reply")
        else "calendar_suggestion",
        {"reply_draft": "reply_draft", "calendar_suggestion": "calendar_suggestion"},
    )
    graph.add_edge("reply_draft", "calendar_suggestion")
    graph.add_edge("calendar_suggestion", "memory_update")
    graph.add_edge("memory_update", "database_update")
    graph.add_edge("database_update", "notification")
    graph.add_edge("notification", END)

    return graph.compile()
