# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from metriplane import release_control as control
from tools.release_artifacts import _REQUIRED_SDIST_PATHS

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATHS = {
    "environment_registry_digest": "docs/status/supported-environments.json",
    "evidence_store_registry_digest": "docs/status/release-evidence-stores.json",
    "obligation_registry_digest": "docs/status/release-test-obligations.json",
    "readiness_registry_digest": "docs/status/release-readiness.json",
    "scenario_registry_digest": "docs/status/release-scenarios.json",
    "target_registry_digest": "docs/status/release-targets.json",
    "task_state_policy_digest": "docs/status/release-task-state-policy.json",
}


def fixture_git(repository: Path, *args: str) -> str:
    environment = dict(os.environ)
    environment.update(
        {"GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}
    )
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repository),
            *args,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_source_fixture(tmp_path: Path) -> dict[str, Any]:
    """Complete gate/target inputs and real tracked byte fixtures; no live authority."""
    repository, run = tmp_path / "source", tmp_path / "run"
    repository.mkdir(parents=True)
    run.mkdir()
    for name in sorted(_REQUIRED_SDIST_PATHS | {"uv.lock"}):
        destination = repository / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    (repository / "metriplane/__init__.py").write_text('__version__ = "0.4.0"\n')
    (repository / "uv.lock").write_text(
        (repository / "uv.lock").read_text().replace('version = "0.4.0.post2"', 'version = "0.4.0"')
    )
    # These are source-byte fixtures. Registry semantic readiness is an upstream
    # software boundary; the fixture deliberately retains unbound live status.
    registries = {
        "supported-environments": {
            "owner": "MP2-007",
            "environments": [],
            "evidence_policy": "all_required_terminal_results",
        },
        "release-evidence-stores": {
            "owner": "MP2-007",
            "attempt_index": {"backend": None, "cas_required": True},
            "backends": [],
            "stores": [],
            "live_status": "UNRESOLVED",
            "secrets_embedded": False,
        },
        "release-test-obligations": {
            "owner": "MP2-007",
            "base_commit": "0" * 40,
            "materialization_id": "0" * 64,
            "commands": [],
            "obligations": [],
            "evidence_resolution": {"status": "BLOCKED_NOT_READY", "resolved_count": 0},
        },
        "release-readiness": {
            "owner": "MP2-007",
            "framework": "BLOCKED_NOT_READY",
            "live_release": "BLOCKED_NOT_READY",
            "blockers": ["UPSTREAM_SOFTWARE_AND_LIVE_ACCEPTANCE_REQUIRED"],
        },
        "release-scenarios": {
            "owner": "MP2-007",
            "phases": ["qualification"],
            "stages": list(control.STAGES),
            "terminal_results": sorted(control.TERMINAL_RESULTS),
            "scenarios": [],
        },
        "release-targets": {
            "owner": "MP2-007",
            "milestones": [
                {
                    "id": "v0.4",
                    "predecessor": "v0.3.0",
                    "required_targets": ["github-release", "pypi", "testpypi"],
                    "version_line": "v0.4.x",
                }
            ],
        },
        "release-task-state-policy": {
            "owner": "MP2-007",
            "authority_status": "POLICY_ONLY_NO_LIVE_PROVIDER_RECEIPT",
            "allowed_transitions": [],
            "cross_system_atomicity": "not_claimed",
            "no_other_authorized_transition": True,
        },
    }
    for name, value in registries.items():
        value["schema_version"] = "metriplane." + name + ".v1"
        destination = repository / "docs/status" / (name + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(control.canonical_json(value))
    note = repository / "docs/releases/v0.4.0-release-notes.md"
    note.parent.mkdir(parents=True)
    note.write_text("Synthetic source/build fixture. No release or provider approval.\n")
    workflow = repository / ".github/workflows/fixture.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: synthetic source fixture\non: workflow_dispatch\njobs: {}\n")
    fixture_git(repository, "init", "--initial-branch=fixture")
    fixture_git(repository, "config", "user.name", "Synthetic source fixture")
    fixture_git(repository, "config", "user.email", "fixture@example.invalid")
    fixture_git(repository, "add", "--all")
    fixture_git(repository, "commit", "-m", "Synthetic source fixture; no release authority")
    target_data = {
        "burn_lineage_digest": "3" * 64,
        "burn_target_ids": [],
        "initial_package_version": "v0.4.0",
        "initial_release_tag": "v0.4.0",
        "milestone": "v0.4",
        "observations_digest": "4" * 64,
        "prior_burn_digests": [],
        "requires_new_burn": False,
        "resolution_rule": "next_unused_same_milestone_patch",
        "selected_package_version": "v0.4.0",
        "selected_release_tag": "v0.4.0",
    }
    target_data["resolution_digest"] = control.sha256_json(target_data)
    target = control.make_record(
        "release-target-resolution",
        target_data,
        invocation_id="fixture-target",
        sequence=1,
        synthetic=True,
    )
    gate_data: dict[str, Any] = {
        key: control.sha256_bytes((repository / name).read_bytes())
        for key, name in REGISTRY_PATHS.items()
    }
    gate_data.update(
        {
            "expected_predecessor_milestone": "v0.3.0",
            "linear_snapshot_digest": "5" * 64,
            "milestone": "v0.4",
            "role_assignments_digest": "6" * 64,
            "run_id": "synthetic-source-fixture",
            "target_burn_digest": "7" * 64,
            "target_burn_index_receipt_digest": None,
            "target_resolution_digest": control.sha256_json(target),
        }
    )
    gate_data["gate_input_digest"] = control.sha256_json(gate_data)
    gate = control.make_record(
        "release-gate-input", gate_data, invocation_id="fixture-gate", sequence=1, synthetic=True
    )
    control.write_immutable_json(run / "target-resolution.json", target)
    control.write_immutable_json(run / "gate-input.json", gate)
    return {
        "repository": repository,
        "run": run,
        "sha": fixture_git(repository, "rev-parse", "HEAD"),
        "tree": fixture_git(repository, "rev-parse", "HEAD^{tree}"),
        "gate": gate,
        "target": target,
    }


