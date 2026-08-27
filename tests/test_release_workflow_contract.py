# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/release-required.yml"
STATUS = ROOT / "docs/status"


def _workflow() -> dict[str, Any]:
    value = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return value


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"] if isinstance(step, dict))


def _named_step(job: dict[str, Any], name: str) -> dict[str, Any]:
    step = next(step for step in job["steps"] if step.get("name") == name)
    assert isinstance(step, dict)
    return step


def _embedded_python(step: dict[str, Any]) -> str:
    command = str(step["run"])
    marker = "python - <<'PY'\n"
    assert command.count(marker) == 1
    return command.split(marker, 1)[1].rsplit("\nPY", 1)[0]


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _live_retention_receipt(
    manifest_digest: str,
    *,
    phase: str = "qualified-publication",
    observed_digest: str | None = None,
    receipt_set_digest: str | None = None,
) -> dict[str, Any]:
    content_digest = observed_digest or manifest_digest
    stores = [
        {
            "content_digest": content_digest,
            "hold_receipt_digest": hold,
            "independence_group": group,
            "namespace": f"release-{store_id[-1]}",
            "object_key": "candidate/evidence-manifest.json",
            "put_receipt_digest": put,
            "read_back_digest": content_digest,
            "store_id": store_id,
        }
        for store_id, group, hold, put in (
            ("payload-store-a", "provider-a", "1" * 64, "2" * 64),
            ("payload-store-b", "provider-b", "3" * 64, "4" * 64),
        )
    ]
    data = {
        "all_content_equal": True,
        "input_digest": manifest_digest,
        "phase": phase,
        "receipt_set_digest": receipt_set_digest or _sha256(_canonical_json(stores)),
        "retained_at": "2026-08-27T00:00:00Z",
        "stores": stores,
    }
    record: dict[str, Any] = {
        "data": data,
        "invocation_id": "live-retention-readback",
        "payload_digest": _sha256(_canonical_json(data)),
        "record_type": "release-retention-receipts",
        "schema_version": "metriplane.release-record.v1",
        "sequence": 1,
        "signatures": [],
        "status": "PASS",
        "synthetic": False,
    }
    signed_fields = (
        "data",
        "invocation_id",
        "payload_digest",
        "record_type",
        "schema_version",
        "sequence",
        "status",
        "synthetic",
    )
    subject_digest = _sha256(_canonical_json({field: record[field] for field in signed_fields}))
    record["signatures"] = [
        {
            "actor_id": "retention-provider",
            "algorithm": "provider-attestation-v1",
            "provider": "github",
            "signature": "provider-signature-proof",
            "subject_digest": subject_digest,
            "synthetic": False,
        }
    ]
    record["record_id"] = _sha256(_canonical_json(record))
    return record


def _write_tar(path: Path, entries: list[tuple[str, str, bytes]]) -> None:
    with tarfile.open(path, mode="w") as archive:
        for name, kind, payload in entries:
            member = tarfile.TarInfo(name)
            if kind == "file":
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            elif kind == "directory":
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = "qualification.json"
                archive.addfile(member)
            elif kind == "hardlink":
                member.type = tarfile.LNKTYPE
                member.linkname = "qualification.json"
                archive.addfile(member)
            elif kind == "device":
                member.type = tarfile.CHRTYPE
                member.devmajor = 1
                member.devminor = 3
                archive.addfile(member)
            else:  # pragma: no cover - test helper misuse
                raise AssertionError(f"unknown tar member kind: {kind}")


def _resolve_context(
    tmp_path: Path,
    *,
    event_name: str,
    event: dict[str, Any],
    dispatch_mode: str = "",
    dispatch_candidate_sha: str = "",
    dispatch_main_health_sha: str = "",
    dispatch_tag: str = "",
    github_ref_name: str = "",
    github_sha: str = "",
    event_sha_fallback: str = "",
) -> subprocess.CompletedProcess[str]:
    workflow = _workflow()
    context_step = next(
        step for step in workflow["jobs"]["contracts"]["steps"] if step.get("id") == "context"
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    event_path = tmp_path / "event.json"
    output_path = tmp_path / "output.txt"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    env = {
        **os.environ,
        "DISPATCH_CANDIDATE_SHA": dispatch_candidate_sha,
        "DISPATCH_MAIN_HEALTH_SHA": dispatch_main_health_sha,
        "DISPATCH_MODE": dispatch_mode,
        "DISPATCH_TAG": dispatch_tag,
        "EVENT_SHA_FALLBACK": event_sha_fallback,
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_REF_NAME": github_ref_name,
        "GITHUB_SHA": github_sha,
    }
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", context_step["run"]],
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )


