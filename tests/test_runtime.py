"""Host boundary, request shaping and provider-response handling."""

from __future__ import annotations

import base64
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import TOKEN, envelope, http_error, invoke, reply

PROD = "https://api.freeagent.com/v2"
SANDBOX = "https://api.sandbox.freeagent.com/v2"


def body_of(request):
    return json.loads(request.data)


def query_of(request):
    return {k: v[0] for k, v in parse_qs(urlparse(request.full_url).query).items()}


def test_read_uses_fixed_host_bearer_user_agent_and_pinned_api_version():
    result, sent, _ = invoke(envelope("get_contact", id="7"))
    assert result == {
        "ok": True,
        "result": {"data": {"url": PROD + "/contacts/7"}},
        "errors": [],
    }
    request = sent[0]
    assert request.full_url == PROD + "/contacts/7"
    assert request.get_method() == "GET"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["X-api-version"] == "2026-09-01"
    assert request.headers["User-agent"].startswith("FlowSteward-FreeAgent")
    assert request.data is None


def test_sandbox_connection_type_selects_sandbox_host():
    result, sent, _ = invoke(
        envelope("get_contact", "freeagent_sandbox_company", id=SANDBOX + "/contacts/9")
    )
    assert result["ok"] is True
    assert sent[0].full_url == SANDBOX + "/contacts/9"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(contract_version="other"),
        lambda p: p["runtime_context"].update(project_id=""),
        lambda p: p.update(mode="source"),
        lambda p: p["action"]["input"].update(connection_ref="company-2"),
        lambda p: p["action"]["target"]["connection"].update(connection_type="quickbooks_company"),
        lambda p: p["action"]["target"]["connection"]["config"].update(
            base_url="https://evil.test"
        ),
        lambda p: p["action"]["target"]["connection"]["secrets"].update(refresh_token="x"),
        lambda p: p["action"]["target"]["connection"]["secrets"].update(access_token="a b"),
        lambda p: p["action"].update(action_id="get_unknown"),
        lambda p: p["action"]["input"].update(id="../users/1"),
        lambda p: p["action"]["input"].update(id=SANDBOX + "/contacts/7"),
        lambda p: p["action"]["input"].update(id="https://evil.test/v2/contacts/7"),
        lambda p: p["action"]["input"].update(path="/users"),
    ],
)
def test_invalid_host_input_or_connection_never_calls_provider(mutate):
    payload = envelope("get_contact", id="7")
    mutate(payload)
    result, sent, _ = invoke(payload)
    assert result["ok"] is False
    assert result["definitely_no_external_effect"] is True
    assert sent == []


def test_list_filters_expand_ids_to_urls_and_pass_typed_values():
    result, sent, _ = invoke(
        envelope(
            "list_invoices",
            view="open_or_overdue",
            contact="12",
            updated_since="2026-01-01T00:00:00Z",
            nested_invoice_items=True,
            per_page=50,
        ),
        reply({"invoices": [{"url": PROD + "/invoices/1"}]}, headers={"X-Total-Count": "1"}),
    )
    assert result["ok"] is True
    assert result["result"] == {
        "data": [{"url": PROD + "/invoices/1"}],
        "page": 1,
        "next_page": None,
        "total_count": 1,
    }
    assert query_of(sent[0]) == {
        "view": "open_or_overdue",
        "contact": PROD + "/contacts/12",
        "updated_since": "2026-01-01T00:00:00Z",
        "nested_invoice_items": "true",
        "per_page": "50",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("from_date", "2026-02-30"),
        ("from_date", "01/02/2026"),
        ("view", "open&x=1"),
        ("contact", "abc"),
        ("per_page", 101),
        ("per_page", "10"),
        ("all_pages", "yes"),
    ],
)
def test_bad_filter_values_are_refused(field, value):
    name = "list_bills"
    result, sent, _ = invoke(envelope(name, **{field: value}))
    assert result["ok"] is False and result["error_code"] == "invalid_payload"
    assert sent == []


