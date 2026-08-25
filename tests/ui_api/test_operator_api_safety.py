# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from metriplane.paths import PlatformPaths
from metriplane.runner.operator_api import OperatorAPI


def make_api(tmp_path: Path) -> OperatorAPI:
    executor = MagicMock()
    executor.execute.return_value = "job-ui-api"
    return OperatorAPI(
        executor=executor,
        repo_root=tmp_path,
        paths=PlatformPaths(
            config_dir=tmp_path / "platform" / "config",
            data_dir=tmp_path / "platform" / "data",
            cache_dir=tmp_path / "platform" / "cache",
            state_dir=tmp_path / "platform" / "state",
        ),
    )


def test_save_config_rejects_path_traversal_filename(tmp_path: Path):
    api = make_api(tmp_path)
    status, payload = api._save_config(
        {
            "filename": "../escape.yaml",
            "config": {"profile": "local_test"},
        }
    )
    assert status == 400
    assert "safe name" in payload["error"]


def test_start_fusion_rejects_config_outside_configs(tmp_path: Path):
    api = make_api(tmp_path)
    status, payload = api._start_fusion(
        {
            "config": "../secret.yaml",
            "duration_s": 30,
            "run_id": "safe_run",
        }
    )
    assert status == 400
    assert "relative path under configs" in payload["error"]


def test_start_fusion_rejects_configs_sibling_prefix(tmp_path: Path):
    api = make_api(tmp_path)
    evil = tmp_path / "configs_evil"
    evil.mkdir()
    (evil / "secret.yaml").write_text("source_mode: replay\n", encoding="utf-8")
    status, payload = api._start_fusion(
        {
            "config": "configs_evil/secret.yaml",
            "duration_s": 30,
            "run_id": "safe_run",
        }
    )
    assert status == 400
    assert "relative path under configs" in payload["error"]


def test_checksum_rejects_paths_outside_runs_or_evidence(tmp_path: Path):
    api = make_api(tmp_path)
    outside = tmp_path / "not_allowed.txt"
    outside.write_text("x", encoding="utf-8")
    status, payload = api._checksum({"path": str(outside)})
    assert status == 400
    assert "Can only checksum" in payload["error"]


def test_checksum_rejects_evidence_sibling_prefix(tmp_path: Path):
    api = make_api(tmp_path)
    evil = tmp_path / "evidence_evil"
    evil.mkdir()
    secret = evil / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    status, payload = api._checksum({"path": str(secret)})
    assert status == 400
    assert "Can only checksum" in payload["error"]


def test_generate_report_rejects_runs_sibling_prefix(tmp_path: Path):
    api = make_api(tmp_path)
    runs_root = api._runs_root()
    runs_evil = runs_root.parent / f"{runs_root.name}-evil"
    runs_evil.mkdir(parents=True)
    session = runs_evil / "session.jsonl"
    session.write_text("{}\n", encoding="utf-8")
    status, payload = api._generate_report(
        {"type": "zones", "session": str(session), "prefix": "safe"}
    )
    assert status == 400
    assert "under the platform runs directory" in payload["error"]


def test_calibrate_rejects_unsafe_camera_path_before_job(tmp_path: Path):
    api = make_api(tmp_path)
    status, payload = api._calibrate(
        {
            "profile": "local_test",
            "cam": "cam0",
            "camera": "../../dev/video0",
        }
    )
    assert status == 400
    assert "Invalid camera path" in payload["error"]
    api.executor.execute.assert_not_called()


def test_create_profile_rejects_unsafe_camera_paths(tmp_path: Path):
    api = make_api(tmp_path)
    status, payload = api._create_profile(
        {
            "name": "test",
            "width_m": 1.0,
            "height_m": 1.0,
            "cameras": [{"name": "cam0", "path": "../../etc/passwd"}],
        }
    )
    assert status == 400
    assert "camera" in payload["error"].lower()


def test_latest_run_fails_cleanly_without_home_or_platform_bases(tmp_path: Path, monkeypatch):
    for name in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
    ):
        monkeypatch.delenv(name, raising=False)
    api = OperatorAPI(executor=MagicMock(), repo_root=tmp_path)

    status, payload = api.route("GET", "/operator/latest-run", {})

    assert status == 503
    assert "Platform paths unavailable" in payload["error"]


def test_command_center_auto_discovery_ignores_external_artifact_symlink(tmp_path: Path):
    api = make_api(tmp_path)
    run = api._runs_root() / "candidate"
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    target = outside / "incident.json"
    target.write_text('{"incident_id": "outside"}\n', encoding="utf-8")
    (run / "incident.json").symlink_to(target)

    assert api._cc_resolve_run_dir({}) is None


def test_command_center_does_not_read_external_camera_trust_symlink(tmp_path: Path):
    api = make_api(tmp_path)
    run = api._runs_root() / "candidate"
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    (run / "session.jsonl").write_text("{}\n", encoding="utf-8")
    target = outside / "camera_trust.json"
    target.write_text('{"camera_scores": {"outside": 1.0}}\n', encoding="utf-8")
    (run / "camera_trust.json").symlink_to(target)

    status, payload = api._cc_camera_trust({})

    assert status == 200
    assert payload["camera_trust"] is None
    assert payload["note"] == "no camera_trust.json in this run"


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")


def test_command_center_auto_discovery_rejects_symlinked_run_outside_root(
    tmp_path: Path,
):
    api = make_api(tmp_path)
    runs_root = api._runs_root()
    runs_root.mkdir(parents=True)
    outside = tmp_path / "outside-run"
    outside.mkdir()
    (outside / "sentinel_summary.json").write_text("{}\n", encoding="utf-8")
    _symlink_or_skip(
        runs_root / "linked-run",
        outside,
        target_is_directory=True,
    )

    assert api._cc_resolve_run_dir({}) is None


def test_command_center_auto_discovery_rejects_symlinked_marker_outside_root(
    tmp_path: Path,
):
    api = make_api(tmp_path)
    run_dir = api._runs_root() / "candidate"
    run_dir.mkdir(parents=True)
    outside_marker = tmp_path / "outside-summary.json"
    outside_marker.write_text("{}\n", encoding="utf-8")
    _symlink_or_skip(
        run_dir / "sentinel_summary.json",
        outside_marker,
        target_is_directory=False,
    )

    assert api._cc_resolve_run_dir({}) is None
