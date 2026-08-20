# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Self-validate and deterministically rebuild this publication package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any, cast

PACKAGE_ROOT = Path(__file__).resolve().parent
INVENTORY_NAME = "SHA256SUMS"
ARCHIVE_PREFIX = "metriplane-external-source-family-matrix-v1"
ALLOWED_DECISIONS = [
    "GO",
    "PARTIALLY SUPPORTED",
    "NO-GO",
    "NOT TESTED",
    "NOT APPLICABLE",
]
EXPECTED_ROWS = {
    "maniskill": ("ManiSkill", "GO", True),
    "calvin": ("CALVIN", "NO-GO", False),
    "robomimic": ("robomimic", "GO", True),
    "mimicgen": ("MimicGen", "PARTIALLY SUPPORTED", False),
    "robocasa": ("RoboCasa / RoboCasa365", "NOT TESTED", False),
    "ros2_mcap_tf2": ("ROS 2 / MCAP + TF2", "NOT TESTED", False),
    "massrobotics_amr_offline_replay": (
        "MassRobotics AMR offline replay",
        "PARTIALLY SUPPORTED",
        False,
    ),
}
EXPECTED_BASELINE = "5606b956e9309802570cfa46857714722fd70187"
EXPECTED_CONTRACT = "b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4"
EXPECTED_CLAIM = (
    "Metriplane's frozen external-source process has produced two successful, "
    "source-specific portable evaluation paths: ManiSkill and robomimic. It also "
    "produced one documented CALVIN rejection because public rights and "
    "authoritative timing did not satisfy the contract."
)
EXPECTED_FIXTURES = {
    "maniskill": (
        "maniskill-pickcube-episode-0-planar-incident-v1",
        "maniskill-pickcube-episode-0-planar-control-v1",
        "7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df",
        "954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2",
        "8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e",
    ),
    "robomimic": (
        "robomimic-can-ph-demo-0-planar-incident-v1",
        "robomimic-can-ph-demo-0-planar-control-v1",
        "bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246",
        "6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6",
        "dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf",
    ),
}
REQUIRED_FILES = {
    "CITATION.cff",
    "EVALUATOR.md",
    "MATRIX.md",
    "PARTNER-SUMMARY.md",
    "PROVENANCE-CROSSWALK.md",
    "READINESS.md",
    "README.md",
    "REOPENING.md",
    "SEMANTICS.md",
    "SOURCE-CROSSWALK.md",
    "STATE-MODEL-CROSSWALK.md",
    "UNSUPPORTED-PATHS.md",
    "VALIDATION.md",
    "evaluator-report-template.md",
    "matrix.json",
    "matrix.schema.json",
    "validate.py",
}
CELL_NAMES = (
    "exact_source_artifact_identity",
    "raw_prepared_derived_normalized_boundary",
    "authoritative_clock_and_domain",
    "frame_authority_and_transform_model",
    "units",
    "stable_identity_model",
    "complete_snapshot_and_missing_state_policy",
    "materialization_or_carry_forward_policy",
    "field_provenance",
    "information_loss",
    "external_source_contract_v1_fit",
    "supported_atlas_semantics",
    "prohibited_semantics",
    "deterministic_conversion_status",
    "portable_evaluation_status",
    "atlas_rerun_status",
    "evidence_bundle_status",
    "regression_status",
    "independent_rerun_status",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PRIVATE_PATH_RE = re.compile(
    rb"/(?:"
    + b"home"
    + rb"|"
    + b"Users"
    + rb"|"
    + b"workspace"
    + rb")/[^\x00\r\n\"'<> ]+"
    + rb"|/private/"
    + b"tmp"
    + rb"/[^\x00\r\n\"'<> ]+"
    + rb"|(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/][^\x00\r\n\"'<> ]+"
)


class PackageError(RuntimeError):
    """Raised when the extracted publication is not self-consistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PackageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    _require(isinstance(value, dict), f"expected JSON object: {path.name}")
    return cast(dict[str, Any], value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_validate(schema: Mapping[str, Any], matrix: Mapping[str, Any], required: bool) -> str:
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
    except ImportError as exc:
        if required:
            raise PackageError("jsonschema is required; install jsonschema==4.25.1") from exc
        return "not-requested"
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(matrix)
    return "valid"


def _evidence_ids(row: Mapping[str, Any]) -> Iterable[str]:
    for name in CELL_NAMES:
        yield from row[name]["evidence"]
    for name in ("code", "dataset", "derived_fixture"):
        yield from row["rights"][name]["evidence"]
    yield from row["frozen_fixture_identities"]["evidence"]


def _validate_matrix(matrix: Mapping[str, Any]) -> None:
    publication = matrix["publication"]
    _require(publication["starting_commit"] == EXPECTED_BASELINE, "starting commit changed")
    _require(publication["public_main_baseline"] == EXPECTED_BASELINE, "baseline changed")
    _require(publication["metriplane_version"] == "0.3.0", "Metriplane version changed")
    _require(publication["strongest_allowed_claim"] == EXPECTED_CLAIM, "claim boundary changed")
    _require(matrix["allowed_decisions"] == ALLOWED_DECISIONS, "decision vocabulary changed")
    _require(matrix["contract"]["schema_sha256"] == EXPECTED_CONTRACT, "contract changed")
    rows = matrix["rows"]
    row_map = {row["row_id"]: row for row in rows}
    _require(len(row_map) == len(rows), "duplicate row ID")
    _require(set(row_map) == set(EXPECTED_ROWS), "row set changed")
    for row_id, expected in EXPECTED_ROWS.items():
        row = row_map[row_id]
        actual = (row["source_family"], row["decision"], row["compatibility_counted"])
        _require(actual == expected, f"decision tuple changed: {row_id}")
        artifacts = row["supporting_artifacts"]
        artifact_ids = [artifact["id"] for artifact in artifacts]
        _require(len(artifact_ids) == len(set(artifact_ids)), f"duplicate evidence ID: {row_id}")
        _require(
            not (set(_evidence_ids(row)) - set(artifact_ids)), f"unresolved evidence: {row_id}"
        )
        for artifact in artifacts:
            if artifact["kind"] == "repository_path":
                _require("path" in artifact and "sha256" in artifact, "incomplete path evidence")
    _require(sum(bool(row["compatibility_counted"]) for row in rows) == 2, "proven count changed")
    massrobotics = row_map["massrobotics_amr_offline_replay"]
    _require(
        massrobotics["status_label"] == "OWNER-GENERATED FORMAT MAPPING / NOT EXTERNAL VALIDATION",
        "MassRobotics label changed",
    )
    _require(
        massrobotics["independent_rerun_status"]["status"] == "NOT TESTED",
        "MassRobotics independent-rerun boundary changed",
    )
    _require(
        massrobotics["frozen_fixture_identities"]["status"] == "PARTIAL",
        "MassRobotics fixture identity boundary changed",
    )
    _require(
        massrobotics["frozen_fixture_identities"]["shared_session_sha256"] is None,
        "distinct MassRobotics sessions were represented as shared",
    )
    massrobotics_text = json.dumps(massrobotics, sort_keys=True)
    for boundary in (
        "synthetic_format_engineering",
        "reference_only",
        "no general MassRobotics compatibility",
        "no conformance",
    ):
        _require(boundary in massrobotics_text, f"MassRobotics boundary missing: {boundary}")
    massrobotics_artifacts = {
        artifact["id"]: artifact for artifact in massrobotics["supporting_artifacts"]
    }
    for reference_id in ("massrobotics-release", "massrobotics-snapshot"):
        _require(
            massrobotics_artifacts[reference_id]["kind"] == "external_artifact",
            f"upstream reference was reclassified: {reference_id}",
        )
    forbidden_upstream_names = {
        "AMR_Interop_Standard.json",
        "AMR_Interop_Standard.pdf",
        "identityReport1.json",
        "statusReport1.json",
    }
    repository_names = {
        PurePosixPath(artifact["path"]).name
        for artifact in massrobotics["supporting_artifacts"]
        if artifact["kind"] == "repository_path"
    }
    _require(
        repository_names.isdisjoint(forbidden_upstream_names),
        "upstream MassRobotics artifact appears as repository evidence",
    )
    for row_id, expected_fixture in EXPECTED_FIXTURES.items():
        identity = row_map[row_id]["frozen_fixture_identities"]
        actual_fixture = (
            identity["incident_fixture_id"],
            identity["control_fixture_id"],
            identity["shared_session_sha256"],
            identity["incident_fingerprint_sha256"],
            identity["control_fingerprint_sha256"],
        )
        _require(
            identity["status"] == "VERIFIED" and actual_fixture == expected_fixture,
            f"fixture changed: {row_id}",
        )


def _package_files() -> set[str]:
    return {
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file() and path.name != INVENTORY_NAME
    }


def _validate_inventory() -> int:
    inventory = PACKAGE_ROOT / INVENTORY_NAME
    _require(inventory.is_file(), "SHA256SUMS is missing")
    entries: dict[str, str] = {}
    for number, line in enumerate(inventory.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise PackageError(f"malformed SHA256SUMS line {number}") from exc
        path = PurePosixPath(relative)
        _require(SHA256_RE.fullmatch(digest) is not None, f"invalid digest: line {number}")
        _require(not path.is_absolute() and ".." not in path.parts, f"unsafe path: {relative}")
        _require(relative not in entries, f"duplicate inventory path: {relative}")
        entries[relative] = digest
    actual = _package_files()
    _require(REQUIRED_FILES <= actual, "required package file is missing")
    _require(set(entries) == actual, "SHA256SUMS is not a complete exact inventory")
    for relative, expected in entries.items():
        _require(_sha256(PACKAGE_ROOT / relative) == expected, f"hash mismatch: {relative}")
    return len(entries)


def _scan() -> int:
    count = 0
    for path in sorted(item for item in PACKAGE_ROOT.rglob("*") if item.is_file()):
        _require(
            PRIVATE_PATH_RE.search(path.read_bytes()) is None, f"machine-local path: {path.name}"
        )
        count += 1
    return count


def _archive(out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(item for item in PACKAGE_ROOT.rglob("*") if item.is_file()):
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            info = zipfile.ZipInfo(
                f"{ARCHIVE_PREFIX}/{relative}",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            archive.writestr(info, path.read_bytes())
    return _sha256(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--require-jsonschema", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.out is not None and arguments.validate_only:
        raise PackageError("--out and --validate-only are mutually exclusive")
    schema = _read_json(PACKAGE_ROOT / "matrix.schema.json")
    matrix = _read_json(PACKAGE_ROOT / "matrix.json")
    schema_status = _schema_validate(schema, matrix, arguments.require_jsonschema)
    _validate_matrix(matrix)
    result: dict[str, object] = {
        "decision_count": 7,
        "inventory_count": _validate_inventory(),
        "json_schema": schema_status,
        "package_scan_file_count": _scan(),
        "pass": True,
        "proven_path_count": 2,
    }
    if arguments.out is not None:
        result["archive_sha256"] = _archive(arguments.out.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
