<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Schema v1.0 (Locked)

## Purpose
Define the versioned message contract for streaming and recording.

## Authoritative Source
**⚠️ IMPORTANT**: This document is a simplified reference. For the exact, authoritative schema definition, see:
- **`metriplane/schema.py`** (Pydantic models)

All fields, types, and optionality rules are defined in the Python code. This document provides human-readable documentation only.

---

## Top-level message: FrameStateModel

### Core Fields (v1.0)
- `schema_version` (string) — fixed value: `"1.0"`
- `source_backend` (string) — e.g. `"aruco"`, detection backend name
- `ts` (float) — event timestamp (seconds since epoch)
- `frame_id` (int) — monotonically increasing per run
- `objects` (list[ObjectStateModel]) — tracked objects (legacy: first camera or fused)
- `events` (list[ZoneEventModel]) — zone enter/exit events
- `alerts` (list[dict]) — optional operational/Sentinel alerts; defaults to an empty list
- `metrics` (dict | null) — optional metrics snapshot

### M9 Provenance Fields (optional, populated at runtime)
- `run_id` (str | null) — unique run identifier
- `config_hash` (str | null) — SHA256 of canonical config
- `git_commit` (str | null) — git commit hash at runtime
- `ts_sim_ns` (int | null) — authoritative simulation time (nanoseconds, for determinism)

### M8 Multi-Camera Fusion Fields (optional)
- `fused` (list[ObjectStateModel] | null) — fused observations across cameras
- `raw_per_camera` (list[CameraFrameModel] | null) — per-camera raw observations

### Metriplane 0.2.0 Operational Layers (optional)
- Object registry metadata may be carried in `ObjectStateModel.extra` or
  resolved downstream by the registry.
- Sentinel alerts are additive and do not replace zone events.
- Contract, incident, forecast, camera-trust, and assistant records live in
  downstream modules and evidence bundles rather than changing the required
  frame-state fields.

---

## Sub-Models

### ObjectStateModel
- `id` (str) — unique object/marker identifier
- `pos_world` (tuple[float, float, float] | null) — `[x, y, z]` meters, world coordinates
- `vel_world` (tuple[float, float, float] | null) — `[vx, vy, vz]` m/s, velocity (Kalman fusion only)
- `zone` (str | null) — zone ID if object inside a defined zone
- `confidence` (float | null) — detection confidence (0.0-1.0)
- `extra` (dict | null) — backend-specific metadata

### ZoneEventModel
- `type` (Literal["zone_enter", "zone_exit"]) — event type
- `object_id` (str) — which object triggered the event
- `zone` (str) — which zone
- `ts` (float) — event timestamp (seconds since epoch)

### CameraFrameModel (M8 multi-camera)
- `camera_id` (str) — camera identifier
- `ts_cam_read` (float) — timestamp when frame was captured
- `objects` (list[ObjectStateModel]) — objects detected by this camera
- `metrics` (dict | null) — optional per-camera metrics

---

## Compatibility rules
- Schema is versioned via `schema_version`.
- Backward-incompatible changes require a version bump.
- v1.x: do not remove fields; only add optional fields.
