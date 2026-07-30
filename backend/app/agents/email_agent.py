"""Runs the email-triage graph for one :class:`~app.infra.queue.AIProcessingJob`.

This is the function the background AI-processing worker (Phase 4) calls for
each ingested email. It owns its own database session (workers are not
request-scoped) and builds a fresh :class:`~app.agents.graph.GraphDependencies`
per job -- cheap, and avoids any state leaking between jobs.
"""

from __future__ import annotations

import httpx
from anthropic import AsyncAnthropic

from app.agents.claude_client import StructuredLLMClient
from app.agents.embeddings import HashingEmbeddingProvider
from app.agents.graph import GraphDependencies, build_graph
from app.agents.memory_retrieval import MemoryRetrievalService
from app.agents.state import EmailTriageState
from app.config.logging import get_logger
from app.config.settings import Settings
from app.infra.db.session import Database
from app.infra.models.email import Email
from app.infra.queue import AIProcessingJob
from app.infra.repositories.ai_history import AIHistoryRepository
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.memory import MemoryRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.reminder import ReminderRepository
from app.infra.repositories.task import TaskRepository
from app.services.memory import MemoryService
from app.services.reminder import ReminderService

logger = get_logger(__name__)


def _build_initial_state(job: AIProcessingJob, email: Email) -> EmailTriageState:
    return EmailTriageState(
        tenant_id=str(job.tenant_id),
        user_id=str(job.user_id),
        email_id=str(job.email_id),
        gmail_message_id=job.gmail_message_id,
        thread_id=email.gmail_thread_id,
        subject=email.subject,
        from_address=email.from_address,
        to_address=email.to_addresses,
        raw_body_text=email.body_text,
        raw_body_html=email.body_html,
        received_at=email.received_at.isoformat(),
    )


async def run_email_triage(
    job: AIProcessingJob,
    database: Database,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Load the ingested email and run the full triage graph over it.

    Never raises: an email that fails to load, or a job for an email that no
    longer exists, is logged and skipped rather than crashing the worker
    loop (see :class:`~app.workers.ai_processing_worker.AIProcessingWorker`,
    which already retries the *call* to this function -- this guards against
    failures this function cannot usefully retry, like a missing row).

    Args:
        job: The queued ingestion job identifying which email to triage.
        database: Owns the connection pool; a fresh session is opened here
            since workers are not request-scoped.
        settings: Application settings, in particular ``settings.ai``.
        http_client: Test-only injection point for a custom transport (see
            ``tests/integration/test_email_agent.py``); production always
            leaves this ``None`` and gets a real client the SDK manages.
    """
    async with database.session() as session:
        email_repo = EmailRepository(session)
        email = await email_repo.get(job.email_id)
        if email is None:
            logger.warning("ai_processing_email_not_found", email_id=str(job.email_id))
            return

        if not settings.ai.is_configured:
            logger.warning(
                "ai_processing_skipped_not_configured", email_id=str(job.email_id)
            )
            return

        # max_retries=0: app.agents.claude_client.StructuredLLMClient owns
        # retry/backoff (tenacity) so there is a single, observable retry
        # policy instead of the SDK's own layer retrying silently underneath.
        raw_client = AsyncAnthropic(
            api_key=settings.ai.anthropic_api_key,
            timeout=settings.ai.request_timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )
        try:
            claude_client = StructuredLLMClient(
                raw_client, settings.ai, PromptLogRepository(session)
            )
            memory_repo = MemoryRepository(session)
            memory_service = MemoryService(
                memory_repo,
                half_life_days=settings.memory.decay_half_life_days,
                summarization_threshold=settings.memory.summarization_threshold,
            )
            embedding_provider = HashingEmbeddingProvider(
                dimensions=settings.memory.embedding_dimensions
            )
            memory_retrieval = MemoryRetrievalService(
                memory_repo,
                memory_service,
                embedding_provider,
                default_top_k=settings.memory.retrieval_top_k,
            )
            deps = GraphDependencies(
                claude_client=claude_client,
                raw_anthropic_client=raw_client,
                settings=settings.ai,
                task_repo=TaskRepository(session),
                ai_history_repo=AIHistoryRepository(session),
                calendar_event_repo=CalendarEventRepository(session),
                draft_reply_repo=DraftReplyRepository(session),
                notification_repo=NotificationRepository(session),
                memory_service=memory_service,
                memory_retrieval=memory_retrieval,
                embedding_provider=embedding_provider,
                reminder_service=ReminderService(ReminderRepository(session)),
            )
            graph = build_graph(deps)
            initial_state = _build_initial_state(job, email)

            logger.info("email_triage_started", email_id=str(job.email_id))
            final_state = await graph.ainvoke(initial_state)
            logger.info(
                "email_triage_completed",
                email_id=str(job.email_id),
                category=final_state.get("category"),
                priority_score=final_state.get("priority_score"),
                task_count=len(final_state.get("created_task_ids", [])),
                errors=final_state.get("errors", []),
            )
        finally:
            if http_client is None:
                await raw_client.close()