def run_cli(
    fixture: dict[str, Any],
    tool: str,
    argv: list[str],
    *,
    fixture_mode: bool = True,
    bootstrap: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE", "VIRTUAL_ENV", "CONDA_PREFIX"):
        environment.pop(key, None)
    environment["METRIPLANE_RELEASE_FIXTURE_MODE"] = "1" if fixture_mode else "0"
    command = [sys.executable, str(ROOT / "tools" / tool), *argv]
    if bootstrap is not None:
        command = [sys.executable, "-c", bootstrap, str(ROOT / "tools" / tool), *argv]
    return subprocess.run(
        command,
        cwd=fixture["repository"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def freeze_argv(fixture: dict[str, Any], sequence: int = 1) -> list[str]:
    run = fixture["run"]
    return [
        "--gate-input",
        str(run / "gate-input.json"),
        "--source-sha",
        fixture["sha"],
        "--out",
        str(run / "source-freeze.json"),
        "--invocation-dir",
        str(run / "invocations/source-freeze" / f"{sequence:03d}"),
    ]


def export_schema_records(destination: Path, paths: list[Path]) -> None:
    destination.mkdir()
    rows = []
    for index, source in enumerate(paths):
        raw = source.read_bytes()
        value = json.loads(raw)
        name = f"record-{index:03d}.json"
        (destination / name).write_bytes(raw)
        rows.append(
            {"path": name, "kind": value["record_type"], "sha256": control.sha256_bytes(raw)}
        )
    (destination / "schema-positive-records.json").write_text(
        json.dumps({"schema_version": "metriplane.s1-synthetic-schema-cases.v1", "records": rows})
    )


def test_freeze_reads_real_git_tree_and_input_bytes(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    result = run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture))
    assert result.returncode == 0, (result.stdout, result.stderr)
    run = fixture["run"]
    record = control.read_json(run / "source-freeze.json")
    data = record["data"]
    assert data["source_sha"] == fixture["sha"] and data["source_tree"] == fixture["tree"]
    assert [row["path"] for row in data["registry_inputs"]] == sorted(REGISTRY_PATHS.values())
    assert data["workflow_inputs"] == [
        {
            "path": ".github/workflows/fixture.yml",
            "schema_id": "application/vnd.github-actions.workflow+yaml",
            "sha256": control.sha256_bytes(
                (fixture["repository"] / ".github/workflows/fixture.yml").read_bytes()
            ),
        }
    ]
    control.validate_release_source_freeze_record(
        record, run / "source-freeze.json", repository=fixture["repository"], live=False
    )
    export_schema_records(
        tmp_path / "schema-cases",
        [
            run / "gate-input.json",
            run / "target-resolution.json",
            run / "source-freeze.json",
            run / "invocations/source-freeze/001/invocation.json",
        ],
    )


def test_freeze_is_deterministic_for_fixed_invocation_inputs(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    kwargs = {
        "frozen_at": "2026-01-01T00:00:00Z",
        "invocation_id": "fixture-freeze",
        "sequence": 1,
        "producer_intent_digest": "a" * 64,
        "repository": fixture["repository"],
        "live": False,
    }
    first = control.build_release_source_freeze_record(
        fixture["run"] / "gate-input.json", fixture["sha"], **kwargs
    )
    second = control.build_release_source_freeze_record(
        fixture["run"] / "gate-input.json", fixture["sha"], **kwargs
    )
    third = control.build_release_source_freeze_record(
        fixture["run"] / "gate-input.json", fixture["sha"], **kwargs
    )
    assert first == second == third
    assert first["data"]["freeze_digest"] == control.sha256_json(
        {k: v for k, v in first["data"].items() if k != "freeze_digest"}
    )
    assert not (fixture["run"] / "source-freeze.json").exists()


@pytest.mark.parametrize(
    "name",
    [
        *REGISTRY_PATHS.values(),
        "pyproject.toml",
        "uv.lock",
        "metriplane/__init__.py",
        "docs/releases/v0.4.0-release-notes.md",
        ".github/workflows/fixture.yml",
    ],
)
def test_freeze_rejects_missing_or_mutated_bound_input(tmp_path: Path, name: str) -> None:
    fixture = make_source_fixture(tmp_path)
    (fixture["repository"] / name).unlink()
    result = run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture))
    assert result.returncode == 3
    assert not (fixture["run"] / "source-freeze.json").exists()
    journal = control.read_json(fixture["run"] / "invocations/source-freeze/001/invocation.json")
    assert journal["status"] == "BLOCKED" and journal["data"]["outputs"] == []


def test_source_validation_recomputes_payload_not_only_envelope(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    path = fixture["run"] / "source-freeze.json"
    original = control.read_json(path)
    data = copy.deepcopy(original["data"])
    data["release_notes_digest"] = "f" * 64
    data["freeze_digest"] = control.sha256_json(
        {k: v for k, v in data.items() if k != "freeze_digest"}
    )
    forged = control.make_record(
        "release-source-freeze",
        data,
        invocation_id=original["invocation_id"],
        sequence=1,
        synthetic=True,
    )
    path.chmod(0o600)
    path.write_bytes(control.canonical_json(forged))
    with pytest.raises(control.ReleaseControlError, match="semantic projection"):
        control.validate_release_source_freeze_record(
            forged, path, repository=fixture["repository"], live=False
        )


def test_invocation_and_output_are_never_overwritten(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    run = fixture["run"]
    original = {str(p.relative_to(run)): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 2
    assert {
        str(p.relative_to(run)): p.read_bytes() for p in run.rglob("*") if p.is_file()
    } == original
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture, 2)).returncode == 3
    assert (run / "source-freeze.json").read_bytes() == original["source-freeze.json"]
    second = control.read_json(run / "invocations/source-freeze/002/invocation.json")
    assert second["data"]["previous_invocation_digest"] == control.sha256_bytes(
        original["invocations/source-freeze/001/invocation.json"]
    )


@pytest.mark.parametrize("terminal_fault", ["missing", "failed", "diagnostic", "duplicate"])
def test_producer_journal_fault_cannot_authorize_output(
    tmp_path: Path, terminal_fault: str
) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    root = fixture["run"]
    invocation = root / "invocations/source-freeze/001"
    terminal = invocation / "invocation.json"
    if terminal_fault == "missing":
        terminal.unlink()
    elif terminal_fault == "failed":
        value = control.read_json(terminal)
        data = value["data"]
        data.update({"exit_code": 3, "terminal_status": "BLOCKED"})
        data["invocation_digest"] = control.sha256_json(
            {k: v for k, v in data.items() if k != "invocation_digest"}
        )
        value = control.make_record(
            "release-stage-invocation",
            data,
            invocation_id=value["invocation_id"],
            sequence=1,
            synthetic=True,
            status="BLOCKED",
        )
        terminal.chmod(0o600)
        terminal.write_bytes(control.canonical_json(value))
    elif terminal_fault == "diagnostic":
        (invocation / "stdout").write_bytes(b"mutated")
    else:
        shutil.copytree(invocation, root / "invocations/source-freeze-copy/001")
    with pytest.raises(control.ReleaseControlError):
        control.validate_release_source_freeze_record(
            control.read_json(root / "source-freeze.json"),
            root / "source-freeze.json",
            repository=fixture["repository"],
            live=False,
        )


def test_relocated_complete_run_preserves_producer_resolution(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    moved = tmp_path / "relocated"
    fixture["run"].rename(moved)
    control.validate_release_source_freeze_record(
        control.read_json(moved / "source-freeze.json"),
        moved / "source-freeze.json",
        repository=fixture["repository"],
        live=False,
    )


@pytest.mark.parametrize("after_install", [False, True])
def test_supervisor_hard_kill_never_leaves_consumable_pass(
    tmp_path: Path, after_install: bool
) -> None:
    fixture = make_source_fixture(tmp_path)
    bootstrap = (
        "import os,signal,sys; from metriplane import release_control as c\noriginal=c._install_release_outputs\ndef killed(*args,**kwargs):\n "
        + ("original(*args,**kwargs)\n " if after_install else "")
        + "os.kill(os.getpid(),signal.SIGKILL)\nc._install_release_outputs=killed\nraise SystemExit(c.tool_main(sys.argv[1],sys.argv[2:]))"
    )
    result = run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture), bootstrap=bootstrap)
    assert result.returncode == -signal.SIGKILL
    root = fixture["run"]
    assert (root / "invocations/source-freeze/001/intent.json").is_file()
    assert not (root / "invocations/source-freeze/001/invocation.json").exists()
    assert (root / "source-freeze.json").exists() is after_install
    if after_install:
        with pytest.raises(control.ReleaseControlError):
            control.validate_release_source_freeze_record(
                control.read_json(root / "source-freeze.json"),
                root / "source-freeze.json",
                repository=fixture["repository"],
                live=False,
            )


def test_live_authority_absence_cannot_be_satisfied_by_synthetic_inputs(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    result = run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture), fixture_mode=False)
    assert result.returncode == 3 and not (fixture["run"] / "source-freeze.json").exists()
    stdout = (fixture["run"] / "invocations/source-freeze/001/stdout").read_text()
    assert "synthetic" in stdout


