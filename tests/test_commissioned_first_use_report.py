# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/evaluations/commissioned-first-use-v030"
TOOL = ROOT / "tools/commissioned_first_use/build_and_validate.py"

spec = importlib.util.spec_from_file_location("met12_build", TOOL)
assert spec and spec.loader
met12 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(met12)


def rows(name: str) -> list[dict[str, str]]:
    with (PACKAGE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_canonical_cohort_and_aggregates() -> None:
    primary = rows("public_results.csv")
    auxiliary = rows("auxiliary_records.csv")
    assert [row["slot"] for row in primary] == [f"T{i:02d}" for i in range(1, 7)]
    assert [row["slot"] for row in auxiliary] == ["AUX-A", "AUX-B"]
    assert all(row["included_in_primary_cohort"] == "YES" for row in primary)
    assert all(row["included_in_primary_cohort"] == "NO" for row in auxiliary)
    assert all(row["metriplane_version"] == "0.3.0" for row in primary + auxiliary)
    assert all(row["installation_source"] == "PyPI" for row in primary + auxiliary)

    summary = met12.compute_summary(primary, auxiliary)
    assert summary["primary_cohort_count"] == 6
    assert summary["primary_core_pass_count"] == 6
    assert summary["auxiliary_record_count"] == 2
    assert summary["environment_counts"] == {
        "Native Linux": 4,
        "WSL2 Ubuntu": 1,
        "macOS": 1,
    }
    assert summary["architecture_counts"] == {"ARM64/AArch64": 2, "x86_64": 4}
    assert summary["python_minor_counts"] == {"3.12": 4, "3.13": 2}
    assert summary["compensation_totals_by_currency"] == {"EUR": 57, "USD": 22}
    assert json.loads((PACKAGE / "summary.json").read_text(encoding="utf-8")) == summary


def test_not_recorded_and_coverage_fields() -> None:
    primary = rows("public_results.csv")
    auxiliary = rows("auxiliary_records.csv")
    assert all(value != "" for row in primary + auxiliary for value in row.values())
    t02 = next(row for row in primary if row["slot"] == "T02")
    for field in (
        "event_count",
        "incident_count",
        "bundle_result",
        "regression_result",
        "first_failed_command",
        "first_confusion",
        "assistance_before_capture",
        "elapsed_seconds",
        "elapsed_status",
    ):
        assert t02[field] == "NOT_RECORDED"

    assistance = [
        row["assistance_before_capture"]
        for row in primary
        if row["assistance_before_capture"] != "NOT_RECORDED"
    ]
    assert assistance == ["NO"] * 5

    confusion = [
        row["first_confusion"]
        for row in primary
        if row["first_confusion"] != "NOT_RECORDED"
    ]
    assert len(confusion) == 5
    assert confusion.count("NOT_APPLICABLE") == 4
    assert sum(value not in {"NOT_APPLICABLE", "NOT_RECORDED"} for value in confusion) == 1


def test_report_manifest_boundaries_and_privacy() -> None:
    report = (PACKAGE / "REPORT.md").read_text(encoding="utf-8")
    claims = (PACKAGE / "CLAIMS.md").read_text(encoding="utf-8")
    manifest = json.loads((PACKAGE / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    assert "Compensation disclosure" in report
    assert "6 of 6 accepted primary records" in report
    assert "Assistance coverage" in report
    assert "Five of six primary records explicitly captured assistance" in report
    assert "First-confusion coverage" in report
    assert "Four recorded no confusion" in report
    assert "## 10. Limitations" in report
    assert "T02 establishes successful installation" in report
    assert "## Prohibited claims" in claims

    source_ids = {source["source_id"] for source in manifest["sources"]}
    assert "FROZEN_PROTOCOL_ARCHIVE" in source_ids
    assert "PRIMARY_COMPENSATION_CROSSWALK" in source_ids
    claim_map = {claim["claim_id"]: set(claim["source_ids"]) for claim in manifest["claims"]}
    assert claim_map["C03"] == {
        "PUBLIC_RESULTS_CSV",
        "PRIMARY_COMPENSATION_CROSSWALK",
    }
    assert claim_map["C05"] == {
        "FROZEN_PROTOCOL_ARCHIVE",
        "PRIMARY_COMPENSATION_CROSSWALK",
    }
    assert claim_map["C06"] == {"FROZEN_PROTOCOL_ARCHIVE"}

    public_files = [
        "README.md",
        "REPORT.md",
        "public_results.csv",
        "auxiliary_records.csv",
        "summary.json",
        "CLAIMS.md",
        "SOURCE_MANIFEST.json",
        "BUILD.md",
    ]
    text = "\n".join((PACKAGE / name).read_text(encoding="utf-8") for name in public_files)
    lowered = text.lower()
    assert ("linear" + ".app") not in lowered
    assert not re.search(r"\bFO[A-Z0-9]{8,}\b", text)
    assert not re.search(r"\bPRIVATE_[A-Z0-9_]+\b", text)
    assert list(rows("public_results.csv")[0]) == met12.EXPECTED_FIELDS


def test_links_pdf_and_checksums() -> None:
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", readme):
        if "://" not in target:
            assert (PACKAGE / target).is_file(), target
    pdf = PACKAGE / "commissioned_first_use_report.pdf"
    assert pdf.is_file()
    assert pdf.stat().st_size > 5_000
    assert met12.validate(write=False) == []
