# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Public adapter operations."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from .constants import (
    DATASET_REPOSITORY,
    DATASET_REVISION,
    PREPARED_REPOSITORY_PATH,
    PREPARED_SHA256,
    PREPARED_SIZE,
    RAW_REPOSITORY_PATH,
    RAW_SHA256,
    RAW_SIZE,
)
from .fixture import (
    FixtureError,
    finalize_conversion_equivalence,
    write_fixtures,
)
from .hdf5_audit import (
    SourceAuditError,
    reject_symlink_components,
    sha256_file,
    verify_source_file,
)
from .hdf5_audit import (
    compare_raw_prepared as audit_raw_prepared,
)
from .identity import AdapterIdentityError, verify_adapter_commit


class AdapterError(RuntimeError):
    """Stable CLI-facing adapter error."""


def _safe_supplied_file(path: str | Path, *, label: str) -> Path:
    try:
        supplied = reject_symlink_components(path, label=label)
    except SourceAuditError as exc:
        raise AdapterError(str(exc)) from exc
    if supplied.is_symlink() or not supplied.is_file():
        raise AdapterError(f"{label}: expected a regular, non-symlink file: {supplied}")
    return supplied.resolve()


def compare_raw_prepared(raw: str | Path, prepared: str | Path) -> dict[str, Any]:
    """Run the exact real-source correspondence and witness audit."""
    try:
        return audit_raw_prepared(raw, prepared, verify_identity=True).report
    except SourceAuditError as exc:
        raise AdapterError(str(exc)) from exc


def inspect_source(raw: str | Path, prepared: str | Path) -> dict[str, Any]:
    """Inspect the pinned pair without reading outcome-array values."""
    try:
        result = audit_raw_prepared(raw, prepared, verify_identity=True)
    except SourceAuditError as exc:
        raise AdapterError(str(exc)) from exc
    first = result.frames[0]
    last = result.frames[-1]
    return {
        **result.report,
        "consumed_hdf5_paths": [
            "data/demo_0/obs/object[:,7:10]",
            "data/demo_0/obs/robot0_eef_pos",
        ],
        "first_can_xyz": list(first.can_xyz),
        "first_tcp_xyz": list(first.tcp_xyz),
        "last_can_xyz": list(last.can_xyz),
        "last_tcp_xyz": list(last.tcp_xyz),
        "next_obs_consumed": False,
        "outcome_values_consumed": False,
        "policy_actions_used_for_state": False,
    }


