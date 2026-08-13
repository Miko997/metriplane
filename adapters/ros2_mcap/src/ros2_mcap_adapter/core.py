# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Public source inspection and atomic conversion operations."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .constants import DEFAULT_LOCK, FROZEN_LOCK_SHA256
from .decoder import DecodeError, decode_source_bytes, decode_source_file, load_config_bytes
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


class AdapterError(RuntimeError):
    """Stable CLI-facing adapter error."""


_SOURCE_MUTATION_TEST_HOOK: Callable[[Path], None] | None = None


def inspect_source(
    source_path: str | Path,
) -> dict[str, Any]:
    try:
        source = decode_source_file(source_path)
    except (DecodeError, PathSafetyError) as exc:
        raise AdapterError(str(exc)) from exc
    return {
        "channel_inventory": list(source.channel_inventory),
        "clock": {
            "authority": "geometry_msgs/msg/PoseStamped.header.stamp",
            "domain": "ROS_TIME",
            "evaluation_unit": "integer nanoseconds",
            "log_time_role": "container provenance only",
            "publish_time_role": "transport provenance only",
        },
        "frame_count": len(source.frames),
        "materialization": "exact co-timestamp join; no carry-forward",
        "outcome_message_count": source.outcome_message_count,
        "outcome_stream_present": source.outcome_stream_present,
        "schema_inventory": list(source.schema_inventory),
        "source_sha256": source.source_sha256,
        "source_size": source.source_size,
        "tf": {
            "interpolation": False,
            "path": ["world->cell_frame", "cell_frame->sensor_frame"],
            "static": True,
        },
    }


def convert(
    source_path: str | Path,
    *,
    config_path: str | Path,
    output_root: str | Path,
    adapter_commit: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    candidate: Path | None = None
    try:
        source_snapshot = read_file_snapshot(source_path, label="MCAP source")
        config_snapshot = read_file_snapshot(config_path, label="frozen config")
        lock_snapshot = read_file_snapshot(DEFAULT_LOCK, label="adapter lock")
        if lock_snapshot.sha256 != FROZEN_LOCK_SHA256:
            raise AdapterError("adapter lock: SHA-256 differs from frozen identity")
        source_file = source_snapshot.path
        config_file = config_snapshot.path
        output = require_safe_output(output_root, label="conversion output")
        reject_overlap(source_file, output)
        reject_overlap(config_file, output)
        reject_overlap(lock_snapshot.path, output)
        verify_adapter_commit(adapter_commit)
        config = load_config_bytes(config_snapshot.data)
        source = decode_source_bytes(source_snapshot.data)
        output.parent.mkdir(parents=True, exist_ok=True)
        candidate = Path(tempfile.mkdtemp(prefix=f".{output.name}.candidate-", dir=output.parent))
        summary = write_conversion(
            config=config,
            adapter_commit=adapter_commit,
            source=source,
            output_root=candidate,
            config_bytes=config_snapshot.data,
            lock_bytes=lock_snapshot.data,
        )

        def verify_publish_inputs() -> None:
            verify_file_snapshot_current(source_snapshot, label="source mutation")
            verify_file_snapshot_current(config_snapshot, label="config mutation")
            verify_file_snapshot_current(lock_snapshot, label="adapter lock mutation")
            verify_adapter_commit(adapter_commit)

        if _SOURCE_MUTATION_TEST_HOOK is not None:
            _SOURCE_MUTATION_TEST_HOOK(source_file)
        verify_publish_inputs()
        candidate_snapshot = read_directory_snapshot(candidate, label="conversion output")
        for durable in candidate_snapshot.entries:
            if durable.entry_type == "file" and durable.data is not None:
                leaks = durable_path_leaks(durable.data, extra_roots=(candidate,))
                if leaks:
                    raise AdapterError(
                        f"conversion output: machine-local path leak in {durable.relative_path}"
                    )
        publish_directory(
            candidate,
            output,
            overwrite=overwrite,
            snapshot=candidate_snapshot,
            commit_check=verify_publish_inputs,
        )
        candidate = None
        return summary
    except (PathSafetyError, DecodeError, FixtureError, AdapterIdentityError, AdapterError) as exc:
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError(str(exc)) from exc
    finally:
        if candidate is not None:
            shutil.rmtree(candidate, ignore_errors=True)


__all__ = ["AdapterError", "convert", "inspect_source"]
