"""Regenerate every declarative host contract from freeagent/catalog.py.

Run from the repository root: python3 scripts/generate_contracts.py
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from freeagent.catalog import (  # noqa: E402
    ATTACHMENT_OPERATIONS,
    OPERATIONS_LIST,
    PDF_OPERATIONS,
    WRITE_EFFECTS,
    Operation,
    Param,
)
from freeagent.validation import ATTACHMENT_TYPES  # noqa: E402

EXTENSION_ID = "flowsteward.freeagent"
VERSION = "0.1.1"
DISPLAY_NAME = "FreeAgent"
DESCRIPTION = (
    "FreeAgent accounting for UK small businesses: contacts, invoices, estimates, credit notes, "
    "bills, expenses, bank accounts, statements and explanations, journals, projects and time, "
    "profit and loss, balance sheet, trial balance, VAT, corporation tax and payroll records."
)
REPOSITORY = "https://github.com/Flow-Steward/ext-finance-freeagent"
CONNECTION_TYPES = {
    "freeagent_company": ("freeagent_oauth", "FreeAgent company", "api.freeagent.com"),
    "freeagent_sandbox_company": (
        "freeagent_sandbox_oauth",
        "FreeAgent sandbox company",
        "api.sandbox.freeagent.com",
    ),
}
ERRORS = [
    "invalid_payload",
    "invalid_connection",
    "effect_claim_required",
    "test_mode_suppressed",
    "write_disabled",
    "provider_unavailable",
    "invalid_provider_response",
    "response_too_large",
    "network_blocked",
    "timeout",
    "authentication_failed",
    "permission_denied",
    "not_found",
    "conflict",
    "rate_limited",
    "provider_validation",
    "artifact_unavailable",
    "file_too_large",
]
CONNECTION_INPUT: dict[str, Any] = {
    "name": "connection_ref",
    "value_type": "connection_ref",
    "required": True,
    "display_name": "FreeAgent connection",
}


def dump(path: str, value: Any) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def param_field(param: Param) -> dict[str, Any]:
    schema: dict[str, Any]
    if param.kind == "integer":
        schema = {"type": "integer", "minimum": param.minimum, "maximum": param.maximum}
        value_type = "integer"
    elif param.kind == "boolean":
        schema, value_type = {"type": "boolean"}, "boolean"
    else:
        value_type = "text"
        schema = {"type": "string", "minLength": 1, "maxLength": 1024}
        if param.kind == "date":
            schema.update(format="date", maxLength=10)
        elif param.kind == "datetime":
            schema.update(format="date-time", maxLength=40)
        elif param.kind == "enum":
            schema["enum"] = list(param.choices)
        elif param.kind == "attachment_type":
            schema["enum"] = sorted(ATTACHMENT_TYPES)
    row: dict[str, Any] = {
        "name": param.name,
        "value_type": value_type,
        "required": param.required,
        "display_name": label(param.name),
        "schema": schema,
    }
    if param.help:
        row["description"] = param.help
    return row


def body_field(name: str, value_type: str, required: bool, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "value_type": value_type,
        "required": required,
        "display_name": label(name),
        "description": description,
        "schema": {"type": "array" if value_type == "array" else "object"},
    }


def inputs_for(op: Operation) -> list[dict[str, Any]]:
    rows = [dict(CONNECTION_INPUT)] + [param_field(param) for param in op.params]
    if op.body in ("data", "estimate_item"):
        rows.append(
            body_field(
                "data",
                "json",
                True,
                f"Native FreeAgent {op.body_root} fields (without the {op.body_root} wrapper).",
            )
        )
    elif op.body == "email":
        rows.append(body_field("email", "json", True, "to, from, subject, body; or use_template."))
    elif op.body == "statement":
        rows.append(
            body_field("statement", "array", True, "Rows with dated_on, amount and description.")
        )
    if op.special in ("explanation_attachment", "statement_file", "inline_attachment"):
        rows.append(
            {
                "name": "artifact_handle",
                "value_type": "artifact_handle",
                "required": op.special != "inline_attachment",
                "display_name": "File",
                "description": "File artifact from an earlier step.",
                "schema": {"type": "string"},
            }
        )
    if op.special == "inline_attachment":
        rows += [
            param_field(Param("attachment_file_name", "file_name", help="Receipt file name.")),
            param_field(
                Param("attachment_content_type", "attachment_type", help="Receipt MIME type.")
            ),
            param_field(Param("attachment_description", "text", help="Optional description.")),
        ]
    return rows


def outputs_for(op: Operation) -> list[dict[str, str]]:
    if op.special == "pdf":
        return [{"name": "pdf_artifact_handle", "value_type": "artifact_handle"}]
    rows = [{"name": "data", "value_type": "json"}]
    if op.paged:
        rows += [
            {"name": "page", "value_type": "integer"},
            {"name": "next_page", "value_type": "integer"},
            {"name": "total_count", "value_type": "integer"},
        ]
    return rows


def widget(row: dict[str, Any]) -> dict[str, Any]:
    schema = row["schema"]
    if "enum" in schema:
        kind = "select"
    elif row["value_type"] in ("integer", "boolean"):
        kind = row["value_type"]
    elif row["value_type"] in ("json", "array"):
        kind = "json"
    elif schema.get("format") == "date":
        kind = "date"
    elif schema.get("format") == "date-time":
        kind = "datetime"
    else:
        kind = "text"
    field: dict[str, Any] = {
        "name": row["name"],
        "widget_type": kind,
        "label": row["display_name"] + (" *" if row["required"] else ""),
        "required": row["required"],
    }
    if kind == "select":
        field["options"] = [{"label": value, "value": value} for value in schema["enum"]]
    if row.get("description"):
        field["help_text"] = row["description"]
    return field


operations: list[dict[str, Any]] = []
actions: list[dict[str, Any]] = []
forms: list[dict[str, Any]] = []
effects: list[dict[str, Any]] = []
policies: list[dict[str, Any]] = []
for op in OPERATIONS_LIST:
    inputs = inputs_for(op)
    outputs = outputs_for(op)
    result_fields = ["result." + row["name"] for row in outputs]
    description = op.description
    if op.effect in WRITE_EFFECTS:
        description += " Suppressed in Test Run."
    operations.append(
        {
            "operation_id": op.name,
            "display_name": op.title,
            "description": description,
            "operation_kind": "report" if op.group == "reports" else "action",
            "workflow_visible": True,
            "connection_type_ids": list(CONNECTION_TYPES),
            "category": "accounting",
            "inputs": inputs,
            "outputs": outputs,
            "result_fields": result_fields,
            "error_codes": ERRORS,
        }
    )
    actions.append(
        {
            "action_id": op.name,
            "workflow_visible": True,
            "title": op.title,
            "description": description,
            "required_scopes": ["extension:invoke"],
            "handler": {"mode": "extension"},
            "parameters": [
                {
                    "name": row["name"],
                    "type": {
                        "connection_ref": "string",
                        "artifact_handle": "string",
                        "text": "string",
                        "json": "object",
                        "array": "array",
                        "integer": "integer",
                        "boolean": "boolean",
                    }[row["value_type"]],
                    "required": row["required"],
                }
                for row in inputs
            ],
            "result_fields": result_fields,
            "error_codes": ERRORS,
            "mutates_platform": False,
        }
    )
    forms.append(
        {
            "operation_id": op.name,
            "title": op.title,
            "fields": [widget(row) for row in inputs if row["name"] != "connection_ref"],
        }
    )
    if op.effect in WRITE_EFFECTS:
        effects.append(
            {
                "operation_id": op.name,
                "effect_kind": "accounting_email" if op.effect == "email" else "accounting_write",
                "channel": "freeagent",
                "idempotency": "required",
                "test_mode_behavior": "suppress",
            }
        )
    if op.name in PDF_OPERATIONS:
        policies.append(
            {
                "operation_id": op.name,
                "outputs": [
                    {
                        "kind": "artifact",
                        "value_type": "artifact_handle",
                        "binding_key": "pdf_artifact_handle",
                        "filename": op.name.removeprefix("get_").removesuffix("_pdf") + ".pdf",
                        "content_type": "application/pdf",
                        "max_size_bytes": 20 * 1024 * 1024,
                        "retention_class": "run_window",
                    }
                ],
            }
        )
    if op.name in ATTACHMENT_OPERATIONS:
        policies.append(
            {
                "operation_id": op.name,
                "inputs": [
                    {
                        "kind": "artifact",
                        "value_type": "artifact_handle",
                        "binding_key": "attachment_input",
                        "from_input": "artifact_handle",
                        "required": op.special != "inline_attachment",
                        "max_size_bytes": (10 if op.special == "statement_file" else 5)
                        * 1024
                        * 1024,
                    }
                ],
            }
        )

actions.append(
    {
        "action_id": "verify_company",
        "title": "Verify FreeAgent company",
        "workflow_visible": False,
        "required_scopes": ["extension:invoke"],
        "handler": {"mode": "extension"},
        "parameters": [],
        "result_fields": [
            "result.subject",
            "result.verified_display_name",
            "result.safe_metadata",
            "result.health",
        ],
        "mutates_platform": False,
    }
)

CONFIG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "allow_create": {"type": "boolean", "default": True},
        "allow_update": {"type": "boolean", "default": True},
        "allow_delete": {"type": "boolean", "default": True},
        "allow_email": {"type": "boolean", "default": True},
        "request_timeout_seconds": {"type": "integer", "minimum": 5, "maximum": 60, "default": 30},
    },
}


def provider(provider_id: str, sandbox: bool) -> dict[str, Any]:
    host = "api.sandbox.freeagent.com" if sandbox else "api.freeagent.com"
    kind = "sandbox" if sandbox else "production"
    return {
        "provider_id": provider_id,
        "display_name": "FreeAgent sandbox" if sandbox else "FreeAgent",
        "description": f"Authorize one FreeAgent {kind} company with your own FreeAgent API app.",
        "setup_page_id": "setup-guide",
        "help_page_id": "setup-guide",
        "flow": {"type": "authorization_code", "pkce": "none"},
        "credential_fields": [
            {
                "field_id": "client_id",
                "value_type": "text",
                "required": True,
                "secret": False,
                "change_policy": "reauthorization_required",
                "label": "OAuth identifier",
                "help_text": "OAuth identifier of your app at dev.freeagent.com (My Apps).",
                "validation": {"min_length": 1, "max_length": 512},
            },
            {
                "field_id": "client_secret",
                "value_type": "secret",
                "required": True,
                "secret": True,
                "change_policy": "reauthorization_required",
                "label": "OAuth secret",
                "help_text": "OAuth secret of the same app; stored and used only by the platform.",
                "validation": {"min_length": 1, "max_length": 4096},
            },
        ],
        "authorization_endpoint": {"url": f"https://{host}/v2/approve_app"},
        "token_endpoint": {
            "url": f"https://{host}/v2/token_endpoint",
            "client_auth_method": "client_secret_basic",
        },
        "callback_id": "oauth_authorization",
        "authorization_intents": [{"intent_id": "company_connect", "static_parameters": {}}],
        "post_connect_action_id": "verify_company",
    }


connection_types = [
    {
        "connection_type_id": type_id,
        "display_name": display,
        "description": (
            f"One FreeAgent company reached at {host}, authorised by one FreeAgent user. "
            "What the extension may read and change follows that user's FreeAgent access level."
        ),
        "auth": {
            "type": "oauth2",
            "provider_id": provider_id,
            # FreeAgent defines no OAuth scopes and ignores the parameter; Core requires one
            # required scope for authorization-code providers, so one name stands for
            # "the authorising user's FreeAgent access".
            "scopes": {"required": ["freeagent"], "optional": []},
        },
        "config_schema": CONFIG_SCHEMA,
        "secret_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"access_token": {"type": "string"}},
        },
        "capabilities": [op.name for op in OPERATIONS_LIST],
    }
    for type_id, (provider_id, display, host) in CONNECTION_TYPES.items()
]
contract_v2 = {
    "oauth_providers": [
        provider("freeagent_oauth", False),
        provider("freeagent_sandbox_oauth", True),
    ],
    "connection_types": "contracts/connection_types.yaml",
    "operation_manifest": "contracts/operation_manifest.yaml",
    "step_ui_manifest": "contracts/step_ui_manifest.yaml",
}
manifest = {
    "manifest_version": 2,
    "extension_id": EXTENSION_ID,
    "kind": "tool_provider",
    "version": VERSION,
    "display_name": DISPLAY_NAME,
    "description": DESCRIPTION,
    "lifecycle": {"data_schema_version": 1, "data_migrations": []},
    "vendor": {
        "name": "Flow Steward",
        "support_url": REPOSITORY + "/issues",
        "website_url": REPOSITORY,
    },
    "listing": {
        "category": "finance",
        "tags": ["freeagent", "accounting", "bookkeeping", "invoices", "vat", "uk"],
        "summary": "Early release. Live FreeAgent testing is pending. Connect invoices, bills, "
        "bank transactions, expenses and reports to your workflows.",
    },
    "features": ["tool", "action"],
    "required_scopes": ["extension:invoke", "artifact:read", "artifact:write"],
    "machine_auth": {
        "service_account_key": "svc_ext_freeagent",
        "required_scopes": ["extension:invoke", "artifact:read", "artifact:write"],
    },
    "egress": {"hosts": ["api.freeagent.com", "api.sandbox.freeagent.com"]},
    "account_scope": {
        "scope_type": "project",
        "description": "Each connection grants access to one FreeAgent company in one project.",
    },
    "entrypoint": {"mode": "subprocess", "command": ["python3", "main.py"], "timeout_seconds": 90},
    "health": {"command": ["python3", "health.py"], "timeout_seconds": 5},
    "ui_manifest": "ui/ui_manifest.yaml",
    "action_manifest": "ui/actions/actions.yaml",
    "python_requirements": [],
    "runtime": {"contract_version": "extension_host_v2", "extension_contract_v2": contract_v2},
    "callbacks": [
        {
            "callback_id": "oauth_authorization",
            "purpose": "oauth_authorization",
            "methods": ["GET"],
            "connection_scoped": False,
        }
    ],
    "external_effects": effects,
    "artifact_policies": policies,
}

SETUP_BODY = """FreeAgent connects through your own FreeAgent API app. Each Flow Steward project stores its own app credentials.

