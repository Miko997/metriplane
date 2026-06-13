from __future__ import annotations

from benchmarks.physical_observability.metrics import (
    compare_replay_hash,
    latency_summary,
    precision_recall_f1,
)
from benchmarks.physical_observability.scenarios import (
    discover_scenarios,
    run_all,
    run_scenario,
)


# --- metrics --------------------------------------------------------------

def test_prf_perfect_match():
    pr = precision_recall_f1(["a", "b"], ["a", "b"])
    assert pr["precision"] == 1.0 and pr["recall"] == 1.0 and pr["f1"] == 1.0


def test_prf_false_positive():
    pr = precision_recall_f1(["a"], ["a", "b"])
    assert pr["fp"] == 1
    assert pr["precision"] < 1.0
    assert pr["recall"] == 1.0


def test_prf_false_negative():
    pr = precision_recall_f1(["a", "b"], ["a"])
    assert pr["fn"] == 1
    assert pr["recall"] < 1.0


def test_replay_hash_compare():
    assert compare_replay_hash("x", "x") is True
    assert compare_replay_hash("x", "y") is False


def test_latency_summary():
    s = latency_summary([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s["p50_ms"] in (3.0, 2.0)
    assert s["n"] == 5


def test_latency_summary_empty():
    assert latency_summary([])["n"] == 0


# --- scenarios ------------------------------------------------------------

def test_discovers_three_scenarios():
    names = discover_scenarios()
    assert "blocked_path_001" in names
    assert "restricted_zone_001" in names
    assert "unsafe_proximity_001" in names


def test_blocked_path_passes():
    rows = run_scenario("blocked_path_001")
    assert all(r.passed for r in rows)
    # the expected incident rule must be observed
    inc_recall = [r for r in rows if r.task == "incidents" and r.metric == "recall"]
    assert inc_recall and inc_recall[0].value == 1.0


def test_restricted_zone_passes():
    rows = run_scenario("restricted_zone_001")
    assert all(r.passed for r in rows)


def test_unsafe_proximity_passes():
    rows = run_scenario("unsafe_proximity_001")
    assert all(r.passed for r in rows)


def test_run_all_passes():
    rows = run_all()
    assert len(rows) == 24  # 3 scenarios x 8 checks
    assert all(r.passed for r in rows)


def test_determinism_check_present():
    rows = run_scenario("blocked_path_001")
    det = [r for r in rows if r.task == "replay_determinism"]
    assert det and det[0].passed
