# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

import yaml


# ======================================================================================
# Runtime config
# ======================================================================================


@dataclass(frozen=True, slots=True)
class CameraSpec:
    """
    One camera input for single-cam OR fusion/multi-cam runs.

    You can identify a camera either by:
      - index: OpenCV index (0,2,...)  [what you're using now]
      - device: explicit /dev/videoX or /dev/v4l/by-id/... path (recommended for stability)

    intrinsics_file + mapping_file:
      - optional overrides per camera
      - if omitted, we will try to auto-resolve from the active profile:
          calib/profiles/<profile>/<name>/camera.yaml
          calib/profiles/<profile>/<name>/mapping.yaml
    """

    name: str = "cam0"
    index: int | None = None
    device: str | None = None

    intrinsics_file: str | None = None
    mapping_file: str | None = None


@dataclass(frozen=True, slots=True)
class Config:
    # -----------------------------
    # Inputs / backends
    # -----------------------------
    camera_backend: str = "usb"
    vision_backend: str = "aruco"
    target_fps: int = 30

    # Legacy single-camera selectors (keep for backwards compatibility)
    camera_index: int | None = 0
    camera_device: str | None = None

    # NEW: multi-camera (fusion) selector
    # If provided, your fusion pipeline should use this instead of camera_index/device.
    cameras: tuple[CameraSpec, ...] | None = None

    # Fusion knobs (safe defaults; only used if your fusion code reads them)
    fusion_enable: bool = False
    fusion_method: str = "nearest"  # e.g. nearest | average | best_conf
    fusion_max_merge_dist_m: float = 0.15

    # --- Fusion config (NEW) ---
    fusion: dict[str, Any] | None = None

    # Optional filtering for cleaner demos
    exclude_marker_ids: list[int] | None = None
    allowed_marker_ids: list[int] | None = None

    # Optional recordings
    record_video: str | None = None
    record_jsonl: str | None = None  # e.g. evidence/sessions/m6_live_001.jsonl

    # M4: object lifetime
    object_timeout_s: float = 2.0

    # M4: metrics endpoint
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 8000

    # WS server (Omniverse connects here)
    ws_host: str = "127.0.0.1"
    ws_port: int = 8765

    # -----------------------------
    # Profile selector
    # -----------------------------
    # If provided, code will prefer calib/profiles/<profile>/...
    # If missing, code will look for calib/active_profile.yaml
    profile: str | None = None

    # Single-camera calibration files (optional)
    intrinsics_file: str | None = None  # e.g. calib/camera.yaml
    mapping_file: str | None = None  # e.g. calib/mapping.yaml

    # Zones + analytics
    zones_file: str | None = None  # e.g. calib/zones.yaml
    analytics_out_dir: str | None = None  # e.g. evidence/analytics/m6_live_001

    # -----------------------------
    # Docker/offline source modes (M9)
    # -----------------------------
    # camera | replay | dummy
    source_mode: str = "camera"

    # Replay controls (used when source_mode == "replay")
    replay_input: str | None = None
    replay_speed: float = 1.0
    replay_loop: bool = True

    # Optional: where docker wants run artifacts (not required by runtime yet, but parsed)
    runs_dir: str | None = None

    # M9.3: health endpoint / registry controls
    # Shape: {"enabled": true} or {"enable": true}
    health: dict[str, Any] | None = None

    # M9.5: timing controls (StageTiming)
    # Shape: {"enabled": true} or {"enable": true}
    timing: dict[str, Any] | None = None

    # M9.6: compute backend selection (cpu/gpu)
    compute: dict[str, Any] | None = None

    # Optional: fault injection config section (metriplane.run uses this pattern)
    faults: dict[str, Any] | None = None


# ======================================================================================
# Config loading (YAML)
# ======================================================================================


