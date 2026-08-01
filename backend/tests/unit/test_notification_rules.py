"""Unit tests for the notification rule-matching engine."""

from __future__ import annotations

import uuid

from app.infra.models.notification import Notification
from app.infra.models.notification_rule import NotificationRule
from app.services.notification_rules import rule_matches, should_deliver


def _notification(**overrides: object) -> Notification:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "type": "reminder",
        "title": "Reminder",
        "body": "Task due soon",
    }
    defaults.update(overrides)
    return Notification(**defaults)  # type: ignore[arg-type]


def _rule(**overrides: object) -> NotificationRule:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "name": "test rule",
        "is_enabled": True,
        "only_important": False,
        "notification_types": None,
        "keyword": None,
    }
    defaults.update(overrides)
    return NotificationRule(**defaults)  # type: ignore[arg-type]


def test_no_rules_means_everything_is_delivered() -> None:
    assert should_deliver([], _notification()) is True


def test_only_important_matches_high_priority_email() -> None:
    rule = _rule(only_important=True)
    note = _notification(type="high_priority_email")
    assert rule_matches(rule, note) is True


def test_only_important_matches_draft_ready() -> None:
    rule = _rule(only_important=True)
    note = _notification(type="draft_ready")
    assert rule_matches(rule, note) is True


def test_only_important_rejects_reminder() -> None:
    rule = _rule(only_important=True)
    note = _notification(type="reminder")
    assert rule_matches(rule, note) is False


def test_notification_types_allow_list() -> None:
    rule = _rule(notification_types=["morning_digest", "weekly_digest"])
    assert rule_matches(rule, _notification(type="morning_digest")) is True
    assert rule_matches(rule, _notification(type="reminder")) is False


def test_keyword_matches_case_insensitively_in_title_or_body() -> None:
    rule = _rule(keyword="URGENT")
    assert rule_matches(rule, _notification(title="Urgent: sign now")) is True
    assert rule_matches(rule, _notification(body="this is urgent")) is True
    assert rule_matches(rule, _notification(title="fyi", body="no rush")) is False


def test_rule_conditions_combine_with_and() -> None:
    rule = _rule(only_important=True, keyword="contract")
    matching = _notification(type="high_priority_email", body="Sign the contract")
    non_matching = _notification(type="high_priority_email", body="unrelated")
    assert rule_matches(rule, matching) is True
    assert rule_matches(rule, non_matching) is False


def test_should_deliver_is_true_if_any_enabled_rule_matches() -> None:
    rules = [_rule(keyword="foo"), _rule(keyword="bar")]
    assert should_deliver(rules, _notification(body="contains bar")) is True
    assert should_deliver(rules, _notification(body="contains neither")) is False