**1. Register an app**

- Sign in at https://dev.freeagent.com/ and open My Apps, then Create New App.
- Add the callback URL that Flow Steward shows in the project OAuth setup as a redirect URI, exactly as shown.
- Copy the OAuth identifier and OAuth secret.

**2. Pick the environment**

- Real books: use the provider "FreeAgent" and the connection type "FreeAgent company".
- Testing: create a free sandbox company at https://signup.sandbox.freeagent.com/signup and finish its setup steps in the FreeAgent web app, then use "FreeAgent sandbox" and "FreeAgent sandbox company".
- Sandbox URLs never work against production and the reverse; the extension refuses to mix them.

**3. Connect**

- Save the OAuth identifier and secret for the provider in this project.
- Create a connection and approve access in FreeAgent. Flow Steward reads the company back to confirm it.
- The extension can do what the approving FreeAgent user can do. Use a user with the access level your workflows need; reports, tax and payroll need "Tax, Accounting and Users" or Full Access.

**Working with records**

- FreeAgent refers to other records by URL, for example https://api.freeagent.com/v2/contacts/123. Inputs such as contact or project also accept the bare id.
- data inputs hold the native FreeAgent fields without their wrapper: for create_invoice send the invoice fields, not {"invoice": ...}.
- Record an invoice payment with create_bank_transaction_explanation and paid_invoice; a bill payment with paid_bill.
- Marking VAT, corporation tax or final accounts as filed only records a status. Nothing is sent to HMRC or Companies House.
- FreeAgent allows 120 requests per minute per user. List operations return next_page; all_pages fetches up to 5000 rows.

