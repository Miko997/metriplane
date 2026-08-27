# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from metriplane.compute.cpu_numpy import CpuNumpyBackend
from metriplane.compute.interface import FusionComputeBackend

try:
    from metriplane.compute.gpu_cupy import GpuCupyBackend, GpuUnavailable
except Exception:  # pragma: no cover
    GpuCupyBackend = None  # type: ignore
    GpuUnavailable = Exception  # type: ignore


@dataclass(frozen=True, slots=True)
class ComputeConfig:
    backend: str = "cpu"  # cpu|gpu
    allow_fallback_to_cpu: bool = True

    # GPU sub-config
    provider: str = "cupy"
    device: int = 0

    # Warmup iterations (used by benchmarks; runner may choose to ignore)
    warmup_iters: int = 20


def _as_dict(v: Any) -> dict[str, Any] | None:
    return dict(v) if isinstance(v, dict) else None


def _normalize_backend(value: str) -> str:
    aliases = {
        "cpu_numpy": "cpu",
        "numpy": "cpu",
        "gpu_cupy": "gpu",
        "cupy": "gpu",
    }
    backend = str(value or "cpu").strip().lower()
    return aliases.get(backend, backend)


def parse_compute_config(cfg_obj: Any) -> ComputeConfig:
    """Parse compute config from a Config.compute dict (or None).

    Supported YAML shape (M9.6):

    compute:
      backend: gpu  # cpu|gpu
      allow_fallback_to_cpu: true
      gpu:
        provider: cupy
        device: 0
        warmup_iters: 20

    Environment overrides (highest priority):
      METRIPLANE_COMPUTE_BACKEND / METRIPLANE_COMPUTE_BACKEND
      METRIPLANE_GPU_DEVICE / METRIPLANE_GPU_DEVICE
    """

    d = _as_dict(cfg_obj) or {}

    backend = _normalize_backend(str(d.get("backend") or "cpu"))
    allow_fb = bool(d.get("allow_fallback_to_cpu", True))

    gd = _as_dict(d.get("gpu")) or {}
    provider = str(gd.get("provider") or "cupy").strip().lower()

    device = int(gd.get("device") or 0)
    warmup_iters = int(gd.get("warmup_iters") or 20)

    # Env overrides
    env_backend = os.getenv("METRIPLANE_COMPUTE_BACKEND") or os.getenv("METRIPLANE_COMPUTE_BACKEND")
    if env_backend:
        backend = _normalize_backend(env_backend)

    env_dev = os.getenv("METRIPLANE_GPU_DEVICE") or os.getenv("METRIPLANE_GPU_DEVICE")
    if env_dev:
        try:
            device = int(env_dev)
        except Exception:
            pass

    return ComputeConfig(
        backend=backend,
        allow_fallback_to_cpu=allow_fb,
        provider=provider,
        device=device,
        warmup_iters=warmup_iters,
    )


def select_fusion_backend(
    cfg_obj: Any,
    *,
    logger: logging.Logger | None = None,
    health: Any | None = None,
) -> FusionComputeBackend:
    """Select a compute backend for the fusion compute block.

    - Returns a CPU backend by default.
    - If GPU requested, tries to initialize a CuPy backend.
    - If GPU initialization fails and allow_fallback_to_cpu=True, falls back to CPU.

    health (optional): expected to have set_ok/set_degraded/set_failed methods.
    """

    log = logger or logging.getLogger("metriplane.compute")
    cfg = parse_compute_config(cfg_obj)

    req = str(cfg.backend).strip().lower()
    if req not in ("cpu", "gpu"):
        log.warning("compute.backend=%s unsupported; using cpu", req)
        req = "cpu"

    if req == "cpu":
        b = CpuNumpyBackend()
        log.info("compute backend: %s", b.name)
        if health is not None:
            try:
                health.set_ok("compute.backend")
            except Exception:
                pass
        return b

    # GPU requested
    if cfg.provider != "cupy":
        msg = f"unsupported GPU provider '{cfg.provider}' (expected 'cupy')"
        if cfg.allow_fallback_to_cpu:
            log.warning("%s; falling back to cpu", msg)
            if health is not None:
                try:
                    health.set_degraded("compute.backend", msg)
                except Exception:
                    pass
            return CpuNumpyBackend()
        if health is not None:
            try:
                health.set_failed("compute.backend", msg)
            except Exception:
                pass
        raise ValueError(msg)

    if GpuCupyBackend is None:
        msg = "CuPy backend not available (import failed)"
        if cfg.allow_fallback_to_cpu:
            log.warning("%s; falling back to cpu", msg)
            if health is not None:
                try:
                    health.set_degraded("compute.backend", msg)
                except Exception:
                    pass
            return CpuNumpyBackend()
        raise RuntimeError(msg)

    try:
        gpu_backend = GpuCupyBackend(device=int(cfg.device))
        log.info("compute backend: %s device=%d", gpu_backend.name, int(cfg.device))
        if health is not None:
            try:
                health.set_ok("compute.backend")
            except Exception:
                pass
        return gpu_backend
    except Exception as e:
        msg = f"GPU backend init failed: {type(e).__name__}: {e}"
        if cfg.allow_fallback_to_cpu:
            log.warning("%s; falling back to cpu", msg)
            if health is not None:
                try:
                    health.set_degraded("compute.backend", msg)
                except Exception:
                    pass
            return CpuNumpyBackend()
        if health is not None:
            try:
                health.set_failed("compute.backend", msg)
            except Exception:
                pass
        raise
