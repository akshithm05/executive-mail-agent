"""ORM model registry.

Importing every model here ensures they are all registered on
``Base.metadata`` before Alembic autogenerate or ``create_all`` runs, and
that every ``relationship()`` string/forward reference resolves. New models
must be added to ``__all__`` and imported below.
"""

from app.infra.models.ai_history import AIHistory
from app.infra.models.attachment import Attachment
from app.infra.models.audit_log import AuditLog
from app.infra.models.calendar_event import CalendarEvent
from app.infra.models.draft_reply import DraftReply
from app.infra.models.email import Email
from app.infra.models.failed_job import FailedJob
from app.infra.models.google_credential import GoogleCredential
from app.infra.models.label import EmailLabel, Label
from app.infra.models.memory import Memory
from app.infra.models.notification import Notification
from app.infra.models.notification_channel_config import NotificationChannelConfig
from app.infra.models.notification_delivery import NotificationDelivery
from app.infra.models.notification_quiet_hours import NotificationQuietHours
from app.infra.models.notification_rule import NotificationRule
from app.infra.models.preference import Preference
from app.infra.models.prompt_log import PromptLog
from app.infra.models.push_device import PushDevice
from app.infra.models.reminder import Reminder
from app.infra.models.session import Session
from app.infra.models.summary import Summary
from app.infra.models.task import Task
from app.infra.models.tenant import Tenant
from app.infra.models.user import User

__all__ = [
    "AIHistory",
    "Attachment",
    "AuditLog",
    "CalendarEvent",
    "DraftReply",
    "Email",
    "EmailLabel",
    "FailedJob",
    "GoogleCredential",
    "Label",
    "Memory",
    "Notification",
    "NotificationChannelConfig",
    "NotificationDelivery",
    "NotificationQuietHours",
    "NotificationRule",
    "Preference",
    "PromptLog",
    "PushDevice",
    "Reminder",
    "Session",
    "Summary",
    "Task",
    "Tenant",
    "User",
]