def test_all_pages_follows_link_header_with_maximum_page_size():
    first = reply(
        {"contacts": [{"n": 1}]},
        headers={
            "Link": f'<{PROD}/contacts?page=2&per_page=100>; rel="next", '
            f'<{PROD}/contacts?page=2&per_page=100>; rel="last"',
            "X-Total-Count": "2",
        },
    )
    second = reply({"contacts": [{"n": 2}]}, headers={"X-Total-Count": "2"})
    result, sent, _ = invoke(envelope("list_contacts", all_pages=True, page=5), first, second)
    assert result["result"] == {
        "data": [{"n": 1}, {"n": 2}],
        "page": 1,
        "next_page": None,
        "total_count": 2,
    }
    assert [query_of(r) for r in sent] == [
        {"per_page": "100", "page": "1"},
        {"per_page": "100", "page": "2"},
    ]


def test_single_page_reports_next_page_from_link():
    result, _, _ = invoke(
        envelope("list_contacts", page=3),
        reply({"contacts": []}, headers={"Link": f'<{PROD}/contacts?page=4>; rel="next"'}),
    )
    assert result["result"]["next_page"] == 4
    assert result["result"]["page"] == 3


def test_required_list_filter_is_enforced():
    result, sent, _ = invoke(envelope("list_bank_transactions"))
    assert result["ok"] is False and "bank_account is required" in result["error"]
    assert sent == []


@pytest.mark.parametrize("given", [{}, {"contact": "1", "project": "2"}])
def test_notes_need_exactly_one_parent(given):
    result, sent, _ = invoke(envelope("list_notes", **given))
    assert result["ok"] is False and sent == []


def test_create_wraps_root_and_accepts_prewrapped_body():
    data = {"contact": PROD + "/contacts/1", "dated_on": "2026-11-10", "payment_terms_in_days": 30}
    for given in (data, {"invoice": data}):
        result, sent, _ = invoke(
            envelope("create_invoice", data=given),
            reply({"invoice": {"url": PROD + "/invoices/5"}}, status=201),
        )
        assert result["result"] == {"data": {"url": PROD + "/invoices/5"}}
        assert sent[0].get_method() == "POST"
        assert sent[0].full_url == PROD + "/invoices"
        assert body_of(sent[0]) == {"invoice": data}
        assert sent[0].headers["Content-type"] == "application/json"


def test_body_with_url_of_other_environment_is_refused():
    result, sent, _ = invoke(
        envelope("create_invoice", data={"contact": SANDBOX + "/contacts/1"}),
    )
    assert result["ok"] is False and "different environment" in result["error"]
    assert sent == []


def test_writes_are_suppressed_in_test_run_and_need_a_claim():
    payload = envelope("delete_contact", id="1")
    payload["runtime_context"]["test_mode"] = True
    result, sent, _ = invoke(payload)
    assert result["error_code"] == "test_mode_suppressed" and sent == []
    payload = envelope("delete_contact", id="1")
    payload["runtime_context"]["external_effect_id"] = ""
    result, sent, _ = invoke(payload)
    assert result["error_code"] == "effect_claim_required" and sent == []


@pytest.mark.parametrize(
    ("operation", "args", "switch"),
    [
        ("create_contact", {"data": {"organisation_name": "A"}}, "allow_create"),
        ("update_contact", {"id": "1", "data": {"email": "a@b.test"}}, "allow_update"),
        ("delete_contact", {"id": "1"}, "allow_delete"),
        ("send_invoice_email", {"id": "1", "email": {"use_template": True}}, "allow_email"),
    ],
)
def test_connection_switches_disable_each_write_kind(operation, args, switch):
    payload = envelope(operation, **args)
    payload["action"]["target"]["connection"]["config"][switch] = False
    result, sent, _ = invoke(payload)
    assert result["error_code"] == "write_disabled" and sent == []


def test_reads_are_allowed_in_test_run():
    payload = envelope("get_contact", id="7")
    payload["runtime_context"]["test_mode"] = True
    result, sent, _ = invoke(payload)
    assert result["ok"] is True and len(sent) == 1


def test_send_email_wraps_email_object():
    result, sent, _ = invoke(
        envelope("send_invoice_email", id="3", email={"use_template": True}), reply(None)
    )
    assert result["ok"] is True
    assert sent[0].full_url == PROD + "/invoices/3/send_email"
    assert body_of(sent[0]) == {"invoice": {"email": {"use_template": True}}}


