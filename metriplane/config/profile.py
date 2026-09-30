# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metriplane.config.runtime import (
    load_active_profile as _load_active_profile,
    maybe_get_calib_paths,
    resolve_calib_root,
    resolve_profile_dir as _resolve_profile_dir,
)
from metriplane.paths import PlatformPaths


@dataclass(frozen=True, slots=True)
class CalibPaths:
    """Legacy positional shape; mapping intentionally precedes zones."""

    profile: str
    profile_dir: Path
    anchors: Path
    mapping: Path
    zones: Path
    test_points: Path


def load_active_profile(
    calib_root: str | Path | None = None,
    *,
    paths: PlatformPaths | None = None,
) -> str:
    """Preserve the legacy directory-based profile lookup."""
    root = resolve_calib_root(calib_root, paths=paths)
    active_profile = root / "active_profile.yaml"
    if not active_profile.exists():
        raise FileNotFoundError(f"Missing {active_profile}. Create it with: profile: <name>")
    profile = _load_active_profile(active_profile, paths=paths)
    if profile is None:
        raise ValueError(f"{active_profile} must contain: profile: <name>")
    return profile


def resolve_profile_dir(
    profile: str | None,
    calib_root: str | Path | None = None,
    *,
    paths: PlatformPaths | None = None,
) -> Path:
    """Preserve the legacy positional calibration-root argument."""
    resolved = _resolve_profile_dir(
        profile,
        calib_root=calib_root,
        paths=paths,
        strict=True,
    )
    if resolved is None:  # pragma: no cover - strict=True guarantees a path or error
        raise AssertionError("strict profile resolution returned no path")
    return resolved


def get_calib_paths(
    profile: str | None,
    calib_root: str | Path | None = None,
    *,
    paths: PlatformPaths | None = None,
) -> CalibPaths:
    """Return canonical calibration paths through the legacy import surface."""
    resolved = maybe_get_calib_paths(profile, calib_root=calib_root, paths=paths)
    if resolved is None:
        root = resolve_calib_root(calib_root, paths=paths)
        raise FileNotFoundError(f"Profile not found under: {root / 'profiles'}")
    return CalibPaths(
        profile=resolved.profile,
        profile_dir=resolved.profile_dir,
        anchors=resolved.anchors,
        mapping=resolved.mapping,
        zones=resolved.zones,
        test_points=resolved.test_points,
    )


__all__ = [
    "CalibPaths",
    "get_calib_paths",
    "load_active_profile",
    "resolve_calib_root",
    "resolve_profile_dir",
]