def test_release_terminal_routes_all_three_modes_fail_closed() -> None:
    workflow = _workflow()
    triggers = _triggers(workflow)
    assert set(triggers) == {"merge_group", "pull_request", "push", "workflow_dispatch"}
    assert triggers["merge_group"] == {"types": ["checks_requested"]}
    assert triggers["push"] == {"tags": ["v*.*.*"]}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["mode"]["options"] == ["release-qualification", "post-publication"]
    assert {
        "authority_bundle_sha256",
        "authority_run_id",
        "candidate_sha",
        "evidence_manifest_sha256",
        "main_health_sha",
        "mode",
    } <= set(inputs)
    assert "authority_artifact" not in inputs
    assert inputs["authority_bundle_sha256"]["required"] is True

    contracts = workflow["jobs"]["contracts"]
    text = _run_text(contracts)
    assert 'mode = "pr-merge-control"' in text
    assert 'mode = "post-publication"' in text
    assert 'event_name == "workflow_dispatch"' in text
    assert "source_sha != main_health_sha" in text
    assert 'git cat-file -t "$tag_ref"' in text
    assert "unsupported release mode" in text


def test_authority_store_urls_require_distinct_https_hosts() -> None:
    contracts = _workflow()["jobs"]["contracts"]
    step = _named_step(contracts, "Download and compare independent authority-store bundles")
    assert step["env"] == {
        "AUTHORITY_BUNDLE_SHA256": "${{ steps.authority-inputs.outputs.bundle_sha256 }}",
        "AUTHORITY_STORE_A_TOKEN": "${{ secrets.RELEASE_AUTHORITY_STORE_A_TOKEN }}",
        "AUTHORITY_STORE_A_URL": "${{ vars.RELEASE_AUTHORITY_STORE_A_URL }}",
        "AUTHORITY_STORE_B_TOKEN": "${{ secrets.RELEASE_AUTHORITY_STORE_B_TOKEN }}",
        "AUTHORITY_STORE_B_URL": "${{ vars.RELEASE_AUTHORITY_STORE_B_URL }}",
    }
    command = str(step["run"])
    assert command.count("curl --proto '=https'") == 2
    assert "--location" not in command
    assert command.count("--max-filesize 536870912") == 2
    assert "cmp --silent" in command
    assert 'test "$store_a_sha256" = "$AUTHORITY_BUNDLE_SHA256"' in command

    script = _embedded_python(step)
    base_env = {
        **os.environ,
        "AUTHORITY_STORE_A_URL": "https://authority-a.example/bundle.tar",
        "AUTHORITY_STORE_B_URL": "https://authority-b.example/bundle.tar",
    }
    valid = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        env=base_env,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr

    same_host_env = {
        **base_env,
        "AUTHORITY_STORE_B_URL": "https://AUTHORITY-A.EXAMPLE./other-bundle.tar",
    }
    same_host = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        env=same_host_env,
        text=True,
    )
    assert same_host.returncode != 0
    assert "distinct HTTPS host identities" in same_host.stderr


