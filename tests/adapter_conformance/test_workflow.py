# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW = REPOSITORY_ROOT / ".github/workflows/cross-adapter-compatibility.yml"
GATE_TOOL = REPOSITORY_ROOT / "tools/cross_adapter_gate.py"
FULL_ACTION_SHA = re.compile(r"uses:\s+[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")


def _workflow() -> dict[Any, Any]:
    value = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_workflow_is_always_on_without_path_filters() -> None:
    workflow = _workflow()
    triggers = workflow[True]

    assert workflow["name"] == "Cross-Adapter Compatibility Gate"
    assert isinstance(triggers, dict)
    assert {"pull_request", "merge_group", "push", "schedule", "workflow_dispatch"} <= set(triggers)
    assert "paths" not in str(triggers["pull_request"])
    assert triggers["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in triggers


def test_workflow_has_dynamic_fail_open_resistant_summary() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    required = jobs["required"]

    assert required["name"] == "required"
    assert required["if"] == "always()"
    assert set(required["needs"]) == {
        "registry",
        "sdk",
        "adapters",
        "fixtures",
        "shared-contract",
        "root-wheel",
    }
    assert jobs["adapters"]["strategy"]["fail-fast"] is False
    assert jobs["fixtures"]["strategy"]["fail-fast"] is False
    assert "fromJSON(needs.registry.outputs.adapter_matrix)" in str(
        jobs["adapters"]["strategy"]["matrix"]
    )
    assert "fromJSON(needs.registry.outputs.fixture_matrix)" in str(
        jobs["fixtures"]["strategy"]["matrix"]
    )
    required_text = json_text(required)
    assert "summarize" in required_text
    assert 'if value.get("result") != "success"' in WORKFLOW.read_text(encoding="utf-8")


def json_text(value: object) -> str:
    return yaml.safe_dump(value, sort_keys=True)


def test_workflow_actions_are_full_sha_pinned_and_jobs_are_bounded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    uses_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("uses:")]

    assert uses_lines
    assert all(FULL_ACTION_SHA.fullmatch(line) for line in uses_lines)
    workflow = _workflow()
    assert all("timeout-minutes" in job for job in workflow["jobs"].values())
    assert all(
        step.get("with", {}).get("persist-credentials") is False
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )


def test_workflow_requires_json_schema_registry_validation() -> None:
    workflow = _workflow()
    registry_steps = workflow["jobs"]["registry"]["steps"]
    validation = next(
        step for step in registry_steps if step["name"] == "Validate authoritative registry"
    )

    command = str(validation["run"])
    assert "validate-registry" in command
    assert "--require-jsonschema" in command


def test_workflow_uses_the_dedicated_locked_gate_environment() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert (REPOSITORY_ROOT / "tests/adapter_conformance/pyproject.toml").is_file()
    assert (REPOSITORY_ROOT / "tests/adapter_conformance/uv.lock").is_file()
    assert "--project tests/adapter_conformance" in text
    assert "uv sync --locked --group dev" not in text


def test_workflow_result_artifacts_are_safe_for_partial_reruns() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    upload_steps = [
        step
        for job in jobs.values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]

    assert len(upload_steps) == 5
    artifact_names = [str(step["with"]["name"]) for step in upload_steps]
    assert len(artifact_names) == len(set(artifact_names))
    assert all(name.startswith("cross-adapter-result-") for name in artifact_names)
    assert all("github.run_attempt" not in name for name in artifact_names)
    assert all(step["with"].get("overwrite") is True for step in upload_steps)

    download = next(
        step
        for step in jobs["required"]["steps"]
        if str(step.get("uses", "")).startswith("actions/download-artifact@")
    )
    assert download["with"]["pattern"] == "cross-adapter-result-*"
    assert "github.run_attempt" not in str(download["with"]["pattern"])
    assert download["with"]["merge-multiple"] is True


def test_workflow_summary_keeps_stable_technical_columns() -> None:
    workflow = _workflow()
    summary_step = next(
        step
        for step in workflow["jobs"]["required"]["steps"]
        if step["name"] == "Summarize records and require every Level A job to pass"
    )
    tool_text = GATE_TOOL.read_text(encoding="utf-8")

    assert '--summary-markdown "$GITHUB_STEP_SUMMARY"' in str(summary_step["run"])
    assert (
        "| Component | Package | Source conversion | Contract | Atlas | Determinism | "
        "Negative tests | Packaging | Rights | Result |"
    ) in tool_text


def test_workflow_concurrency_separates_event_families() -> None:
    concurrency = _workflow()["concurrency"]

    assert concurrency["cancel-in-progress"] is True
    group = str(concurrency["group"])
    assert "${{ github.workflow }}" in group
    assert "${{ github.event_name }}" in group
    assert "${{ github.event.pull_request.number || github.ref }}" in group
