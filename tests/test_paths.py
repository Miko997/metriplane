# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from metriplane.paths import (
    PlatformPathError,
    PlatformPaths,
    normalize_runs_dir,
    resolve_platform_paths,
)

ROOT = Path(__file__).resolve().parents[1]
_PLATFORM_ENV = (
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
)


def test_linux_xdg_paths_are_canonical_and_do_not_write(tmp_path: Path):
    root = tmp_path / "not-created"
    paths = resolve_platform_paths(
        environment={
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_STATE_HOME": str(root / "state"),
        },
        system="Linux",
    )

    assert paths == PlatformPaths(
        config_dir=root / "config" / "metriplane",
        data_dir=root / "data" / "metriplane",
        cache_dir=root / "cache" / "metriplane",
        state_dir=root / "state" / "metriplane",
    )
    assert paths.runs_dir == root / "data" / "metriplane" / "runs"
    assert paths.launcher_state_file == root / "state" / "metriplane" / "launcher-state.json"
    assert not root.exists()


def test_linux_paths_fall_back_to_home(tmp_path: Path):
    paths = resolve_platform_paths(environment={"HOME": str(tmp_path)}, system="Linux")

    assert paths.config_dir == tmp_path / ".config" / "metriplane"
    assert paths.data_dir == tmp_path / ".local" / "share" / "metriplane"
    assert paths.cache_dir == tmp_path / ".cache" / "metriplane"
    assert paths.state_dir == tmp_path / ".local" / "state" / "metriplane"


def test_darwin_paths_use_library_conventions(tmp_path: Path):
    paths = resolve_platform_paths(environment={"HOME": str(tmp_path)}, system="Darwin")

    support = tmp_path / "Library" / "Application Support" / "metriplane"
    assert paths.config_dir == support
    assert paths.data_dir == support
    assert paths.cache_dir == tmp_path / "Library" / "Caches" / "metriplane"
    assert paths.state_dir == support


def test_windows_paths_use_roaming_and_local_app_data(tmp_path: Path):
    roaming = tmp_path / "roaming"
    local = tmp_path / "local"
    paths = resolve_platform_paths(
        environment={"APPDATA": str(roaming), "LOCALAPPDATA": str(local)},
        system="Windows",
    )

    assert paths.config_dir == roaming / "metriplane"
    assert paths.data_dir == local / "metriplane"
    assert paths.runs_dir == local / "metriplane" / "runs"
    assert paths.cache_dir == local / "metriplane" / "cache"
    assert paths.state_dir == local / "metriplane" / "state"


def test_windows_paths_fall_back_to_user_profile_app_data(tmp_path: Path):
    paths = resolve_platform_paths(
        environment={"USERPROFILE": str(tmp_path)},
        system="Windows",
    )

    assert paths.config_dir == tmp_path / "AppData" / "Roaming" / "metriplane"
    assert paths.runs_dir == tmp_path / "AppData" / "Local" / "metriplane" / "runs"


def test_explicit_runs_dir_is_canonical_and_does_not_change_other_paths(
    tmp_path: Path,
    monkeypatch,
):
    paths = PlatformPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
    )
    monkeypatch.chdir(tmp_path)

    overridden = paths.with_runs_dir("recordings")

    assert overridden.runs_dir == tmp_path / "recordings"
    assert overridden.config_dir == paths.config_dir
    assert overridden.data_dir == paths.data_dir
    assert paths.runs_dir == tmp_path / "data" / "runs"


@pytest.mark.parametrize("value", [None, "", " ", " \t\r\n "])
def test_blank_runs_dir_override_is_absent(value: str | None) -> None:
    assert normalize_runs_dir(value) is None


def test_whitespace_runs_dir_override_keeps_injected_default(tmp_path: Path) -> None:
    paths = PlatformPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
    )

    assert paths.with_runs_dir(" \t ") is paths
    assert paths.with_runs_dir(" \t ").runs_dir == tmp_path / "data" / "runs"


def test_no_home_works_with_complete_xdg_environment(tmp_path: Path):
    paths = resolve_platform_paths(
        environment={
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
        },
        system="Linux",
    )

    paths.runs_dir.mkdir(parents=True)
    paths.runs_dir.joinpath("probe").write_text("ok", encoding="utf-8")
    assert paths.runs_dir.joinpath("probe").read_text(encoding="utf-8") == "ok"


