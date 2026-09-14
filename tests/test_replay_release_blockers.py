# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from benchmarks.run_replay_determinism import compare
from benchmarks.run_replay_determinism import main as benchmark_main
from metriplane.cli import _main_replay
from metriplane.replay.compare_determinism import (
    _equivalence_structure_errors,
)
from metriplane.replay.compare_determinism import (
    main as equivalence_main,
)
from metriplane.replay.engine import EngineConfig, iter_replay_outputs


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _frame(frame_id: int, ts: float, object_ids: tuple[str, ...] = ("7",)) -> dict:
    return {
        "source_backend": "test",
        "frame_id": frame_id,
        "ts": ts,
        "objects": [
            {"id": object_id, "pos_world": [float(frame_id), 0.0, 0.0]} for object_id in object_ids
        ],
    }


def test_replay_engine_prefers_authoritative_ts_sim_ns(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "conflicting.jsonl",
        [
            {**_frame(1, 100.0), "ts_ns": 9_000, "ts_sim_ns": 5_000_000_000},
            {**_frame(2, 200.0), "ts_ns": 10_000, "ts_sim_ns": 5_100_000_000},
        ],
    )

    outputs = list(iter_replay_outputs(EngineConfig(input_path=path, clock="replay")))

    assert [record["ts_sim_ns"] for record in outputs] == [0, 100_000_000]


def test_replay_engine_rejects_decrease_after_later_timestamp(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "nonmonotonic.jsonl",
        [
            {**_frame(1, 1.0), "ts_sim_ns": 100},
            {**_frame(2, 2.0), "ts_sim_ns": 300},
            {**_frame(3, 3.0), "ts_sim_ns": 200},
        ],
    )

    with pytest.raises(ValueError, match="Non-monotonic timestamps"):
        list(iter_replay_outputs(EngineConfig(input_path=path, clock="replay")))


@pytest.mark.parametrize("record", ["{not-json}", "[]"])
def test_replay_engine_rejects_invalid_jsonl_records(
    tmp_path: Path,
    record: str,
) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(_frame(1, 1.0)) + "\n" + record + "\n")

    with pytest.raises(ValueError, match="Invalid JSONL"):
        list(iter_replay_outputs(EngineConfig(input_path=path, clock="replay")))


def test_replay_engine_rejects_nonpositive_frame_cap(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "input.jsonl", [_frame(1, 1.0)])

    with pytest.raises(ValueError, match="greater than zero"):
        list(
            iter_replay_outputs(
                EngineConfig(input_path=path, output_max_frames=0),
            )
        )


def test_replay_cli_keeps_speed_compatibility_with_explicit_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = _write_jsonl(tmp_path / "input.jsonl", [_frame(1, 1.0)])
    output_path = tmp_path / "output.jsonl"

    assert (
        _main_replay(
            [
                "--input",
                str(input_path),
                "--output-file",
                str(output_path),
                "--speed",
                "2",
            ]
        )
        == 0
    )

    assert output_path.is_file()
    assert "retained for compatibility" in capsys.readouterr().err


def test_benchmark_keeps_success_csv_compatible(tmp_path: Path) -> None:
    records = [
        {"type": "run_header", "run_id": "test"},
        {**_frame(1, 1.0), "ts_sim_ns": 0},
    ]
    a = _write_jsonl(tmp_path / "a.jsonl", records)
    b = _write_jsonl(tmp_path / "b.jsonl", records)
    out = tmp_path / "report.csv"

    assert benchmark_main(["--a", str(a), "--b", str(b), "--out", str(out)]) == 0
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "frames_compared",
        "object_pairs_compared",
        "mean_pos_diff_cm",
        "max_pos_diff_cm",
        "event_mismatch_count",
        "pass",
    ]
    assert rows[0]["pass"] == "true"