def validation_argv(fixture: dict[str, Any], sequence: int = 1) -> list[str]:
    run = fixture["run"]
    return [
        "--record",
        str(run / "source-freeze.json"),
        "--verify-tree-clean",
        "--invocation-dir",
        str(run / "invocations/source-freeze-validation" / f"{sequence:03d}"),
    ]


def rewrite_json(path: Path, value: object) -> None:
    path.chmod(0o600)
    path.write_bytes(control.canonical_json(value))


def rehash_record(value: dict[str, Any]) -> dict[str, Any]:
    return control.make_record(
        value["record_type"],
        value["data"],
        invocation_id=value["invocation_id"],
        sequence=value["sequence"],
        synthetic=value["synthetic"],
        status=value["status"],
    )


@pytest.mark.parametrize(
    "fault",
    [
        "source-sha",
        "source-tree",
        "gate",
        "version",
        "recipe",
        "extra-ref",
        "missing-ref",
        "duplicate-ref",
        "schema-id",
        "media-type",
        "unsafe-path",
        "unknown-field",
    ],
)
def test_complete_semantic_projection_rejects_forged_source_fields(
    tmp_path: Path, fault: str
) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    path = fixture["run"] / "source-freeze.json"
    value = control.read_json(path)
    data = value["data"]
    if fault in {"source-sha", "source-tree", "gate", "version", "recipe"}:
        key = {
            "source-sha": "source_sha",
            "source-tree": "source_tree",
            "gate": "gate_input_digest",
            "version": "version_metadata_digest",
            "recipe": "build_recipe_digest",
        }[fault]
        data[key] = "f" * (40 if key.startswith("source_") else 64)
    elif fault == "extra-ref":
        data["registry_inputs"].append(
            {"path": "extra.json", "schema_id": "unknown", "sha256": "f" * 64}
        )
    elif fault == "missing-ref":
        data["registry_inputs"].pop()
    elif fault == "duplicate-ref":
        data["registry_inputs"].append(copy.deepcopy(data["registry_inputs"][0]))
    elif fault == "schema-id":
        data["registry_inputs"][0]["schema_id"] = "wrong"
    elif fault == "media-type":
        data["workflow_inputs"][0]["schema_id"] = "text/plain"
    elif fault == "unsafe-path":
        data["registry_inputs"][0]["path"] = "../outside"
    else:
        data["unexpected"] = True
    data["freeze_digest"] = control.sha256_json(
        {k: v for k, v in data.items() if k != "freeze_digest"}
    )
    value = rehash_record(value)
    rewrite_json(path, value)
    with pytest.raises(control.ReleaseControlError):
        control.validate_release_source_freeze_record(
            value, path, repository=fixture["repository"], live=False
        )


