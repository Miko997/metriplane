# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.compute.select import parse_compute_config


def test_compute_backend_aliases_normalize() -> None:
    assert parse_compute_config({"backend": "cpu_numpy"}).backend == "cpu"
    assert parse_compute_config({"backend": "gpu_cupy"}).backend == "gpu"


def test_compute_backend_env_alias_normalizes(monkeypatch) -> None:
    monkeypatch.setenv("METRIPLANE_COMPUTE_BACKEND", "gpu_cupy")
    assert parse_compute_config({"backend": "cpu"}).backend == "gpu"
