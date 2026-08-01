"""Fake Anthropic Messages API server for tests.

Serves ``POST /v1/messages`` with real ``Message``-shaped JSON. Which canned
response to return is decided by inspecting the *actual* fields the real SDK
sends -- ``output_config.format.schema.properties`` for a structured-output
call (identifies which graph node's Pydantic schema is being requested), or
``tools`` with a forced ``tool_choice`` for the one real tool-call site in
``app/agents/tools.py``. Nothing here is a stub of our own code -- it is a
model of Anthropic's actual endpoint.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Default, realistic per-node responses, keyed by a schema field unique to
# that node's Pydantic ``response_model`` (see app/agents/schemas.py).
_DEFAULT_RESPONSES: dict[str, dict[str, Any]] = {
    "category": {
        "category": "action_required",
        "reasoning": "The sender asks for a signed contract by Friday.",
        "confidence": 0.92,
    },
    "priority_score": {
        "priority_score": 0.8,
        "reasoning": "Explicit deadline and a direct client request.",
        "confidence": 0.85,
    },
    "has_deadline": {
        "has_deadline": True,
        "deadline_at": "2026-08-01T17:00:00+00:00",
        "deadline_description": "by Friday",
        "confidence": 0.8,
    },
    "tasks": {
        "tasks": [
            {
                "title": "Sign and return the contract",
                "description": "Review and sign the attached contract.",
                "priority": "high",
            }
        ],
        "confidence": 0.75,
    },
    "should_reply": {
        "should_reply": True,
        "reasoning": "The sender is waiting on a direct response.",
        "confidence": 0.7,
    },
    # NOTE: checked before "should_reply" would also match -- see
    # _detect_node, which checks in an order that disambiguates overlaps.
    "should_create_event": {
        "should_create_event": False,
        "title": "",
        "start_at": None,
        "end_at": None,
        "location": "",
        "confidence": 0.9,
    },
    "should_remember": {
        "should_remember": False,
        "memory_type": "fact",
        "content": "",
        "confidence": 0.9,
    },
    "body_text": {
        "subject": "Re: Contract",
        "body_text": "Hi, I will review and sign the contract by Friday. Thanks!",
        "tone": "professional",
        "reasoning": "A neutral, courteous confirmation is appropriate here.",
        "confidence": 0.65,
    },
    "memories": {
        "memories": [
            {
                "memory_type": "important_sender",
                "memory_key": "client@example.com",
                "content": "Client who sends contracts with explicit deadlines.",
                "confidence": 0.8,
            }
        ],
        "confidence": 0.75,
    },
    "summary": {
        "summary": "This sender consistently requires signed contracts by a deadline.",
        "confidence": 0.8,
    },
    "semantic_query": {
        "semantic_query": "recruiter emails",
        "category": None,
        "is_read": None,
        "has_deadline": None,
        "days_back": None,
        "keyword": None,
        "confidence": 0.85,
    },
}

# Order matters: schemas share some field names (e.g. "confidence" on all of
# them), so check the most specific/unique field for each node first.
_NODE_FIELD_ORDER = [
    "semantic_query",
    "tasks",
    "body_text",
    "should_create_event",
    "memories",
    "summary",
    "should_reply",
    "has_deadline",
    "priority_score",
    "category",
]


class FakeAnthropicState:
    """Mutable state for one fake-server instance (fresh per test)."""

    def __init__(self) -> None:
        self.fail_fields: set[str] = set()
        self.overrides: dict[str, dict[str, Any]] = {}
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []


def _detect_node_field(schema_properties: dict[str, Any]) -> str | None:
    for field in _NODE_FIELD_ORDER:
        if field in schema_properties:
            return field
    return None


def _text_message_response(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


def _tool_use_response(
    model: str, tool_name: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [
            {
                "type": "tool_use",
                "id": f"toolu_{uuid.uuid4().hex[:24]}",
                "name": tool_name,
                "input": tool_input,
            }
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 80,
            "output_tokens": 20,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


def create_fake_anthropic_app() -> FastAPI:
    """Build a fresh fake Anthropic app with isolated in-memory state."""
    app = FastAPI(title="fake-anthropic")
    state = FakeAnthropicState()
    app.state.fake_anthropic = state

    @app.post("/v1/messages")
    async def messages(request: Request) -> JSONResponse:
        body: dict[str, Any] = await request.json()
        state.call_count += 1
        state.calls.append(body)
        model = str(body.get("model", "claude-opus-5"))

        tool_choice = body.get("tool_choice") or {}
        if tool_choice.get("type") == "tool":
            tool_name = str(tool_choice["name"])
            # The one real tool call this codebase makes: list_open_tasks
            # with a model-chosen "status" argument (see app/agents/tools.py).
            return JSONResponse(
                _tool_use_response(model, tool_name, {"status": "pending"})
            )

        output_config = body.get("output_config") or {}
        schema = (output_config.get("format") or {}).get("schema") or {}
        properties = schema.get("properties") or {}
        node_field = _detect_node_field(properties)

        if node_field is None or node_field in state.fail_fields:
            return JSONResponse(
                {
                    "type": "error",
                    "error": {
                        "type": "overloaded_error",
                        "message": "simulated transient failure",
                    },
                },
                status_code=529,
            )

        payload = state.overrides.get(node_field, _DEFAULT_RESPONSES[node_field])
        return JSONResponse(_text_message_response(model, payload))

    return app