@pytest.mark.parametrize(
    "fault",
    [
        "gate-digest",
        "target-digest",
        "registry-digest",
        "gate-extra",
        "target-extra",
        "selected-version",
        "registry-schema",
        "version-metadata",
        "symlink",
    ],
)
def test_freeze_rejects_complete_but_contradictory_inputs(tmp_path: Path, fault: str) -> None:
    fixture = make_source_fixture(tmp_path)
    run, repository = fixture["run"], fixture["repository"]
    if fault in {"registry-schema", "version-metadata", "symlink"}:
        if fault == "registry-schema":
            path = repository / REGISTRY_PATHS["target_registry_digest"]
            value = json.loads(path.read_bytes())
            value["schema_version"] = "wrong"
            rewrite_json(path, value)
        elif fault == "version-metadata":
            (repository / "metriplane/__init__.py").write_text('__version__ = "0.4.1"\n')
        else:
            path = repository / REGISTRY_PATHS["target_registry_digest"]
            path.unlink()
            path.symlink_to(repository / REGISTRY_PATHS["scenario_registry_digest"])
        fixture_git(repository, "add", "--all")
        fixture_git(repository, "commit", "-m", "Synthetic contradictory source")
        fixture["sha"] = fixture_git(repository, "rev-parse", "HEAD")
    else:
        path = run / (
            "target-resolution.json"
            if fault.startswith("target") or fault == "selected-version"
            else "gate-input.json"
        )
        value = control.read_json(path)
        data = value["data"]
        if fault.endswith("extra"):
            data["unexpected"] = True
        elif fault == "gate-digest":
            data["gate_input_digest"] = "e" * 64
        elif fault == "target-digest":
            data["resolution_digest"] = "e" * 64
        elif fault == "registry-digest":
            data["target_registry_digest"] = "e" * 64
        else:
            data["selected_package_version"] = "v0.4.1"
        rewrite_json(path, rehash_record(value))
    result = run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture))
    assert result.returncode == 3
    assert not (run / "source-freeze.json").exists()
    assert (
        control.read_json(run / "invocations/source-freeze/001/invocation.json")["status"]
        == "BLOCKED"
    )