def test_transition_with_empty_reply_reads_the_record_back():
    result, sent, _ = invoke(
        envelope("transition_invoice", id="3", transition="mark_as_sent"),
        reply(None),
        reply({"invoice": {"status": "Sent"}}),
    )
    assert result["result"] == {"data": {"status": "Sent"}}
    assert [(r.get_method(), r.full_url) for r in sent] == [
        ("PUT", PROD + "/invoices/3/transitions/mark_as_sent"),
        ("GET", PROD + "/invoices/3"),
    ]


def test_transition_refuses_unknown_state():
    result, sent, _ = invoke(envelope("transition_invoice", id="3", transition="mark_as_paid"))
    assert result["ok"] is False and sent == []


def test_delete_reports_deleted_path():
    result, sent, _ = invoke(envelope("delete_bill", id=PROD + "/bills/8"), reply(None))
    assert result["result"] == {"data": {"deleted": True, "path": "/v2/bills/8"}}
    assert sent[0].get_method() == "DELETE"


def test_validation_error_surfaces_provider_messages_as_known_outcome():
    error = http_error(422, {"errors": {"error": {"message": "Contact can't be blank"}}})
    result, _, _ = invoke(envelope("create_invoice", data={"dated_on": "2026-11-10"}), error)
    assert result["ok"] is False
    assert result["error_code"] == "provider_validation"
    assert "Contact can't be blank" in result["error"]
    assert result["definitely_no_external_effect"] is True
    assert result["external_effect_status"] == "not_applied"


def test_provider_message_list_form_is_read():
    error = http_error(400, {"errors": [{"message": "Bad date"}, {"message": "Bad total"}]})
    result, _, _ = invoke(envelope("get_contact", id="1"), error)
    assert "Bad date" in result["error"] and "Bad total" in result["error"]


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "authentication_failed"), (403, "permission_denied"), (404, "not_found")],
)
def test_status_codes_map_to_stable_error_codes(status, code):
    result, _, _ = invoke(envelope("get_contact", id="1"), http_error(status))
    assert result["error_code"] == code


def test_server_error_after_write_is_reported_as_uncertain():
    result, _, _ = invoke(
        envelope("create_contact", data={"organisation_name": "A"}), http_error(502)
    )
    assert result["error_code"] == "provider_unavailable"
    assert result["definitely_no_external_effect"] is False
    assert result["external_effect_status"] == "timeout_unknown"


def test_network_timeout_after_write_is_uncertain_and_before_read_is_not():
    result, _, _ = invoke(
        envelope("create_contact", data={"organisation_name": "A"}), TimeoutError()
    )
    assert result["external_effect_status"] == "timeout_unknown"
    result, _, _ = invoke(envelope("get_contact", id="1"), TimeoutError())
    assert result["external_effect_status"] == "not_applied"
    assert result["retryable"] is False


def test_read_rate_limit_waits_once_then_succeeds():
    result, sent, sleep = invoke(
        envelope("get_contact", id="1"),
        http_error(429, b"slow down", {"Retry-After": "3"}),
        reply({"contact": {"n": 1}}),
    )
    assert result["ok"] is True and len(sent) == 2
    sleep.assert_called_once_with(3.0)


def test_write_rate_limit_is_not_retried_and_is_retryable_for_the_host():
    result, sent, sleep = invoke(
        envelope("create_contact", data={"organisation_name": "A"}),
        http_error(429, b"", {"Retry-After": "60"}),
    )
    assert result["error_code"] == "rate_limited"
    assert result["retryable"] is True
    assert result["definitely_no_external_effect"] is True
    assert "Retry after 60 seconds" in result["error"]
    assert len(sent) == 1 and not sleep.called


def test_long_rate_limit_wait_is_not_slept():
    result, sent, sleep = invoke(
        envelope("get_contact", id="1"), http_error(429, b"", {"Retry-After": "60"})
    )
    assert result["error_code"] == "rate_limited" and len(sent) == 1 and not sleep.called


def test_token_echoed_by_provider_is_redacted():
    result, _, _ = invoke(envelope("get_contact", id="1"), reply({"contact": {"note": TOKEN}}))
    assert TOKEN not in json.dumps(result)