def _parse_camera_specs(v: Any) -> tuple[CameraSpec, ...] | None:
    """
    Accepts multiple YAML shapes:

    List form (recommended):
    cameras:
      - {name: cam0, index: 0}
      - {name: cam1, index: 2}

    Shorthand list:
    cameras: [0, 2]              # -> cam0(index=0), cam1(index=2)
    cameras: [/dev/video0, ...]  # -> cam0(device=...), cam1(device=...)

    Dict form (legacy / convenience):
    cameras:
      cam0: 0
      cam1: 2
    """
    if v is None:
        return None

    cam_fields = {f.name for f in fields(CameraSpec)}
    out: list[CameraSpec] = []

    if isinstance(v, dict):
        for k, item in v.items():
            name = str(k).strip() or "cam0"
            if isinstance(item, int):
                out.append(CameraSpec(name=name, index=item))
                continue
            if isinstance(item, str):
                out.append(CameraSpec(name=name, device=item))
                continue
            if isinstance(item, dict):
                kwargs = {kk: item[kk] for kk in item.keys() if kk in cam_fields}
                kwargs["name"] = name
                out.append(CameraSpec(**kwargs))
                continue
            raise ValueError(f"Invalid cameras['{name}'] entry type: {type(item)}")
        return tuple(out)

    if not isinstance(v, list):
        raise ValueError("Config key 'cameras' must be a list or dict")

    for i, item in enumerate(v):
        if isinstance(item, int):
            out.append(CameraSpec(name=f"cam{i}", index=item))
            continue

        if isinstance(item, str):
            out.append(CameraSpec(name=f"cam{i}", device=item))
            continue

        if isinstance(item, dict):
            kwargs = {k: item[k] for k in item.keys() if k in cam_fields}
            name = str(kwargs.get("name", "")).strip()
            if not name:
                kwargs["name"] = f"cam{i}"
            out.append(CameraSpec(**kwargs))
            continue

        raise ValueError(f"Invalid cameras[{i}] entry type: {type(item)}")

    return tuple(out)


