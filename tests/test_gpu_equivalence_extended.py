# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from benchmarks.gpu_fusion_scaling import _gen_observations, _percentile, _rmse
from metriplane.compute.cpu_numpy import CpuNumpyBackend


def test_cpu_avg_deterministic():
    obs = _gen_observations(50, 4, seed=7)
    b = CpuNumpyBackend()
    out1 = b.fuse_xy(obs, method="avg")
    out2 = b.fuse_xy(obs, method="avg")
    assert out1 == out2
    assert len(out1) == 50


def test_cpu_weighted_deterministic():
    obs = _gen_observations(20, 4, seed=7)
    b = CpuNumpyBackend()
    assert b.fuse_xy(obs, method="weighted") == b.fuse_xy(obs, method="weighted")


def test_avg_of_two_points():
    obs = {"a": [{"x": 0.0, "y": 0.0, "confidence": 1.0},
                 {"x": 2.0, "y": 4.0, "confidence": 1.0}]}
    out = CpuNumpyBackend().fuse_xy(obs, method="avg")
    assert out["a"] == (1.0, 2.0)


def test_invalid_method_fails():
    with pytest.raises(ValueError):
        CpuNumpyBackend().fuse_xy({"a": [{"x": 0.0, "y": 0.0}]}, method="bogus")


def test_percentile_helper():
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.5) in (2.0, 3.0)
    assert _percentile([], 0.5) == 0.0


def test_rmse_identical_outputs_is_zero():
    out = {"a": (1.0, 2.0), "b": (3.0, 4.0)}
    rmse, max_abs = _rmse(out, out)
    assert rmse == 0.0
    assert max_abs == 0.0


def test_gpu_matches_cpu_if_available():
    cupy = pytest.importorskip("cupy")
    from metriplane.compute.gpu_cupy import GpuCupyBackend
    obs = _gen_observations(100, 4, seed=11)
    cpu_out = CpuNumpyBackend().fuse_xy(obs, method="weighted")
    gpu_out = GpuCupyBackend(device=0).fuse_xy(obs, method="weighted")
    rmse, max_abs = _rmse(cpu_out, gpu_out)
    assert rmse < 1e-6
    assert max_abs < 1e-6


def test_benchmark_run_cpu_only():
    import argparse
    from benchmarks.gpu_fusion_scaling import run
    args = argparse.Namespace(
        methods=["avg"], n_objects=[1, 50], obs_per_object=[2], iters=5,
        warmup=2, backend="cpu", require_gpu=False, seed=1234)
    rows = run(args)
    assert len(rows) == 2
    assert all(r.backend == "cpu_numpy" for r in rows)
    assert all(r.p50_ms >= 0 for r in rows)
