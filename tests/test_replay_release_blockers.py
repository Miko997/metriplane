# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from benchmarks.run_replay_determinism import compare, main as benchmark_main
from metriplane.replay.compare_determinism import (
    _equivalence_structure_errors,
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
            {"id": object_id, "pos_world": [float(frame_id), 0.0, 0.0]}
            for object_id in object_ids
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


def test_equivalence_reports_frame_and_object_loss() -> None:
    live = [_frame(1, 1.0), _frame(2, 2.0, ("7", "12"))]
    replay = [_frame(1, 1.0, ())]

    errors = _equivalence_structure_errors(live, replay)

    assert any("frame_count_mismatch" in error for error in errors)
    assert any("frame_key_mismatch" in error for error in errors)
    assert any("object_ids_mismatch" in error for error in errors)


def test_equivalence_cli_returns_failure_for_truncated_output(tmp_path: Path) -> None:
    input_path = _write_jsonl(
        tmp_path / "input.jsonl",
        [_frame(1, 0.0), _frame(2, 0.05)],
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

    assert status == 1
    assert "frame_count_mismatch" in report.read_text(encoding="utf-8")