**Safety**

- Test Run suppresses every change and email.
- Each connection can switch off creating, updating, deleting or emailing.
- A write that times out is reported as uncertain. Check FreeAgent before running it again.
- Tokens stay in Flow Steward. Never paste tokens or secrets into workflow inputs."""

skill = {
    "skill_id": "freeagent_accounting_workflows",
    "version": VERSION,
    "display_name": "FreeAgent accounting workflows",
    "description": "Plan FreeAgent bookkeeping, invoicing, banking and reporting workflows with the "
    "installed FreeAgent extension operations.",
    "enabled": True,
    "category": "finance",
    "instructions": [
        "Discover flowsteward.freeagent operations and their input schemas through the platform catalog before building a workflow.",
        "Require an explicit FreeAgent connection_ref. Call get_company first to confirm the company, its currency and VAT status.",
        "FreeAgent references records by URL (https://api.freeagent.com/v2/<resource>/<id>); carry the url field from earlier results into later inputs.",
        "Pass data without the root wrapper and never invent required fields: obtain contact, category, bank account and dates from earlier steps or the user.",
        "Money is a decimal string. Money out is negative on expenses, bank statement rows and most explanations.",
        "Record invoice payments with create_bank_transaction_explanation using paid_invoice, bill payments with paid_bill, and transfers with transfer_bank_account.",
        "Use list operations with from_date, to_date or updated_since and follow next_page, or set all_pages; never claim the first page is the full ledger.",
        "For financial analysis use get_profit_and_loss, get_balance_sheet, get_trial_balance, list_accounting_transactions and get_cashflow; keep provider totals as returned.",
        "Changes run through declared operations so the host owns external-effect claims and Test Run suppression. After an uncertain write, read the provider state before retrying.",
        "Filing transitions only record a status in FreeAgent; they do not submit returns to HMRC or Companies House.",
        "Pass files as platform artifact handles. Never pass local paths, tokens or download URLs.",
    ],
    "expected_inputs": [
        {
            "name": "request",
            "type": "paragraph",
            "required": True,
            "description": "The bookkeeping task, the FreeAgent connection, the period and any approved change.",
        }
    ],
    "expected_outputs": [
        {
            "name": "accounting_result",
            "type": "text",
            "required": True,
            "description": "The plan or the verified FreeAgent result with record URLs, dates and amounts.",
        }
    ],
    "builder_metadata_jsonb": {
        "purpose": "Use the installed FreeAgent operations accurately in accounting workflows.",
        "use_cases": [
            "invoice creation and chasing",
            "bank statement import and reconciliation",
            "expense and bill capture with receipts",
            "management reports",
        ],
        "anti_use_cases": [
            "HMRC or Companies House submission",
            "moving money",
            "unapproved accounting changes",
        ],
        "composition_role": "execution",
        "determinism_level": "hybrid",
        "safe_for_auto_use": False,
    },
    "tags": ["freeagent", "accounting", "workflow"],
}

dump("contracts/operation_manifest.yaml", {"operations": operations})
dump("contracts/step_ui_manifest.yaml", {"forms": forms})
dump("contracts/connection_types.yaml", {"connection_types": connection_types})
dump("ui/actions/actions.yaml", {"actions": actions})
dump("extension.yaml", manifest)
dump(
    "extension-descriptor.yaml",
    {
        "schema_version": "extension_descriptor_v1",
        "extension_id": EXTENSION_ID,
        "release_version": VERSION,
        "extension_type": "service_extension",
        "artifacts": {
            "skills": [
                {
                    "skill_id": skill["skill_id"],
                    "ref": "artifacts/skills/freeagent_accounting_workflows.yaml",
                    "publish": True,
                }
            ]
        },
        "identity": {
            "display_name": DISPLAY_NAME,
            "description": DESCRIPTION,
            "tags": ["freeagent", "accounting"],
        },
        "vendor": {"vendor_name": "Flow Steward"},
        "listing": {"visibility": "public_reference", "category": "finance"},
        "distribution": {
            "channel": "private_byo",
            "execution_modes": ["local"],
            "allows_self_hosted": True,
            "requires_connected_control_plane": False,
            "import_sources": ["file"],
        },
        "runtime": manifest["runtime"],
        "lifecycle": manifest["lifecycle"],
    },
)
dump(
    "ui/ui_manifest.yaml",
    {
        "version": "1",
        "pages": [{"ref": "pages/setup-guide.yaml"}, {"ref": "pages/support.yaml"}],
    },
)
dump(
    "ui/pages/support.yaml",
    {
        "page_id": "support",
        "title": "Support",
        "description": "Get help with the Flow Steward FreeAgent extension.",
        "project_scoped": False,
        "components": [
            {
                "component_id": "freeagent_support",
                "type": "markdown",
                "title": "Get help with the FreeAgent extension",
                "body": (
                    f"- [Browse existing issues]({REPOSITORY}/issues)\n"
                    f"- [Report a problem or request a feature]({REPOSITORY}/issues/new/choose)\n\n"
                    "Include your Flow Steward and extension versions, the affected operation, "
                    "and the error message. Remove tokens and accounting data before posting."
                ),
            }
        ],
    },
)
dump(
    "ui/pages/setup-guide.yaml",
    {
        "page_id": "setup-guide",
        "title": "FreeAgent setup",
        "description": "Register a FreeAgent API app, save its credentials and connect a company.",
        "project_scoped": True,
        "components": [
            {
                "component_id": "freeagent_setup",
                "type": "markdown",
                "title": "Connect your FreeAgent company",
                "body": SETUP_BODY,
            }
        ],
    },
)
dump("artifacts/skills/freeagent_accounting_workflows.yaml", skill)
print(len(OPERATIONS_LIST), "operations,", len(effects), "with external effects")
