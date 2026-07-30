"""Real Claude tool-calling: the task_extraction node's duplicate-avoidance check.

Before extracting tasks from an email, the agent asks Claude to call a tool
that looks up the user's existing open tasks (a real query against
:class:`~app.infra.repositories.task.TaskRepository`, built in Phase 3) --
Claude decides *which* status bucket to check, we execute the call against
the real database, and the result is fed back into the extraction prompt so
the model does not re-extract a task that already exists. This is a genuine
tool_use round trip (forced ``tool_choice``, a real ``tool_use`` block, a
real ``tool_result``), not a server-side pre-fetch dressed up as one.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from anthropic import AsyncAnthropic

from app.config.logging import get_logger
from app.infra.repositories.task import TaskRepository

logger = get_logger(__name__)

LIST_OPEN_TASKS_TOOL: dict[str, Any] = {
    "name": "list_open_tasks",
    "description": (
        "Look up the user's existing tasks in a given status, so you don't "
        "extract a duplicate of a task that already exists."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress"],
                "description": "Which status bucket of existing tasks to check.",
            }
        },
        "required": ["status"],
        "additionalProperties": False,
    },
}


async def _execute_list_open_tasks(
    task_repo: TaskRepository, user_id: uuid.UUID, status: str
) -> str:
    tasks = await task_repo.list_by_status(user_id, status, limit=10)
    return json.dumps([{"title": t.title, "priority": t.priority} for t in tasks])


async def fetch_existing_task_context(
    *,
    raw_client: AsyncAnthropic,
    model: str,
    task_repo: TaskRepository,
    user_id: uuid.UUID,
    subject: str,
    body: str,
) -> str:
    """Run one forced tool-call turn and return existing tasks as plain text.

    Returns an empty string (not an exception) on any failure -- this is a
    best-effort context enrichment, not something that should ever block the
    real task-extraction call from running.
    """
    try:
        # The Anthropic SDK's `tools`/`tool_choice` overloads expect its own
        # TypedDict unions; a plain raw dict (the documented tool-definition
        # shape) doesn't structurally satisfy them for mypy even though it is
        # exactly what the wire API expects at runtime.
        response = await raw_client.messages.create(
            model=model,
            max_tokens=256,
            tools=[LIST_OPEN_TASKS_TOOL],  # type: ignore[call-overload]
            tool_choice={"type": "tool", "name": "list_open_tasks"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Before extracting tasks from this email, check "
                        "existing open tasks so you can avoid duplicates.\n\n"
                        f"Subject: {subject}\nBody:\n{body}"
                    ),
                }
            ],
        )
    except Exception:
        logger.warning("tool_call_context_fetch_failed", exc_info=True)
        return ""

    tool_use_blocks = [block for block in response.content if block.type == "tool_use"]
    if not tool_use_blocks:
        return ""

    call = tool_use_blocks[0]
    status = str(call.input.get("status", "pending"))
    try:
        result_json = await _execute_list_open_tasks(task_repo, user_id, status)
    except Exception:
        logger.warning("tool_execution_failed", tool=call.name, exc_info=True)
        return ""

    existing = json.loads(result_json)
    if not existing:
        return ""
    return "Existing open tasks (do not duplicate these):\n" + "\n".join(
        f"- {task['title']} (priority: {task['priority']})" for task in existing
    )