def test_oversized_response_is_refused():
    big = {"contacts": [{"x": "y" * 1024}] * 5000}
    result, _, _ = invoke(envelope("list_contacts"), reply(big))
    assert result["error_code"] == "response_too_large"


def test_verify_company_reads_company_without_workflow_input():
    payload = envelope("verify_company", "freeagent_sandbox_company")
    payload["action"]["input"] = {}
    result, sent, _ = invoke(
        payload,
        reply(
            {
                "company": {
                    "name": "Acme Ltd",
                    "subdomain": "acme",
                    "type": "UkLimitedCompany",
                    "currency": "GBP",
                }
            }
        ),
    )
    assert result["result"] == {
        "subject": "sandbox:acme",
        "verified_display_name": "Acme Ltd (sandbox)",
        "safe_metadata": {
            "environment": "sandbox",
            "subdomain": "acme",
            "company_type": "UkLimitedCompany",
            "currency": "GBP",
        },
        "health": "ok",
    }
    assert sent[0].full_url == SANDBOX + "/company"


def test_statement_rows_are_sent_to_the_selected_bank_account():
    rows = [{"dated_on": "2026-11-01", "amount": "-12.50", "description": "Coffee"}]
    result, sent, _ = invoke(
        envelope("upload_bank_statement", bank_account="4", statement=rows), reply(None)
    )
    assert result["ok"] is True
    assert sent[0].full_url == PROD + "/bank_transactions/statement?bank_account=" + (
        "https%3A%2F%2Fapi.freeagent.com%2Fv2%2Fbank_accounts%2F4"
    )
    assert body_of(sent[0]) == {"statement": rows}


def test_statement_rows_need_dates():
    result, sent, _ = invoke(
        envelope("upload_bank_statement", bank_account="4", statement=[{"amount": "1"}])
    )
    assert result["ok"] is False and sent == []


def test_invoice_pdf_is_decoded_and_written_as_artifact():
    from freeagent import documents

    pdf = b"%PDF-1.7 fixture"
    with patch.object(
        documents, "write_artifact_bytes", return_value={"artifact_handle": "art-1"}
    ) as write:
        result, sent, _ = invoke(
            envelope("get_invoice_pdf", id="5"),
            reply({"pdf": {"content": base64.b64encode(pdf).decode()}}),
        )
    assert result["result"] == {"pdf_artifact_handle": "art-1"}
    assert sent[0].full_url == PROD + "/invoices/5/pdf"
    assert write.call_args.args[1] == pdf
    assert write.call_args.kwargs["binding_key"] == "pdf_artifact_handle"


def test_non_pdf_content_is_refused():
    from freeagent import documents

    with patch.object(documents, "write_artifact_bytes") as write:
        result, _, _ = invoke(
            envelope("get_invoice_pdf", id="5"),
            reply({"pdf": {"content": base64.b64encode(b"<html>").decode()}}),
        )
    assert result["error_code"] == "invalid_provider_response"
    assert not write.called


def test_expense_receipt_artifact_is_embedded_as_base64_attachment():
    from freeagent import documents

    data = {
        "user": PROD + "/users/1",
        "category": PROD + "/categories/285",
        "dated_on": "2026-11-01",
        "description": "Taxi",
        "gross_value": "-20.00",
    }
    with patch.object(documents, "read_artifact_bytes", return_value=b"%PDF-receipt"):
        result, sent, _ = invoke(
            envelope(
                "create_expense",
                data=data,
                artifact_handle="art-9",
                attachment_file_name="taxi.pdf",
                attachment_content_type="application/x-pdf",
            ),
            reply({"expense": {"url": PROD + "/expenses/2"}}, status=201),
        )
    assert result["ok"] is True
    sent_body = body_of(sent[0])["expense"]
    assert sent_body["attachment"] == {
        "data": base64.b64encode(b"%PDF-receipt").decode(),
        "file_name": "taxi.pdf",
        "content_type": "application/x-pdf",
    }
    assert {k: v for k, v in sent_body.items() if k != "attachment"} == data


def test_oversized_receipt_is_refused_before_sending():
    from freeagent import documents

    with patch.object(documents, "read_artifact_bytes", return_value=b"x" * (5 * 1024 * 1024 + 1)):
        result, sent, _ = invoke(
            envelope(
                "create_bill",
                data={"contact": PROD + "/contacts/1"},
                artifact_handle="art-9",
                attachment_file_name="bill.png",
                attachment_content_type="image/png",
            )
        )
    assert result["error_code"] == "file_too_large" and sent == []


