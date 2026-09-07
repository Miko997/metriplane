# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from metriplane.atlas.bundles import export_bundle, verify_bundle
from metriplane.atlas.models import AtlasRunManifest
from metriplane.atlas.regression import run_regression
from metriplane.atlas.run_assessment import read_run_assessment
from metriplane.atlas.runtime import run_atlas

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/external_sources/maniskill_pickcube/incident"
ASSESSMENT = "requirement_assessment.json"


def _run(tmp_path: Path, *, frame_count: int | None = None) -> Path:
    session = FIXTURE / "session.jsonl"
    if frame_count is not None:
        session = tmp_path / "truncated.jsonl"
        rows = (FIXTURE / "session.jsonl").read_text(encoding="utf-8").splitlines()
        session.write_text("\n".join(rows[:frame_count]) + "\n", encoding="utf-8")
    output = tmp_path / "run"
    run_atlas(session, FIXTURE / "domain-pack", output, run_id="assessment-integration")
    return output


def test_runtime_assessment_distinguishes_observed_wait_from_legacy_metric(tmp_path: Path) -> None:
    run = _run(tmp_path)
    manifest = AtlasRunManifest.model_validate_json((run / "atlas_manifest.json").read_text())
    assert manifest.artifacts["requirement_assessment"] == ASSESSMENT
    assert (
        manifest.requirement_assessment_sha256
        == hashlib.sha256((run / ASSESSMENT).read_bytes()).hexdigest()
    )
    payload = read_run_assessment(run)
    assessment = payload["process_assessment"]
    assert assessment["outcome"] == "violated"
    step = assessment["steps"][0]
    assert step["observed_wait_s"] == pytest.approx(0.25)
    assert step["trigger_ts"] == pytest.approx(3.3)
    assert step["completion_ts"] == pytest.approx(3.55)
    metrics = json.loads((run / "metrics.json").read_text())
    assert sum(metrics["wait_time_s"].values()) == pytest.approx(0.2)
    assert payload["observed_wait"]["total_s"] == pytest.approx(0.25)
    report = (run / "cell_truth_report.md").read_text()
    assert "Overall recorded outcome: `violated`" in report
    assert "0.25 s" in report
    assert "not total observed waiting time" in report
    html = (run / "cell_truth_report.html").read_text()
    assert "<h3>Requirement outcomes</h3>" in html
    assert "Overall recorded outcome: <code>violated</code>" in html


@pytest.mark.parametrize(("frame_count", "outcome"), [(68, "unresolved"), (20, "not_exercised")])
def test_zero_incident_report_does_not_claim_unobserved_success(
    tmp_path: Path, frame_count: int, outcome: str
) -> None:
    run = _run(tmp_path, frame_count=frame_count)
    payload = read_run_assessment(run)
    assert payload["process_assessment"]["outcome"] == outcome
    assert payload["observed_wait"]["total_s"] is None
    assert payload["coverage"]["complete"] is False
    report = (run / "cell_truth_report.md").read_text()
    assert f"Overall recorded outcome: `{outcome}`" in report
    assert "No process rule was broken" not in report
    assert "Zero incidents alone does not establish compliance" in report
    if outcome == "unresolved":
        assert "at least 0.05 s (unfinished)" in report
    assert not (run / "evidence_bundles").exists()


def test_assessment_is_retained_and_checksummed_in_replayable_bundle(tmp_path: Path) -> None:
    run = _run(tmp_path)
    bundle = next((run / "evidence_bundles").glob("*.zip"))
    with zipfile.ZipFile(bundle) as archive:
        assert archive.read(ASSESSMENT) == (run / ASSESSMENT).read_bytes()
        assert ASSESSMENT in json.loads(archive.read("manifest.json"))["required_files"]
        assert ASSESSMENT in archive.read("checksums.sha256").decode()
    assert verify_bundle(bundle)["pass"] is True
    regression = next((run / "regression_tests").glob("*.yaml"))
    assert run_regression(regression)["pass"] is True
    tampered = tmp_path / "tampered"
    shutil.copytree(bundle.with_suffix(""), tampered)
    (tampered / ASSESSMENT).write_text("{}\n")
    assert verify_bundle(tampered)["pass"] is False


def test_export_rejects_changed_assessment_before_creating_bundle(tmp_path: Path) -> None:
    run = _run(tmp_path)
    (run / ASSESSMENT).write_text("{}\n")
    destination = tmp_path / "invalid.zip"
    with pytest.raises(ValueError):
        export_bundle(run, "INC-0001", destination)
    assert not destination.exists()
    assert not destination.with_suffix("").exists()


def test_manifest_without_additive_assessment_remains_readable(tmp_path: Path) -> None:
    run = _run(tmp_path)
    manifest = json.loads((run / "atlas_manifest.json").read_text())
    del manifest["requirement_assessment_sha256"]
    del manifest["artifacts"]["requirement_assessment"]
    loaded = AtlasRunManifest.model_validate(manifest)
    assert loaded.requirement_assessment_sha256 is None
    assert "requirement_assessment_sha256" not in loaded.model_dump(exclude_none=True)


def test_custom_segment_export_omits_full_run_assessment_without_breaking_export(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    rows = [json.loads(line) for line in (run / "state_segment.jsonl").read_text().splitlines()]
    bundle = export_bundle(run, "INC-0001", tmp_path / "custom.zip", rows[:71])
    assert verify_bundle(bundle)["pass"] is True
    with zipfile.ZipFile(bundle) as archive:
        assert ASSESSMENT not in archive.namelist()
        assert ASSESSMENT not in json.loads(archive.read("manifest.json"))["required_files"]
        assert (
            "custom recorded-state segment" in archive.read("reports/cell_truth_report.md").decode()
        )
        assert "full-run requirement assessment omitted" in archive.read("limitations.md").decode()
    assert read_run_assessment(run)["process_assessment"]["steps"][0]["completion_ts"] == 3.55


def test_bundle_rejects_segment_replacement_even_when_inventory_is_rehashed(tmp_path: Path) -> None:
    run = _run(tmp_path)
    original = next((run / "evidence_bundles").glob("*.zip")).with_suffix("")
    changed = tmp_path / "changed-segment"
    shutil.copytree(original, changed)
    segment = changed / "state_segment.jsonl"
    segment.write_text("\n".join(segment.read_text().splitlines()[:71]) + "\n")
    checksum_file = changed / "checksums.sha256"
    checksum_file.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(changed).as_posix()}\n"
            for path in sorted(changed.rglob("*"))
            if path.is_file() and path != checksum_file
        )
    )
    result = verify_bundle(changed)
    assert result["pass"] is False
    assert any(
        "state/config binding mismatch: state_segment.jsonl" in error for error in result["errors"]
    )


def test_outcome_labels_cannot_inject_html_or_markdown_structure(tmp_path: Path) -> None:
    run = _run(tmp_path)
    from metriplane.atlas.assessment import RequirementAssessment
    from metriplane.atlas.reports import _assessment_lines, render_html

    assessment = RequirementAssessment.model_validate(
        read_run_assessment(run)["process_assessment"]
    )
    assessment.steps[0].step_id = "step|extra\n## forged <script>alert(1)</script>"
    markdown = "\n".join(_assessment_lines(assessment))
    assert "\n## forged" not in markdown
    assert "step|extra" not in markdown
    html = render_html(markdown)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
