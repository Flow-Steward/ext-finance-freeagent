"""Every catalog operation traverses the real runtime and reaches its one fixed route."""

from __future__ import annotations

import base64
import re
from typing import Any
from unittest.mock import patch

import pytest
from conftest import envelope, invoke, reply

from freeagent.catalog import OPERATIONS, Operation, Param

PROD = "https://api.freeagent.com/v2"
SAMPLE: dict[str, Any] = {
    "id": "7",
    "date": "2026-03-31",
    "datetime": "2026-01-01T00:00:00Z",
    "slug": "all",
    "text": "Austria",
    "boolean": True,
    "nominal_code": "250",
    "accounting_period": "2025/26",
    "file_name": "file.png",
    "attachment_type": "image/png",
}


def sample(param: Param) -> Any:
    if param.kind == "integer":
        return param.minimum
    if param.kind in ("enum",):
        return param.choices[0]
    if param.kind == "resource":
        return "3"
    if param.name == "file_name" and param.kind == "file_name":
        return "file.ofx"
    return SAMPLE[param.kind]


def arguments(op: Operation) -> dict[str, Any]:
    args = {param.name: sample(param) for param in op.params if param.required}
    if op.name in ("list_notes", "create_note"):
        args["contact"] = "3"
    if op.body in ("data", "estimate_item"):
        args["data"] = {"description": "Example"}
    if op.body == "email":
        args["email"] = {"use_template": True}
    if op.body == "statement":
        args["statement"] = [{"dated_on": "2026-01-01", "amount": "1.00", "description": "x"}]
    if op.special in ("statement_file", "explanation_attachment"):
        args["artifact_handle"] = "art-1"
    return args


def expected_path(op: Operation, args: dict[str, Any]) -> str:
    return PROD + re.sub(r"\{([a-z_]+)\}", lambda m: str(args[str(m.group(1))]), op.path)


def provider_reply(op: Operation) -> Any:
    if op.special == "pdf":
        return reply({"pdf": {"content": base64.b64encode(b"%PDF-1.4").decode()}})
    if op.paged:
        return reply({op.response_root: [{"url": PROD + "/x/1"}]})
    if op.response_root:
        return reply({op.response_root: {"url": PROD + "/x/1"}})
    return reply({"anything": [1]})


@pytest.mark.parametrize("name", sorted(OPERATIONS))
def test_operation_reaches_its_route_and_normalizes(name):
    from freeagent import documents

    op = OPERATIONS[name]
    args = arguments(op)
    with (
        patch.object(documents, "read_artifact_bytes", return_value=b"OFX-or-PNG"),
        patch.object(documents, "write_artifact_bytes", return_value={"artifact_handle": "out-1"}),
    ):
        result, sent, _ = invoke(envelope(name, **args), provider_reply(op))
    assert result["ok"] is True, result
    request = sent[0]
    assert request.get_method() == op.method
    assert request.full_url.split("?")[0] == expected_path(op, args)
    if op.method == "GET":
        assert request.data is None
    data = result["result"].get("data")
    if op.special == "pdf":
        assert result["result"] == {"pdf_artifact_handle": "out-1"}
    elif op.method == "DELETE" and not op.response_root:
        assert data["deleted"] is True
    elif op.paged:
        assert data == [{"url": PROD + "/x/1"}]
    elif op.response_root:
        assert data == {"url": PROD + "/x/1"}
    else:
        assert data == {"anything": [1]}


@pytest.mark.parametrize("name", sorted(n for n, op in OPERATIONS.items() if op.effect != "read"))
def test_every_write_is_suppressed_in_test_run(name):
    payload = envelope(name, **arguments(OPERATIONS[name]))
    payload["runtime_context"]["test_mode"] = True
    result, sent, _ = invoke(payload)
    assert result["error_code"] == "test_mode_suppressed"
    assert sent == []


def test_catalog_paths_are_fixed_templates():
    for op in OPERATIONS.values():
        assert re.fullmatch(r"(/[a-z_]+|/\{[a-z_]+\})+", op.path), op.name
        placeholders = set(re.findall(r"\{([a-z_]+)\}", op.path))
        path_params = {p.name for p in op.params if p.location == "path"}
        assert placeholders == path_params, op.name
        assert all(p.required for p in op.params if p.location == "path"), op.name
        assert (op.method == "GET") == (op.effect == "read"), op.name
