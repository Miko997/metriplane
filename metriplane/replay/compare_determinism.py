# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator

from pydantic import ValidationError

from metriplane.replay.engine import EngineConfig, iter_replay_outputs, write_outputs_jsonl
from metriplane.schema import FrameStateModel


HEADER_TYPES = {"header", "run_header", "provenance"}


def _is_header_record(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    t = obj.get("type") or obj.get("record_type")
    return t in HEADER_TYPES


def _read_first_header(path: Path) -> dict[str, Any] | None:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict) and _is_header_record(obj):
                return obj
            return None
    return None


def _iter_non_header_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(
                    f"Invalid JSONL record at {path}:{line_number}: expected an object"
                )
            if _is_header_record(obj):
                continue
            yield obj


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sort_objects_inplace(rec: dict[str, Any]) -> None:
    # Stable sort common list fields that contain dicts with "id"
    for key in ("objects", "fused"):
        v = rec.get(key)
        if isinstance(v, list):
            v.sort(key=lambda o: str(o.get("id", "")) if isinstance(o, dict) else "")

    # raw_per_camera: list of camera frames, each has objects
    rpc = rec.get("raw_per_camera")
    if isinstance(rpc, list):
        # sort cameras by camera_id for stable compare
        rpc.sort(key=lambda c: str(c.get("camera_id", "")) if isinstance(c, dict) else "")
        for camrec in rpc:
            if isinstance(camrec, dict) and isinstance(camrec.get("objects"), list):
                camrec["objects"].sort(
                    key=lambda o: str(o.get("id", "")) if isinstance(o, dict) else ""
                )


def _canonical(
    rec: dict[str, Any],
    *,
    drop_ts_sim_ns: bool,
    sort_objects: bool,
) -> str:
    obj = dict(rec)

    if drop_ts_sim_ns:
        obj.pop("ts_sim_ns", None)

    if sort_objects:
        _sort_objects_inplace(obj)

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compare_records(
    a_records: Iterable[dict[str, Any]],
    b_records: Iterable[dict[str, Any]],
    *,
    drop_ts_sim_ns: bool,
    sort_objects: bool,
    max_mismatches_to_log: int = 3,
) -> tuple[int, int, list[str]]:
    mismatches = 0
    total = 0
    notes: list[str] = []

    for i, (ra, rb) in enumerate(zip(a_records, b_records), start=1):
        total += 1
        sa = _canonical(ra, drop_ts_sim_ns=drop_ts_sim_ns, sort_objects=sort_objects)
        sb = _canonical(rb, drop_ts_sim_ns=drop_ts_sim_ns, sort_objects=sort_objects)
        if sa != sb:
            mismatches += 1
            if len(notes) < max_mismatches_to_log:
                notes.append(f"mismatch_line={i}")

    return total, mismatches, notes


def _equivalence_frame_key(rec: dict[str, Any], fallback_index: int) -> tuple[str, Any]:
    """Return the recorded frame identity, excluding generated replay clock fields."""
    for field in ("frame_id", "ts_ns", "ts"):
        value = rec.get(field)
        if value is not None:
            try:
                hash(value)
            except TypeError:
                # Structural validation rejects this value; keeping the key
                # hashable lets the comparison report the error instead of
                # crashing while it builds identity sets.
                value = repr(value)
            return (field, value)
    return ("index", fallback_index)


def _object_ids(rec: dict[str, Any], field: str) -> set[str] | None:
    value = rec.get(field)
    if not isinstance(value, list):
        return None
    return {
        str(obj.get("id"))
        for obj in value
        if isinstance(obj, dict) and obj.get("id") not in (None, "")
    }


def _record_validation_note(
    rec: dict[str, Any],
    *,
    side: str,
    line_number: int,
) -> str | None:
    try:
        FrameStateModel.model_validate(rec)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "record"
        return (
            f"invalid_frame:{side}:line={line_number}:field={location}:"
            f"{first.get('msg', 'validation failed')}"
        )
    return None


def _duplicate_object_notes(
    rec: dict[str, Any],
    *,
    side: str,
    line_number: int,
) -> list[str]:
    notes: list[str] = []

    def inspect(value: Any, field: str) -> None:
        if not isinstance(value, list):
            return
        ids = [
            obj["id"].strip()
            for obj in value
            if isinstance(obj, dict) and isinstance(obj.get("id"), str) and obj["id"].strip()
        ]
        for object_id, count in Counter(ids).items():
            if count > 1:
                notes.append(
                    f"duplicate_object_id:{side}:line={line_number}:field={field}:id={object_id!r}"
                )

    inspect(rec.get("objects"), "objects")
    inspect(rec.get("fused"), "fused")
    raw_per_camera = rec.get("raw_per_camera")
    if isinstance(raw_per_camera, list):
        for camera_index, camera in enumerate(raw_per_camera):
            if isinstance(camera, dict):
                inspect(camera.get("objects"), f"raw_per_camera[{camera_index}].objects")
    return notes


