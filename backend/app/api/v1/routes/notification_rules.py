"""Custom notification-rule endpoints (e.g. "only notify for important emails")."""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, NotificationRuleServiceDep
from app.core.exceptions import NotFoundError
from app.infra.models.notification_rule import NotificationRule
from app.schemas.notification_rule import (
    NotificationRuleCreate,
    NotificationRuleRead,
    NotificationRuleUpdate,
)

router = APIRouter(prefix="/notification-rules", tags=["notification-rules"])


async def _get_owned_rule(
    rule_id: uuid.UUID, user: CurrentUserDep, service: NotificationRuleServiceDep
) -> NotificationRule:
    """Fetch a rule, scoped to the current user (404 if not theirs)."""
    rule = await service.get(rule_id)
    if rule is None or rule.user_id != user.id:
        raise NotFoundError("No notification rule with this id was found.")
    return rule


OwnedRuleDep = Annotated[NotificationRule, Depends(_get_owned_rule)]


@router.get(
    "", response_model=list[NotificationRuleRead], summary="List notification rules"
)
async def list_rules(
    user: CurrentUserDep, service: NotificationRuleServiceDep
) -> list[NotificationRuleRead]:
    """List every custom notification rule the current user has defined."""
    rules = await service.list_by_user(user.id)
    return [NotificationRuleRead.model_validate(r) for r in rules]


@router.post(
    "", response_model=NotificationRuleRead, summary="Create a notification rule"
)
async def create_rule(
    body: NotificationRuleCreate,
    user: CurrentUserDep,
    service: NotificationRuleServiceDep,
) -> NotificationRuleRead:
    """Create a new custom notification rule.

    ``only_important=true`` is the built-in "only notify for important
    emails" rule -- see the module docstring on
    ``app/services/notification_rules.py`` for the exact definition.
    """
    rule = await service.create(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=body.name,
        is_enabled=body.is_enabled,
        only_important=body.only_important,
        notification_types=body.notification_types,
        keyword=body.keyword,
    )
    return NotificationRuleRead.model_validate(rule)


@router.patch(
    "/{rule_id}", response_model=NotificationRuleRead, summary="Update a rule"
)
async def update_rule(
    body: NotificationRuleUpdate,
    rule: OwnedRuleDep,
    service: NotificationRuleServiceDep,
) -> NotificationRuleRead:
    """Update one or more fields on a rule."""
    fields = body.model_dump(exclude_unset=True)
    if fields:
        await service.update(rule.id, **fields)
    updated = await service.get(rule.id)
    return NotificationRuleRead.model_validate(cast(NotificationRule, updated))


@router.delete(
    "/{rule_id}", status_code=204, response_model=None, summary="Delete a rule"
)
async def delete_rule(rule: OwnedRuleDep, service: NotificationRuleServiceDep) -> None:
    """Delete a custom notification rule."""
    await service.delete(rule.id)
