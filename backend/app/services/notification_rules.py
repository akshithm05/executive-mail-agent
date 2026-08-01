"""Custom notification-filtering rules.

See the module docstring on ``app/infra/models/notification_rule.py`` for
the full semantics. In short: no enabled rules -> everything is delivered;
at least one enabled rule -> delivered only if it matches at least one of
them; a rule matches when all of its own non-null conditions hold.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.infra.models.notification import Notification
from app.infra.models.notification_rule import NotificationRule
from app.infra.repositories.notification_rule import NotificationRuleRepository

# `Notification.type` values the triage agent already flags as important --
# see `only_important`'s docstring on the model. Kept in one place so the
# "only notify for important emails" shorthand rule and any future caller
# agree on the definition.
IMPORTANT_NOTIFICATION_TYPES = frozenset({"high_priority_email", "draft_ready"})


def rule_matches(rule: NotificationRule, notification: Notification) -> bool:
    """Return True if every non-null condition on ``rule`` holds for ``notification``.

    Called only for a rule that is itself already enabled.
    """
    if rule.only_important and notification.type not in IMPORTANT_NOTIFICATION_TYPES:
        return False
    if rule.notification_types and notification.type not in rule.notification_types:
        return False
    if rule.keyword:
        keyword = rule.keyword.lower()
        haystack = f"{notification.title}\n{notification.body}".lower()
        if keyword not in haystack:
            return False
    return True


def should_deliver(
    rules: Sequence[NotificationRule], notification: Notification
) -> bool:
    """Return True if ``notification`` passes the given (already-enabled) rule set.

    An empty rule set always passes (no filtering configured).
    """
    if not rules:
        return True
    return any(rule_matches(rule, notification) for rule in rules)


class NotificationRuleService:
    """CRUD operations for a user's custom notification-filtering rules."""

    def __init__(self, repository: NotificationRuleRepository) -> None:
        self._repo = repository

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[NotificationRule]:
        """Return every rule (enabled or not) for a user."""
        return await self._repo.list_by_user(user_id)

    async def list_enabled_by_user(
        self, user_id: uuid.UUID
    ) -> Sequence[NotificationRule]:
        """Return a user's enabled rules."""
        return await self._repo.list_enabled_by_user(user_id)

    async def get(self, rule_id: uuid.UUID) -> NotificationRule | None:
        """Return a rule by id, or ``None`` if it does not exist."""
        return await self._repo.get(rule_id)

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        is_enabled: bool = True,
        only_important: bool = False,
        notification_types: list[str] | None = None,
        keyword: str | None = None,
    ) -> NotificationRule:
        """Create a new custom notification rule."""
        return await self._repo.add(
            NotificationRule(
                tenant_id=tenant_id,
                user_id=user_id,
                name=name,
                is_enabled=is_enabled,
                only_important=only_important,
                notification_types=notification_types,
                keyword=keyword,
            )
        )

    async def update(
        self, rule_id: uuid.UUID, **fields: object
    ) -> NotificationRule | None:
        """Update one or more fields on a rule, or ``None`` if it does not exist."""
        return await self._repo.update_fields(rule_id, **fields)

    async def delete(self, rule_id: uuid.UUID) -> bool:
        """Hard-delete a rule. Returns ``False`` if it did not exist."""
        return await self._repo.delete(rule_id)