def test_input_changed_after_intent_is_blocked_before_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_source_fixture(tmp_path)
    run = fixture["run"]
    monkeypatch.chdir(fixture["repository"])
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    context = control.begin_release_invocation(
        "freeze_release_source.py",
        freeze_argv(fixture),
        run / "invocations/source-freeze/001",
        input_paths=[
            (run / "gate-input.json", "metriplane.release-gate-input.v1"),
            (run / "target-resolution.json", "metriplane.release-target-resolution.v1"),
        ],
        planned_outputs=[(run / "source-freeze.json", "metriplane.release-source-freeze.v1")],
    )
    path = run / "gate-input.json"
    value = control.read_json(path)
    value["data"]["linear_snapshot_digest"] = "e" * 64
    value["data"]["gate_input_digest"] = control.sha256_json(
        {k: v for k, v in value["data"].items() if k != "gate_input_digest"}
    )
    rewrite_json(path, rehash_record(value))
    assert control._supervise_release_invocation(context) == 3
    assert not (context.directory / "worker.pid").exists()
    assert not (run / "source-freeze.json").exists()
    assert "captured bytes changed" in (context.directory / "stderr").read_text()


@pytest.mark.parametrize("fault", ["empty-plan", "wrong-output", "wrong-input-set"])
def test_self_hashed_journal_contradictions_do_not_authorize_output(
    tmp_path: Path, fault: str
) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    run = fixture["run"]
    directory = run / "invocations/source-freeze/001"
    intent = control.read_json(directory / "intent.json")
    if fault == "empty-plan":
        intent["planned_outputs"] = []
    if fault == "wrong-input-set":
        intent["inputs"] = []
    intent["invocation_id"] = control._intent_identity(intent)
    rewrite_json(directory / "intent.json", intent)
    path = run / "source-freeze.json"
    record = control.read_json(path)
    record["invocation_id"] = intent["invocation_id"]
    record["data"]["producer_intent_digest"] = control.sha256_json(intent)
    record["data"]["freeze_digest"] = control.sha256_json(
        {k: v for k, v in record["data"].items() if k != "freeze_digest"}
    )
    record = rehash_record(record)
    rewrite_json(path, record)
    terminal = control.read_json(directory / "invocation.json")
    terminal["invocation_id"] = intent["invocation_id"]
    data = terminal["data"]
    data["inputs"][0]["sha256"] = control.sha256_json(intent)
    data["outputs"][0]["sha256"] = control.sha256_json(record)
    if fault == "wrong-output":
        (run / "wrong.json").write_bytes(path.read_bytes())
        data["outputs"][0]["path"] = "wrong.json"
    data["invocation_digest"] = control.sha256_json(
        {k: v for k, v in data.items() if k != "invocation_digest"}
    )
    rewrite_json(directory / "invocation.json", rehash_record(terminal))
    with pytest.raises(control.ReleaseControlError):
        control.validate_release_source_freeze_record(
            record, path, repository=fixture["repository"], live=False
        )