def test_authority_bundle_extraction_accepts_directories_and_rejects_unsafe_members(
    tmp_path: Path,
) -> None:
    contracts = _workflow()["jobs"]["contracts"]
    script = _embedded_python(_named_step(contracts, "Extract the exact authority bundle safely"))

    valid_root = tmp_path / "valid"
    valid_root.mkdir()
    valid_archive = valid_root / "bundle.tar"
    _write_tar(
        valid_archive,
        [
            (".", "directory", b""),
            ("prepublication/", "directory", b""),
            ("qualification.json", "file", b'{"status":"PASS"}'),
            ("prepublication/approval.json", "file", b'{"decision":"APPROVED"}'),
        ],
    )
    valid = subprocess.run(
        [sys.executable, "-c", script],
        cwd=valid_root,
        env={**os.environ, "AUTHORITY_BUNDLE": str(valid_archive)},
        capture_output=True,
        check=False,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr
    assert (
        valid_root / ".release-authority/qualification.json"
    ).read_bytes() == b'{"status":"PASS"}'
    assert (valid_root / ".release-authority/prepublication").is_dir()
    assert (valid_root / ".release-authority/prepublication/approval.json").read_bytes() == (
        b'{"decision":"APPROVED"}'
    )

    mutations: dict[str, list[tuple[str, str, bytes]]] = {
        "absolute": [("/escape.json", "file", b"escape")],
        "traversal": [("../escape.json", "file", b"escape")],
        "duplicate": [
            ("qualification.json", "file", b"first"),
            ("qualification.json", "file", b"second"),
        ],
        "collision": [
            ("prepublication", "file", b"not-a-directory"),
            ("prepublication/approval.json", "file", b"approval"),
        ],
        "symlink": [("qualification.json", "symlink", b"")],
        "hardlink": [("qualification.json", "hardlink", b"")],
        "device": [("qualification.json", "device", b"")],
    }
    for label, entries in mutations.items():
        case_root = tmp_path / label
        case_root.mkdir()
        archive = case_root / "bundle.tar"
        _write_tar(archive, entries)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=case_root,
            env={**os.environ, "AUTHORITY_BUNDLE": str(archive)},
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode != 0, label
        assert not (tmp_path / "escape.json").exists(), label


def test_retention_receipts_bind_to_both_observed_store_bundles(tmp_path: Path) -> None:
    contracts = _workflow()["jobs"]["contracts"]
    step = _named_step(contracts, "Bind retention receipts to both exact store read-backs")
    script = _embedded_python(step)
    manifest_bytes = b'{"manifest":"exact-authority"}\n'
    manifest_digest = _sha256(manifest_bytes)
    bundle_bytes = b"exact-store-bundle-bytes"

    def run_case(
        label: str,
        receipt: dict[str, Any],
        *,
        second_bundle: bytes = bundle_bytes,
    ) -> subprocess.CompletedProcess[str]:
        case_root = tmp_path / label
        runner_temp = case_root / "runner-temp"
        authority = case_root / ".release-authority"
        receipts = authority / "prepublication"
        receipts.mkdir(parents=True)
        runner_temp.mkdir()
        (runner_temp / "authority-store-a.tar").write_bytes(bundle_bytes)
        (runner_temp / "authority-store-b.tar").write_bytes(second_bundle)
        (authority / "evidence-manifest.json").write_bytes(manifest_bytes)
        (receipts / "retention-receipts.json").write_text(json.dumps(receipt), encoding="utf-8")
        env = {
            **os.environ,
            "AUTHORITY_BUNDLE_SHA256": _sha256(bundle_bytes),
            "EVIDENCE_MANIFEST_SHA256": manifest_digest,
            "RELEASE_MODE": "release-qualification",
            "RUNNER_TEMP": str(runner_temp),
        }
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=case_root,
            env=env,
            capture_output=True,
            check=False,
            text=True,
        )

    valid = run_case("valid", _live_retention_receipt(manifest_digest))
    assert valid.returncode == 0, valid.stderr

    divergent_bundle = run_case(
        "divergent-bundle",
        _live_retention_receipt(manifest_digest),
        second_bundle=b"different-store-bytes",
    )
    assert divergent_bundle.returncode != 0
    assert "not exact-byte identical" in divergent_bundle.stderr

    divergent_receipt = run_case(
        "divergent-receipt",
        _live_retention_receipt(manifest_digest, observed_digest="0" * 64),
    )
    assert divergent_receipt.returncode != 0
    assert "differs from observed store bytes" in divergent_receipt.stderr

    wrong_phase = run_case(
        "wrong-phase",
        _live_retention_receipt(manifest_digest, phase="prepublication"),
    )
    assert wrong_phase.returncode != 0
    assert "transported manifest and phase" in wrong_phase.stderr

    wrong_receipt_set = run_case(
        "wrong-receipt-set",
        _live_retention_receipt(manifest_digest, receipt_set_digest="f" * 64),
    )
    assert wrong_receipt_set.returncode != 0
    assert "receipt-set digest mismatch" in wrong_receipt_set.stderr


