# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import pytest

import metriplane.config as config
import metriplane.config.profile as legacy_profile
from metriplane.atlas.cli import main as atlas_main
from metriplane.atlas.freeze import claim_audit
from metriplane.cli import _main_run, _main_start
from metriplane.paths import PlatformPaths
from metriplane.runner.allowlist import get_command


def _platform_paths(root: Path) -> PlatformPaths:
    return PlatformPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        state_dir=root / "state",
    )


def _write_profile(calib_root: Path, name: str = "site") -> Path:
    profile_dir = calib_root / "profiles" / name
    profile_dir.mkdir(parents=True)
    (calib_root / "active_profile.yaml").write_text(f"profile: {name}\n", encoding="utf-8")
    return profile_dir


def test_default_calibration_root_is_injected_platform_configuration(
    tmp_path: Path,
) -> None:
    paths = _platform_paths(tmp_path)
    profile_dir = _write_profile(paths.config_dir / "calib")

    assert config.resolve_calib_root(paths=paths) == paths.config_dir / "calib"
    assert config.load_active_profile(paths=paths) == "site"
    assert config.resolve_profile_dir(None, paths=paths) == profile_dir
    assert config.maybe_get_calib_paths(None, paths=paths).profile_dir == profile_dir


def test_explicit_calibration_root_remains_supported(tmp_path: Path) -> None:
    explicit_root = tmp_path / "explicit-calibration"
    profile_dir = _write_profile(explicit_root)

    assert config.resolve_calib_root(explicit_root) == explicit_root
    assert config.resolve_profile_dir("site", calib_root=explicit_root) == profile_dir


def test_legacy_profile_module_is_a_compatible_facade(tmp_path: Path) -> None:
    calib_root = tmp_path / "legacy-calibration"
    profile_dir = _write_profile(calib_root)

    positional = legacy_profile.CalibPaths(
        "site",
        profile_dir,
        profile_dir / "anchors.yaml",
        profile_dir / "mapping.yaml",
        profile_dir / "zones.yaml",
        profile_dir / "test_points.yaml",
    )
    assert positional.mapping == profile_dir / "mapping.yaml"
    assert positional.zones == profile_dir / "zones.yaml"
    assert not hasattr(legacy_profile, "REPO_ROOT")
    assert not hasattr(legacy_profile, "CALIB_ROOT")
    assert legacy_profile.load_active_profile(calib_root) == "site"
    assert legacy_profile.resolve_profile_dir(None, calib_root) == profile_dir
    assert legacy_profile.get_calib_paths(None, calib_root).profile_dir == profile_dir


def test_legacy_profile_errors_remain_fail_closed(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        legacy_profile.load_active_profile(missing_root)

    invalid_root = tmp_path / "invalid"
    invalid_root.mkdir()
    (invalid_root / "active_profile.yaml").write_text("profile: ''\n", encoding="utf-8")
    with pytest.raises(ValueError):
        legacy_profile.load_active_profile(invalid_root)


def test_runtime_command_requires_an_explicit_config() -> None:
    with pytest.raises(SystemExit) as error:
        _main_run([])
    assert error.value.code == 2


def test_launcher_does_not_turn_absent_config_into_literal_none(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_start(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("metriplane.launcher.cmd_start", fake_start)
    assert _main_start(["--no-open"]) == 0
    assert captured["config"] is None


def test_atlas_source_inputs_are_explicit(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        atlas_main(["freeze", "audit"])
    assert error.value.code == 2

    assert atlas_main(["run-pack", "robot_cell", "--out", str(tmp_path)]) == 2
    audit = claim_audit(tmp_path)
    assert audit["schema_version"] == "metriplane.atlas.claim_audit.v1"


def test_allowlisted_source_audit_is_disabled_without_an_explicit_root() -> None:
    command = get_command("atlas-freeze-build")
    assert command is not None
    assert command.enabled is False
    assert "{explicit_repository_root_required}" in command.command
    assert command.disabled_reason is not None
    assert "explicit repository root" in command.disabled_reason


def test_targeted_modules_have_no_checkout_relative_defaults() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = (
        root / "metriplane/config/runtime.py",
        root / "metriplane/config/profile.py",
        root / "metriplane/cli.py",
        root / "metriplane/atlas/cli.py",
        root / "metriplane/runner/allowlist.py",
    )
    forbidden = (
        'default="config.example.yaml"',
        'Path("calib/active_profile.yaml")',
        'Path("configs/domain_packs")',
        'default="."',
        '"--root",\n            "."',
    )
    for target in targets:
        source = target.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in source, f"{target}: checkout-relative default {value!r}"