def test_file_inputs_are_refused_where_no_file_is_declared():
    result, sent, _ = invoke(
        envelope("create_contact", data={"organisation_name": "A"}, artifact_handle="art-1")
    )
    assert result["ok"] is False and sent == []


def test_explanation_attachment_posts_attachments_array():
    from freeagent import documents

    with patch.object(documents, "read_artifact_bytes", return_value=b"\x89PNG"):
        result, sent, _ = invoke(
            envelope(
                "add_bank_transaction_explanation_attachment",
                id="77",
                artifact_handle="art-2",
                file_name="r.png",
                content_type="image/png",
                description="Receipt",
            ),
            reply({"attachments": [{"url": PROD + "/attachments/1"}]}, status=201),
        )
    assert result["result"] == {"data": [{"url": PROD + "/attachments/1"}]}
    assert sent[0].full_url == PROD + "/bank_transaction_explanations/77/attachments"
    assert body_of(sent[0]) == {
        "attachments": [
            {
                "data": base64.b64encode(b"\x89PNG").decode(),
                "file_name": "r.png",
                "content_type": "image/png",
                "description": "Receipt",
            }
        ]
    }


def test_statement_file_is_sent_as_multipart():
    from freeagent import documents

    with patch.object(documents, "read_artifact_bytes", return_value=b"OFXHEADER:100"):
        result, sent, _ = invoke(
            envelope(
                "upload_bank_statement_file",
                bank_account=PROD + "/bank_accounts/4",
                file_name="nov.ofx",
                artifact_handle="art-3",
            ),
            reply(None),
        )
    assert result["result"] == {"data": {"received": True}}
    request = sent[0]
    assert request.headers["Content-type"].startswith("multipart/form-data; boundary=fs-freeagent-")
    assert b'name="statement"; filename="nov.ofx"' in request.data
    assert b"OFXHEADER:100" in request.data
    assert "file_name" not in query_of(request)


@pytest.mark.parametrize("name", ["nov.pdf", "../nov.ofx", 'a".ofx'])
def test_statement_file_name_is_restricted(name):
    from freeagent import documents

    with patch.object(documents, "read_artifact_bytes", return_value=b"x"):
        result, sent, _ = invoke(
            envelope(
                "upload_bank_statement_file", bank_account="4", file_name=name, artifact_handle="a"
            )
        )
    assert result["ok"] is False and sent == []


def test_category_path_uses_nominal_code():
    result, sent, _ = invoke(envelope("get_category", nominal_code="750-1"), reply({"x": 1}))
    assert result["ok"] is True and sent[0].full_url == PROD + "/categories/750-1"
    result, sent, _ = invoke(envelope("get_category", nominal_code="75/../1"))
    assert result["ok"] is False and sent == []


def test_create_task_puts_project_in_query():
    result, sent, _ = invoke(
        envelope("create_task", project="9", data={"name": "Design"}),
        reply({"task": {"name": "Design"}}, status=201),
    )
    assert result["ok"] is True
    assert query_of(sent[0]) == {"project": PROD + "/projects/9"}
    assert body_of(sent[0]) == {"task": {"name": "Design"}}


def test_estimate_item_body_carries_estimate_url():
    result, sent, _ = invoke(
        envelope(
            "create_estimate_item", estimate="3", data={"description": "Work", "quantity": "1"}
        ),
        reply({"estimate_item": {"url": PROD + "/estimate_items/1"}}, status=201),
    )
    assert result["ok"] is True
    assert sent[0].full_url == PROD + "/estimate_items"
    assert body_of(sent[0]) == {
        "estimate": PROD + "/estimates/3",
        "estimate_item": {"description": "Work", "quantity": "1"},
    }


def test_main_entrypoint_rejects_garbage_without_side_effects(monkeypatch, capsys):
    import io

    import main

    monkeypatch.setattr("sys.stdin", type("S", (), {"buffer": io.BytesIO(b"not json")})())
    assert main.main() == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["definitely_no_external_effect"] is True