def convert(
    raw: str | Path,
    prepared: str | Path,
    *,
    config_path: str | Path,
    output_root: str | Path,
    adapter_commit: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    try:
        raw_supplied = reject_symlink_components(raw, label="raw source")
        prepared_supplied = reject_symlink_components(prepared, label="prepared source")
        output_supplied = reject_symlink_components(output_root, label="output")
    except SourceAuditError as exc:
        raise AdapterError(str(exc)) from exc
    if raw_supplied.is_symlink() or prepared_supplied.is_symlink():
        raise AdapterError("source HDF5 symlinks are prohibited")
    raw_path = raw_supplied.resolve()
    prepared_path = prepared_supplied.resolve()
    if output_supplied.is_symlink():
        raise AdapterError("output symlinks are prohibited")
    output = output_supplied.resolve()
    candidate: Path | None = None
    for source in (raw_path, prepared_path):
        if output == source or output in source.parents or source in output.parents:
            raise AdapterError("output/source overlap: source files and output must be disjoint")
    try:
        verify_adapter_commit(adapter_commit)
        verify_source_file(
            raw_path, label="raw HDF5", expected_size=RAW_SIZE, expected_sha256=RAW_SHA256
        )
        verify_source_file(
            prepared_path,
            label="prepared HDF5",
            expected_size=PREPARED_SIZE,
            expected_sha256=PREPARED_SHA256,
        )
        before = {
            "raw": (raw_path.stat().st_size, sha256_file(raw_path)),
            "prepared": (prepared_path.stat().st_size, sha256_file(prepared_path)),
        }
        audit = audit_raw_prepared(raw_path, prepared_path, verify_identity=False)
        # Write into a disjoint candidate root so a source-mutation failure cannot
        # publish partial/new output or destroy an existing overwrite target.
        output.parent.mkdir(parents=True, exist_ok=True)
        candidate = Path(tempfile.mkdtemp(prefix=f".{output.name}.candidate-", dir=output.parent))
        candidate.rmdir()
        summary = write_fixtures(
            audit.frames,
            config_path=config_path,
            output_root=candidate,
            adapter_commit=adapter_commit,
            audit_report=audit.report,
            overwrite=False,
        )
        after = {
            "raw": (raw_path.stat().st_size, sha256_file(raw_path)),
            "prepared": (prepared_path.stat().st_size, sha256_file(prepared_path)),
        }
        if before != after:
            raise AdapterError("source mutation: source size or SHA-256 changed during conversion")
        if output.exists() and not overwrite:
            raise AdapterError(f"output {output}: already exists; pass --overwrite explicitly")
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise AdapterError("output: refusing non-directory replacement")
            shutil.rmtree(output)
        candidate.replace(output)
    except (SourceAuditError, FixtureError, AdapterIdentityError, AdapterError) as exc:
        if candidate is not None:
            shutil.rmtree(candidate, ignore_errors=True)
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError(str(exc)) from exc
    return {
        **summary,
        "audit": {
            "can_named_qpos_rows_verified": audit.report["can_named_qpos_rows_verified"],
            "clock_rows_verified": audit.report["clock_rows_verified"],
            "demo_count": audit.report["demo_count"],
            "mask_membership_equal": audit.report["mask_membership_equal"],
            "max_fk_abs_error": audit.report["max_fk_abs_error"],
            "selected_demo": audit.report["selected_demo"],
            "selected_frame_count": audit.report["selected_frame_count"],
            "source_unchanged": True,
        },
    }


def acquire(
    output_root: str | Path,
    *,
    downloaded_raw: str | Path | None = None,
    downloaded_prepared: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Acquire only the exact pinned pair, or verify supplied pre-downloaded files."""
    try:
        output_supplied = reject_symlink_components(output_root, label="acquire output")
    except SourceAuditError as exc:
        raise AdapterError(str(exc)) from exc
    if output_supplied.is_symlink():
        raise AdapterError("acquire: output symlinks are prohibited")
    output = output_supplied.resolve()
    supplied = [value for value in (downloaded_raw, downloaded_prepared) if value is not None]
    if bool(downloaded_raw is None) != bool(downloaded_prepared is None):
        raise AdapterError("acquire: provide both --raw and --prepared, or neither")
    supplied_paths = [_safe_supplied_file(path, label="supplied source") for path in supplied]
    for source in supplied_paths:
        if output == source or output in source.parents or source in output.parents:
            raise AdapterError("acquire: output and supplied files must be disjoint")
    if output.exists() and not overwrite:
        raise AdapterError(f"acquire output {output}: exists; pass --overwrite explicitly")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        if downloaded_raw is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise AdapterError("acquire: huggingface-hub is not installed") from exc
            raw_cache = Path(
                hf_hub_download(
                    repo_id=DATASET_REPOSITORY,
                    filename=RAW_REPOSITORY_PATH,
                    revision=DATASET_REVISION,
                    repo_type="dataset",
                )
            )
            prepared_cache = Path(
                hf_hub_download(
                    repo_id=DATASET_REPOSITORY,
                    filename=PREPARED_REPOSITORY_PATH,
                    revision=DATASET_REVISION,
                    repo_type="dataset",
                )
            )
            # Hugging Face cache entries may be symlinks to verified content blobs.
            # Resolve these library-owned cache paths, then copy only regular bytes
            # into our read-only acquisition root.
            raw_source = raw_cache.resolve()
            prepared_source = prepared_cache.resolve()
            if not raw_source.is_file() or not prepared_source.is_file():
                raise AdapterError("acquire: downloaded cache path is not a regular file")
            for source in (raw_source, prepared_source):
                if output == source or output in source.parents or source in output.parents:
                    raise AdapterError(
                        "acquire: output and downloaded cache files must be disjoint"
                    )
        else:
            raw_source, prepared_source = supplied_paths
        verify_source_file(
            raw_source, label="raw HDF5", expected_size=RAW_SIZE, expected_sha256=RAW_SHA256
        )
        verify_source_file(
            prepared_source,
            label="prepared HDF5",
            expected_size=PREPARED_SIZE,
            expected_sha256=PREPARED_SHA256,
        )
        destinations = {
            RAW_REPOSITORY_PATH: raw_source,
            PREPARED_REPOSITORY_PATH: prepared_source,
        }
        for relative, source in destinations.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            destination.chmod(0o444)
        verify_source_file(
            stage / RAW_REPOSITORY_PATH,
            label="staged raw HDF5",
            expected_size=RAW_SIZE,
            expected_sha256=RAW_SHA256,
        )
        verify_source_file(
            stage / PREPARED_REPOSITORY_PATH,
            label="staged prepared HDF5",
            expected_size=PREPARED_SIZE,
            expected_sha256=PREPARED_SHA256,
        )
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise AdapterError("acquire: refusing non-directory output replacement")
            shutil.rmtree(output)
        stage.replace(output)
        return {
            "dataset_repository": DATASET_REPOSITORY,
            "dataset_revision": DATASET_REVISION,
            "files": {
                RAW_REPOSITORY_PATH: {"sha256": RAW_SHA256, "size": RAW_SIZE},
                PREPARED_REPOSITORY_PATH: {
                    "sha256": PREPARED_SHA256,
                    "size": PREPARED_SIZE,
                },
            },
            "schema_version": "org.metriplane.robomimic_lowdim.acquisition.v1",
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


__all__ = [
    "AdapterError",
    "acquire",
    "compare_raw_prepared",
    "convert",
    "finalize_conversion_equivalence",
    "inspect_source",
]