def test_fifo_input_is_rejected_without_waiting_for_a_writer(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; from metriplane.release_control import _safe_release_bytes,ReleaseControlError\ntry: _safe_release_bytes(Path(sys.argv[1]))\nexcept ReleaseControlError: raise SystemExit(3)",
            str(fifo),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 3


@pytest.mark.parametrize("sequence", ["0", "000", "01", "002", "0001", "foreign"])
def test_noncanonical_or_gapped_invocation_cannot_produce(tmp_path: Path, sequence: str) -> None:
    fixture = make_source_fixture(tmp_path)
    argv = freeze_argv(fixture)
    argv[-1] = str(fixture["run"] / "invocations/source-freeze" / sequence)
    assert run_cli(fixture, "freeze_release_source.py", argv).returncode == 2
    assert not (fixture["run"] / "source-freeze.json").exists()


def test_concurrent_reservation_has_one_winner(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    fixture = make_source_fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)),
                range(2),
            )
        )
    assert sorted(result.returncode for result in results) == [0, 2]
    run = fixture["run"]
    control.validate_release_source_freeze_record(
        control.read_json(run / "source-freeze.json"),
        run / "source-freeze.json",
        repository=fixture["repository"],
        live=False,
    )


@pytest.mark.parametrize("interrupted", [False, True])
def test_validator_retry_preserves_exact_predecessor_boundary(
    tmp_path: Path, interrupted: bool
) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    bootstrap = None
    if interrupted:
        bootstrap = "import os,signal,sys; from metriplane import release_control as c\nc._install_release_outputs=lambda *args,**kwargs: os.kill(os.getpid(),signal.SIGKILL)\nraise SystemExit(c.tool_main(sys.argv[1],sys.argv[2:]))"
    first = run_cli(
        fixture, "validate_release_source_freeze.py", validation_argv(fixture), bootstrap=bootstrap
    )
    assert first.returncode == (-signal.SIGKILL if interrupted else 0)
    directory = fixture["run"] / "invocations/source-freeze-validation"
    old = {
        str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()
    }
    second = run_cli(fixture, "validate_release_source_freeze.py", validation_argv(fixture, 2))
    assert second.returncode == 0, (second.stdout, second.stderr)
    assert all((directory / path).read_bytes() == raw for path, raw in old.items())
    intent = control.read_json(directory / "002/intent.json")
    terminal = control.read_json(directory / "002/invocation.json")
    expected = None if interrupted else control.sha256_bytes(old["001/invocation.json"])
    assert intent["previous_invocation_digest"] == expected
    assert intent["predecessor"]["disposition"] == (
        "INTERRUPTED_MISSING_TERMINAL" if interrupted else "TERMINAL"
    )
    assert terminal["data"]["previous_invocation_digest"] == expected
    assert any(row["path"].endswith("/001/intent.json") for row in terminal["data"]["inputs"])
    if not interrupted:
        terminal["data"]["inputs"] = [
            r for r in terminal["data"]["inputs"] if not r["path"].endswith("/001/invocation.json")
        ]
        terminal["data"]["invocation_digest"] = control.sha256_json(
            {k: v for k, v in terminal["data"].items() if k != "invocation_digest"}
        )
        rewrite_json(directory / "002/invocation.json", rehash_record(terminal))
        with pytest.raises(control.ReleaseControlError, match="exact pre-effect"):
            control._validate_terminal(control._validate_intent(directory / "002"))