def test_event_mode_resolution_executes_against_provider_payloads(tmp_path: Path) -> None:
    source = "a" * 40
    base = "b" * 40
    cases = [
        (
            "pull_request",
            {"pull_request": {"base": {"sha": base}, "head": {"sha": source}}},
            {"event_sha_fallback": source},
            {"main_health_sha": base, "mode": "pr-merge-control", "source_sha": source},
        ),
        (
            "merge_group",
            {"merge_group": {"base_sha": base, "head_sha": source}},
            {},
            {"main_health_sha": base, "mode": "pr-merge-control", "source_sha": source},
        ),
        (
            "push",
            {},
            {
                "event_sha_fallback": source,
                "github_ref_name": "v0.4.0",
                "github_sha": source,
            },
            {
                "checkout_ref": "refs/tags/v0.4.0",
                "main_health_sha": "",
                "mode": "post-publication",
                "source_sha": "",
                "tag": "v0.4.0",
            },
        ),
        (
            "workflow_dispatch",
            {},
            {
                "dispatch_candidate_sha": source,
                "dispatch_main_health_sha": source,
                "dispatch_mode": "release-qualification",
            },
            {
                "main_health_sha": source,
                "mode": "release-qualification",
                "source_sha": source,
            },
        ),
    ]
    for ordinal, (event_name, event, kwargs, expected) in enumerate(cases):
        case_path = tmp_path / str(ordinal)
        case_path.mkdir()
        result = _resolve_context(case_path, event_name=event_name, event=event, **kwargs)
        assert result.returncode == 0, result.stderr
        observed = dict(
            line.split("=", 1)
            for line in (case_path / "output.txt").read_text(encoding="utf-8").splitlines()
        )
        assert all(observed.get(key) == value for key, value in expected.items())


def test_event_mode_resolution_rejects_identity_and_tag_drift(tmp_path: Path) -> None:
    source = "a" * 40
    mismatch = _resolve_context(
        tmp_path / "mismatch",
        event_name="workflow_dispatch",
        event={},
        dispatch_candidate_sha=source,
        dispatch_main_health_sha="b" * 40,
        dispatch_mode="release-qualification",
    )
    assert mismatch.returncode != 0
    assert "must equal the protected-main health identity" in mismatch.stderr

    bad_tag_path = tmp_path / "bad-tag"
    bad_tag_path.mkdir()
    bad_tag = _resolve_context(
        bad_tag_path,
        event_name="workflow_dispatch",
        event={},
        dispatch_candidate_sha=source,
        dispatch_main_health_sha=source,
        dispatch_mode="post-publication",
        dispatch_tag="latest",
    )
    assert bad_tag.returncode != 0
    assert "requires one canonical semantic-version tag" in bad_tag.stderr


def test_matrix_executes_every_exact_registry_cell() -> None:
    workflow = _workflow()
    matrix = workflow["jobs"]["matrix"]
    declared = matrix["strategy"]["matrix"]["include"]
    environments = json.loads((STATUS / "supported-environments.json").read_text(encoding="utf-8"))[
        "environments"
    ]
    expected = [
        {
            "environment": row["id"],
            "python": row["python"],
            "runner": row["runner"],
        }
        for row in environments
        if row["required"]
    ]
    assert declared == expected
    assert matrix["strategy"]["fail-fast"] is False
    assert matrix["runs-on"] == "${{ matrix.runner }}"
    assert "python -m pytest -q" in _run_text(matrix)
    assert all(row["command"] == "python -m pytest -q" for row in environments)
    assert all(row["runner_kind"] == "github-hosted" for row in environments)


def test_main_health_and_repair_history_are_consumed_read_only() -> None:
    workflow = _workflow()
    contracts = workflow["jobs"]["contracts"]
    checkout = next(
        step
        for step in contracts["steps"]
        if step.get("name") == "Check out immutable main-health history read-only"
    )
    assert checkout["with"] == {
        "fetch-depth": 0,
        "path": ".release-main-health-state",
        "persist-credentials": False,
        "ref": "metriplane-main-health-state",
    }
    text = _run_text(contracts)
    assert "stop_the_line.py github-provider-clock" in text
    assert "stop_the_line.py candidate" in text
    assert '--base-sha "$MAIN_HEALTH_SHA"' in text
    assert "stop_the_line.py ingest" not in text
    assert "stop_the_line.py resolve" not in text


