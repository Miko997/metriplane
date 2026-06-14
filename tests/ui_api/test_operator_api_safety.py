# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from metriplane.runner.operator_api import OperatorAPI


def make_api(tmp_path: Path) -> OperatorAPI:
    executor = MagicMock()
    executor.execute.return_value = "job-ui-api"
    return OperatorAPI(executor=executor, repo_root=tmp_path)


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


def test_generate_report_rejects_runs_sibling_prefix(tmp_path: Path, monkeypatch):
    api = make_api(tmp_path)
    home = tmp_path / "home"
    runs_evil = home / "metriplane-runs-evil"
    runs_evil.mkdir(parents=True)
    session = runs_evil / "session.jsonl"
    session.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    status, payload = api._generate_report(
        {"type": "zones", "session": str(session), "prefix": "safe"}
    )
    assert status == 400
    assert "under ~/metriplane-runs" in payload["error"]


def test_calibrate_rejects_unsafe_camera_path_before_job(tmp_path: Path):
    executor = MagicMock()
    api = OperatorAPI(executor=executor, repo_root=tmp_path)
    status, payload = api._calibrate(
        {
            "profile": "local_test",
            "cam": "cam0",
            "camera": "../../dev/video0",
        }
    )
    assert status == 400
    assert "Invalid camera path" in payload["error"]
    executor.execute.assert_not_called()


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