def test_no_home_and_missing_xdg_path_fails_cleanly(tmp_path: Path):
    with pytest.raises(PlatformPathError, match="XDG_STATE_HOME"):
        resolve_platform_paths(
            environment={
                "XDG_CONFIG_HOME": str(tmp_path / "config"),
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_CACHE_HOME": str(tmp_path / "cache"),
            },
            system="Linux",
        )


def test_relative_environment_path_is_rejected(tmp_path: Path):
    with pytest.raises(PlatformPathError, match="XDG_DATA_HOME must be an absolute path"):
        resolve_platform_paths(
            environment={"HOME": str(tmp_path), "XDG_DATA_HOME": "relative/data"},
            system="Linux",
        )


def test_read_only_home_is_not_touched_when_xdg_paths_are_writable(tmp_path: Path):
    home = tmp_path / "read-only-home"
    home.mkdir()
    home.chmod(0o500)
    try:
        paths = resolve_platform_paths(
            environment={
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(tmp_path / "config"),
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_CACHE_HOME": str(tmp_path / "cache"),
                "XDG_STATE_HOME": str(tmp_path / "state"),
            },
            system="Linux",
        )
        paths.runs_dir.mkdir(parents=True)
        paths.runs_dir.joinpath("writable").write_text("yes", encoding="utf-8")
        assert list(home.iterdir()) == []
    finally:
        home.chmod(0o700)


def test_runtime_modules_import_without_home_or_xdg_paths():
    environment = os.environ.copy()
    for name in _PLATFORM_ENV:
        environment.pop(name, None)

    imports = """
import importlib
import pkgutil
from pathlib import Path

def blocked(name):
    raise RuntimeError(f"import-time platform path resolution: {name}")

Path.home = classmethod(lambda cls: blocked("Path.home"))
Path.expanduser = lambda self: blocked("Path.expanduser")

import metriplane
import metriplane.paths as path_api

path_api.resolve_platform_paths = lambda **kwargs: blocked("resolve_platform_paths")

modules = sorted(
    item.name
    for item in pkgutil.walk_packages(metriplane.__path__, metriplane.__name__ + ".")
)
for module_name in modules:
    importlib.import_module(module_name)
importlib.import_module("tools.run_ui_demo_replay")
importlib.import_module("benchmarks.run_latency_breakdown")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            imports,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "helper",
    ["mp", "ui-demo", "latency", "demo-all", "vt-env", "sd4-demo"],
)
def test_shipped_helpers_fail_cleanly_without_platform_home(
    helper: str,
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    for name in (*_PLATFORM_ENV, "METRIPLANE_DATA_DIR", "RUNS", "RUNS_DIR"):
        environment.pop(name, None)
    commands = {
        "mp": ["bash", "tools/mp.sh", "help"],
        "ui-demo": [sys.executable, "tools/run_ui_demo_replay.py"],
        "latency": [
            sys.executable,
            "benchmarks/run_latency_breakdown.py",
            "--out",
            str(tmp_path / "latency.csv"),
        ],
        "demo-all": ["bash", "scripts/DEMO_ALL.sh"],
        "vt-env": ["bash", "scripts/_vt_env.sh"],
        "sd4-demo": ["bash", "scripts/sd4_demo.sh"],
    }

    result = subprocess.run(
        commands[helper],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "platform path error:" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        [sys.executable, "tools/run_ui_demo_replay.py", "--help"],
        [sys.executable, "benchmarks/run_latency_breakdown.py", "--help"],
        ["bash", "scripts/DEMO_ALL.sh", "--help"],
    ],
)
def test_changed_helper_help_names_platform_runs_directory(command: list[str]) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    normalized = " ".join(result.stdout.split())
    assert "default: platform runs directory" in normalized
    assert "default: platform data directory" not in normalized


def test_full_suite_uses_isolated_writable_home():
    root = Path(os.environ["METRIPLANE_TEST_HOME"])
    for name in _PLATFORM_ENV:
        assert Path(os.environ[name]).is_relative_to(root)
    home = Path(os.environ["HOME"])
    probe = home / "suite-write-probe"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"


def test_full_suite_windows_paths_are_isolated():
    root = Path(os.environ["METRIPLANE_TEST_HOME"])
    paths = resolve_platform_paths(environment=os.environ, system="Windows")

    for path in (paths.config_dir, paths.data_dir, paths.cache_dir, paths.state_dir):
        assert path.is_relative_to(root)
