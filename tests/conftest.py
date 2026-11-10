"""Shared fixtures: HTTP is the only mocked boundary, everything else runs for real."""

from __future__ import annotations

import io
import json
import sys
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOKEN = "fixture-access-value"


def envelope(name: str = "get_contact", connection_type: str = "freeagent_company", **args: Any):
    return {
        "contract_version": "extension_host_v2",
        "mode": "action",
        "runtime_context": {
            "account_id": "a",
            "project_id": "p",
            "workflow_id": "w",
            "job_id": "j",
            "group_id": None,
            "for_each_id": None,
            "step_id": "s",
            "step_execution_id": "e",
            "test_mode": False,
            "external_effect_id": "effect-1",
        },
        "action": {
            "action_id": name,
            "input": {"connection_ref": "company-1", **args},
            "target": {
                "connection": {
                    "connection_id": "company-1",
                    "connection_type": connection_type,
                    "config": {},
                    "secrets": {"access_token": TOKEN},
                }
            },
        },
    }


class Response(io.BytesIO):
    def __init__(self, raw: bytes, status: int = 200, headers: dict[str, str] | None = None):
        super().__init__(raw)
        self.status = status
        message = Message()
        for key, value in (headers or {"Content-Type": "application/json"}).items():
            message[key] = value
        self.headers = message


def http_error(code: int, body: Any = b"", headers: dict[str, str] | None = None) -> HTTPError:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return HTTPError("https://api.freeagent.com/v2/x", code, "error", message, io.BytesIO(raw))


def reply(value: Any = None, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    raw = (
        value if isinstance(value, bytes) else b"" if value is None else json.dumps(value).encode()
    )
    return Response(raw, status, headers)


def invoke(payload: dict[str, Any], *responses: Any):
    """Run the real handler; each provider call takes the next scripted response or error."""
    from freeagent import transport
    from main import handle

    queue = list(responses) or [
        reply({"contact": {"url": "https://api.freeagent.com/v2/contacts/7"}})
    ]
    sent: list[Any] = []

    def fake_open(request, **_: Any):
        sent.append(request)
        item = queue.pop(0) if queue else reply({})
        if isinstance(item, BaseException):
            raise item
        return item

    with (
        patch.object(transport, "resolve_pinned_ips", return_value=("8.8.8.8",)),
        patch.object(transport, "open_pinned_url", side_effect=fake_open),
        patch.object(transport.time, "sleep") as sleep,
    ):
        result = handle(payload)
    return result, sent, sleep
