"""Email repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_naive_utc
from app.infra.models.email import Email
from app.infra.repositories.base import SoftDeleteRepository

# How urgent an email's own priority_score must be to count as "urgent" on
# the dashboard, independent of its category (an "action_required" email is
# always urgent regardless of score -- see ``list_urgent``/``count_urgent``).
_URGENT_PRIORITY_THRESHOLD = 0.7


class EmailRepository(SoftDeleteRepository[Email]):
    """Persistence operations for emails."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Email)

    async def get_by_gmail_message_id(
        self, user_id: uuid.UUID, gmail_message_id: str
    ) -> Email | None:
        """Return the email with the given Gmail message id for this user."""
        stmt = select(Email).where(
            Email.user_id == user_id,
            Email.gmail_message_id == gmail_message_id,
            Email.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_thread(
        self, user_id: uuid.UUID, gmail_thread_id: str
    ) -> Sequence[Email]:
        """Return all emails in a thread, oldest first."""
        stmt = (
            select(Email)
            .where(
                Email.user_id == user_id,
                Email.gmail_thread_id == gmail_thread_id,
                Email.deleted_at.is_(None),
            )
            .order_by(Email.received_at)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_unread(
        self, user_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Email]:
        """Return unread emails for a user, most recent first."""
        stmt = (
            select(Email)
            .where(
                Email.user_id == user_id,
                Email.is_read.is_(False),
                Email.deleted_at.is_(None),
            )
            .order_by(Email.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    def _base_filters(
        self,
        user_id: uuid.UUID,
        *,
        category: str | None,
        is_read: bool | None,
        has_deadline: bool | None,
    ) -> list[Any]:
        filters: list[Any] = [Email.user_id == user_id, Email.deleted_at.is_(None)]
        if category is not None:
            filters.append(Email.category == category)
        if is_read is not None:
            filters.append(Email.is_read.is_(is_read))
        if has_deadline is not None:
            filters.append(Email.has_deadline.is_(has_deadline))
        return filters

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        category: str | None = None,
        is_read: bool | None = None,
        has_deadline: bool | None = None,
        sort: str = "recent",
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Email]:
        """Return a user's emails, filtered and sorted for dashboard views.

        ``sort`` is ``"recent"`` (default, most recently received first) or
        ``"priority"`` (highest ``priority_score`` first, nulls last).
        """
        filters = self._base_filters(
            user_id, category=category, is_read=is_read, has_deadline=has_deadline
        )
        stmt = select(Email).where(*filters)
        if sort == "priority":
            stmt = stmt.order_by(
                Email.priority_score.desc().nulls_last(), Email.received_at.desc()
            )
        else:
            stmt = stmt.order_by(Email.received_at.desc())
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_urgent(
        self, user_id: uuid.UUID, *, limit: int = 10
    ) -> Sequence[Email]:
        """Return the most urgent emails: action_required or high priority score."""
        stmt = (
            select(Email)
            .where(
                Email.user_id == user_id,
                Email.deleted_at.is_(None),
                (Email.category == "action_required")
                | (Email.priority_score >= _URGENT_PRIORITY_THRESHOLD),
            )
            .order_by(
                Email.priority_score.desc().nulls_last(), Email.received_at.desc()
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_upcoming_deadlines(
        self, user_id: uuid.UUID, *, now: datetime, limit: int = 10
    ) -> Sequence[Email]:
        """Return emails with a future deadline, soonest first.

        ``now`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``deadline_at`` is a naive column.
        """
        stmt = (
            select(Email)
            .where(
                Email.user_id == user_id,
                Email.deleted_at.is_(None),
                Email.has_deadline.is_(True),
                Email.deadline_at.is_not(None),
                Email.deadline_at >= as_naive_utc(now),
            )
            .order_by(Email.deadline_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_total(self, user_id: uuid.UUID) -> int:
        """Return the total number of active emails for a user."""
        stmt = select(func.count()).where(
            Email.user_id == user_id, Email.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_received_since(self, user_id: uuid.UUID, *, since: datetime) -> int:
        """Return the number of emails received on/after ``since`` (weekly digest).

        ``since`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``received_at`` is a naive column.
        """
        stmt = select(func.count()).where(
            Email.user_id == user_id,
            Email.received_at >= as_naive_utc(since),
            Email.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """Return the number of unread emails for a user."""
        stmt = select(func.count()).where(
            Email.user_id == user_id,
            Email.is_read.is_(False),
            Email.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_urgent(self, user_id: uuid.UUID) -> int:
        """Return the number of urgent (action_required or high-priority) emails."""
        stmt = select(func.count()).where(
            Email.user_id == user_id,
            Email.deleted_at.is_(None),
            (Email.category == "action_required")
            | (Email.priority_score >= _URGENT_PRIORITY_THRESHOLD),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_upcoming_deadlines(
        self, user_id: uuid.UUID, *, now: datetime
    ) -> int:
        """Return the number of emails with a future deadline.

        ``now`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``deadline_at`` is a naive column.
        """
        stmt = select(func.count()).where(
            Email.user_id == user_id,
            Email.deleted_at.is_(None),
            Email.has_deadline.is_(True),
            Email.deadline_at.is_not(None),
            Email.deadline_at >= as_naive_utc(now),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def category_counts(self, user_id: uuid.UUID) -> Sequence[tuple[str, int]]:
        """Return ``(category, count)`` pairs for every categorized email."""
        stmt = (
            select(Email.category, func.count())
            .where(
                Email.user_id == user_id,
                Email.deleted_at.is_(None),
                Email.category.is_not(None),
            )
            .group_by(Email.category)
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def list_received_between(
        self,
        user_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime | None = None,
        limit: int = 20_000,
    ) -> Sequence[Email]:
        """Return a user's emails received in ``[since, until)``, most recent first.

        Feeds ``AnalyticsService`` -- every time-series/distribution chart
        that groups by ``received_at`` fetches this once, then buckets in
        Python (see that module's docstring for why: cross-dialect date
        truncation in SQL is a real footgun between SQLite tests and
        Postgres production). ``since``/``until`` are normalized to naive
        UTC (see ``app/core/time.py``); ``limit`` bounds the fetch so one
        request can't force an unbounded table scan.
        """
        filters = [
            Email.user_id == user_id,
            Email.deleted_at.is_(None),
            Email.received_at >= as_naive_utc(since),
        ]
        if until is not None:
            filters.append(Email.received_at < as_naive_utc(until))
        stmt = (
            select(Email)
            .where(*filters)
            .order_by(Email.received_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_missing_embeddings(self, *, limit: int = 200) -> Sequence[Email]:
        """Return active emails with no embedding yet, oldest-received first.

        Feeds the scheduled ``backfill_email_embeddings`` job (see
        ``app/scheduler.py``) -- oldest-first so a mailbox with a large
        backlog fills in chronological order across repeated runs rather
        than the newest emails winning every batch.
        """
        stmt = (
            select(Email)
            .where(Email.deleted_at.is_(None), Email.embedding.is_(None))
            .order_by(Email.received_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def search_candidates(
        self,
        user_id: uuid.UUID,
        *,
        category: str | None = None,
        is_read: bool | None = None,
        has_deadline: bool | None = None,
        since: datetime | None = None,
        keyword: str | None = None,
        limit: int = 500,
    ) -> Sequence[Email]:
        """Return a bounded, SQL-filtered candidate pool for AI-powered search.

        Applies every structured filter the query parser extracted (see
        ``app/services/search_query_parser.py``) at the database level, then
        hands the (still large) result to ``EmailSearchService`` for
        semantic/keyword ranking in Python -- mirrors ``MemoryRepository.
        list_embedding_candidates``'s bounded-pool pattern. ``since`` is
        normalized to naive UTC (see ``app/core/time.py``); ``keyword`` does
        a case-insensitive substring match across subject/body/sender.
        """
        filters = self._base_filters(
            user_id, category=category, is_read=is_read, has_deadline=has_deadline
        )
        if since is not None:
            filters.append(Email.received_at >= as_naive_utc(since))
        if keyword:
            pattern = f"%{keyword}%"
            filters.append(
                or_(
                    Email.subject.ilike(pattern),
                    Email.body_text.ilike(pattern),
                    Email.from_address.ilike(pattern),
                )
            )
        stmt = (
            select(Email)
            .where(*filters)
            .order_by(Email.received_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def heatmap_rows(
        self, user_id: uuid.UUID, *, limit: int = 1000
    ) -> Sequence[tuple[str, float]]:
        """Return recent ``(category, priority_score)`` pairs for the heatmap.

        Bucketing into priority bands happens in the service layer (plain
        Python, five fixed bands) -- cheap enough at this row count that a
        SQL ``CASE`` expression would only add complexity, not speed.
        """
        stmt = (
            select(Email.category, Email.priority_score)
            .where(
                Email.user_id == user_id,
                Email.deleted_at.is_(None),
                Email.category.is_not(None),
                Email.priority_score.is_not(None),
            )
            .order_by(Email.received_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
