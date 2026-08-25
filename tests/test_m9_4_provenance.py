# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metriplane.config import Config
from metriplane.paths import PlatformPaths
from metriplane.provenance.run_provenance import create_run_context, open_jsonl_writer


def _platform_paths(root: Path) -> PlatformPaths:
    return PlatformPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        state_dir=root / "state",
    )


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "implementation_name"),
    [
        ("metriplane.run", "run_loop", "_run_loop_impl"),
        ("metriplane.run_fusion", "run_loop_fusion", "_run_loop_fusion_impl"),
    ],
)
def test_runtime_provenance_uses_injected_platform_runs_dir(
    module_name: str,
    entrypoint_name: str,
    implementation_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    captured: dict[str, object] = {}

    def fake_implementation(_cfg, **kwargs):
        captured.update(kwargs)
        return 17

    monkeypatch.setattr(module, implementation_name, fake_implementation)
    entrypoint = getattr(module, entrypoint_name)

    assert entrypoint(Config(), paths=_platform_paths(tmp_path)) == 17
    assert captured["runs_dir"] == str(tmp_path / "data" / "runs")


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "implementation_name"),
    [
        ("metriplane.run", "run_loop", "_run_loop_impl"),
        ("metriplane.run_fusion", "run_loop_fusion", "_run_loop_fusion_impl"),
    ],
)
def test_runtime_provenance_preserves_explicit_runs_dir_override(
    module_name: str,
    entrypoint_name: str,
    implementation_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    captured: dict[str, object] = {}

    def fake_implementation(_cfg, **kwargs):
        captured.update(kwargs)
        return 23

    monkeypatch.setattr(module, implementation_name, fake_implementation)
    entrypoint = getattr(module, entrypoint_name)
    explicit = tmp_path / "explicit"

    assert (
        entrypoint(
            Config(),
            runs_dir=str(explicit),
            paths=_platform_paths(tmp_path / "injected"),
        )
        == 23
    )
    assert captured["runs_dir"] == str(explicit)


def test_metriplane_run_cli_propagates_injected_platform_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane import cli

    paths = _platform_paths(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr("metriplane.config.load_config", lambda _path: Config())

    def fake_run_loop(_cfg, **kwargs):
        captured.update(kwargs)
        return 29

    monkeypatch.setattr("metriplane.run.run_loop", fake_run_loop)

    assert cli.main(["run"], paths=paths) == 29
    assert captured["paths"] is paths


def test_shell_run_writers_use_canonical_defaults_and_preserve_overrides() -> None:
    root = Path(__file__).resolve().parents[1]
    mp_script = (root / "tools" / "mp.sh").read_text(encoding="utf-8")
    demo_script = (root / "scripts" / "DEMO_ALL.sh").read_text(encoding="utf-8")

    assert 'RUNS="${RUNS:-$ROOT/runs}"' not in mp_script
    assert "resolve_platform_paths().runs_dir" in mp_script
    assert 'if [[ -z "${RUNS:-}" ]]' in mp_script
    assert 'LOG_DIR="$ROOT/runs/$RUN_ID"' not in demo_script
    assert 'if [[ -n "${RUNS:-}" ]]' in demo_script
    assert 'LOG_DIR="$RUNS_DIR/$RUN_ID"' in demo_script


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
        "rtsp://camera-user:super-secret@camera.local:8554/stream?token=query-secret&quality=high"
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
    persisted = ctx.config_yaml.read_text(
        encoding="utf-8"
    ) + ctx.config_canonical_json_path.read_text(encoding="utf-8")

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
