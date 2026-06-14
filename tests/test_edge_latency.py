# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from benchmarks.edge_latency import run_edge_latency

SESSION = "tests/fixtures/contracts/sentinel_minimal_session.jsonl"
RULES = "configs/rules.example.yaml"
OBJECTS = "configs/objects.example.yaml"


def test_single_pass_metrics():
    r = run_edge_latency(SESSION, duration_s=0.0, rules_path=RULES, objects_path=OBJECTS)
    assert r["frames_processed"] == 9  # fixture has 9 frames
    assert r["fps"] > 0
    assert r["p50_ms"] >= 0
    assert r["dropped_frames"] == 0


def test_duration_loops_frames():
    r = run_edge_latency(SESSION, duration_s=0.2, rules_path=RULES, objects_path=OBJECTS)
    assert r["frames_processed"] >= 9
    assert r["elapsed_s"] >= 0.2


def test_runs_without_rules():
    r = run_edge_latency(SESSION, duration_s=0.0)
    assert r["frames_processed"] == 9
