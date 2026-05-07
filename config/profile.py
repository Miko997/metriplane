from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

# metriplane-core/metriplane/config/profile.py
REPO_ROOT = Path(__file__).resolve().parents[2]  # .../metriplane-core
CALIB_ROOT = REPO_ROOT / "calib"


@dataclass(frozen=True, slots=True)
class CalibPaths:
    profile: str
    profile_dir: Path
    anchors: Path
    mapping: Path
    zones: Path
    test_points: Path


def load_active_profile(calib_root: Path = CALIB_ROOT) -> str:
    p = calib_root / "active_profile.yaml"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}. Create calib/active_profile.yaml with: profile: <name>")
    data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    prof = data.get("profile")
    if not prof or not isinstance(prof, str):
        raise ValueError(f"{p} must contain: profile: <name>")
    return prof


def resolve_profile_dir(profile: str | None, calib_root: Path = CALIB_ROOT) -> Path:
    # profile=None means: read calib/active_profile.yaml
    if profile is None or str(profile).strip() == "":
        profile = load_active_profile(calib_root)
    d = calib_root / "profiles" / profile
    if not d.exists():
        raise FileNotFoundError(f"Profile not found: {d}")
    return d


def get_calib_paths(profile: str | None) -> CalibPaths:
    d = resolve_profile_dir(profile)
    return CalibPaths(
        profile=d.name,
        profile_dir=d,
        anchors=d / "anchors.yaml",
        mapping=d / "mapping.yaml",
        zones=d / "zones.yaml",
        test_points=d / "test_points.yaml",
    )
