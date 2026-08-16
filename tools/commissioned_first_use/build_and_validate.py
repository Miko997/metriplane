# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "docs/evaluations/commissioned-first-use-v030"
PRIMARY_CSV = PACKAGE / "public_results.csv"
AUXILIARY_CSV = PACKAGE / "auxiliary_records.csv"
SUMMARY_JSON = PACKAGE / "summary.json"
MANIFEST_JSON = PACKAGE / "SOURCE_MANIFEST.json"
CHECKSUMS = PACKAGE / "SHA256SUMS"

EXPECTED_FIELDS = """slot included_in_primary_cohort execution_date
recruitment_platform compensation_amount compensation_currency os_environment
environment_type architecture python_version metriplane_version
installation_source core_result doctor_result demo_result event_count
incident_count bundle_result regression_result first_failed_command
first_confusion assistance_before_capture elapsed_seconds elapsed_status
methodology_note missing_fields public_result_url""".split()
PRIMARY_SLOTS = [f"T{i:02d}" for i in range(1, 7)]
AUXILIARY_SLOTS = ["AUX-A", "AUX-B"]
RESULTS = {"PASS", "FAIL", "NOT_RECORDED", "NOT_APPLICABLE"}
YES_NO = {"YES", "NO", "NOT_RECORDED", "NOT_APPLICABLE"}
ELAPSED = {"EXACT", "APPROXIMATE", "NOT_RECORDED", "NOT_APPLICABLE"}
CHECKSUM_FILES = [
    "README.md",
    "REPORT.md",
    "public_results.csv",
    "auxiliary_records.csv",
    "summary.json",
    "CLAIMS.md",
    "SOURCE_MANIFEST.json",
    "commissioned_first_use_report.pdf",
    "BUILD.md",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_FIELDS:
            raise ValueError(f"{path}: unexpected columns: {reader.fieldnames}")
        return list(reader)


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def compute_summary(
    primary: list[dict[str, str]], auxiliary: list[dict[str, str]]
) -> dict[str, object]:
    compensation: dict[str, int] = defaultdict(int)
    for row in primary:
        compensation[row["compensation_currency"]] += int(
            row["compensation_amount"]
        )
    python_counts = Counter(".".join(row["python_version"].split(".")[:2]) for row in primary)
    return {
        "schema_version": "1.0.0",
        "protocol_id": "MP-EXT-UX-001",
        "protocol_version": "1.0",
        "evidence_class": "E2 commissioned external execution",
        "report_version": "1.0.0",
        "report_date": "2026-08-15",
        "archive_status": "HOLD",
        "artifact": "metriplane==0.3.0",
        "installation_source": "PyPI",
        "primary_cohort_count": len(primary),
        "primary_core_pass_count": sum(row["core_result"] == "PASS" for row in primary),
        "auxiliary_record_count": len(auxiliary),
        "environment_counts": dict(
            sorted(Counter(row["environment_type"] for row in primary).items())
        ),
        "architecture_counts": dict(
            sorted(Counter(row["architecture"] for row in primary).items())
        ),
        "python_minor_counts": dict(sorted(python_counts.items())),
        "compensation_totals_by_currency": dict(sorted(compensation.items())),
        "primary_success_statement": (
            "6 of 6 accepted primary records completed the bounded packaged "
            "first-use workflow in their observed environments."
        ),
        "auxiliary_statement": (
            "2 commissioned records were retained as auxiliary evidence and "
            "excluded from the primary denominator."
        ),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_text() -> str:
    lines = []
    for name in CHECKSUM_FILES:
        path = PACKAGE / name
        if not path.is_file():
            raise ValueError(f"missing checksum target: {path}")
        lines.append(f"{sha256(path)}  {name}")
    return "\n".join(lines) + "\n"


def validate_rows(
    primary: list[dict[str, str]], auxiliary: list[dict[str, str]]
) -> list[str]:
    errors: list[str] = []
    if [row["slot"] for row in primary] != PRIMARY_SLOTS:
        errors.append("primary slots must be T01 through T06 in order")
    if [row["slot"] for row in auxiliary] != AUXILIARY_SLOTS:
        errors.append("auxiliary slots must be AUX-A and AUX-B in order")
    if len(primary) != 6 or len(auxiliary) != 2:
        errors.append("expected exactly six primary and two auxiliary rows")

    result_fields = (
        "core_result",
        "doctor_result",
        "demo_result",
        "bundle_result",
        "regression_result",
    )
    numeric_fields = ("event_count", "incident_count", "elapsed_seconds")
    for row in primary + auxiliary:
        slot = row.get("slot", "<unknown>")
        errors.extend(
            f"{slot}: blank field {field}"
            for field, value in row.items()
            if value is None or value == ""
        )
        for field in result_fields:
            if row[field] not in RESULTS:
                errors.append(f"{slot}: invalid {field}: {row[field]}")
        if row["included_in_primary_cohort"] not in YES_NO:
            errors.append(f"{slot}: invalid cohort flag")
        if row["assistance_before_capture"] not in YES_NO:
            errors.append(f"{slot}: invalid assistance value")
        if row["elapsed_status"] not in ELAPSED:
            errors.append(f"{slot}: invalid elapsed status")
        for field in numeric_fields:
            if row[field] != "NOT_RECORDED" and not row[field].isdigit():
                errors.append(f"{slot}: {field} must be numeric or NOT_RECORDED")
        if not row["compensation_amount"].isdigit():
            errors.append(f"{slot}: compensation must be an integer")
        expected_prefix = "https://github.com/Miko997/metriplane/issues/27#issuecomment-"
        if not row["public_result_url"].startswith(expected_prefix):
            errors.append(f"{slot}: unexpected public result URL")
        if row["metriplane_version"] != "0.3.0":
            errors.append(f"{slot}: unexpected Metriplane version")
        if row["installation_source"] != "PyPI":
            errors.append(f"{slot}: installation source must be PyPI")

    if any(row["included_in_primary_cohort"] != "YES" for row in primary):
        errors.append("all primary rows must be included")
    if any(row["included_in_primary_cohort"] != "NO" for row in auxiliary):
        errors.append("all auxiliary rows must be excluded")

    t02 = next((row for row in primary if row["slot"] == "T02"), None)
    t02_unknown = (
        "event_count",
        "incident_count",
        "bundle_result",
        "regression_result",
        "first_failed_command",
        "first_confusion",
        "assistance_before_capture",
        "elapsed_seconds",
        "elapsed_status",
    )
    if t02 is None:
        errors.append("T02 is missing")
    else:
        errors.extend(
            f"T02: {field} must remain NOT_RECORDED"
            for field in t02_unknown
            if t02[field] != "NOT_RECORDED"
        )
    return errors


def validate_files(
    primary: list[dict[str, str]], auxiliary: list[dict[str, str]]
) -> list[str]:
    errors: list[str] = []
    required = [PACKAGE / name for name in CHECKSUM_FILES] + [CHECKSUMS]
    errors.extend(f"missing required file: {path}" for path in required if not path.is_file())

    report = (PACKAGE / "REPORT.md").read_text(encoding="utf-8")
    claims = (PACKAGE / "CLAIMS.md").read_text(encoding="utf-8")
    required_phrases = (
        "Compensation disclosure",
        "6 of 6 accepted primary records",
        "Assistance coverage",
        "First-confusion coverage",
        "T02 establishes successful installation",
        "AI-assistance use was not separately captured",
        "issue [#60]",
        "pull request [#61]",
        "documentation only",
        "## 10. Limitations",
    )
    errors.extend(
        f"REPORT.md missing required text: {phrase}"
        for phrase in required_phrases
        if phrase not in report
    )
    if "## Prohibited claims" not in claims:
        errors.append("CLAIMS.md missing prohibited claims section")

    prose = "\n".join(
        (PACKAGE / name).read_text(encoding="utf-8")
        for name in ("README.md", "REPORT.md", "CLAIMS.md")
    ).lower()
    unsafe = (
        "metriplane is production ready",
        "metriplane is safety certified",
        "all users can install metriplane successfully",
        "the study proves customer demand",
        "the study proves universal compatibility",
    )
    errors.extend(f"unsafe positive claim found: {claim}" for claim in unsafe if claim in prose)

    text_names = (
        "README.md",
        "REPORT.md",
        "public_results.csv",
        "auxiliary_records.csv",
        "summary.json",
        "CLAIMS.md",
        "SOURCE_MANIFEST.json",
        "BUILD.md",
    )
    public_text = "\n".join(
        (PACKAGE / name).read_text(encoding="utf-8") for name in text_names
    )
    if ("linear" + ".app") in public_text.lower():
        errors.append("internal project-management URL found")
    if re.search(r"\bFO[A-Z0-9]{8,}\b", public_text):
        errors.append("marketplace order identifier found")
    if re.search(r"\bPRIVATE_[A-Z0-9_]+\b", public_text):
        errors.append("private evidence identifier found")

    manifest = read_json(MANIFEST_JSON)
    sources = manifest.get("sources", [])
    claims_data = manifest.get("claims", [])
    if not isinstance(sources, list):
        errors.append("SOURCE_MANIFEST.json sources must be a list")
        sources = []
    if not isinstance(claims_data, list):
        errors.append("SOURCE_MANIFEST.json claims must be a list")
        claims_data = []

    source_ids = {
        source.get("source_id")
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    for source_id in ("FROZEN_PROTOCOL_ARCHIVE", "PRIMARY_COMPENSATION_CROSSWALK"):
        if source_id not in source_ids:
            errors.append(f"SOURCE_MANIFEST.json missing source: {source_id}")

    claim_map = {
        claim.get("claim_id"): set(claim.get("source_ids", []))
        for claim in claims_data
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    expected_claim_sources = {
        "C03": {"PUBLIC_RESULTS_CSV", "PRIMARY_COMPENSATION_CROSSWALK"},
        "C05": {"FROZEN_PROTOCOL_ARCHIVE", "PRIMARY_COMPENSATION_CROSSWALK"},
        "C06": {"FROZEN_PROTOCOL_ARCHIVE"},
    }
    for claim_id, expected in expected_claim_sources.items():
        if claim_map.get(claim_id) != expected:
            errors.append(f"SOURCE_MANIFEST.json incorrect sources for {claim_id}")

    manifest_urls = {
        source["url"]
        for source in sources
        if isinstance(source, dict) and source.get("url")
    }
    errors.extend(
        f"{row['slot']}: public URL missing from source manifest"
        for row in primary + auxiliary
        if row["public_result_url"] not in manifest_urls
    )

    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", readme):
        if "://" not in target and not (PACKAGE / target).is_file():
            errors.append(f"broken README link: {target}")
    pdf = PACKAGE / "commissioned_first_use_report.pdf"
    if pdf.is_file() and pdf.stat().st_size < 5_000:
        errors.append("PDF is unexpectedly small")
    return errors


def validate(write: bool = False) -> list[str]:
    primary = read_csv(PRIMARY_CSV)
    auxiliary = read_csv(AUXILIARY_CSV)
    errors = validate_rows(primary, auxiliary)
    summary = compute_summary(primary, auxiliary)
    if write:
        SUMMARY_JSON.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif read_json(SUMMARY_JSON) != summary:
        errors.append("summary.json does not match canonical CSV data")

    errors.extend(validate_files(primary, auxiliary))
    if not errors:
        expected = checksum_text()
        if write:
            CHECKSUMS.write_text(expected, encoding="utf-8")
        elif not CHECKSUMS.is_file() or CHECKSUMS.read_text(encoding="utf-8") != expected:
            errors.append("SHA256SUMS does not match public artifacts")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the MET-12 report package")
    parser.add_argument("--write", action="store_true")
    errors = validate(write=parser.parse_args().write)
    if errors:
        print("MET-12 validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("MET-12 validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
