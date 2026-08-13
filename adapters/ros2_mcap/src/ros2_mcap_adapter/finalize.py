# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Verify and finalize exactly three byte-identical clean conversions."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, pretty_json_bytes, sha256_bytes
from .constants import (
    DEFAULT_CONFIG,
    DEFAULT_LOCK,
    DEFAULT_SOURCE,
    FROZEN_CONFIG_SHA256,
    FROZEN_LOCK_SHA256,
    PROFILE_ID,
    SOURCE_SHA256,
    SOURCE_SIZE,
)
from .decoder import DecodeError, decode_source_bytes, load_config_bytes
from .fixture import FixtureError, write_conversion
from .identity import AdapterIdentityError, verify_adapter_commit
from .path_safety import (
    PathSafetyError,
    durable_path_leaks,
    publish_directory,
    read_directory_snapshot,
    read_file_snapshot,
    reject_overlap,
    require_safe_output,
    verify_file_snapshot_current,
)


class FinalizationError(RuntimeError):
    """Raised when conversion equivalence or output safety is not proven."""


_ADAPTER_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FinalizationError(f"equivalence: cannot read JSON {path}: {exc}") from exc
    return _parse_json(data, label=str(path))


def _parse_json(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"equivalence: invalid JSON {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise FinalizationError(f"equivalence: JSON root is not an object: {label}")
    return value


def _inventory(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise FinalizationError(f"equivalence: expected regular conversion directory: {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise FinalizationError(f"equivalence: symlink prohibited: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise FinalizationError(f"equivalence: non-file entry prohibited: {path}")
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    required = {
        "capability-record.json",
        "conversion-summary.json",
        "rights-record.json",
        "transform-provenance.json",
    }
    for variant in ("incident", "control"):
        required.update(
            {
                f"{variant}/CHECKSUMS.sha256",
                f"{variant}/domain-pack/assets.yaml",
                f"{variant}/domain-pack/contracts.yaml",
                f"{variant}/domain-pack/process.yaml",
                f"{variant}/domain-pack/work_orders.csv",
                f"{variant}/domain-pack/workspace.yaml",
                f"{variant}/entity-mapping.json",
                f"{variant}/expected-outcome.json",
                f"{variant}/normalization-report.json",
                f"{variant}/session.jsonl",
                f"{variant}/source-manifest.json",
                f"{variant}/source/frozen-config.json",
                f"{variant}/source/uv.lock",
            }
        )
    missing = sorted(required - set(files))
    if missing:
        raise FinalizationError(f"equivalence: required artifacts missing: {missing}")
    return files


def _verify_checksums(root: Path, variant: str, files: dict[str, bytes]) -> None:
    prefix = f"{variant}/"
    try:
        lines = files[f"{variant}/CHECKSUMS.sha256"].decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise FinalizationError(f"equivalence: {variant} checksums are not ASCII") from exc
    actual: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise FinalizationError(f"equivalence: malformed {variant} checksum line")
        digest, relative = match.groups()
        if relative.startswith(("/", "../")) or "\\" in relative or relative in actual:
            raise FinalizationError(f"equivalence: unsafe or duplicate checksum path: {relative}")
        actual[relative] = digest
    expected_paths = {
        relative[len(prefix) :]
        for relative in files
        if relative.startswith(prefix) and relative != f"{variant}/CHECKSUMS.sha256"
    }
    if set(actual) != expected_paths:
        raise FinalizationError(f"equivalence: {variant} checksum inventory is incomplete")
    for relative, digest in actual.items():
        if sha256_bytes(files[f"{prefix}{relative}"]) != digest:
            raise FinalizationError(f"equivalence: {variant} checksum mismatch: {relative}")
    manifest = _parse_json(
        files[f"{variant}/source-manifest.json"],
        label=f"{root}/{variant}/source-manifest.json",
    )
    if manifest.get("schema_version") != "metriplane.external_source_contract.v1":
        raise FinalizationError(f"equivalence: {variant} Contract v1 manifest identity differs")
    if manifest.get("adapter", {}).get("parameters", {}).get("sha256") != FROZEN_CONFIG_SHA256:
        raise FinalizationError(f"equivalence: {variant} config identity differs")
    source_artifacts = manifest.get("source_artifacts")
    if not isinstance(source_artifacts, list) or len(source_artifacts) != 1:
        raise FinalizationError(f"equivalence: {variant} source identity missing")
    if source_artifacts[0].get("sha256") != SOURCE_SHA256:
        raise FinalizationError(f"equivalence: {variant} is not the exact frozen source")
    extension = manifest.get("extensions", {}).get("org.metriplane.ros2_mcap_recorded_state", {})
    if extension.get("source_size") != SOURCE_SIZE:
        raise FinalizationError(f"equivalence: {variant} source byte size differs")
    session_digest = sha256_bytes(files[f"{variant}/session.jsonl"])
    if manifest.get("normalized_artifacts", {}).get("session", {}).get("sha256") != session_digest:
        raise FinalizationError(f"equivalence: {variant} normalized session identity differs")
    mapping_digest = sha256_bytes(files[f"{variant}/entity-mapping.json"])
    if manifest.get("normalization", {}).get("entity_mapping", {}).get("sha256") != mapping_digest:
        raise FinalizationError(f"equivalence: {variant} mapping identity differs")


def _read_adapter_commit(root: Path, files: dict[str, bytes]) -> tuple[str, dict[str, Any]]:
    summary = _parse_json(files["conversion-summary.json"], label=f"{root}/conversion-summary.json")
    adapter_commit = summary.get("adapter_commit")
    if (
        not isinstance(adapter_commit, str)
        or _ADAPTER_COMMIT_PATTERN.fullmatch(adapter_commit) is None
    ):
        raise FinalizationError("equivalence: adapter commit must be one exact 40-hex identity")
    return adapter_commit, summary


def _expected_inventory(
    adapter_commit: str,
    *,
    source_bytes: bytes,
    config_bytes: bytes,
    lock_bytes: bytes,
) -> dict[str, bytes]:
    """Reconstruct one exact clean conversion without trusting supplied roots."""

    try:
        source = decode_source_bytes(source_bytes)
        config = load_config_bytes(config_bytes)
        with tempfile.TemporaryDirectory(prefix="metriplane-ros2-mcap-expected-") as temporary:
            private_root = Path(temporary)
            private_root.chmod(0o700)
            expected_root = private_root / "conversion"
            write_conversion(
                config=config,
                adapter_commit=adapter_commit,
                source=source,
                output_root=expected_root,
                config_bytes=config_bytes,
                lock_bytes=lock_bytes,
            )
            return _inventory(expected_root)
    except (DecodeError, FixtureError, OSError) as exc:
        raise FinalizationError(f"equivalence: cannot rebuild expected conversion: {exc}") from exc


def _require_exact_adapter_output(
    root: Path, supplied: dict[str, bytes], expected: dict[str, bytes]
) -> None:
    if supplied == expected:
        return
    supplied_paths = set(supplied)
    expected_paths = set(expected)
    missing = sorted(expected_paths - supplied_paths)
    unexpected = sorted(supplied_paths - expected_paths)
    changed = sorted(
        relative
        for relative in supplied_paths & expected_paths
        if supplied[relative] != expected[relative]
    )
    raise FinalizationError(
        "equivalence: conversion root is not exact adapter-produced output: "
        f"{root}; missing={missing}; unexpected={unexpected}; changed={changed}"
    )


def _write_root_inventory(root: Path) -> None:
    files = [
        path
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    lines = "".join(
        f"{sha256_bytes(path.read_bytes())}  {path.relative_to(root).as_posix()}\n"
        for path in files
    )
    (root / "SHA256SUMS").write_text(lines, encoding="ascii")


def _write_inventory_bytes(root: Path, files: dict[str, bytes]) -> None:
    """Construct output only from the already validated in-memory inventory."""

    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def finalize_conversion_equivalence(
    conversion_roots: list[str | Path],
    *,
    output_root: str | Path,
    run_ids: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    if len(conversion_roots) != 3:
        raise FinalizationError("equivalence: exactly three conversion roots are required")
    if run_ids is None:
        run_ids = ["clean-conversion-1", "clean-conversion-2", "clean-conversion-3"]
    if len(run_ids) != 3 or len(set(run_ids)) != 3:
        raise FinalizationError("equivalence: exactly three distinct run IDs are required")
    if any(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", run_id) is None for run_id in run_ids):
        raise FinalizationError("equivalence: unsafe run ID")
    try:
        roots = [require_safe_output(path, label="conversion root") for path in conversion_roots]
        output = require_safe_output(output_root, label="final output")
        if len(set(roots)) != 3:
            raise FinalizationError("equivalence: conversion roots must be distinct")
        for root in roots:
            reject_overlap(root, output)
    except PathSafetyError as exc:
        raise FinalizationError(str(exc)) from exc
    try:
        source_snapshot = read_file_snapshot(DEFAULT_SOURCE, label="frozen MCAP source")
        config_snapshot = read_file_snapshot(DEFAULT_CONFIG, label="frozen config")
        lock_snapshot = read_file_snapshot(DEFAULT_LOCK, label="adapter lock")
        if lock_snapshot.sha256 != FROZEN_LOCK_SHA256:
            raise FinalizationError("equivalence: adapter lock SHA-256 differs")
        for snapshot in (source_snapshot, config_snapshot, lock_snapshot):
            reject_overlap(snapshot.path, output)
    except PathSafetyError as exc:
        raise FinalizationError(str(exc)) from exc
    inventories = [_inventory(root) for root in roots]
    identities = [
        _read_adapter_commit(root, files) for root, files in zip(roots, inventories, strict=True)
    ]
    adapter_commits = {adapter_commit for adapter_commit, _summary in identities}
    if len(adapter_commits) != 1:
        raise FinalizationError("equivalence: conversions do not share one adapter commit")
    adapter_commit = next(iter(adapter_commits))
    try:
        verify_adapter_commit(adapter_commit)
    except AdapterIdentityError as exc:
        raise FinalizationError(str(exc)) from exc
    expected_inventory = _expected_inventory(
        adapter_commit,
        source_bytes=source_snapshot.data,
        config_bytes=config_snapshot.data,
        lock_bytes=lock_snapshot.data,
    )
    for root, files, (adapter_commit, summary) in zip(roots, inventories, identities, strict=True):
        _require_exact_adapter_output(root, files, expected_inventory)
        _verify_checksums(root, "incident", files)
        _verify_checksums(root, "control", files)
        expected = {
            "config_sha256": FROZEN_CONFIG_SHA256,
            "profile": PROFILE_ID,
            "source_sha256": SOURCE_SHA256,
            "source_size": SOURCE_SIZE,
            "source_unchanged_during_conversion": True,
        }
        if any(summary.get(key) != value for key, value in expected.items()):
            raise FinalizationError(f"equivalence: frozen identity differs in {root}")
        if summary.get("outcome_stream_present") is not True:
            raise FinalizationError("equivalence: exact source outcome stream must be present")
        capability = _parse_json(
            files["capability-record.json"], label=f"{root}/capability-record.json"
        )
        capability_digest = sha256_bytes(canonical_json_bytes(capability))
        if summary.get("capability_fingerprint_sha256") != capability_digest:
            raise FinalizationError("equivalence: capability record identity differs")
        if capability.get("adapter", {}).get("implementation_commit") != adapter_commit:
            raise FinalizationError("equivalence: adapter commit identity differs")
        for variant in ("incident", "control"):
            manifest = _parse_json(
                files[f"{variant}/source-manifest.json"],
                label=f"{root}/{variant}/source-manifest.json",
            )
            if manifest.get("adapter", {}).get("commit") != adapter_commit:
                raise FinalizationError("equivalence: manifest adapter commit differs")
            if summary.get("shared_session_sha256") != sha256_bytes(
                files[f"{variant}/session.jsonl"]
            ):
                raise FinalizationError("equivalence: shared session identity differs")
        for data in files.values():
            if durable_path_leaks(data, extra_roots=tuple(roots)):
                raise FinalizationError("equivalence: machine-local path leaked into conversion")
    if inventories[1] != inventories[0] or inventories[2] != inventories[0]:
        raise FinalizationError("equivalence: three clean conversions are not byte-identical")

    candidate: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        candidate = Path(tempfile.mkdtemp(prefix=f".{output.name}.candidate-", dir=output.parent))
        _write_inventory_bytes(candidate, inventories[0])
        run_records: list[dict[str, object]] = []
        for run_id, files in zip(run_ids, inventories, strict=True):
            run_records.append(
                {
                    "conversion_tree_sha256": sha256_bytes(
                        canonical_json_bytes(
                            {relative: sha256_bytes(data) for relative, data in files.items()}
                        )
                    ),
                    "run_id": run_id,
                }
            )
        for variant in ("incident", "control"):
            report_path = candidate / variant / "normalization-report.json"
            report = _load_json(report_path)
            variant_runs = [
                {
                    "artifacts": {
                        "entity-mapping.json": sha256_bytes(
                            files[f"{variant}/entity-mapping.json"]
                        ),
                        "session.jsonl": sha256_bytes(files[f"{variant}/session.jsonl"]),
                    },
                    "run_id": record["run_id"],
                }
                for record, files in zip(run_records, inventories, strict=True)
            ]
            report["conversion_reproducibility"] = {
                "comparison_policy": "sha256_byte_identity",
                "equivalent": True,
                "input_fingerprint_sha256": report["conversion_reproducibility"][
                    "input_fingerprint_sha256"
                ],
                "runs": variant_runs,
                "status": "demonstrated",
            }
            report_path.write_bytes(pretty_json_bytes(report))
            manifest_path = candidate / variant / "source-manifest.json"
            manifest = _load_json(manifest_path)
            manifest["normalized_artifacts"]["normalization_report"]["sha256"] = sha256_bytes(
                report_path.read_bytes()
            )
            manifest_path.write_bytes(pretty_json_bytes(manifest))
            variant_files = {
                path.relative_to(candidate / variant).as_posix(): path.read_bytes()
                for path in (candidate / variant).rglob("*")
                if path.is_file() and path.name != "CHECKSUMS.sha256"
            }
            checksums = "".join(
                f"{sha256_bytes(variant_files[path])}  {path}\n" for path in sorted(variant_files)
            ).encode()
            (candidate / variant / "CHECKSUMS.sha256").write_bytes(checksums)
        capability_path = candidate / "capability-record.json"
        capability = _load_json(capability_path)
        deterministic = capability["capabilities"]["deterministic_conversion"]
        deterministic.update(
            {
                "status": "verified",
                "comparison_policy": "byte_identity",
                "clean_run_count": 3,
                "compared_output_count": 3,
                "equivalent": True,
            }
        )
        capability_path.write_bytes(pretty_json_bytes(capability))
        summary_path = candidate / "conversion-summary.json"
        summary = _load_json(summary_path)
        summary["capability_fingerprint_sha256"] = sha256_bytes(canonical_json_bytes(capability))
        summary["conversion_reproducibility"] = {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": True,
            "run_ids": run_ids,
            "status": "demonstrated",
        }
        for variant in ("incident", "control"):
            summary[variant]["fixture_fingerprint_sha256"] = sha256_bytes(
                (candidate / variant / "CHECKSUMS.sha256").read_bytes()
            )
        summary_path.write_bytes(pretty_json_bytes(summary))
        _write_root_inventory(candidate)
        candidate_snapshot = read_directory_snapshot(candidate, label="equivalence output")
        for entry in candidate_snapshot.entries:
            if (
                entry.entry_type == "file"
                and entry.data is not None
                and durable_path_leaks(entry.data, extra_roots=tuple(roots))
            ):
                raise FinalizationError("equivalence: final output contains a machine-local path")

        def verify_publish_inputs() -> None:
            verify_file_snapshot_current(source_snapshot, label="frozen MCAP source")
            verify_file_snapshot_current(config_snapshot, label="frozen config")
            verify_file_snapshot_current(lock_snapshot, label="adapter lock")
            verify_adapter_commit(adapter_commit)

        try:
            verify_publish_inputs()
        except (PathSafetyError, AdapterIdentityError) as exc:
            raise FinalizationError(str(exc)) from exc
        try:
            publish_directory(
                candidate,
                output,
                overwrite=overwrite,
                snapshot=candidate_snapshot,
                commit_check=verify_publish_inputs,
            )
        except (PathSafetyError, AdapterIdentityError) as exc:
            raise FinalizationError(str(exc)) from exc
        candidate = None
        return {
            "conversion_tree_sha256": run_records[0]["conversion_tree_sha256"],
            "equivalent": True,
            "final_inventory_sha256": sha256_bytes((output / "SHA256SUMS").read_bytes()),
            "output": output.name,
            "run_ids": run_ids,
            "schema_version": "org.metriplane.ros2_mcap.equivalence.v1",
        }
    finally:
        if candidate is not None:
            import shutil

            shutil.rmtree(candidate, ignore_errors=True)


__all__ = ["FinalizationError", "finalize_conversion_equivalence"]
