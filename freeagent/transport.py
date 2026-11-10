"""Bounded, DNS-pinned HTTPS requests to the one FreeAgent API host of a connection."""

from __future__ import annotations

import ipaddress
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from flowsteward_extension_sdk import open_pinned_url, parse_retry_after, resolve_pinned_ips

from freeagent.catalog import API_VERSION
from freeagent.validation import RESULT_LIMIT, Failure, require

USER_AGENT = "FlowSteward-FreeAgent-Extension/0.1.0"
ERROR_LIMIT = 32 * 1024
READ_CHUNK = 64 * 1024
MAX_RATE_LIMIT_WAIT = 10.0


@dataclass(frozen=True)
class Reply:
    status: int
    headers: dict[str, str]
    raw: bytes

    def json(self) -> Any:
        if not self.raw.strip():
            return None
        try:
            return json.loads(self.raw)
        except (ValueError, UnicodeError, RecursionError):
            raise Failure("invalid_provider_response", "FreeAgent returned invalid JSON.") from None


def provider_messages(raw: bytes) -> list[str]:
    """Human-readable FreeAgent validation messages, bounded and stripped of control chars."""
    try:
        value = json.loads(raw) if raw and len(raw) <= ERROR_LIMIT else None
    except (ValueError, UnicodeError, RecursionError):
        return []
    found: list[str] = []

    def visit(item: Any, depth: int) -> None:
        if depth > 6 or len(found) >= 5:
            return
        if isinstance(item, dict):
            message = item.get("message")
            if isinstance(message, str):
                found.append(message)
            for key, child in item.items():
                if key != "message":
                    visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str) and depth > 0:
            found.append(item)

    if isinstance(value, dict):
        visit(value.get("errors", value.get("error")), 1)
    return [
        "".join(c for c in message if c.isprintable())[:300] for message in found[:5] if message
    ]


class Transport:
    """One FreeAgent host per connection; the deadline covers every request of the step."""

    def __init__(self, host: str, token: str, timeout_seconds: int) -> None:
        self.host = host
        self.token = token
        self.deadline = time.monotonic() + timeout_seconds
        self.dispatched = False
        self._ips: tuple[str, ...] = ()

    def _pinned(self) -> tuple[str, ...]:
        if self._ips:
            return self._ips
        try:
            ips = tuple(resolve_pinned_ips(self.host, port=443, purpose="FreeAgent API"))
            require(
                ips and all(ipaddress.ip_address(ip).is_global for ip in ips),
                "FreeAgent DNS resolved to a forbidden address.",
                "network_blocked",
            )
        except (OSError, ValueError):
            raise Failure(
                "network_blocked",
                "FreeAgent DNS resolution failed or returned a forbidden address.",
            ) from None
        self._ips = ips
        return ips

    def send(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        *,
        body: bytes | None = None,
        content_type: str = "application/json",
        limit: int = RESULT_LIMIT,
    ) -> Reply:
        require(
            path.startswith("/")
            and not path.startswith("//")
            and "?" not in path
            and ".." not in path,
            "Invalid internal provider route.",
        )
        url = f"https://{self.host}/v2{path}"
        if query:
            url += "?" + urlencode(query)
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-Api-Version": API_VERSION,
        }
        if body is not None:
            headers["Content-Type"] = content_type
        for attempt in (1, 2):
            request = Request(url, data=body, method=method, headers=headers)
            ips = self._pinned()
            remaining = self.deadline - time.monotonic()
            require(remaining > 0, "Operation deadline exceeded.", "timeout")
            if method != "GET":
                self.dispatched = True
            try:
                with open_pinned_url(
                    request, timeout_seconds=remaining, purpose="FreeAgent API", pinned_ips=ips
                ) as response:
                    status = int(response.status)
                    reply_headers = {k.lower(): v for k, v in response.headers.items()}
                    require(
                        status in (200, 201, 202, 204),
                        "Unexpected FreeAgent response status.",
                        "invalid_provider_response",
                    )
                    return Reply(status, reply_headers, self._read(response, limit))
            except HTTPError as exc:
                wait = self._retry_wait(exc, method, attempt)
                if wait is None:
                    raise self._http_failure(exc, method) from None
                exc.close()
                time.sleep(wait)
            except (TimeoutError, OSError, URLError):
                raise Failure(
                    "provider_unavailable",
                    "FreeAgent request failed. No automatic retry was performed.",
                    applied_unknown=self.dispatched,
                ) from None
        raise Failure(
            "rate_limited", "FreeAgent rate limit reached.", retryable=True
        )  # pragma: no cover

    def _retry_wait(self, exc: HTTPError, method: str, attempt: int) -> float | None:
        """One short wait for a read refused by the per-minute rate limit; never for writes."""
        if exc.code != 429 or method != "GET" or attempt != 1:
            return None
        wait = parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
        if wait is None or wait > MAX_RATE_LIMIT_WAIT:
            return None
        if self.deadline - time.monotonic() <= wait + 2:
            return None
        return wait

    def _read(self, response: Any, maximum: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            if time.monotonic() >= self.deadline:
                raise Failure(
                    "timeout",
                    "FreeAgent response deadline exceeded.",
                    applied_unknown=self.dispatched,
                )
            chunk = response.read(min(READ_CHUNK, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise Failure(
                    "response_too_large",
                    "FreeAgent response exceeds the byte limit; narrow the filter or page size.",
                    applied_unknown=self.dispatched,
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _http_failure(self, exc: HTTPError, method: str) -> Failure:
        try:
            raw = exc.read(ERROR_LIMIT + 1)
        except OSError:
            raw = b""
        finally:
            exc.close()
        messages = provider_messages(raw)
        code = {
            400: "provider_validation",
            401: "authentication_failed",
            403: "permission_denied",
            404: "not_found",
            406: "provider_validation",
            409: "conflict",
            422: "provider_validation",
            429: "rate_limited",
        }.get(exc.code, "provider_unavailable")
        text = {
            "authentication_failed": "FreeAgent refused the access token; reconnect the account.",
            "permission_denied": "The FreeAgent user who connected lacks the access level this "
            "operation needs.",
            "not_found": "FreeAgent has no such record or route.",
            "rate_limited": "FreeAgent rate limit reached (120 requests per minute, 3600 per hour).",
        }.get(code, f"FreeAgent returned HTTP {exc.code}.")
        if code == "rate_limited":
            wait = parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            if wait:
                text += f" Retry after {int(wait)} seconds."
        if messages:
            text += " " + " ".join(messages)
        return Failure(
            code,
            text,
            applied_unknown=method != "GET" and exc.code >= 500,
            retryable=code == "rate_limited"
            or (code == "provider_unavailable" and method == "GET"),
        )
