"""Turn one catalog operation plus validated workflow input into one fixed HTTP request plan."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from freeagent.catalog import Operation, Param
from freeagent.validation import (
    ATTACHMENT_TYPES,
    bounded_json,
    foreign_api_urls,
    integer,
    iso_date,
    iso_datetime,
    record_id,
    require,
    resource_url,
    text,
)

ONE_OF_PARENT = frozenset({"list_notes", "create_note"})
ARTIFACT_INPUTS = (
    "artifact_handle",
    "attachment_file_name",
    "attachment_content_type",
    "attachment_description",
)


@dataclass(frozen=True)
class Plan:
    operation: Operation
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    body: Any = None
    all_pages: bool = False
    reread: str = ""


def _value(param: Param, raw: Any, host: str) -> str:
    name = param.name
    if param.kind == "integer":
        return str(integer(raw, param.minimum, param.maximum, name))
    if param.kind == "boolean":
        require(type(raw) is bool, f"{name} must be true or false.")
        return "true" if raw else "false"
    if param.kind == "date":
        return iso_date(raw, name)
    if param.kind == "datetime":
        return iso_datetime(raw, name)
    if param.kind == "enum":
        require(raw in param.choices, f"{name} must be one of: {', '.join(param.choices)}.")
        return str(raw)
    if param.kind == "resource":
        return resource_url(raw, param.resource, host, name)
    if param.kind == "id":
        return record_id(raw, host, name)
    if param.kind == "slug":
        value = text(raw, 64, name)
        require(re.fullmatch(r"-?[a-z0-9_]{1,63}", value), f"{name} must be a FreeAgent keyword.")
        return value
    if param.kind == "nominal_code":
        value = text(str(raw) if type(raw) is int else raw, 16, name)
        require(
            re.fullmatch(r"[0-9]{3}(?:-[0-9]{1,6})?", value), f"{name} must look like 250 or 750-1."
        )
        return value
    if param.kind == "accounting_period":
        value = text(raw, 7, name)
        require(re.fullmatch(r"[0-9]{4}/[0-9]{2}", value), f"{name} must look like 2025/26.")
        return value
    if param.kind == "file_name":
        value = text(raw, 255, name)
        require(not re.search(r'[/\\"]', value), f"{name} must be a plain file name.")
        return value
    if param.kind == "attachment_type":
        require(raw in ATTACHMENT_TYPES, f"{name} must be PNG, JPEG, GIF or PDF.")
        return str(raw)
    return text(raw, 1024, name)


def _body(operation: Operation, args: dict[str, Any], host: str, key: str, kind: type) -> Any:
    value = args.get(key)
    if kind is dict and isinstance(value, dict) and set(value) == {operation.body_root}:
        # Accept a body already wrapped in its FreeAgent root key.
        value = value[operation.body_root]
    require(
        isinstance(value, kind) and len(value) > 0,
        f"{key} must be a nonempty {'object' if kind is dict else 'array'}.",
    )
    bounded_json(value)
    require(
        not foreign_api_urls(value, host),
        f"{key} references a FreeAgent URL of a different environment than this connection.",
    )
    return value


def prepare(operation: Operation, args: dict[str, Any], host: str) -> Plan:
    declared = {param.name for param in operation.params} | {
        "connection_ref",
        "data",
        "email",
        "statement",
        *ARTIFACT_INPUTS,
    }
    unknown = sorted(set(args) - declared)
    require(not unknown, "Unknown input: " + ", ".join(unknown[:5]) + ".")
    path_values: dict[str, str] = {}
    query: dict[str, str] = {}
    all_pages = False
    for param in operation.params:
        raw = args.get(param.name)
        if raw is None or raw == "":
            require(not param.required, f"{param.name} is required.")
            continue
        if param.name == "all_pages":
            require(type(raw) is bool, "all_pages must be true or false.")
            all_pages = raw
            continue
        value = _value(param, raw, host)
        if param.location == "path":
            path_values[param.name] = value
        elif operation.special in ("explanation_attachment", "statement_file") and param.name in (
            "file_name",
            "content_type",
            "description",
        ):
            continue  # These describe the uploaded file, not the HTTP query.
        else:
            query[param.name] = value
    if operation.name in ONE_OF_PARENT:
        require(
            ("contact" in query) != ("project" in query),
            "Give exactly one of contact or project.",
        )
    path = re.sub(r"\{([a-z_]+)\}", lambda m: path_values[m.group(1)], operation.path)
    reread = (
        re.sub(r"\{([a-z_]+)\}", lambda m: path_values[m.group(1)], operation.reread_path)
        if operation.reread_path
        else ""
    )
    body: Any = None
    if operation.body == "data":
        data = _body(operation, args, host, "data", dict)
        body = {operation.body_root: data} if operation.body_root else data
    elif operation.body == "email":
        body = {operation.body_root: {"email": _body(operation, args, host, "email", dict)}}
    elif operation.body == "statement":
        rows = _body(operation, args, host, "statement", list)
        require(all(isinstance(row, dict) for row in rows), "statement rows must be objects.")
        for row in rows:
            iso_date(row.get("dated_on"), "statement dated_on")
        body = {"statement": rows}
    elif operation.body == "estimate_item":
        body = {
            "estimate": query.pop("estimate"),
            "estimate_item": _body(operation, args, host, "data", dict),
        }
    if operation.special != "inline_attachment":
        stray = [name for name in ARTIFACT_INPUTS if args.get(name) not in (None, "")]
        require(
            operation.special in ("explanation_attachment", "statement_file") or not stray,
            "This operation does not take a file.",
        )
    if operation.paged and all_pages:
        query.pop("page", None)
        query["per_page"] = "100"
    return Plan(operation, operation.method, path, query, body, all_pages, reread)


def attachment_meta(args: dict[str, Any], *, file_key: str, type_key: str) -> tuple[str, str]:
    file_name = text(args.get(file_key), 255, file_key)
    require(not re.search(r'[/\\"]', file_name), f"{file_key} must be a plain file name.")
    content_type = args.get(type_key)
    require(content_type in ATTACHMENT_TYPES, f"{type_key} must be PNG, JPEG, GIF or PDF.")
    return file_name, str(content_type)
