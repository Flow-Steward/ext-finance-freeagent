"""Bounded JSON, typed workflow inputs and connection configuration validation."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any

INPUT_LIMIT = 8 * 1024 * 1024
JSON_LIMIT = 2 * 1024 * 1024
RESULT_LIMIT = 4 * 1024 * 1024
ATTACHMENT_LIMIT = 5 * 1024 * 1024
STATEMENT_LIMIT = 10 * 1024 * 1024
PDF_LIMIT = 20 * 1024 * 1024

HOSTS = {"production": "api.freeagent.com", "sandbox": "api.sandbox.freeagent.com"}
CONNECTION_TYPES = {
    "freeagent_company": "production",
    "freeagent_sandbox_company": "sandbox",
}
ATTACHMENT_TYPES = frozenset(
    {
        "image/png",
        "image/x-png",
        "image/jpeg",
        "image/jpg",
        "image/gif",
        "application/x-pdf",
        "application/pdf",
    }
)
CONFIG_KEYS = frozenset(
    {"allow_create", "allow_update", "allow_delete", "allow_email", "request_timeout_seconds"}
)
ANY_FREEAGENT_API = re.compile(r"https?://api(?:\.sandbox)?\.freeagent\.com(?:[/:?#]|$)", re.I)


class Failure(ValueError):
    """A safe public failure with an explicit external-effect outcome."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        applied_unknown: bool = False,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.applied_unknown = applied_unknown
        self.retryable = retryable


def require(condition: Any, message: str, code: str = "invalid_payload") -> None:
    if not condition:
        raise Failure(code, message)


def text(value: Any, maximum: int = 512, name: str = "value") -> str:
    require(
        isinstance(value, str) and 0 < len(value) <= maximum,
        f"{name} must be a nonempty string of at most {maximum} characters.",
    )
    require(
        all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in value),
        f"{name} contains control characters.",
    )
    return str(value)


def integer(value: Any, low: int, high: int, name: str = "value") -> int:
    require(
        type(value) is int and low <= value <= high,
        f"{name} must be an integer from {low} to {high}.",
    )
    return int(value)


def iso_date(value: Any, name: str) -> str:
    raw = text(value, 10, name)
    try:
        ok = len(raw) == 10 and date.fromisoformat(raw).isoformat() == raw
    except ValueError:
        ok = False
    require(ok, f"{name} must be a date YYYY-MM-DD.")
    return raw


def iso_datetime(value: Any, name: str) -> str:
    raw = text(value, 40, name)
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        ok = re.fullmatch(r"[0-9T:.+\-Z]+", raw) is not None
    except ValueError:
        ok = False
    require(ok, f"{name} must be an ISO 8601 timestamp, e.g. 2026-01-31T09:00:00Z.")
    return raw


def bounded_json(value: Any, maximum: int = JSON_LIMIT) -> None:
    def visit(item: Any, depth: int) -> None:
        require(depth <= 24, "JSON nesting exceeds the limit.")
        if isinstance(item, dict):
            require(
                len(item) <= 2048 and all(isinstance(k, str) for k in item), "Invalid JSON object."
            )
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            require(len(item) <= 10000, "Too many array items.")
            for child in item:
                visit(child, depth + 1)
        elif type(item) is float:
            require(math.isfinite(item), "JSON numbers must be finite.")
        else:
            require(item is None or type(item) in (str, bool, int), "Invalid JSON value.")

    visit(value, 0)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    require(
        len(raw) <= maximum,
        "JSON exceeds the byte limit.",
        "response_too_large" if maximum >= RESULT_LIMIT else "invalid_payload",
    )


def foreign_api_urls(value: Any, host: str) -> bool:
    """True when any string in a request body names a FreeAgent API on another environment.

    A sandbox URL sent to production (or the reverse) would silently reference a record
    that does not exist there, so it is refused before anything is sent.
    """
    if isinstance(value, str):
        match = ANY_FREEAGENT_API.match(value)
        return bool(match) and not value.lower().startswith(f"https://{host}/")
    if isinstance(value, dict):
        return any(foreign_api_urls(item, host) for item in value.values())
    if isinstance(value, list):
        return any(foreign_api_urls(item, host) for item in value)
    return False


def resource_url(value: Any, resource: str, host: str, name: str) -> str:
    """A FreeAgent record URL on this connection's host; a bare numeric id is expanded."""
    if type(value) is int and value > 0:
        value = str(value)
    raw = text(value, 512, name)
    if re.fullmatch(r"[0-9]{1,20}", raw):
        return f"https://{host}/v2/{resource}/{raw}"
    pattern = rf"https://{re.escape(host)}/v2/{re.escape(resource)}/[A-Za-z0-9_.-]{{1,64}}"
    require(
        re.fullmatch(pattern, raw),
        f"{name} must be a numeric id or a {resource} URL of this FreeAgent connection.",
    )
    return raw


def record_id(value: Any, host: str, name: str = "id") -> str:
    """The trailing numeric id, given either the id itself or the record's API URL."""
    if type(value) is int and value > 0:
        return str(value)
    raw = text(value, 512, name)
    if re.fullmatch(r"[0-9]{1,20}", raw):
        return raw
    match = re.fullmatch(rf"https://{re.escape(host)}/v2/[a-z_]+(?:/[a-z_]+)?/([0-9]{{1,20}})", raw)
    require(match, f"{name} must be a numeric FreeAgent id or a record URL of this connection.")
    return match.group(1) if match else ""


def connection_values(connection: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    try:
        environment = CONNECTION_TYPES[connection.get("connection_type", "")]
        raw = connection.get("config", {})
        secrets = connection.get("secrets", {})
        require(isinstance(raw, dict) and isinstance(secrets, dict), "Invalid connection.")
        require(set(raw) <= CONFIG_KEYS, "Unknown connection configuration.")
        require(set(secrets) == {"access_token"}, "Only a host-injected access token is accepted.")
        config = dict(raw)
        config["environment"] = environment
        config["request_timeout_seconds"] = integer(
            config.get("request_timeout_seconds", 30), 5, 60
        )
        for key in ("allow_create", "allow_update", "allow_delete", "allow_email"):
            config[key] = config.get(key, True)
            require(type(config[key]) is bool, "Write permissions must be boolean.")
        token = text(secrets.get("access_token"), 8192)
        require(not any(c.isspace() for c in token), "Invalid access token.")
        return config, token, HOSTS[environment]
    except (ValueError, TypeError, KeyError):
        raise Failure(
            "invalid_connection", "Invalid FreeAgent connection configuration or access token."
        ) from None
