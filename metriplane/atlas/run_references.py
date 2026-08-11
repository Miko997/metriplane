# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

STATE_SEGMENT_RUN_PATH = "state_segment.jsonl"
DOMAIN_PACK_RUN_PATH = "configs"


def _is_absolute_reference(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _validate_run_relative_reference(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    reference = PurePosixPath(normalized)
    if (
        not normalized
        or reference.is_absolute()
        or bool(PureWindowsPath(value).drive)
        or any(part in {"", ".", ".."} for part in reference.parts)
    ):
        raise ValueError(f"unsafe run-relative reference: {value!r}")
    return reference


def _contained_path(run: Path, relative_reference: str) -> Path:
    reference = _validate_run_relative_reference(relative_reference)
    candidate = run.joinpath(*reference.parts)
    try:
        candidate.resolve().relative_to(run.resolve())
    except ValueError as exc:
        raise ValueError(
            f"run-relative reference escapes the run directory: {relative_reference!r}"
        ) from exc
    return candidate


def resolve_run_reference(
    run_dir: str | Path,
    recorded_reference: str,
    *,
    contained_reference: str,
) -> Path:
    """Resolve a durable Atlas reference without tying new runs to input paths.

    A run-contained immutable copy always wins, including for a legacy manifest
    that recorded an absolute operational path. Safe relative references resolve
    inside the run. Absolute references remain readable only as a compatibility
    fallback for historical runs that lack the contained copy.
    """

    run = Path(run_dir)
    recorded = str(recorded_reference)
    if not _is_absolute_reference(recorded):
        _validate_run_relative_reference(recorded)

    contained = _contained_path(run, contained_reference)
    if contained.exists():
        return contained

    if _is_absolute_reference(recorded):
        return Path(recorded)

    return _contained_path(run, recorded)