def load_config(path: Path) -> Config:
    """
    Load YAML into Config.

    Backwards-safe:
    - Unknown keys in YAML are ignored.
    - 'cameras' supports structured lists/dicts for fusion/multi-camera.
    - Supports Docker nested config keys (metrics, streaming.ws, time, replay, source).
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config must parse to a dict. Path={path}")

    valid = {f.name for f in fields(Config)}
    kwargs: dict[str, Any] = {k: v for (k, v) in raw.items() if k in valid}

    # Allow nested fusion config
    if "fusion" in raw and isinstance(raw["fusion"], dict):
        kwargs["fusion"] = raw["fusion"]

    # Allow marker filtering lists
    for key in ("exclude_marker_ids", "allowed_marker_ids"):
        if key in raw and isinstance(raw[key], list):
            kwargs[key] = [int(x) for x in raw[key]]

    if "cameras" in raw:
        kwargs["cameras"] = _parse_camera_specs(raw.get("cameras"))

    # health:
    h = raw.get("health")
    if isinstance(h, dict):
        hv = dict(h)
        if "enabled" not in hv and "enable" in hv:
            hv["enabled"] = bool(hv.get("enable"))
        kwargs["health"] = hv
    elif isinstance(h, bool):
        kwargs["health"] = {"enabled": bool(h)}

    # timing:
    tcfg = raw.get("timing")
    if isinstance(tcfg, dict):
        tv = dict(tcfg)
        if "enabled" not in tv and "enable" in tv:
            tv["enabled"] = bool(tv.get("enable"))
        kwargs["timing"] = tv
    elif isinstance(tcfg, bool):
        kwargs["timing"] = {"enabled": bool(tcfg)}

    # compute:
    ccfg = raw.get("compute")
    if isinstance(ccfg, dict):
        kwargs["compute"] = dict(ccfg)

    # faults:
    fcfg = raw.get("faults")
    if isinstance(fcfg, dict):
        kwargs["faults"] = dict(fcfg)

    # -----------------------------
    # Docker-style nested keys support (M9)
    # -----------------------------

    # metrics:
    m = raw.get("metrics")
    if isinstance(m, dict):
        if isinstance(m.get("host"), str):
            kwargs["metrics_host"] = m["host"]
        if m.get("port") is not None:
            kwargs["metrics_port"] = int(m["port"])

    # streaming.ws:
    s = raw.get("streaming")
    if isinstance(s, dict):
        ws = s.get("ws")
        if isinstance(ws, dict):
            if isinstance(ws.get("host"), str):
                kwargs["ws_host"] = ws["host"]
            if ws.get("port") is not None:
                kwargs["ws_port"] = int(ws["port"])

    # run.runs_dir:
    r = raw.get("run")
    if isinstance(r, dict):
        if isinstance(r.get("runs_dir"), str):
            kwargs["runs_dir"] = r["runs_dir"]

    # source.mode:
    src = raw.get("source")
    if isinstance(src, dict) and isinstance(src.get("mode"), str):
        kwargs["source_mode"] = src["mode"].strip()

    # time.mode, time.speed, time.loop:
    t = raw.get("time")
    if isinstance(t, dict):
        tmode = t.get("mode")
        if isinstance(tmode, str) and tmode.strip().lower() == "replay":
            # If user didn't explicitly set dummy, default to replay mode.
            if str(kwargs.get("source_mode", "camera")).lower() != "dummy":
                kwargs["source_mode"] = "replay"
        if t.get("speed") is not None:
            kwargs["replay_speed"] = float(t["speed"])
        if t.get("loop") is not None:
            kwargs["replay_loop"] = bool(t["loop"])

    # replay.input:
    rep = raw.get("replay")
    if isinstance(rep, dict) and isinstance(rep.get("input"), str):
        kwargs["replay_input"] = rep["input"]

    return Config(**kwargs)


# ======================================================================================
# Profile helpers — kept in THIS module to avoid name conflicts
# ======================================================================================


@dataclass(frozen=True, slots=True)
class CameraCalibPaths:
    """
    Resolved per-camera calibration paths inside a profile.

    Expected layout for fusion/multi-cam:
      calib/profiles/<profile>/
        anchors.yaml
        zones.yaml
        cam0/
          camera.yaml   (optional but recommended)
          mapping.yaml  (recommended)
        cam1/
          camera.yaml
          mapping.yaml
    """

    name: str
    cam_dir: Path
    intrinsics: Path | None
    mapping: Path | None


@dataclass(frozen=True, slots=True)
class CalibPaths:
    """
    Resolved per-profile calibration paths.

    Supports BOTH layouts:

    Single-cam layout:
      calib/profiles/<profile>/
        anchors.yaml
        mapping.yaml
        zones.yaml
        test_points.yaml
        camera.yaml (optional)

    Fusion layout:
      calib/profiles/<profile>/
        anchors.yaml
        zones.yaml
        cam0/{camera.yaml,mapping.yaml}
        cam1/{camera.yaml,mapping.yaml}
        test_points.yaml (optional)
    """

    profile: str
    profile_dir: Path

    anchors: Path
    zones: Path

    # Legacy single-camera slots:
    mapping: Path
    test_points: Path
    intrinsics: Path | None = None

    # NEW: discovered multi-camera sub-calibs (cam0, cam1, ...)
    cameras: tuple[CameraCalibPaths, ...] | None = None


def load_active_profile(
    active_profile_path: Path = Path("calib/active_profile.yaml"),
) -> str | None:
    """
    Read calib/active_profile.yaml:
      profile: board_110x40_warehouse_story_v1_fusion
    """
    if not active_profile_path.is_file():
        return None

    try:
        data = yaml.safe_load(active_profile_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    if isinstance(data, dict):
        p = data.get("profile") or data.get("name")
        if p is None:
            return None
        p = str(p).strip()
        return p or None

    if isinstance(data, str):
        p = data.strip()
        return p or None

    return None


def resolve_profile(
    profile: str | None, *, active_profile_path: Path = Path("calib/active_profile.yaml")
) -> str | None:
    """
    Resolve profile name:
    - prefer explicit `profile`
    - else use calib/active_profile.yaml
    """
    if profile is not None and str(profile).strip():
        return str(profile).strip()
    return load_active_profile(active_profile_path)


def resolve_profile_dir(
    profile: str | None,
    *,
    calib_root: Path = Path("calib"),
    active_profile_path: Path | None = None,
    strict: bool = True,
) -> Path | None:
    """
    Resolve calib/profiles/<profile> directory.
    If strict=False: return None when unresolved.
    """
    ap = active_profile_path or (calib_root / "active_profile.yaml")
    prof = resolve_profile(profile, active_profile_path=ap)
    if not prof:
        if strict:
            raise ValueError("No profile specified and calib/active_profile.yaml missing/empty.")
        return None

    d = calib_root / "profiles" / prof
    if not d.is_dir():
        if strict:
            raise FileNotFoundError(f"Profile directory not found: {d}")
        return None
    return d


def _discover_camera_dirs(profile_dir: Path) -> tuple[CameraCalibPaths, ...] | None:
    cams: list[CameraCalibPaths] = []
    for child in sorted(profile_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if not child.name.startswith("cam"):
            continue

        intr = child / "camera.yaml"

        # Prefer known-good mapping_raw.yaml, fallback to mapping.yaml
        m_raw = child / "mapping_raw.yaml"
        m_std = child / "mapping.yaml"
        mapping = m_raw if m_raw.is_file() else m_std

        cams.append(
            CameraCalibPaths(
                name=child.name,
                cam_dir=child,
                intrinsics=(intr if intr.is_file() else None),
                mapping=(mapping if mapping.is_file() else None),
            )
        )
    return tuple(cams) if cams else None


def maybe_get_calib_paths(
    profile: str | None,
    *,
    calib_root: Path = Path("calib"),
    active_profile_path: Path | None = None,
) -> CalibPaths | None:
    """
    Best-effort (non-throwing) profile resolution.
    Returns None if no profile (or directory missing).

    For fusion profiles:
      - discovers cam0/, cam1/, ...
      - sets legacy `mapping` to:
          1) profile_dir/mapping.yaml if it exists
          2) else cam0/mapping.yaml if it exists
          3) else profile_dir/mapping.yaml (fallback path)
      - sets `intrinsics` similarly (root camera.yaml, else cam0/camera.yaml)
    """
    ap = active_profile_path or (calib_root / "active_profile.yaml")
    prof = resolve_profile(profile, active_profile_path=ap)
    if not prof:
        return None

    d = calib_root / "profiles" / prof
    if not d.is_dir():
        return None

    cams = _discover_camera_dirs(d)

    root_intr = d / "camera.yaml"
    root_map = d / "mapping.yaml"
    root_map_raw = d / "mapping_raw.yaml"

    intrinsics = root_intr if root_intr.is_file() else None
    mapping = root_map_raw if root_map_raw.is_file() else root_map

    # If no root mapping.yaml but we have cam0 mapping, use that for legacy field.
    if (not root_map.is_file()) and cams:
        cam0 = next((c for c in cams if c.name == "cam0"), cams[0])
        if cam0.mapping is not None:
            mapping = cam0.mapping

    # If no root camera.yaml but we have cam0 intrinsics, use it.
    if intrinsics is None and cams:
        cam0 = next((c for c in cams if c.name == "cam0"), cams[0])
        if cam0.intrinsics is not None:
            intrinsics = cam0.intrinsics

    return CalibPaths(
        profile=prof,
        profile_dir=d,
        anchors=d / "anchors.yaml",
        zones=d / "zones.yaml",
        mapping=mapping,
        test_points=d / "test_points.yaml",
        intrinsics=intrinsics,
        cameras=cams,
    )


# ======================================================================================
# Convenience: apply profile defaults to runtime config
# ======================================================================================


def apply_profile_defaults(cfg: Config, *, calib_root: Path = Path("calib")) -> Config:
    """
    Returns a NEW Config where missing calibration paths are auto-filled from the active profile.

    This is intentionally non-throwing: if files are missing, we leave fields as-is.
    """
    cal = maybe_get_calib_paths(cfg.profile, calib_root=calib_root)
    if cal is None:
        return cfg

    # Fill global/single-cam defaults if missing
    intr = cfg.intrinsics_file
    if intr is None and cal.intrinsics is not None:
        intr = str(cal.intrinsics)

    mp = cfg.mapping_file
    if mp is None and cal.mapping is not None:
        mp = str(cal.mapping)

    zf = cfg.zones_file
    if zf is None and cal.zones.is_file():
        zf = str(cal.zones)

    # Fill per-camera defaults if we have cameras configured
    cams_out: tuple[CameraSpec, ...] | None = cfg.cameras
    if cfg.cameras:
        # Build lookup for discovered cam dirs
        cam_lookup: dict[str, CameraCalibPaths] = {c.name: c for c in (cal.cameras or ())}

        new_list: list[CameraSpec] = []
        for c in cfg.cameras:
            resolved_intr = c.intrinsics_file
            resolved_map = c.mapping_file

            # Prefer explicit per-camera file settings. Otherwise use profile camX files.
            if resolved_intr is None:
                prof_cam = cam_lookup.get(c.name)
                if prof_cam and prof_cam.intrinsics is not None:
                    resolved_intr = str(prof_cam.intrinsics)
                elif intr is not None:
                    resolved_intr = intr

            if resolved_map is None:
                prof_cam = cam_lookup.get(c.name)
                if prof_cam and prof_cam.mapping is not None:
                    resolved_map = str(prof_cam.mapping)
                elif mp is not None:
                    resolved_map = mp

            new_list.append(
                replace(
                    c,
                    intrinsics_file=resolved_intr,
                    mapping_file=resolved_map,
                )
            )

        cams_out = tuple(new_list)

    return replace(
        cfg,
        intrinsics_file=intr,
        mapping_file=mp,
        zones_file=zf,
        cameras=cams_out,
    )
