"""Host-v2 envelope, explicit connection selection and external-effect policy."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from flowsteward_extension_sdk import runtime_context_from_payload

from freeagent.catalog import OPERATIONS, READ, WRITE_EFFECTS, Operation
from freeagent.documents import explanation_attachment, inline_attachment, save_pdf, statement_file
from freeagent.plans import Plan, prepare
from freeagent.transport import Reply, Transport
from freeagent.validation import (
    CONNECTION_TYPES,
    RESULT_LIMIT,
    Failure,
    bounded_json,
    connection_values,
    require,
    text,
)

MAX_PAGES = 50
VERIFY_ACTION = "verify_company"
ALLOWANCE = {
    "create": "allow_create",
    "update": "allow_update",
    "delete": "allow_delete",
    "email": "allow_email",
}
KNOWN_OUTCOME_CODES = frozenset(
    {
        "provider_validation",
        "conflict",
        "authentication_failed",
        "permission_denied",
        "not_found",
        "rate_limited",
    }
)


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    transport: Transport | None = None
    try:
        bounded_json(payload, 8 * 1024 * 1024)
        context = runtime_context_from_payload(payload)
        require(
            context.account_id and context.project_id,
            "An account and project are required.",
            "invalid_connection",
        )
        require(payload.get("mode") == "action", "An action envelope is required.")
        raw_context = payload["runtime_context"]
        require(type(raw_context.get("test_mode", False)) is bool, "test_mode must be boolean.")
        action = payload.get("action")
        if not isinstance(action, dict):
            raise Failure("invalid_payload", "Invalid action.")
        name = text(action.get("action_id"), 128, "action_id")
        require(name in OPERATIONS or name == VERIFY_ACTION, "Unknown FreeAgent operation.")
        args = action.get("input", {})
        target = action.get("target", {})
        require(
            isinstance(args, dict) and isinstance(target, dict), "Invalid action input or target."
        )
        connection = target.get("connection", {})
        require(
            isinstance(connection, dict) and connection.get("connection_type") in CONNECTION_TYPES,
            "Select a FreeAgent connection.",
            "invalid_connection",
        )
        if name != VERIFY_ACTION:
            require(
                isinstance(args.get("connection_ref"), str)
                and bool(args["connection_ref"])
                and connection.get("connection_id") == args["connection_ref"],
                "Select the matching explicit FreeAgent connection.",
                "invalid_connection",
            )
        config, token, host = connection_values(connection)
        operation = OPERATIONS["get_company" if name == VERIFY_ACTION else name]
        plan = prepare(operation, {} if name == VERIFY_ACTION else args, host)
        if operation.effect in WRITE_EFFECTS:
            require(
                not raw_context.get("test_mode", False),
                "FreeAgent writes are suppressed in Test Run.",
                "test_mode_suppressed",
            )
            require(
                config[ALLOWANCE[operation.effect]],
                "This kind of FreeAgent change is disabled on the connection.",
                "write_disabled",
            )
            require(
                isinstance(raw_context.get("external_effect_id"), str)
                and bool(raw_context["external_effect_id"]),
                "A durable host external-effect claim is required.",
                "effect_claim_required",
            )
        transport = Transport(host, token, config["request_timeout_seconds"])
        if name == VERIFY_ACTION:
            result = _verify(transport, config["environment"])
        else:
            result = _execute(payload, args, plan, transport)
        result = _redact(result, token)
        bounded_json(result, RESULT_LIMIT)
        return {"ok": True, "result": result, "errors": []}
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        unknown = transport is not None and transport.dispatched
        retryable = False
        if isinstance(exc, Failure):
            code, message, retryable = exc.code, str(exc), exc.retryable
            # An explicit provider rejection is a known outcome; anything after dispatch that
            # could not be read back stays uncertain for writes.
            unknown = (
                exc.applied_unknown
                if code in KNOWN_OUTCOME_CODES
                else unknown or exc.applied_unknown
            )
        else:
            code, message = "invalid_payload", "Invalid input or provider response."
        return {
            "ok": False,
            "result": {},
            "error_code": code,
            "error": message,
            "errors": [{"code": code, "message": message}],
            "retryable": retryable,
            "definitely_no_external_effect": not unknown,
            "external_effect_status": "timeout_unknown" if unknown else "not_applied",
        }


def _verify(transport: Transport, environment: str) -> dict[str, Any]:
    company = _root(transport.send("GET", "/company").json(), "company")
    require(
        isinstance(company, dict), "FreeAgent returned no company.", "invalid_provider_response"
    )
    name = company.get("name")
    display = (
        text(name, 200, "company name") if isinstance(name, str) and name else "FreeAgent company"
    )
    subdomain = company.get("subdomain")
    marker = (
        subdomain
        if isinstance(subdomain, str) and re.fullmatch(r"[a-z0-9-]{1,63}", subdomain)
        else ""
    )
    url = company.get("url") if isinstance(company.get("url"), str) else ""
    return {
        "subject": f"{environment}:{marker or url or display}",
        "verified_display_name": display + (" (sandbox)" if environment == "sandbox" else ""),
        "safe_metadata": {
            "environment": environment,
            "subdomain": marker,
            "company_type": str(company.get("type", ""))[:64],
            "currency": str(company.get("currency", ""))[:8],
        },
        "health": "ok",
    }


def _execute(
    payload: dict[str, Any], args: dict[str, Any], plan: Plan, transport: Transport
) -> dict[str, Any]:
    operation = plan.operation
    if operation.special == "pdf":
        reply = transport.send("GET", plan.path, plan.query, limit=30 * 1024 * 1024)
        return save_pdf(payload, operation, reply.json(), transport)
    if operation.special == "statement_file":
        body, content_type = statement_file(payload, args, transport)
        reply = transport.send(
            plan.method, plan.path, plan.query, body=body, content_type=content_type
        )
        return {"data": _root(reply.json(), "") or {"received": True}}
    if operation.special == "explanation_attachment":
        body_value = explanation_attachment(payload, args, transport)
        return _single(transport, plan, body_value)
    body_value = plan.body
    if operation.special == "inline_attachment" and args.get("artifact_handle"):
        body_value = inline_attachment(payload, args, plan, transport)
    if operation.paged:
        return _pages(transport, plan)
    return _single(transport, plan, body_value)


def _single(transport: Transport, plan: Plan, body_value: Any) -> dict[str, Any]:
    operation = plan.operation
    body = (
        json.dumps(body_value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if body_value is not None
        else None
    )
    reply = transport.send(plan.method, plan.path, plan.query, body=body)
    value = reply.json()
    if operation.method == "DELETE" and operation.effect != READ and not operation.response_root:
        return {"data": {"deleted": True, "path": "/v2" + plan.path}}
    if value is None and plan.reread:
        # Several FreeAgent updates and transitions answer 200 with an empty body; the
        # change is applied, so read the record back instead of reporting nothing.
        try:
            value = transport.send("GET", plan.reread).json()
        except Failure:
            return {"data": {"applied": True, "path": "/v2" + plan.path}}
    if value is None:
        location = reply.headers.get("location", "")
        return {"data": {"applied": True, "url": location} if location else {"applied": True}}
    return {"data": _root(value, operation.response_root)}


def _pages(transport: Transport, plan: Plan) -> dict[str, Any]:
    operation: Operation = plan.operation
    query = dict(plan.query)
    first_page = page = int(query.get("page", "1"))
    rows: list[Any] = []
    total: int | None = None
    next_page: int | None = None
    for _ in range(MAX_PAGES if plan.all_pages else 1):
        if plan.all_pages:
            query["page"] = str(page)
        reply = transport.send("GET", plan.path, query)
        value = _root(reply.json(), operation.response_root)
        require(isinstance(value, list), "FreeAgent returned no list.", "invalid_provider_response")
        rows.extend(value)
        total = _total(reply) if total is None else total
        next_page = _next_page(reply)
        if next_page is None:
            break
        page = next_page
    bounded_json(rows, RESULT_LIMIT)
    return {"data": rows, "page": first_page, "next_page": next_page, "total_count": total}


def _total(reply: Reply) -> int | None:
    raw = reply.headers.get("x-total-count", "")
    return int(raw) if raw.isdigit() else None


def _next_page(reply: Reply) -> int | None:
    for part in reply.headers.get("link", "").split(","):
        match = re.search(r'<([^>]+)>\s*;\s*rel="?next"?', part)
        if match:
            values = parse_qs(urlparse(match.group(1)).query).get("page", [])
            if values and values[0].isdigit():
                return int(values[0])
    return None


def _root(value: Any, root: str) -> Any:
    if not root:
        return value
    require(
        isinstance(value, dict) and root in value,
        "FreeAgent response is missing " + root + ".",
        "invalid_provider_response",
    )
    return value[root]


def _redact(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {
            str(key).replace(token, "[redacted]"): _redact(item, token)
            for key, item in value.items()
        }
    return value