def _duplicate_frame_key_notes(
    keys: list[tuple[str, Any]],
    *,
    side: str,
) -> list[str]:
    # ``repr`` also makes malformed, unhashable fallback values safe to diagnose;
    # frame validation separately rejects those values.
    rendered = [repr(key) for key in keys]
    return [
        f"duplicate_frame_identity:{side}:key={key}"
        for key, count in Counter(rendered).items()
        if count > 1
    ]


def _equivalence_structure_errors(
    live_records: list[dict[str, Any]],
    replay_records: list[dict[str, Any]],
    *,
    max_notes: int = 10,
) -> list[str]:
    notes: list[str] = []
    if not live_records or not replay_records:
        notes.append(
            f"empty_comparison:live_frames={len(live_records)}:replay_frames={len(replay_records)}"
        )
        return notes

    if len(live_records) != len(replay_records):
        notes.append(f"frame_count_mismatch:live={len(live_records)}:replay={len(replay_records)}")

    live_keys = [_equivalence_frame_key(rec, i) for i, rec in enumerate(live_records)]
    replay_keys = [_equivalence_frame_key(rec, i) for i, rec in enumerate(replay_records)]

    for side, records, keys in (
        ("live", live_records, live_keys),
        ("replay", replay_records, replay_keys),
    ):
        for line_number, rec in enumerate(records, start=1):
            validation_note = _record_validation_note(
                rec,
                side=side,
                line_number=line_number,
            )
            if validation_note is not None:
                notes.append(validation_note)
            notes.extend(
                _duplicate_object_notes(
                    rec,
                    side=side,
                    line_number=line_number,
                )
            )
            if len(notes) >= max_notes:
                return notes[:max_notes]
        notes.extend(_duplicate_frame_key_notes(keys, side=side))
        if len(notes) >= max_notes:
            return notes[:max_notes]

    if live_keys != replay_keys:
        missing_live = sorted(set(replay_keys) - set(live_keys), key=repr)
        missing_replay = sorted(set(live_keys) - set(replay_keys), key=repr)

        def summarize(keys: list[tuple[str, Any]]) -> str:
            shown = keys[:max_notes]
            suffix = f" (+{len(keys) - len(shown)} more)" if len(keys) > len(shown) else ""
            return f"{shown}{suffix}"

        notes.append(
            f"frame_key_mismatch:missing_in_live={summarize(missing_live)}:"
            f"missing_in_replay={summarize(missing_replay)}"
        )

    for i, (live, replay) in enumerate(zip(live_records, replay_records), start=1):
        for field in ("objects", "fused"):
            live_ids = _object_ids(live, field)
            replay_ids = _object_ids(replay, field)
            if live_ids is None and replay_ids is None:
                continue
            if live_ids != replay_ids:
                notes.append(
                    f"object_ids_mismatch:line={i}:field={field}:"
                    f"missing_in_live={sorted((replay_ids or set()) - (live_ids or set()))}:"
                    f"missing_in_replay={sorted((live_ids or set()) - (replay_ids or set()))}"
                )
                if len(notes) >= max_notes:
                    return notes

    return notes


