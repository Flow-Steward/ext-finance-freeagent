"""Each file Flow Steward validates on its own declares what its contract references.

On install the host validates extension-descriptor.yaml by itself, without extension.yaml.
FreeAgent 0.1.1 shipped a descriptor whose inline contract named the OAuth callback
`oauth_authorization` but did not declare it, and the install was refused.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OAUTH_CALLBACK_PURPOSE = "oauth_authorization"


def read(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def undeclared_oauth_callbacks(document: dict) -> set[str]:
    contract = document.get("runtime", {}).get("extension_contract_v2") or {}
    referenced = {provider["callback_id"] for provider in contract.get("oauth_providers", [])}
    declared = {
        callback["callback_id"]
        for callback in document.get("callbacks", [])
        if callback.get("purpose") == OAUTH_CALLBACK_PURPOSE
        and "GET" in callback.get("methods", [])
    }
    return referenced - declared


@pytest.mark.parametrize("path", ["extension.yaml", "extension-descriptor.yaml"])
def test_oauth_callbacks_are_declared_where_they_are_referenced(path):
    assert undeclared_oauth_callbacks(read(path)) == set()


def test_descriptor_takes_the_executable_contract_from_the_manifest():
    manifest = read("extension.yaml")
    runtime = read("extension-descriptor.yaml")["runtime"]
    assert runtime == {"contract_version": manifest["runtime"]["contract_version"]}
    assert manifest["runtime"]["extension_contract_v2"]["oauth_providers"]


def test_the_check_catches_the_0_1_1_descriptor():
    released = {
        "runtime": {
            "extension_contract_v2": read("extension.yaml")["runtime"]["extension_contract_v2"]
        }
    }
    assert undeclared_oauth_callbacks(released) == {"oauth_authorization"}
