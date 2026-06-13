#!/usr/bin/env python3
"""Audit the MetriPlane v0.2.0 release evidence manifest, checksums, and docs."""

from __future__ import annotations

import csv
import hashlib
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
RELEASE_TAG = "v0.2.0"
MANIFEST_PATH = ROOT / "evidence" / "manifest.csv"
CHECKSUMS_PATH = ROOT / "evidence" / "CHECKSUMS.sha256"
CANONICAL_TITLE = (
    "Benchmarking Camera-First Planar Digital Twins: "
    "A Reproducible Protocol and MetriPlane Evaluation"
)
AUTHORITATIVE_WARNING = (
    "For Paper B, the authoritative metric table is "
    "docs/eval/CANONICAL_EVIDENCE.md in release v0.1.3. Other summaries are "
    "non-authoritative convenience summaries."
)
REQUIRED_MANIFEST_COLUMNS = {
    "claim_id",
    "artifact_path",
    "metric_name",
    "metric_value",
    "units",
    "source_command",
    "sha256",
    "release_tag",
    "notes",
}

# The aggregate checksum command intentionally includes evidence/manifest.csv.
# The manifest cannot also pin its own final digest without becoming
# self-referential, so this is the one explicit coverage exemption.
CHECKSUM_MANIFEST_EXEMPTIONS = {"evidence/manifest.csv"}
RELEASE_TREE_PATHS = (".",)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_csv_rows(path: str) -> list[dict[str, str]]:
    with (ROOT / path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(os.readlink(path).encode("utf-8"))
        return digest.hexdigest()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fmt(value: float, places: int) -> str:
    return f"{value:.{places}f}"


def rows_by_stage() -> dict[str, dict[str, str]]:
    return {row["stage"]: row for row in read_csv_rows("evidence/experiments/latency_summary.csv")}


def latency_samples() -> str:
    stages = rows_by_stage()
    counts = {int(stages[name]["count"]) for name in ("detect.cam0", "detect.cam1", "fuse")}
    if len(counts) != 1:
        raise ValueError(f"latency stage counts differ: {sorted(counts)}")
    return str(counts.pop())


def latency_p95(stage: str) -> str:
    return fmt(float(rows_by_stage()[stage]["p95_ms"]), 3)


def non_pacing_p95() -> str:
    total = sum(
        float(row["p95_ms"])
        for row in read_csv_rows("evidence/experiments/latency_summary.csv")
        if row["stage"] != "sleep"
    )
    return fmt(total, 2)


def mapping_mean_error() -> str:
    rows = read_csv_rows("evidence/experiments/mapping_error_001.csv")
    return fmt(sum(float(row["err_cm"]) for row in rows) / len(rows), 2)


def mapping_max_error() -> str:
    rows = read_csv_rows("evidence/experiments/mapping_error_001.csv")
    return fmt(max(float(row["err_cm"]) for row in rows), 2)


def mapping_points() -> str:
    return str(len(read_csv_rows("evidence/experiments/mapping_error_001.csv")))


def static_ids() -> str:
    rows = read_csv_rows("evidence/experiments/id_stability_001.csv")
    return ",".join(str(int(row["object_id"])) for row in sorted(rows, key=lambda item: int(item["object_id"])))


def static_frames() -> str:
    frames = {int(row["total_frames"]) for row in read_csv_rows("evidence/experiments/id_stability_001.csv")}
    if len(frames) != 1:
        raise ValueError(f"static total frame counts differ: {sorted(frames)}")
    return str(frames.pop())


def static_coverage() -> str:
    rows = read_csv_rows("evidence/experiments/id_stability_001.csv")
    return fmt(min(float(row["coverage_pct"]) for row in rows), 1)


def movement_frames() -> str:
    frames = {int(row["total_frames"]) for row in read_csv_rows("evidence/experiments/id_stability_movement_001.csv")}
    if len(frames) != 1:
        raise ValueError(f"movement total frame counts differ: {sorted(frames)}")
    return str(frames.pop())


def movement_coverage_range() -> str:
    coverages = [float(row["coverage_pct"]) for row in read_csv_rows("evidence/experiments/id_stability_movement_001.csv")]
    return f"{fmt(min(coverages), 2)}-{fmt(max(coverages), 2)}"


def movement_max_gap() -> str:
    rows = read_csv_rows("evidence/experiments/id_stability_movement_001.csv")
    return str(max(int(row["max_missing_gap_frames"]) for row in rows))


def replay_value(column: str) -> str:
    rows = read_csv_rows("evidence/experiments/replay_determinism.csv")
    if len(rows) != 1:
        raise ValueError("replay_determinism.csv must have one data row")
    return rows[0][column]


def backpressure_value(column: str) -> str:
    rows = read_csv_rows("evidence/experiments/backpressure_summary.csv")
    if len(rows) != 1:
        raise ValueError("backpressure_summary.csv must have one data row")
    return rows[0][column]


def fusion_jitter_range_mm() -> str:
    jitters = [
        float(row["jitter_std_m"]) * 1000.0
        for row in read_csv_rows("evidence/experiments/fusion_jitter_001.csv")
    ]
    return f"{fmt(min(jitters), 3)}-{fmt(max(jitters), 3)}"


def compute_value(column: str) -> str:
    rows = read_csv_rows("evidence/experiments/compute_equivalence_001.csv")
    if len(rows) != 1:
        raise ValueError("compute_equivalence_001.csv must have one data row")
    return rows[0][column]


def zone_count() -> str:
    return str(len(read_csv_rows("evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv")))


def zone_dwell_total() -> str:
    rows = read_csv_rows("evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv")
    return fmt(sum(float(row["dwell_s"]) for row in rows), 2)


def zone_transitions() -> str:
    rows = read_csv_rows("evidence/experiments/case_study_1_movement_zone_transitions.csv")
    return str(sum(int(row["count"]) for row in rows))


def gpu_relation() -> str:
    rows = read_csv_rows("evidence/experiments/gpu_benchmark_001.csv")
    by_n: dict[int, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_n[int(row["n_objects"])][row["backend"]] = row

    expected_n = {1, 10, 50, 200, 1000}
    if set(by_n) != expected_n:
        raise ValueError(f"unexpected GPU benchmark N set: {sorted(by_n)}")
    for n_objects, paired in by_n.items():
        cpu = paired.get("cpu")
        gpu = paired.get("gpu")
        if cpu is None or gpu is None:
            raise ValueError(f"missing CPU/GPU pair for N={n_objects}")
        if float(gpu["p50_ms"]) <= float(cpu["p50_ms"]):
            raise ValueError(f"GPU p50 is not slower than CPU for N={n_objects}")
        if float(gpu["p95_ms"]) <= float(cpu["p95_ms"]):
            raise ValueError(f"GPU p95 is not slower than CPU for N={n_objects}")
    if compute_value("pass").lower() != "true":
        raise ValueError("CPU/GPU equivalence artifact is not passing")
    return "gpu_correct_slower_for_tested_n_1_1000_fusion_compute_only"


METRIC_SPECS: dict[str, tuple[str, Callable[[], str]]] = {
    "timing_samples": ("evidence/experiments/latency_summary.csv", latency_samples),
    "detect.cam0_p95_ms": ("evidence/experiments/latency_summary.csv", lambda: latency_p95("detect.cam0")),
    "detect.cam1_p95_ms": ("evidence/experiments/latency_summary.csv", lambda: latency_p95("detect.cam1")),
    "fuse_p95_ms": ("evidence/experiments/latency_summary.csv", lambda: latency_p95("fuse")),
    "summed_non_pacing_p95_ms": ("evidence/experiments/latency_summary.csv", non_pacing_p95),
    "mapping_mean_error_cm": ("evidence/experiments/mapping_error_001.csv", mapping_mean_error),
    "mapping_max_error_cm": ("evidence/experiments/mapping_error_001.csv", mapping_max_error),
    "mapping_points": ("evidence/experiments/mapping_error_001.csv", mapping_points),
    "static_continuity_ids": ("evidence/experiments/id_stability_001.csv", static_ids),
    "static_continuity_coverage_pct": ("evidence/experiments/id_stability_001.csv", static_coverage),
    "static_continuity_frames": ("evidence/experiments/id_stability_001.csv", static_frames),
    "movement_frames": ("evidence/experiments/id_stability_movement_001.csv", movement_frames),
    "movement_coverage_range_pct": ("evidence/experiments/id_stability_movement_001.csv", movement_coverage_range),
    "movement_max_gap_frames": ("evidence/experiments/id_stability_movement_001.csv", movement_max_gap),
    "replay_frames": ("evidence/experiments/replay_determinism.csv", lambda: replay_value("frames_compared")),
    "replay_object_pairs": ("evidence/experiments/replay_determinism.csv", lambda: replay_value("object_pairs_compared")),
    "replay_max_diff_cm": ("evidence/experiments/replay_determinism.csv", lambda: replay_value("max_pos_diff_cm")),
    "replay_event_mismatches": ("evidence/experiments/replay_determinism.csv", lambda: replay_value("event_mismatch_count")),
    "backpressure_published": ("evidence/experiments/backpressure_summary.csv", lambda: backpressure_value("published")),
    "backpressure_dropped": ("evidence/experiments/backpressure_summary.csv", lambda: backpressure_value("drops_total")),
    "queue_depth": ("evidence/experiments/backpressure_summary.csv", lambda: backpressure_value("max_queue_depth")),
    "fusion_jitter_range_mm": ("evidence/experiments/fusion_jitter_001.csv", fusion_jitter_range_mm),
    "cpu_gpu_equivalence_samples": ("evidence/experiments/compute_equivalence_001.csv", lambda: compute_value("samples")),
    "cpu_gpu_rmse_diff_cm": ("evidence/experiments/compute_equivalence_001.csv", lambda: compute_value("rmse_diff_cm")),
    "cpu_gpu_max_diff_cm": ("evidence/experiments/compute_equivalence_001.csv", lambda: compute_value("max_abs_diff_cm")),
    "zone_count": ("evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv", zone_count),
    "zone_dwell_object_seconds": ("evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv", zone_dwell_total),
    "zone_transitions": ("evidence/experiments/case_study_1_movement_zone_transitions.csv", zone_transitions),
    "cpu_gpu_benchmark_scope": ("evidence/experiments/gpu_benchmark_001.csv", gpu_relation),
}


STALE_VALUE_PATTERNS = {
    "old_replay_frame_count": re.compile(r"(?<![\d.])" + "3" + "01" + r"(?![\d.])"),
    "old_timing_frame_count": re.compile(r"(?<![\d.])" + "4" + r",?" + "384" + r"(?![\d.])"),
    "old_movement_frame_count": re.compile(r"(?<![\d.])" + "87" + r",?" + "608" + r"(?![\d.])"),
    "old_detect_cam0_p95": re.compile(r"(?<![\d.])" + "1" + r"\." + "50" + r"(?![\d.])"),
    "old_detect_cam1_p95": re.compile(r"(?<![\d.])" + "1" + r"\." + "72" + r"(?![\d.])"),
    "old_fusion_jitter": re.compile(r"(?<![\d.])" + "0" + r"\." + "23" + r"\s*mm(?![\d.])"),
    "old_backpressure_drops": re.compile(r"(?<![\d.])" + "2" + r",?" + "600" + r"(?![\d.])"),
    "old_motion_coverage": re.compile(r"(?<![\d.])" + "97" + r"\." + "4" + r"(?![\d.])"),
    "old_zone_transitions": re.compile(r"\b" + "77" + r" transitions\b", re.IGNORECASE),
    "old_zone_count": re.compile(r"\bzone_count=" + "2" + r"\b"),
}
OLD_TITLE = (
    "Benchmarking Camera-First Planar Digital Twins: "
    "A Reproducible "
    "Evaluation of MetriPlane"
)
FORBIDDEN_CLAIMS = (
    "is a peer-reviewed publication",
    "has been peer-reviewed",
    "accepted paper at",
    "accepted for publication",
    "DOI-archived artifact",
    "ACM-badged artifact",
)


def read_manifest(errors: list[str]) -> list[dict[str, str]]:
    if not MANIFEST_PATH.exists():
        errors.append("missing evidence/manifest.csv")
        return []
    with MANIFEST_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            errors.append("manifest has no header row")
            return []
        missing = REQUIRED_MANIFEST_COLUMNS - set(reader.fieldnames)
        if missing:
            errors.append(f"manifest missing required columns: {sorted(missing)}")
            return []
        return list(reader)


def read_checksums(errors: list[str]) -> dict[str, str]:
    if not CHECKSUMS_PATH.exists():
        errors.append("missing evidence/CHECKSUMS.sha256")
        return {}
    checksums: dict[str, str] = {}
    for line_number, line in enumerate(CHECKSUMS_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            errors.append(f"bad checksum line {line_number}: {line!r}")
            continue
        digest, path = parts
        path = path.lstrip("*")
        checksums[path] = digest
    return checksums


def release_tree_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "-z", *RELEASE_TREE_PATHS],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return {
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
        and not path.decode("utf-8").endswith("/CHECKSUMS.sha256")
        and not (ROOT / path.decode("utf-8")).is_symlink()
    }


def audit_manifest_and_checksums(
    manifest_rows: list[dict[str, str]],
    checksum_rows: dict[str, str],
    errors: list[str],
) -> tuple[int, int]:
    manifest_paths = {row["artifact_path"] for row in manifest_rows}
    tree_paths = release_tree_paths()

    for path in sorted(tree_paths - set(checksum_rows)):
        errors.append(f"release tree file missing from CHECKSUMS.sha256: {path}")

    for path in sorted(set(checksum_rows) - tree_paths):
        errors.append(f"CHECKSUMS.sha256 contains path outside release tree: {path}")

    for path in sorted(set(checksum_rows) - manifest_paths - CHECKSUM_MANIFEST_EXEMPTIONS):
        errors.append(f"checksum path missing from manifest: {path}")

    sha_checks = 0
    for row_index, row in enumerate(manifest_rows, start=2):
        artifact_path = row["artifact_path"]
        path = ROOT / artifact_path
        if not artifact_path:
            errors.append(f"manifest row {row_index} has empty artifact_path")
            continue
        if not path.exists():
            errors.append(f"manifest artifact does not exist: {artifact_path}")
            continue
        if row["release_tag"] != RELEASE_TAG:
            errors.append(f"{artifact_path}: release_tag is {row['release_tag']!r}, expected {RELEASE_TAG!r}")

        actual = sha256_file(path)
        if row["sha256"] != actual:
            errors.append(f"{artifact_path}: manifest SHA256 differs from actual file hash")
        if artifact_path in checksum_rows and row["sha256"] != checksum_rows[artifact_path]:
            errors.append(f"{artifact_path}: manifest SHA256 differs from CHECKSUMS.sha256")
        elif artifact_path not in checksum_rows:
            errors.append(f"{artifact_path}: manifest path missing from CHECKSUMS.sha256")
        sha_checks += 1

    metric_checks = 0
    for row in manifest_rows:
        metric_name = row["metric_name"]
        if metric_name not in METRIC_SPECS:
            continue
        expected_artifact, actual_func = METRIC_SPECS[metric_name]
        if row["artifact_path"] != expected_artifact:
            errors.append(
                f"{metric_name}: artifact_path is {row['artifact_path']!r}, "
                f"expected {expected_artifact!r}"
            )
        try:
            actual_value = actual_func()
        except Exception as exc:  # pragma: no cover - defensive audit reporting
            errors.append(f"{metric_name}: could not compute actual CSV value: {exc}")
            continue
        if row["metric_value"] != actual_value:
            errors.append(
                f"{metric_name}: manifest metric_value {row['metric_value']!r} "
                f"differs from actual CSV value {actual_value!r}"
            )
        metric_checks += 1

    return sha_checks, metric_checks


def text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def audit_docs(errors: list[str]) -> int:
    docs_to_scan = [ROOT / "README.md", ROOT / "ARTIFACTS.md"]
    docs_to_scan.extend(sorted((ROOT / "docs" / "eval").glob("*.md")))
    docs_to_scan.append(ROOT / "docs" / "references" / "reference_audit.md")
    docs_to_scan.extend(
        ROOT / path
        for path in (
            "docs/scope_rules.md",
            "docs/gpu_compute_backend.md",
            "docs/pipeline_backpressure.md",
        )
    )
    if (ROOT / "CITATION.cff").exists():
        docs_to_scan.append(ROOT / "CITATION.cff")

    checked = 0
    for path in docs_to_scan:
        text = text_file(path)
        if text is None:
            continue
        checked += 1
        for label, pattern in STALE_VALUE_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{rel(path)} contains stale Paper B value pattern: {label}")
        if OLD_TITLE in text:
            errors.append(f"{rel(path)} contains old paper title")
        for phrase in FORBIDDEN_CLAIMS:
            if phrase in text:
                errors.append(f"{rel(path)} contains forbidden claim phrase: {phrase}")

    for required_path in (ROOT / "README.md", ROOT / "docs" / "eval" / "evidence_index.md"):
        text = required_path.read_text(encoding="utf-8")
        if AUTHORITATIVE_WARNING not in text:
            errors.append(f"{rel(required_path)} is missing the authoritative metric-table warning")

    canonical = (ROOT / "docs" / "eval" / "CANONICAL_EVIDENCE.md").read_text(encoding="utf-8")
    if CANONICAL_TITLE not in canonical:
        errors.append("CANONICAL_EVIDENCE.md is missing the canonical paper title")

    citation = ROOT / "CITATION.cff"
    if citation.exists():
        citation_text = citation.read_text(encoding="utf-8")
        empty_doi = re.search(r"(?m)^doi:\s*(?:\"\"\s*)?$", citation_text)
        if empty_doi:
            errors.append("CITATION.cff has an empty doi field; omit doi until a real DOI exists")

    return checked


def main() -> int:
    errors: list[str] = []
    manifest_rows = read_manifest(errors)
    checksum_rows = read_checksums(errors)

    sha_checks, metric_checks = audit_manifest_and_checksums(manifest_rows, checksum_rows, errors)
    docs_checked = audit_docs(errors)

    if errors:
        print("audit_evidence: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("audit_evidence: PASS")
    print(f"manifest rows: {len(manifest_rows)}")
    print(f"checksum entries: {len(checksum_rows)}")
    print(f"manifest sha checks: {sha_checks}")
    print(f"csv metric checks: {metric_checks}")
    print(f"paper-facing docs checked: {docs_checked}")
    print("stale paper-facing values: none")
    print("checksum manifest exemptions: evidence/manifest.csv (self-referential)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