@dataclass(frozen=True)
class ReportRow:
    input_path: str
    input_run_id: str
    clock: str
    dt_ms: int | None
    frames_total: int

    # Live-vs-replay equivalence (ignore ts_sim_ns)
    live_vs_replay_mismatches_exact: int
    live_vs_replay_mismatches_sorted: int

    # Replay determinism (run1 vs run2; includes ts_sim_ns)
    replay1_sha256: str
    replay2_sha256: str
    replay_mismatches: int

    pass_: bool
    notes: str


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("metriplane.replay.compare_determinism")
    ap.add_argument("--input", required=True, help="Input session.jsonl")
    ap.add_argument("--clock", choices=["fixed", "replay"], default="fixed")
    ap.add_argument(
        "--dt-ms", type=int, default=50, help="Required for fixed clock; ignored for replay clock"
    )
    ap.add_argument("--out-csv", required=True, help="Where to write the CSV report")
    ap.add_argument("--max-frames", type=int, default=None, help="Optional cap for quick runs")

    args = ap.parse_args(argv)

    if args.max_frames is not None and args.max_frames <= 0:
        ap.error("--max-frames must be greater than zero")

    in_path = Path(args.input)
    if not in_path.is_file():
        raise SystemExit(f"input not found: {in_path}")

    header = _read_first_header(in_path) or {}
    input_run_id = str(header.get("run_id") or "replay")

    clock = str(args.clock)
    dt_ms = int(args.dt_ms) if args.dt_ms is not None else None
    if clock == "fixed" and dt_ms is None:
        raise SystemExit("--dt-ms is required when --clock fixed")

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    # --- Generate two replay outputs (determinism check) ---
    tmp_dir = out_csv.parent / (out_csv.stem + "_artifacts")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    out1 = tmp_dir / "replay_out_1.jsonl"
    out2 = tmp_dir / "replay_out_2.jsonl"

    cfg_common = EngineConfig(
        input_path=in_path,
        clock=("fixed" if clock == "fixed" else "replay"),
        dt_ms=(dt_ms if clock == "fixed" else None),
        run_id=input_run_id,  # match live session run_id for equivalence compare
        output_max_frames=(int(args.max_frames) if args.max_frames is not None else None),
    )

    write_outputs_jsonl(out1, iter_replay_outputs(cfg_common))
    write_outputs_jsonl(out2, iter_replay_outputs(cfg_common))

    sha1 = _sha256_file(out1)
    sha2 = _sha256_file(out2)

    # Replay determinism: exact byte equality should hold
    replay_mismatches = 0 if sha1 == sha2 else 1

    # --- Live vs replay equivalence ---
    if args.max_frames is None:
        live_records = list(_iter_non_header_records(in_path))
        replay_records = list(_iter_non_header_records(out1))
    else:
        live_records = list(islice(_iter_non_header_records(in_path), args.max_frames))
        replay_records = list(islice(_iter_non_header_records(out1), args.max_frames))

    frames_total = min(len(live_records), len(replay_records))
    structure_errors = _equivalence_structure_errors(live_records, replay_records)

    # "Exact" equivalence ignoring only ts_sim_ns (but preserving list order)
    _, mism_exact, _ = _compare_records(
        live_records[:frames_total],
        replay_records[:frames_total],
        drop_ts_sim_ns=True,
        sort_objects=False,
    )

    # "Sorted" equivalence: also enforce stable ordering of objects lists for semantic equality
    _, mism_sorted, _ = _compare_records(
        live_records[:frames_total],
        replay_records[:frames_total],
        drop_ts_sim_ns=True,
        sort_objects=True,
    )

    passed = replay_mismatches == 0 and mism_sorted == 0 and not structure_errors

    notes = str(tmp_dir)
    if structure_errors:
        notes += "; " + "; ".join(structure_errors)

    row = ReportRow(
        input_path=str(in_path),
        input_run_id=input_run_id,
        clock=clock,
        dt_ms=dt_ms if clock == "fixed" else None,
        frames_total=frames_total,
        live_vs_replay_mismatches_exact=int(mism_exact),
        live_vs_replay_mismatches_sorted=int(mism_sorted),
        replay1_sha256=sha1,
        replay2_sha256=sha2,
        replay_mismatches=int(replay_mismatches),
        pass_=bool(passed),
        notes=notes,
    )

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "input_path",
                "input_run_id",
                "clock",
                "dt_ms",
                "frames_total",
                "live_vs_replay_mismatches_exact",
                "live_vs_replay_mismatches_sorted",
                "replay1_sha256",
                "replay2_sha256",
                "replay_mismatches",
                "PASS",
                "artifacts_dir",
            ]
        )
        w.writerow(
            [
                row.input_path,
                row.input_run_id,
                row.clock,
                "" if row.dt_ms is None else int(row.dt_ms),
                int(row.frames_total),
                int(row.live_vs_replay_mismatches_exact),
                int(row.live_vs_replay_mismatches_sorted),
                row.replay1_sha256,
                row.replay2_sha256,
                int(row.replay_mismatches),
                "true" if row.pass_ else "false",
                row.notes,
            ]
        )

    print(f"[determinism] replay sha1={sha1}")
    print(f"[determinism] replay sha2={sha2}")
    print(f"[determinism] replay_mismatches={replay_mismatches}")
    print(f"[equivalence] mismatches_exact={mism_exact} (ignoring ts_sim_ns only)")
    print(
        f"[equivalence] mismatches_sorted={mism_sorted} (ignoring ts_sim_ns + sorting object lists)"
    )
    for note in structure_errors:
        print(f"[equivalence] {note}")
    print(f"[result] PASS={str(passed).lower()}")
    print(f"[report] {out_csv}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
