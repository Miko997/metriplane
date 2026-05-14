# Onboarding Summary

**Evidence ID**: `onboarding_001`  
**Commit**: `15037e0` | **Status**: ✅ EXECUTED  
**Date**: 2026-04-29  
**Artifact**: `evidence/onboarding/onboarding_001.md`

---

## Environment Label

> **Fresh clone on same machine — NOT clean-machine, NOT fresh user**

The run used a fresh `git clone` to `/tmp/metriplane-onboarding` on the
development machine. Pip cache was warm. Live 2-camera hardware was connected.
A bare-VM experiment with cold cache is needed before making quantitative
time claims in the evaluation.

---

## Results

| Metric | Value |
|--------|-------|
| Time to first live demo (incl. tests, warm cache) | **2.1 min** (123s) |
| Time to live stack only (venv + install + start) | **~20s** (warm cache) |
| Steps to first demo (non-trivial) | **6** |
| Friction steps (undocumented) | **1** (pytest not in deps) |
| Tests from clone | **193/193 PASS** |
| Stack start time | **3s** |
| All 14 health components OK | ✅ |
| WebSocket schema_version | `1.0` |
| WebSocket raw_per_camera count | `2` |

---

## RQ1 Alignment

This evidence contributes to RQ1 (product value vs. sensor-heavy approaches):

**Platform friction claim (qualified):**
- A developer with Python and git can go from zero to a running 2-camera live
  digital twin in 6 non-trivial steps.
- The only undocumented step is `pip install pytest` (needed for test verification).
- The actual stack launches in 3 seconds once installed.

**Comparison baseline:**
- Sensor-heavy approaches (e.g. ROS 2 + LIDAR + proprietary SDK) typically
  require: system-level driver installation, hardware calibration GUIs, custom
  launch file configuration, and multi-terminal service startup.
- MetriPlane's equivalent is: `pip install -e . && ./tools/start_metriplane.sh --live`

**What this evidence does NOT support:**
- Clean-machine timing claims (warm pip cache inflates speed)
- Non-developer operator onboarding (assumes Python/git familiarity)
- Onboarding without live camera hardware (hardware must be pre-connected)

---

## Friction Identified

| # | Friction | Severity | Recommended Fix |
|---|----------|----------|-----------------|
| 1 | `pytest` not in `pyproject.toml` optional deps | **Medium** | Add `[dev]` extras group: `pytest`, `pytest-asyncio` |

**Recommended `pyproject.toml` addition (NOT yet done — documentation-only):**
```toml
[project.optional-dependencies]
dev = ["pytest>=7", "pytest-asyncio"]
```

Then the developer onboarding command becomes:
```bash
pip install -e ".[dev]"
pytest -q
```

---

## Pending: Clean-machine onboarding

For evaluation RQ1 quantitative adoption-friction claim, a clean-machine run is
needed with:
- Fresh Ubuntu (or Windows) install with only Python and git
- No pip cache (cold download)
- A fresh user account with no prior MetriPlane exposure
- Time measured with `time` from first `git clone` to first WebSocket frame

This would give a defensible "time to first demo on a clean machine" figure.
Current onboarding_001 provides the **command sequence** and **friction list**,
which are the prerequisite for the clean-machine run.
