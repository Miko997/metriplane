# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from metriplane.sentinel.bundles import (
    UNSIGNED_DERIVED_SIDECARS,
    write_checksums,
)
from metriplane.testing.cli import main_test
from metriplane.testing.runner import PhysicalRegressionRunner

BUNDLE = "evidence/incidents/INC-0001"


@pytest.fixture
def bundle_copy(tmp_path):
    dst = tmp_path / "INC-0001"
    shutil.copytree(BUNDLE, dst)
    return dst


def _resign_bundle(bundle: Path) -> None:
    write_checksums(
        bundle,
        exclude={"CHECKSUMS.sha256", *UNSIGNED_DERIVED_SIDECARS},
    )


def test_demo_bundle_passes(bundle_copy):
    result = PhysicalRegressionRunner().run_bundle(bundle_copy)
    assert result.pass_ is True
    assert result.observed["incidents"] >= 1


def test_missing_expected_fails(tmp_path, bundle_copy):
    (bundle_copy / "expected.yaml").unlink()
    result = PhysicalRegressionRunner().run_bundle(bundle_copy)
    assert result.pass_ is False


def test_checksum_tamper_fails(bundle_copy):
    (bundle_copy / "trace.csv").write_text("tampered")
    result = PhysicalRegressionRunner().run_bundle(bundle_copy)
    assert result.pass_ is False
    assert any("checksum" in c["check"] for c in result.checks)


def test_skip_checksums_allows_eval(bundle_copy):
    (bundle_copy / "trace.csv").write_text("tampered")
    # trace.csv is not used by evaluation; skipping checksums should let it pass
    result = PhysicalRegressionRunner(verify_checksums=False).run_bundle(bundle_copy)
    assert result.pass_ is True


def test_cli_writes_result_json(bundle_copy):
    rc = main_test([str(bundle_copy)])
    assert rc == 0
    data = json.loads((bundle_copy / "test_result.json").read_text())
    assert data["pass"] is True
    assert (bundle_copy / "test_result.md").exists()

    # Generated result sidecars remain outside the immutable checksum inventory.
    assert main_test([str(bundle_copy)]) == 0


def test_cli_output_flag(tmp_path, bundle_copy):
    out = tmp_path / "result.json"
    rc = main_test([str(bundle_copy), "--output", str(out), "--no-write-reports"])
    assert rc == 0
    assert json.loads(out.read_text())["pass"] is True
    assert not (bundle_copy / "test_result.json").exists()


def test_cli_returns_one_on_failure(bundle_copy):
    (bundle_copy / "expected.yaml").write_text(
        "expected:\n  incidents:\n    - type: t\n      rule_id: nonexistent\n"
    )
    rc = main_test([str(bundle_copy), "--no-write-reports"])
    assert rc == 1


def test_bad_bundle_inputs_fail_cleanly_without_creating_paths(tmp_path):
    missing = tmp_path / "typo-bundle"

    result = PhysicalRegressionRunner().run_bundle(missing)

    assert result.pass_ is False
    assert main_test([str(missing)]) == 1
    assert not missing.exists()

    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "expected.yaml").write_text("incidents: [", encoding="utf-8")
    assert PhysicalRegressionRunner().run_bundle(malformed).pass_ is False


def test_determinism_check_present(bundle_copy):
    result = PhysicalRegressionRunner().run_bundle(bundle_copy)
    assert any(c["check"] == "replay.deterministic_hash_match" for c in result.checks)
    assert result.output_hash


@pytest.mark.parametrize("contents", ["", "{broken\n"])
def test_empty_or_malformed_session_excerpt_fails_closed(bundle_copy, contents):
    (bundle_copy / "session_excerpt.jsonl").write_text(contents, encoding="utf-8")

    result = PhysicalRegressionRunner(verify_checksums=False).run_bundle(bundle_copy)

    assert result.pass_ is False
    assert any(check["check"] == "bundle.input" for check in result.checks)


def test_empty_semantic_oracle_cannot_pass(bundle_copy):
    (bundle_copy / "expected.yaml").write_text(
        'schema_version: "1.0"\nexpected: {}\n',
        encoding="utf-8",
    )

    result = PhysicalRegressionRunner().run_bundle(bundle_copy)

    assert result.pass_ is False
    assert result.checks[0]["check"] == "expected.semantic_oracle"


def test_missing_required_evidence_cannot_pass(bundle_copy: Path) -> None:
    (bundle_copy / "report.md").unlink()
    _resign_bundle(bundle_copy)

    result = PhysicalRegressionRunner().run_bundle(bundle_copy)

    assert result.pass_ is False
    assert result.checks[0]["check"] == "bundle.input"
    assert "report.md" in result.checks[0]["detail"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_id", "wrong-run", "run_id"),
        ("alert_ids", ["fake-a", "fake-b", "fake-c"], "alert IDs"),
    ],
)
def test_stored_incident_reference_mismatch_cannot_pass(
    bundle_copy: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    incident_path = bundle_copy / "incident.json"
    incidents = json.loads(incident_path.read_text(encoding="utf-8"))
    incidents[0][field] = value
    incident_path.write_text(json.dumps(incidents), encoding="utf-8")
    _resign_bundle(bundle_copy)

    result = PhysicalRegressionRunner().run_bundle(bundle_copy)

    assert result.pass_ is False
    assert result.checks[0]["check"] == "bundle.input"
    assert message in result.checks[0]["detail"]


def test_consistently_rewritten_alert_ids_do_not_reproduce(
    bundle_copy: Path,
) -> None:
    fake_ids = ["fake-a", "fake-b", "fake-c"]
    incident_path = bundle_copy / "incident.json"
    incidents = json.loads(incident_path.read_text(encoding="utf-8"))
    incidents[0]["alert_ids"] = fake_ids
    incident_path.write_text(json.dumps(incidents), encoding="utf-8")
    alerts_path = bundle_copy / "alerts.jsonl"
    alerts = [
        json.loads(line) for line in alerts_path.read_text(encoding="utf-8").splitlines() if line
    ]
    for alert, fake_id in zip(alerts, fake_ids, strict=True):
        alert["alert_id"] = fake_id
    alerts_path.write_text(
        "\n".join(json.dumps(alert) for alert in alerts) + "\n",
        encoding="utf-8",
    )
    _resign_bundle(bundle_copy)

    result = PhysicalRegressionRunner().run_bundle(bundle_copy)

    assert result.pass_ is False
    assert any(
        check["check"] == "bundle.replayed_references" and not check["pass"]
        for check in result.checks
    )
