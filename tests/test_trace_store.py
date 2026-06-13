from __future__ import annotations

import csv
import json

import pytest

from metriplane.trace.store import TraceStore


def make_frame(ts: float, frame_id: int, objects: list[dict], run_id: str = "test_run") -> str:
    objs = [
        {
            "id": str(o["id"]),
            "pos_world": o.get("pos"),
            "vel_world": o.get("vel"),
            "zone": o.get("zone"),
        }
        for o in objects
    ]
    return json.dumps({
        "schema_version": "1.0",
        "source_backend": "dummy",
        "run_id": run_id,
        "ts": ts,
        "frame_id": frame_id,
        "objects": objs,
        "events": [],
    })


BASIC_JSONL = "\n".join([
    make_frame(0.0, 0, [
        {"id": 7, "pos": [1.0, 0.0, 0.0]},
        {"id": 12, "pos": [0.5, 0.5, 0.0], "zone": "entry_lane"},
    ]),
    make_frame(1.0, 1, [
        {"id": 7, "pos": [2.0, 0.0, 0.0]},
        {"id": 12, "pos": [0.5, 0.5, 0.0], "zone": "entry_lane"},
    ]),
    make_frame(2.0, 2, [
        {"id": 7, "pos": [3.0, 0.0, 0.0]},
        {"id": 12, "pos": [0.5, 0.5, 0.0], "zone": "entry_lane"},
    ]),
])


def test_load_session_point_count():
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    assert len(store.points()) == 6


def test_summarize_distance():
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    summaries = {s.object_id: s for s in store.summarize()}
    assert abs(summaries["marker_7"].total_distance_m - 2.0) < 0.01


def test_summarize_zones():
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    summaries = {s.object_id: s for s in store.summarize()}
    assert summaries["marker_12"].zones_visited == ["entry_lane"]


def test_summarize_duration():
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    summaries = {s.object_id: s for s in store.summarize()}
    assert summaries["marker_7"].duration_s == 2.0


def test_export_csv_header(tmp_path):
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    out = tmp_path / "traces.csv"
    store.export_csv(out)
    with out.open() as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == ["ts", "object_id", "marker_id", "x_m", "y_m", "speed_mps", "zone", "run_id"]


def test_export_csv_row_count(tmp_path):
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    out = tmp_path / "traces.csv"
    store.export_csv(out)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 7  # 1 header + 6 data rows


def test_resolve_with_registry(tmp_path):
    reg = (
        "objects:\n"
        "  - object_id: cart_01\n"
        "    marker_id: 7\n"
        "    type: cart\n"
        "    display_name: Cart 01\n"
    )
    reg_path = tmp_path / "objects.yaml"
    reg_path.write_text(reg)
    store = TraceStore(registry_path=reg_path)
    store.load_session_text(BASIC_JSONL)
    ids = {p.object_id for p in store.points()}
    assert "cart_01" in ids


def test_resolve_fallback():
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    ids = {p.object_id for p in store.points()}
    assert "marker_7" in ids


def test_gap_detection():
    gap_jsonl = "\n".join([
        make_frame(0.0, 0, [{"id": 7, "pos": [1.0, 0.0, 0.0]}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [2.0, 0.0, 0.0]}]),
        make_frame(5.0, 2, [{"id": 7, "pos": [3.0, 0.0, 0.0]}]),
    ])
    store = TraceStore()
    store.load_session_text(gap_jsonl)
    summaries = {s.object_id: s for s in store.summarize()}
    assert summaries["marker_7"].gap_count == 1


def test_load_session_text():
    store = TraceStore()
    store.load_session_text(BASIC_JSONL)
    assert len(store.points()) > 0