def test_live_modes_require_real_authority_and_exact_validators() -> None:
    workflow = _workflow()
    contracts = workflow["jobs"]["contracts"]
    text = _run_text(contracts)
    assert 'value.get("synthetic") is not False' in text
    assert "evidence manifest transport digest mismatch" in text
    assert "validate_release_gate_instance.py" in text
    assert "check_release_readiness.py" in text
    assert "validate_release_qualification_plan.py" in text
    assert "validate_release_qualification.py" in text
    assert "validate_release_role_assignments.py" in text
    assert "--check-conflicts" in text
    assert "--check-freshness" in text
    assert "validate_release_approval.py" in text
    assert '--role-assignments "$root/role-assignments.json"' in text
    assert "validate_release_retention.py" not in text
    assert "Bind retention receipts to both exact store read-backs" in (
        WORKFLOW_PATH.read_text(encoding="utf-8")
    )
    assert "validate_publication_reconciliation.py" in text
    assert "authority store read-backs are not exact-byte identical" in text
    assert '--record "$root/prepublication/approval.json"' in text
    assert 'cmp --silent "$root/readiness.json"' in text


def test_release_terminal_cannot_hide_matrix_or_contract_failure() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert jobs["fake-release"]["needs"] == ["contracts", "matrix"]
    assert jobs["fake-release"]["if"] == "always() && needs.contracts.result == 'success'"
    assert jobs["required"]["name"] == "Release / required"
    assert jobs["required"]["if"] == "always()"
    assert jobs["required"]["needs"] == ["contracts", "fake-release"]
    assert 'test "$MATRIX_RESULT" = success' in _run_text(jobs["fake-release"])
    required_text = _run_text(jobs["required"])
    assert "--expected-dependency contracts" in required_text
    assert "--expected-dependency fake-release" in required_text


def test_current_readiness_resolves_absence_as_blocked() -> None:
    readiness = json.loads((STATUS / "release-readiness.json").read_text(encoding="utf-8"))
    obligations = json.loads((STATUS / "release-test-obligations.json").read_text(encoding="utf-8"))
    assert readiness["framework"] == "BLOCKED_NOT_READY"
    assert readiness["live_release"] == "BLOCKED_NOT_READY"
    assert readiness["evidence_resolution"]["status"] == "BLOCKED_NOT_READY"
    assert obligations["evidence_resolution"] == {
        "allow_synthetic": False,
        "required_count": 13,
        "resolved_count": 0,
        "status": "BLOCKED_NOT_READY",
    }
    rows = obligations["obligations"]
    assert len(rows) == 13
    assert all(row["result_required"] is True for row in rows)
    assert all(row["result_state"] == "ABSENT" for row in rows)
    assert all(row["result_digest"] is None for row in rows)
    assert all(not (ROOT / row["result"]).exists() for row in rows)


def test_scenario_catalog_closes_phases_terminals_and_recovery_edges() -> None:
    registry = json.loads((STATUS / "release-scenarios.json").read_text(encoding="utf-8"))
    scenarios = registry["scenarios"]
    assert {scenario["phase"] for scenario in scenarios} == set(registry["phases"])
    assert {scenario["expected"] for scenario in scenarios} == set(registry["terminal_results"])
    assert {stage for scenario in scenarios for stage in scenario["covers_stages"]} == set(
        registry["stages"]
    )
    assert all(scenario["fault"] and scenario["retry"] for scenario in scenarios)
    assert all(scenario["test_node_id"].endswith(f"[{scenario['id']}]") for scenario in scenarios)
    assert {
        "hard-runner-loss",
        "runner-service-retry",
        "staging-cancelled",
        "required-cell-skipped",
        "concurrent-writer",
        "kill-after-cas",
        "capability-limited-tag-burn",
    } <= {scenario["id"] for scenario in scenarios}


def test_workflow_has_no_mutation_authority() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        permissions = job.get("permissions", {})
        assert all(value == "read" for value in permissions.values())
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "id-token: write" not in text
    assert "contents: write" not in text
    assert "git push" not in text
    assert "gh release create" not in text
