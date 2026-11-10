"""Generated host contracts stay in sync with the catalog and keep their safety properties."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from freeagent.catalog import OPERATIONS, WRITE_EFFECTS

ROOT = Path(__file__).resolve().parents[1]
GENERATED = [
    "extension.yaml",
    "extension-descriptor.yaml",
    "contracts/connection_types.yaml",
    "contracts/operation_manifest.yaml",
    "contracts/step_ui_manifest.yaml",
    "ui/actions/actions.yaml",
    "ui/ui_manifest.yaml",
    "ui/pages/setup-guide.yaml",
    "artifacts/skills/freeagent_accounting_workflows.yaml",
]


def read(path: str):
    return json.loads((ROOT / path).read_text())


def test_generated_files_match_the_catalog(tmp_path):
    copy = tmp_path / "repo"
    shutil.copytree(
        ROOT / "freeagent", copy / "freeagent", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(ROOT / "scripts", copy / "scripts")
    subprocess.run(
        [sys.executable, str(copy / "scripts/generate_contracts.py")],
        check=True,
        capture_output=True,
    )
    for path in GENERATED:
        assert (copy / path).read_text() == (ROOT / path).read_text(), path


def test_operations_actions_forms_and_effects_cover_the_catalog():
    operations = {
        o["operation_id"]: o for o in read("contracts/operation_manifest.yaml")["operations"]
    }
    actions = {a["action_id"]: a for a in read("ui/actions/actions.yaml")["actions"]}
    forms = {f["operation_id"] for f in read("contracts/step_ui_manifest.yaml")["forms"]}
    assert set(operations) == set(OPERATIONS) == forms
    assert set(actions) == set(OPERATIONS) | {"verify_company"}
    assert actions["verify_company"]["workflow_visible"] is False
    effects = {e["operation_id"] for e in read("extension.yaml")["external_effects"]}
    assert effects == {n for n, op in OPERATIONS.items() if op.effect in WRITE_EFFECTS}
    for name, operation in operations.items():
        assert operation["result_fields"] == actions[name]["result_fields"]
        assert operation["inputs"][0]["value_type"] == "connection_ref"


def test_two_environments_use_their_own_fixed_oauth_endpoints():
    manifest = read("extension.yaml")
    providers = {
        p["provider_id"]: p for p in manifest["runtime"]["extension_contract_v2"]["oauth_providers"]
    }
    assert providers["freeagent_oauth"]["authorization_endpoint"] == {
        "url": "https://api.freeagent.com/v2/approve_app"
    }
    assert providers["freeagent_oauth"]["token_endpoint"] == {
        "url": "https://api.freeagent.com/v2/token_endpoint",
        "client_auth_method": "client_secret_basic",
    }
    assert providers["freeagent_sandbox_oauth"]["token_endpoint"]["url"] == (
        "https://api.sandbox.freeagent.com/v2/token_endpoint"
    )
    types = {
        t["connection_type_id"]: t
        for t in read("contracts/connection_types.yaml")["connection_types"]
    }
    assert types["freeagent_company"]["auth"]["provider_id"] == "freeagent_oauth"
    assert types["freeagent_sandbox_company"]["auth"]["provider_id"] == "freeagent_sandbox_oauth"
    assert manifest["egress"]["hosts"] == ["api.freeagent.com", "api.sandbox.freeagent.com"]
    assert manifest["python_requirements"] == []


def test_connection_config_cannot_carry_urls_or_secrets():
    for connection in read("contracts/connection_types.yaml")["connection_types"]:
        schema = connection["config_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == {
            "allow_create",
            "allow_update",
            "allow_delete",
            "allow_email",
            "request_timeout_seconds",
        }
        assert set(connection["secret_schema"]["properties"]) == {"access_token"}


def test_file_policies_match_file_operations():
    policies = {p["operation_id"]: p for p in read("extension.yaml")["artifact_policies"]}
    for name, op in OPERATIONS.items():
        if op.special == "pdf":
            assert policies[name]["outputs"][0]["binding_key"] == "pdf_artifact_handle"
        elif op.special:
            assert policies[name]["inputs"][0]["from_input"] == "artifact_handle"
        else:
            assert name not in policies


def test_offline_health_and_garbage_input():
    health = subprocess.run(
        [sys.executable, str(ROOT / "health.py")], capture_output=True, text=True, check=False
    )
    assert health.returncode == 0, health.stdout
    assert json.loads(health.stdout)["result"]["operation_count"] == len(OPERATIONS)
    invalid = subprocess.run(
        [sys.executable, str(ROOT / "main.py")],
        input="{}",
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["definitely_no_external_effect"] is True