def test_unimplemented_fixture_route_cannot_echo_a_pass(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    run = fixture["run"]
    bootstrap = "import sys; from metriplane.release_control import tool_main; raise SystemExit(tool_main(sys.argv[1],sys.argv[2:]))"
    result = run_cli(
        fixture,
        "check_release_delta.py",
        [
            "--milestone",
            "v0.4",
            "--target-resolution",
            "fixture",
            "--predecessor",
            "fixture",
            "--candidate-sha",
            fixture["sha"],
            "--impact-manifest",
            "fixture",
            "--out",
            str(run / "delta.json"),
            "--invocation-dir",
            str(run / "invocations/check-release-delta/001"),
        ],
        bootstrap=bootstrap,
    )
    assert result.returncode == 3
    assert not (run / "delta.json").exists()
    terminal = control.read_json(run / "invocations/check-release-delta/001/invocation.json")
    assert terminal["status"] == "BLOCKED"
    assert terminal["data"]["argv"].count("fixture") == 3


def test_sequences_remain_numeric_after_999_and_reject_existing_gaps(tmp_path: Path) -> None:
    stage = tmp_path / "invocations/source-freeze-validation"
    stage.mkdir(parents=True)
    for sequence in range(1, 1002):
        (stage / f"{sequence:03d}").mkdir()
    assert [p.name for p in control._journal_sequences(stage)[-3:]] == ["999", "1000", "1001"]
    (stage / "500").rmdir()
    with pytest.raises(control.ReleaseControlError, match="gaps"):
        control._journal_sequences(stage)


def test_public_consumer_rejects_foreign_sequence_even_with_valid_producer(tmp_path: Path) -> None:
    fixture = make_source_fixture(tmp_path)
    assert run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture)).returncode == 0
    run = fixture["run"]
    (run / "invocations/source-freeze/003").mkdir()
    with pytest.raises(control.ReleaseControlError, match="gaps"):
        control.validate_release_source_freeze_record(
            control.read_json(run / "source-freeze.json"),
            run / "source-freeze.json",
            repository=fixture["repository"],
            live=False,
        )


@pytest.mark.parametrize("replacement", ["file", "fifo", "absent"])
def test_partial_projection_preserves_root_kind(
    tmp_path: Path, replacement: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "run/invocations/source-freeze/001"
    directory.mkdir(parents=True)
    context = control.ReleaseInvocation(directory, tmp_path / "run", {})
    staged = directory / "staged"
    staged.mkdir()
    original = control._partial_file_projection(context)
    staged.rmdir()
    if replacement == "file":
        staged.write_bytes(b"replaced root")
    elif replacement == "fifo":
        os.mkfifo(staged)
    changed = control._partial_file_projection(context)
    assert original != changed
    assert changed["roots"][0]["kind"] == ("absent" if replacement == "absent" else "unsafe")
