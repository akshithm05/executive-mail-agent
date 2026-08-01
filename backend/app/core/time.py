"""UTC time helpers.

Nearly every timestamp column in this schema is a naive ``DateTime`` that
stores UTC by convention (see ``app/infra/db/mixins.py``'s ``TimestampMixin``
and ``SoftDeleteMixin``) -- only ``Session.expires_at``/``revoked_at`` and
``GoogleCredential.access_token_expires_at``/``last_polled_at`` are declared
``DateTime(timezone=True)``. Postgres's asyncpg driver is strict about
naive-vs-aware datetime parameters and rejects a timezone-aware Python value
bound against a naive column (``asyncpg.exceptions.DataError: can't
subtract offset-naive and offset-aware datetimes``) -- a mismatch SQLite
silently tolerates, which is why this can pass every test against the
SQLite-backed suite and still fail the moment it runs against real
Postgres.

Use :func:`utcnow` when writing into (or building comparison values for)
one of those naive columns. Keep using ``datetime.now(UTC)`` directly for
the small set of genuinely timezone-aware columns listed above.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as a naive UTC datetime.

    Numerically identical to ``datetime.now(UTC)`` -- only the tzinfo is
    stripped, so this remains directly comparable to/assignable into a
    naive ``DateTime`` column without an aware/naive driver error.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def as_naive_utc(value: datetime) -> datetime:
    """Strip tzinfo from an aware datetime, assuming it is already UTC.

    Idempotent for an already-naive value. Used at repository query
    boundaries to defensively normalize a caller-supplied datetime before
    comparing it against a naive column, regardless of whether the caller
    passed an aware or naive value.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value
