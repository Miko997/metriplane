# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from metriplane_source_adapter_sdk import (
    canonical_json_bytes,
    capability_fingerprint,
    validate_capability,
)

from .constants import (
    DEFAULT_CONFIG,
    DEFAULT_SOURCE_ROOT,
    PROFILE_ID,
    SOURCE_CLASSIFICATION,
    SOURCE_DESCRIPTION,
    UPSTREAM_RAW_SHA256,
)
from .core import AdapterError, convert, find_path_leaks, publish_candidate, verify_adapter_commit
from .reporting import pretty_json_bytes, sha256_bytes


class FinalizationError(RuntimeError):
    """Raised when three-run conversion equivalence is not established."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"equivalence: invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FinalizationError(f"equivalence: JSON root must be an object: {path}")
    return value


def _read_inventory(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise FinalizationError(f"equivalence: regular conversion directory required: {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise FinalizationError(f"equivalence: symlink prohibited: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise FinalizationError(f"equivalence: non-file entry prohibited: {path}")
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _conversion_inventory(root: Path) -> dict[str, bytes]:
    files = _read_inventory(root)
    required = {
        "SHA256SUMS",
        "capability-record.json",
        "conversion-summary.json",
        "coordinate-binding.json",
        "fixture/CHECKSUMS.sha256",
        "fixture/domain-pack/assets.yaml",
        "fixture/domain-pack/contracts.yaml",
        "fixture/domain-pack/process.yaml",
        "fixture/domain-pack/work_orders.csv",
        "fixture/domain-pack/workspace.yaml",
        "fixture/entity-mapping.json",
        "fixture/expected-outcome.json",
        "fixture/normalization-report.json",
        "fixture/session.jsonl",
        "fixture/source/adapter-environment.txt",
        "fixture/source/frozen-config.json",
        "fixture/source/identity.jsonl",
        "fixture/source/status.jsonl",
        "fixture/source/uv.lock",
        "fixture/source-manifest.json",
        "rights-record.json",
        "source-reference-register.json",
    }
    missing = sorted(required - set(files))
    unexpected = sorted(set(files) - required)
    if missing or unexpected:
        raise FinalizationError(
            "equivalence: conversion inventory differs from the exact profile; "
            f"missing={missing}; unexpected={unexpected}"
        )
    return files


def _frozen_conversion_inventories(adapter_commit: str) -> dict[str, dict[str, bytes]]:
    expected: dict[str, dict[str, bytes]] = {}
    with tempfile.TemporaryDirectory(prefix="metriplane-massrobotics-expected-") as temporary:
        private_root = Path(temporary)
        for variant in ("incident", "control"):
            output = private_root / variant
            try:
                convert(
                    DEFAULT_SOURCE_ROOT / variant,
                    config_path=DEFAULT_CONFIG,
                    output_root=output,
                    adapter_commit=adapter_commit,
                )
            except AdapterError as exc:
                raise FinalizationError(
                    f"equivalence: cannot reconstruct exact frozen {variant} conversion: {exc}"
                ) from exc
            expected[variant] = _conversion_inventory(output)
    return expected


def _verify_inventory_file(
    files: dict[str, bytes], *, inventory_path: str, prefix: str = ""
) -> None:
    try:
        lines = files[inventory_path].decode("ascii").splitlines()
    except (KeyError, UnicodeDecodeError) as exc:
        raise FinalizationError(
            f"equivalence: invalid checksum inventory {inventory_path}"
        ) from exc
    recorded: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise FinalizationError(f"equivalence: malformed checksum line in {inventory_path}")
        digest, relative = match.groups()
        if relative.startswith(("/", "../")) or "\\" in relative or relative in recorded:
            raise FinalizationError(f"equivalence: unsafe checksum path {relative}")
        recorded[relative] = digest
    expected = {
        path[len(prefix) :] for path in files if path.startswith(prefix) and path != inventory_path
    }
    if set(recorded) != expected:
        raise FinalizationError(f"equivalence: checksum inventory incomplete: {inventory_path}")
    for relative, digest in recorded.items():
        if sha256_bytes(files[f"{prefix}{relative}"]) != digest:
            raise FinalizationError(f"equivalence: checksum mismatch: {relative}")


def _tree_digest(files: dict[str, bytes]) -> str:
    return hashlib.sha256(
        canonical_json_bytes({path: sha256_bytes(data) for path, data in files.items()})
    ).hexdigest()


def _write_checksums(root: Path, *, name: str) -> None:
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != name
    }
    (root / name).write_text(
        "".join(f"{sha256_bytes(files[path])}  {path}\n" for path in sorted(files)),
        encoding="ascii",
    )


def _finalize_variant(
    source: Path,
    destination: Path,
    *,
    variant_runs: list[tuple[str, dict[str, bytes]]],
) -> None:
    shutil.copytree(source / "fixture", destination)
    mapping_sha = sha256_bytes((destination / "entity-mapping.json").read_bytes())
    session_sha = sha256_bytes((destination / "session.jsonl").read_bytes())
    report_path = destination / "normalization-report.json"
    report = _load_json(report_path)
    report["conversion_reproducibility"].update(
        {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": True,
            "runs": [
                {
                    "artifacts": {
                        "entity-mapping.json": mapping_sha,
                        "session.jsonl": session_sha,
                    },
                    "run_id": run_id,
                }
                for run_id, _files in variant_runs
            ],
            "status": "demonstrated",
        }
    )
    report_path.write_bytes(pretty_json_bytes(report))
    manifest_path = destination / "source-manifest.json"
    manifest = _load_json(manifest_path)
    manifest["normalized_artifacts"]["normalization_report"]["sha256"] = sha256_bytes(
        report_path.read_bytes()
    )
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _write_checksums(destination, name="CHECKSUMS.sha256")


def finalize_conversion_equivalence(
    conversion_roots: list[str | Path],
    *,
    output_root: str | Path,
    run_ids: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    if len(conversion_roots) != 6:
        raise FinalizationError("equivalence: exactly six roots are required (three per variant)")
    roots = [Path(item).resolve() for item in conversion_roots]
    if len(set(roots)) != 6:
        raise FinalizationError("equivalence: conversion roots must be distinct")
    if run_ids is None:
        run_ids = [f"clean-conversion-{index}" for index in range(1, 7)]
    if len(run_ids) != 6 or len(set(run_ids)) != 6:
        raise FinalizationError("equivalence: exactly six distinct run IDs are required")
    if any(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", item) is None for item in run_ids):
        raise FinalizationError("equivalence: unsafe run ID")
    inventories = [_conversion_inventory(root) for root in roots]
    for files in inventories:
        _verify_inventory_file(files, inventory_path="SHA256SUMS")
        _verify_inventory_file(
            files,
            inventory_path="fixture/CHECKSUMS.sha256",
            prefix="fixture/",
        )
    grouped: dict[str, list[tuple[Path, str, dict[str, bytes], dict[str, Any]]]] = {
        "incident": [],
        "control": [],
    }
    commits: set[str] = set()
    for root, run_id, files in zip(roots, run_ids, inventories, strict=True):
        summary = json.loads(files["conversion-summary.json"])
        if not isinstance(summary, dict):
            raise FinalizationError("equivalence: conversion summary must be an object")
        variant = summary.get("variant")
        if variant not in grouped:
            raise FinalizationError("equivalence: unknown conversion variant")
        if summary.get("profile") != PROFILE_ID:
            raise FinalizationError("equivalence: profile identity differs")
        commit = summary.get("adapter_commit")
        if not isinstance(commit, str):
            raise FinalizationError("equivalence: adapter commit must be a string")
        try:
            commits.add(verify_adapter_commit(commit))
        except AdapterError as exc:
            raise FinalizationError(str(exc)) from exc
        grouped[variant].append((root, run_id, files, summary))
    if any(len(values) != 3 for values in grouped.values()):
        raise FinalizationError("equivalence: exactly three conversions per variant are required")
    if len(commits) != 1:
        raise FinalizationError("equivalence: all conversions must share one adapter commit")
    adapter_commit = next(iter(commits))
    frozen_inventories = _frozen_conversion_inventories(adapter_commit)
    for variant, values in grouped.items():
        reference = values[0][2]
        if any(item[2] != reference for item in values[1:]):
            raise FinalizationError(
                f"equivalence: three {variant} conversions are not byte-identical"
            )
        if reference != frozen_inventories[variant]:
            raise FinalizationError(
                f"equivalence: {variant} conversion differs from exact frozen adapter output"
            )
        if any(
            item[3].get("conversion_reproducibility", {}).get("status") != "not_demonstrated"
            for item in values
        ):
            raise FinalizationError("equivalence: supplied roots are not clean converter outputs")
    output = Path(os.path.abspath(output_root))
    if output.exists() or output.is_symlink():
        suffix = " even with --overwrite" if overwrite else ""
        raise FinalizationError(f"equivalence: output collision{suffix}; replacement is prohibited")
    for root in roots:
        if output == root or output in root.parents or root in output.parents:
            raise FinalizationError("equivalence: source/output path overlap is prohibited")
    candidate: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        candidate = Path(tempfile.mkdtemp(prefix=f".{output.name}.candidate-", dir=output.parent))
        for variant in ("incident", "control"):
            values = grouped[variant]
            _finalize_variant(
                values[0][0],
                candidate / variant,
                variant_runs=[(item[1], item[2]) for item in values],
            )
            capability = json.loads(values[0][2]["capability-record.json"])
            deterministic = capability["capabilities"]["deterministic_conversion"]
            deterministic.update(
                {
                    "clean_run_count": 3,
                    "compared_output_count": 3,
                    "comparison_policy": "byte_identity",
                    "equivalent": True,
                    "status": "verified",
                }
            )
            validate_capability(capability)
            (candidate / f"{variant}-capability-record.json").write_bytes(
                pretty_json_bytes(capability)
            )
        reference_files = grouped["incident"][0][2]
        for name in (
            "coordinate-binding.json",
            "rights-record.json",
            "source-reference-register.json",
        ):
            if reference_files[name] != grouped["control"][0][2][name]:
                raise FinalizationError(f"equivalence: shared record differs by variant: {name}")
            (candidate / name).write_bytes(reference_files[name])
        incident_summary = grouped["incident"][0][3]
        summary = {
            "adapter_commit": adapter_commit,
            "config_sha256": incident_summary["config_sha256"],
            "control": {
                "capability_fingerprint_sha256": capability_fingerprint(
                    _load_json(candidate / "control-capability-record.json")
                ),
                "fixture_fingerprint_sha256": sha256_bytes(
                    (candidate / "control" / "CHECKSUMS.sha256").read_bytes()
                ),
                "fixture_id": "massrobotics_amr_synthetic_control_v1",
                "run_ids": [item[1] for item in grouped["control"]],
            },
            "conversion_reproducibility": {
                "comparison_policy": "sha256_byte_identity",
                "equivalent": True,
                "status": "demonstrated",
                "variant_tree_sha256": {
                    variant: _tree_digest(values[0][2]) for variant, values in grouped.items()
                },
            },
            "incident": {
                "capability_fingerprint_sha256": capability_fingerprint(
                    _load_json(candidate / "incident-capability-record.json")
                ),
                "fixture_fingerprint_sha256": sha256_bytes(
                    (candidate / "incident" / "CHECKSUMS.sha256").read_bytes()
                ),
                "fixture_id": "massrobotics_amr_synthetic_incident_v1",
                "run_ids": [item[1] for item in grouped["incident"]],
            },
            "profile": PROFILE_ID,
            "schema_version": "org.metriplane.massrobotics_amr.equivalence.v1",
            "source_classification": SOURCE_CLASSIFICATION,
            "source_description": SOURCE_DESCRIPTION,
        }
        (candidate / "conversion-summary.json").write_bytes(pretty_json_bytes(summary))
        _write_checksums(candidate, name="SHA256SUMS")
        expected = _read_inventory(candidate)
        leaks = find_path_leaks(expected, extra_roots=(*roots, candidate))
        if leaks:
            raise FinalizationError(
                f"equivalence: final output contains machine-local paths: {leaks}"
            )
        upstream_digests = set(UPSTREAM_RAW_SHA256.values())
        copied_upstream = sorted(
            path for path, data in expected.items() if sha256_bytes(data) in upstream_digests
        )
        if copied_upstream:
            raise FinalizationError(
                f"equivalence: final output contains reference-only upstream bytes: {copied_upstream}"
            )
        publish_candidate(candidate, output, expected=expected)
        candidate = None
        return {
            "adapter_commit": adapter_commit,
            "equivalent": True,
            "final_inventory_sha256": sha256_bytes((output / "SHA256SUMS").read_bytes()),
            "output": output.name,
            "profile": PROFILE_ID,
            "run_ids": run_ids,
            "schema_version": "org.metriplane.massrobotics_amr.equivalence.v1",
        }
    except (AdapterError, ValueError) as exc:
        if isinstance(exc, FinalizationError):
            raise
        raise FinalizationError(str(exc)) from exc
    finally:
        if candidate is not None:
            shutil.rmtree(candidate, ignore_errors=True)


__all__ = ["FinalizationError", "finalize_conversion_equivalence"]
