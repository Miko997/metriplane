# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metriplane.config import Config
from metriplane.provenance.run_provenance import create_run_context, open_jsonl_writer


def test_run_context_creates_expected_files(tmp_path: Path, monkeypatch) -> None:
    # Avoid slow pip freeze in tests
    monkeypatch.setenv("METRIPLANE_NO_PIP_FREEZE", "1")
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "deadbeef" * 5)

    cfg = Config(source_mode="dummy", target_fps=5, runs_dir=str(tmp_path / "runs"))

    ctx = create_run_context(
        cfg,
        config_path=tmp_path / "cfg.yaml",
        argv=["metriplane", "--config", "cfg.yaml"],
        run_id="test_run",
        runs_dir=str(tmp_path / "runs"),
    )

    assert ctx.run_dir.exists()
    assert ctx.meta_json.is_file()
    assert ctx.env_txt.is_file()
    assert ctx.config_yaml.is_file()
    assert ctx.config_canonical_json_path.is_file()

    meta = json.loads(ctx.meta_json.read_text(encoding="utf-8"))
    assert meta["run_id"] == ctx.run_id
    assert meta["config"]["hash"] == ctx.config_hash


def test_header_record_written_first_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("METRIPLANE_NO_PIP_FREEZE", "1")
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "cafebabe" * 5)

    cfg = Config(source_mode="dummy", target_fps=5, runs_dir=str(tmp_path / "runs"))
    ctx = create_run_context(
        cfg,
        config_path=None,
        argv=["metriplane", "--config", "none"],
        run_id="test_header",
        runs_dir=str(tmp_path / "runs"),
    )

    w = open_jsonl_writer(primary_path=ctx.session_jsonl, mirror_path=None)
    w.write(ctx.header_record())
    w.close()

    first = ctx.session_jsonl.read_text(encoding="utf-8").splitlines()[0]
    obj = json.loads(first)
    assert obj["type"] == "run_header"
    assert obj["run_id"] == ctx.run_id
    assert obj["config_hash"] == ctx.config_hash


def test_run_context_redacts_credentials_from_persisted_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("METRIPLANE_NO_PIP_FREEZE", "1")
    secret_url = (
        "rtsp://camera-user:super-secret@camera.local:8554/stream"
        "?token=query-secret&quality=high"
    )
    cfg = Config(
        source_mode="camera",
        camera_backend="rtsp",
        camera_device=secret_url,
        fusion={
            "api-key": "nested-secret",
            "camera_password": "camera-password",
            "openai_api_key": "provider-key",
            "X-Amz-Signature": "signed-query",
            "credential": "credential-value",
            "headers": {
                "Authorization": "Bearer header-secret",
                "Set-Cookie": "session=browser-secret",
            },
            "endpoint": secret_url,
            "invalid_endpoint": "rtsp://camera.local:bad/stream?token=bad-port-secret",
        },
        runs_dir=str(tmp_path / "runs"),
    )

    ctx = create_run_context(
        cfg,
        config_path=None,
        argv=["metriplane", "run"],
        run_id="redacted",
        runs_dir=str(tmp_path / "runs"),
    )
    persisted = (
        ctx.config_yaml.read_text(encoding="utf-8")
        + ctx.config_canonical_json_path.read_text(encoding="utf-8")
    )

    assert "super-secret" not in persisted
    assert "query-secret" not in persisted
    assert "nested-secret" not in persisted
    assert "camera-password" not in persisted
    assert "provider-key" not in persisted
    assert "signed-query" not in persisted
    assert "credential-value" not in persisted
    assert "header-secret" not in persisted
    assert "browser-secret" not in persisted
    assert "bad-port-secret" not in persisted
    assert "camera-user" not in persisted
    assert "camera.local:8554/stream" in persisted
    assert "<redacted>" in persisted


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", "..", "bad id"])
def test_run_context_rejects_unsafe_run_id(tmp_path: Path, monkeypatch, run_id: str) -> None:
    monkeypatch.setenv("METRIPLANE_NO_PIP_FREEZE", "1")
    cfg = Config(source_mode="dummy", target_fps=5, runs_dir=str(tmp_path / "runs"))

    with pytest.raises(ValueError, match="run_id"):
        create_run_context(
            cfg,
            config_path=None,
            argv=[],
            run_id=run_id,
            runs_dir=str(tmp_path / "runs"),
        )

    assert not (tmp_path / "escape").exists()
