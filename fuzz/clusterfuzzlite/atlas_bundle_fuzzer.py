"""Coverage-guided fuzz target for Atlas evidence-bundle verification.

The target exercises the untrusted ZIP, path, checksum, JSON, schema, timeline,
and incident-validation boundary. It builds a small valid bundle and then makes
one bounded mutation chosen from the fuzzer input. The production verifier must
always return a structurally valid result and must only report a pass when no
errors were recorded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from tempfile import TemporaryDirectory
import warnings
import zipfile

import atheris

with atheris.instrument_imports():
    from metriplane.atlas.bundles import (
        REQUIRED_BUNDLE_FILES,
        _safe_relative_path,
        verify_bundle,
    )


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")


def _baseline_files() -> dict[str, bytes]:
    event = {
        "schema_version": "metriplane.atlas.event.v1",
        "event_id": "evt-1",
        "run_id": "run-1",
        "ts": 0.0,
        "frame_id": 0,
        "event_type": "fuzz_event",
        "severity": "info",
        "message": "structured fuzz seed",
    }
    incident = {
        "schema_version": "metriplane.atlas.incident.v1",
        "incident_id": "inc-1",
        "incident_type": "fuzz_incident",
        "severity": "warning",
        "title": "Structured fuzz seed",
        "start_ts": 0.0,
        "end_ts": 0.0,
        "event_ids": ["evt-1"],
        "summary": "Valid baseline used before bounded mutation.",
    }
    frame = {
        "schema_version": "1.0",
        "source_backend": "clusterfuzzlite",
        "ts": 0.0,
        "frame_id": 0,
        "objects": [],
    }
    manifest = {
        "schema_version": "metriplane.atlas.evidence_bundle.v1",
        "bundle_id": "bundle-inc-1",
        "incident_id": "inc-1",
        "run_id": "run-1",
        "required_files": list(REQUIRED_BUNDLE_FILES),
    }

    files: dict[str, bytes] = {
        "manifest.json": _json_bytes(manifest),
        "incident.json": _json_bytes(incident),
        "event_timeline.jsonl": _json_bytes(event),
        "state_segment.jsonl": _json_bytes(frame),
        "reality_graph_excerpt.json": b"{}\n",
        "process_trace_excerpt.json": b"{}\n",
        "configs/assets.yaml": b"assets: []\n",
        "configs/workspace.yaml": b"zones: []\n",
        "configs/process.yaml": b"steps: []\n",
        "reports/cell_truth_report.md": b"# Fuzz seed report\n",
        "replay_command.sh": b"#!/bin/sh\nexit 0\n",
        "limitations.md": b"# Limitations\n\nSynthetic fuzz input.\n",
    }
    checksum_lines = [
        f"{hashlib.sha256(content).hexdigest()}  {name}"
        for name, content in sorted(files.items())
    ]
    files["checksums.sha256"] = ("\n".join(checksum_lines) + "\n").encode("utf-8")
    return files


def _assert_result(result: object) -> None:
    assert isinstance(result, dict)
    assert result.get("schema_version") == "metriplane.atlas.bundle_verifier.v1"
    assert isinstance(result.get("bundle"), str)
    assert isinstance(result.get("pass"), bool)
    errors = result.get("errors")
    assert isinstance(errors, list)
    assert all(isinstance(error, str) for error in errors)
    assert result["pass"] == (len(errors) == 0)


def _bounded_path(fdp: atheris.FuzzedDataProvider) -> str:
    value = fdp.ConsumeUnicodeNoSurrogates(96)
    return value or "fuzz-extra"


def _mutated_members(
    files: dict[str, bytes],
    fdp: atheris.FuzzedDataProvider,
) -> tuple[list[tuple[str, bytes, bool]], bool]:
    """Return ZIP members and whether the unmodified valid baseline was selected."""

    members = [(name, content, False) for name, content in sorted(files.items())]
    names = list(files)
    mode = fdp.ConsumeIntInRange(0, 8)
    selected = fdp.PickValueInList(names)

    if mode == 0:
        return members, True
    if mode == 1:
        replacement = fdp.ConsumeBytes(4096)
        members = [
            (name, replacement if name == selected else content, symlink)
            for name, content, symlink in members
        ]
    elif mode == 2:
        members = [member for member in members if member[0] != selected]
    elif mode == 3:
        members.append((_bounded_path(fdp), fdp.ConsumeBytes(2048), False))
    elif mode == 4:
        members = [
            (
                name,
                fdp.ConsumeBytes(4096) if name == "checksums.sha256" else content,
                symlink,
            )
            for name, content, symlink in members
        ]
    elif mode == 5:
        members.append((selected, fdp.ConsumeBytes(2048), False))
    elif mode == 6:
        replacement_name = _bounded_path(fdp)
        members = [
            (replacement_name if name == selected else name, content, symlink)
            for name, content, symlink in members
        ]
    elif mode == 7:
        unsafe_names = [
            "../escape",
            "/absolute",
            "nested/../../escape",
            "back\\slash",
            "./dot",
        ]
        members.append((fdp.PickValueInList(unsafe_names), b"unsafe", False))
    else:
        members.append((_bounded_path(fdp), b"symlink-target", True))
    return members, False


def _write_zip(path: Path, members: list[tuple[str, bytes, bool]], compress: bool) -> None:
    compression = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, content, symlink in members:
                if symlink:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                    archive.writestr(info, content)
                else:
                    archive.writestr(name, content)


def _exercise_path_validator(fdp: atheris.FuzzedDataProvider) -> None:
    candidate = _bounded_path(fdp)
    try:
        normalized = _safe_relative_path(candidate)
    except ValueError:
        return
    path = PurePosixPath(normalized)
    assert normalized
    assert not path.is_absolute()
    assert "\\" not in normalized and "\x00" not in normalized
    assert all(part not in ("", ".", "..") for part in path.parts)


def test_one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    _exercise_path_validator(fdp)

    with TemporaryDirectory(prefix="metriplane-fuzz-") as temp_dir:
        root = Path(temp_dir)

        # First exercise the raw, potentially malformed archive boundary.
        raw_path = root / "raw-input.zip"
        raw_path.write_bytes(data[:65536])
        _assert_result(verify_bundle(raw_path))

        # Then exercise deeper verification stages with a valid baseline plus one
        # bounded structural or content mutation.
        files = _baseline_files()
        members, valid_baseline = _mutated_members(files, fdp)
        structured_path = root / "structured-input.zip"
        try:
            _write_zip(structured_path, members, fdp.ConsumeBool())
        except (OSError, OverflowError, RuntimeError, ValueError):
            return

        result = verify_bundle(structured_path)
        _assert_result(result)
        if valid_baseline:
            assert result["pass"], result["errors"]


def main() -> None:
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()


if __name__ == "__main__":
    main()
