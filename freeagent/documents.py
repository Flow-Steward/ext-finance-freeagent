"""Host-granted file inputs and PDF outputs; no local paths and no arbitrary download URLs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import time
from typing import Any

from flowsteward_extension_sdk import ArtifactAccessError, read_artifact_bytes, write_artifact_bytes

from freeagent.catalog import Operation
from freeagent.plans import Plan, attachment_meta
from freeagent.transport import Transport
from freeagent.validation import (
    ATTACHMENT_LIMIT,
    PDF_LIMIT,
    STATEMENT_LIMIT,
    Failure,
    require,
    text,
)

INPUT_BINDING = "attachment_input"
PDF_BINDING = "pdf_artifact_handle"


def _read(payload: dict[str, Any], transport: Transport, limit: int) -> bytes:
    remaining = max(1.0, transport.deadline - time.monotonic())
    try:
        raw = read_artifact_bytes(payload, binding_key=INPUT_BINDING, timeout_seconds=remaining)
    except (ArtifactAccessError, OSError, ValueError):
        raise Failure("artifact_unavailable", "The approved file input is unavailable.") from None
    require(len(raw) > 0, "The file is empty.")
    require(
        len(raw) <= limit,
        f"The file exceeds FreeAgent's {limit // (1024 * 1024)} MB limit.",
        "file_too_large",
    )
    return raw


def _encoded(raw: bytes, file_name: str, content_type: str, description: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "data": base64.b64encode(raw).decode("ascii"),
        "file_name": file_name,
        "content_type": content_type,
    }
    if description not in (None, ""):
        item["description"] = text(description, 1024, "attachment_description")
    return item


def inline_attachment(
    payload: dict[str, Any], args: dict[str, Any], plan: Plan, transport: Transport
) -> dict[str, Any]:
    """A bill or expense body carrying its receipt as FreeAgent's base64 `attachment`."""
    file_name, content_type = attachment_meta(
        args, file_key="attachment_file_name", type_key="attachment_content_type"
    )
    raw = _read(payload, transport, ATTACHMENT_LIMIT)
    body = dict(plan.body or {})
    record = dict(body[plan.operation.body_root])
    require(
        "attachment" not in record,
        "Give the receipt either in data.attachment or as a file, not both.",
    )
    record["attachment"] = _encoded(
        raw, file_name, content_type, args.get("attachment_description")
    )
    body[plan.operation.body_root] = record
    return body


def explanation_attachment(
    payload: dict[str, Any], args: dict[str, Any], transport: Transport
) -> dict[str, Any]:
    file_name, content_type = attachment_meta(args, file_key="file_name", type_key="content_type")
    raw = _read(payload, transport, ATTACHMENT_LIMIT)
    return {"attachments": [_encoded(raw, file_name, content_type, args.get("description"))]}


def statement_file(
    payload: dict[str, Any], args: dict[str, Any], transport: Transport
) -> tuple[bytes, str]:
    file_name = text(args.get("file_name"), 255, "file_name")
    require(
        re.fullmatch(r"[A-Za-z0-9 ._()-]{1,251}\.(?:ofx|qif|csv)", file_name, re.I),
        "file_name must be a plain .ofx, .qif or .csv name.",
    )
    raw = _read(payload, transport, STATEMENT_LIMIT)
    boundary = "fs-freeagent-" + hashlib.sha256(raw).hexdigest()[:32]
    require(boundary.encode() not in raw, "The file contains a multipart boundary collision.")
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="statement"; '
        f'filename="{file_name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
        + raw
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, "multipart/form-data; boundary=" + boundary


def save_pdf(
    payload: dict[str, Any], operation: Operation, value: Any, transport: Transport
) -> dict[str, Any]:
    pdf = value.get("pdf") if isinstance(value, dict) else None
    content = pdf.get("content") if isinstance(pdf, dict) else None
    require(
        isinstance(content, str) and content,
        "FreeAgent returned no PDF.",
        "invalid_provider_response",
    )
    try:
        raw = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        raise Failure(
            "invalid_provider_response", "FreeAgent returned an invalid PDF encoding."
        ) from None
    require(
        raw.startswith(b"%PDF-"), "FreeAgent did not return a PDF.", "invalid_provider_response"
    )
    require(len(raw) <= PDF_LIMIT, "The PDF exceeds the size limit.", "response_too_large")
    remaining = max(1.0, transport.deadline - time.monotonic())
    try:
        written = write_artifact_bytes(
            payload,
            raw,
            binding_key=PDF_BINDING,
            content_type="application/pdf",
            timeout_seconds=remaining,
        )
    except (ArtifactAccessError, OSError, ValueError):
        raise Failure("artifact_unavailable", "The approved PDF output is unavailable.") from None
    handle = written.get("artifact_handle") if isinstance(written, dict) else None
    require(
        isinstance(handle, str) and handle, "Invalid PDF output artifact.", "artifact_unavailable"
    )
    return {PDF_BINDING: handle}