@pytest.mark.parametrize("mutation", ["drop_frame", "drop_object", "empty"])
def test_benchmark_fails_incomplete_comparisons(tmp_path: Path, mutation: str) -> None:
    a_records = [
        {**_frame(1, 1.0), "ts_sim_ns": 0},
        {**_frame(2, 2.0, ("7", "12")), "ts_sim_ns": 1_000_000_000},
    ]
    b_records = [dict(record) for record in a_records]
    if mutation == "drop_frame":
        b_records.pop()
    elif mutation == "drop_object":
        b_records[1] = {
            **b_records[1],
            "objects": b_records[1]["objects"][:1],
        }
    else:
        a_records = []
        b_records = []

    a = _write_jsonl(tmp_path / "a.jsonl", a_records)
    b = _write_jsonl(tmp_path / "b.jsonl", b_records)
    out = tmp_path / "report.csv"

    result = compare(a, b)
    assert result["comparison_valid"] is False
    assert benchmark_main(["--a", str(a), "--b", str(b), "--out", str(out)]) == 1
    assert "false" in out.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        ("missing_position", "invalid_position_count"),
        ("nonfinite_position", "invalid_position_count"),
        ("changed_frame_id", "missing_frame_count_in_a"),
        ("reordered_frames", "frame_order_matches"),
        ("duplicate_object_id", "duplicate_object_ids"),
        ("duplicate_frame_id", "duplicate_frame_ids_in_b"),
        ("duplicate_tick", "duplicate_ticks_in_b"),
    ],
)
def test_benchmark_rejects_structurally_invalid_frames(
    tmp_path: Path,
    mutation: str,
    diagnostic: str,
) -> None:
    a_records = [
        {**_frame(1, 1.0), "ts_sim_ns": 0},
        {**_frame(2, 2.0), "ts_sim_ns": 1_000_000_000},
    ]
    b_records = json.loads(json.dumps(a_records))
    if mutation == "missing_position":
        b_records[0]["objects"][0].pop("pos_world")
    elif mutation == "nonfinite_position":
        b_records[0]["objects"][0]["pos_world"] = [float("nan"), 0.0, 0.0]
    elif mutation == "changed_frame_id":
        b_records[0]["frame_id"] = 99
    elif mutation == "reordered_frames":
        b_records.reverse()
    elif mutation == "duplicate_object_id":
        b_records[0]["objects"].append(dict(b_records[0]["objects"][0]))
    elif mutation == "duplicate_frame_id":
        for record in a_records + b_records:
            record.pop("ts_sim_ns")
        a_records[1]["frame_id"] = a_records[0]["frame_id"]
        b_records[1]["frame_id"] = b_records[0]["frame_id"]
    else:
        b_records[1]["ts_sim_ns"] = b_records[0]["ts_sim_ns"]

    a = _write_jsonl(tmp_path / "a.jsonl", a_records)
    b = _write_jsonl(tmp_path / "b.jsonl", b_records)
    out = tmp_path / "report.csv"

    result = compare(a, b)
    assert result["comparison_valid"] is False
    assert diagnostic in result
    if mutation == "reordered_frames":
        assert result[diagnostic] is False
    elif mutation in {"missing_position", "nonfinite_position"}:
        assert result[diagnostic] > 0
    else:
        assert result[diagnostic]
    assert benchmark_main(["--a", str(a), "--b", str(b), "--out", str(out)]) == 1


@pytest.mark.parametrize("threshold", ["nan", "inf", "-0.1"])
def test_benchmark_rejects_invalid_position_threshold(
    tmp_path: Path,
    threshold: str,
) -> None:
    records = [{**_frame(1, 1.0), "ts_sim_ns": 0}]
    a = _write_jsonl(tmp_path / "a.jsonl", records)
    b = _write_jsonl(tmp_path / "b.jsonl", records)
    out = tmp_path / "report.csv"

    assert (
        benchmark_main(
            [
                "--a",
                str(a),
                "--b",
                str(b),
                "--out",
                str(out),
                "--max-pos-diff-cm",
                threshold,
            ]
        )
        == 2
    )
    assert not out.exists()


def test_equivalence_reports_frame_and_object_loss() -> None:
    live = [_frame(1, 1.0), _frame(2, 2.0, ("7", "12"))]
    replay = [_frame(1, 1.0, ())]

    errors = _equivalence_structure_errors(live, replay)

    assert any("frame_count_mismatch" in error for error in errors)
    assert any("frame_key_mismatch" in error for error in errors)
    assert any("object_ids_mismatch" in error for error in errors)


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        ("duplicate_frame", "duplicate_frame_identity"),
        ("duplicate_object", "duplicate_object_id"),
        ("blank_object_id", "invalid_frame"),
        ("malformed_object", "invalid_frame"),
        ("malformed_objects_list", "invalid_frame"),
        ("malformed_frame_identity", "invalid_frame"),
    ],
)
def test_equivalence_rejects_invalid_frame_structure(
    mutation: str,
    diagnostic: str,
) -> None:
    records = [_frame(1, 1.0), _frame(2, 2.0)]
    if mutation == "duplicate_frame":
        records[1]["frame_id"] = records[0]["frame_id"]
    elif mutation == "duplicate_object":
        records[0]["objects"].append(dict(records[0]["objects"][0]))
    elif mutation == "blank_object_id":
        records[0]["objects"][0]["id"] = "   "
    elif mutation == "malformed_object":
        records[0]["objects"] = ["not-an-object"]
    elif mutation == "malformed_objects_list":
        records[0]["objects"] = {"id": "7"}
    else:
        records[0]["frame_id"] = [1]

    errors = _equivalence_structure_errors(records, json.loads(json.dumps(records)))

    assert any(diagnostic in error for error in errors)


def test_equivalence_cli_caps_live_and_replay_records(tmp_path: Path) -> None:
    input_path = _write_jsonl(
        tmp_path / "input.jsonl",
        [
            {**_frame(1, 0.0), "run_id": "replay"},
            {**_frame(2, 0.05), "run_id": "replay"},
        ],
    )
    report = tmp_path / "equivalence.csv"

    status = equivalence_main(
        [
            "--input",
            str(input_path),
            "--clock",
            "fixed",
            "--dt-ms",
            "50",
            "--max-frames",
            "1",
            "--out-csv",
            str(report),
        ]
    )

    assert status == 0
    with report.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["frames_total"] == "1"
    assert row["PASS"] == "true"


@pytest.mark.parametrize("max_frames", ["0", "-1"])
def test_equivalence_cli_rejects_nonpositive_frame_cap(
    tmp_path: Path,
    max_frames: str,
) -> None:
    input_path = _write_jsonl(tmp_path / "input.jsonl", [_frame(1, 0.0)])
    report = tmp_path / "equivalence.csv"

    with pytest.raises(SystemExit) as exc_info:
        equivalence_main(
            [
                "--input",
                str(input_path),
                "--out-csv",
                str(report),
                "--max-frames",
                max_frames,
            ]
        )

    assert exc_info.value.code == 2
    assert not report.exists()
