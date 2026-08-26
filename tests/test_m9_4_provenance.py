# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metriplane.config import Config
from metriplane.paths import PlatformPathError, PlatformPaths
from metriplane.provenance.run_provenance import (
    create_run_context,
    open_jsonl_writer,
)
from metriplane.run_ids import validate_portable_run_id


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
    monkeypatch.setenv("METRIPLANE_DATA_DIR", str(tmp_path / "environment"))
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
def test_runtime_provenance_preserves_data_dir_environment_precedence(
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
        return 19

    monkeypatch.setenv("METRIPLANE_DATA_DIR", str(tmp_path / "docker-data"))
    monkeypatch.setattr(module, implementation_name, fake_implementation)
    monkeypatch.setattr(
        module,
        "resolve_platform_paths",
        lambda: pytest.fail("METRIPLANE_DATA_DIR must precede ambient platform paths"),
    )

    assert getattr(module, entrypoint_name)(Config()) == 19
    assert captured["runs_dir"] is None


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "implementation_name"),
    [
        ("metriplane.run", "run_loop", "_run_loop_impl"),
        ("metriplane.run_fusion", "run_loop_fusion", "_run_loop_fusion_impl"),
    ],
)
def test_runtime_path_resolution_failure_is_user_facing(
    module_name: str,
    entrypoint_name: str,
    implementation_name: str,
    monkeypatch,
    capsys,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    monkeypatch.delenv("METRIPLANE_DATA_DIR", raising=False)
    monkeypatch.setattr(
        module,
        "resolve_platform_paths",
        lambda: (_ for _ in ()).throw(PlatformPathError("home unavailable")),
    )
    monkeypatch.setattr(
        module,
        implementation_name,
        lambda *_args, **_kwargs: pytest.fail("runtime must not start"),
    )

    assert getattr(module, entrypoint_name)(Config()) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "platform path error: home unavailable\n"


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name"),
    [
        ("metriplane.run", "run_loop"),
        ("metriplane.run_fusion", "run_loop_fusion"),
    ],
)
def test_runtime_run_storage_permission_failure_is_clean(
    module_name: str,
    entrypoint_name: str,
    tmp_path: Path,
    caplog,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    read_only = tmp_path / "read-only-data"
    read_only.mkdir()
    read_only.chmod(0o500)
    paths = PlatformPaths(
        config_dir=tmp_path / "config",
        data_dir=read_only,
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
    )

    try:
        result = getattr(module, entrypoint_name)(
            Config(source_mode="dummy"),
            run_id="read_only_probe",
            paths=paths,
        )
    finally:
        read_only.chmod(0o700)

    assert result == 2
    assert "run storage unavailable:" in caplog.text


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


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "implementation_name"),
    [
        ("metriplane.run", "run_loop", "_run_loop_impl"),
        ("metriplane.run_fusion", "run_loop_fusion", "_run_loop_fusion_impl"),
    ],
)
@pytest.mark.parametrize("override_source", ["cli", "config"])
def test_runtime_whitespace_runs_dir_uses_injected_root_without_writing_ambient(
    module_name: str,
    entrypoint_name: str,
    implementation_name: str,
    override_source: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    captured: dict[str, object] = {}
    ambient = tmp_path / "ambient"
    injected = _platform_paths(tmp_path / "injected")
    cfg = Config(runs_dir=" \t ") if override_source == "config" else Config()
    direct_runs_dir = " \t " if override_source == "cli" else None

    def fake_implementation(_cfg, **kwargs):
        captured.update(kwargs)
        return 25

    monkeypatch.setenv("METRIPLANE_DATA_DIR", str(ambient))
    monkeypatch.setattr(module, implementation_name, fake_implementation)

    assert (
        getattr(module, entrypoint_name)(
            cfg,
            runs_dir=direct_runs_dir,
            paths=injected,
        )
        == 25
    )
    assert captured["runs_dir"] == str(injected.runs_dir)
    assert not ambient.exists()
    assert not injected.data_dir.exists()


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "implementation_name"),
    [
        ("metriplane.run", "run_loop", "_run_loop_impl"),
        ("metriplane.run_fusion", "run_loop_fusion", "_run_loop_fusion_impl"),
    ],
)
def test_runtime_whitespace_data_environment_uses_platform_root(
    module_name: str,
    entrypoint_name: str,
    implementation_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    paths = _platform_paths(tmp_path / "injected")
    captured: dict[str, object] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("METRIPLANE_DATA_DIR", " \t ")
    monkeypatch.setattr(module, "resolve_platform_paths", lambda: paths)
    monkeypatch.setattr(
        module,
        implementation_name,
        lambda _cfg, **kwargs: (captured.update(kwargs), 33)[1],
    )

    assert getattr(module, entrypoint_name)(Config()) == 33
    assert captured["runs_dir"] == str(paths.runs_dir)
    assert not (tmp_path / " \t ").exists()


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "implementation_name"),
    [
        ("metriplane.run", "run_loop", "_run_loop_impl"),
        ("metriplane.run_fusion", "run_loop_fusion", "_run_loop_fusion_impl"),
    ],
)
@pytest.mark.parametrize("run_id", ["CON", "nul.txt", "COM1.capture", "LPT9.log"])
def test_runtime_public_entrypoints_reject_windows_device_run_ids_before_writing(
    module_name: str,
    entrypoint_name: str,
    implementation_name: str,
    run_id: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(
        module,
        implementation_name,
        lambda *_args, **_kwargs: pytest.fail("invalid run ID reached the runtime writer"),
    )

    assert (
        getattr(module, entrypoint_name)(
            Config(record_jsonl=str(tmp_path / "mirror" / "session.jsonl")),
            run_id=run_id,
            runs_dir=str(runs_dir),
        )
        == 2
    )
    assert not runs_dir.exists()
    assert not (tmp_path / "mirror").exists()


@pytest.mark.parametrize(
    ("module_name", "entrypoint_name", "implementation_name"),
    [
        ("metriplane.run", "run_loop", "_run_loop_impl"),
        ("metriplane.run_fusion", "run_loop_fusion", "_run_loop_fusion_impl"),
    ],
)
def test_runtime_whitespace_direct_override_reveals_config_precedence(
    module_name: str,
    entrypoint_name: str,
    implementation_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = __import__(module_name, fromlist=[entrypoint_name])
    captured: dict[str, object] = {}
    configured = tmp_path / "configured"

    def fake_implementation(_cfg, **kwargs):
        captured.update(kwargs)
        return 27

    monkeypatch.setattr(module, implementation_name, fake_implementation)

    assert (
        getattr(module, entrypoint_name)(
            Config(runs_dir=f"  {configured}  "),
            runs_dir=" \t ",
            paths=_platform_paths(tmp_path / "injected"),
        )
        == 27
    )
    assert captured["runs_dir"] == str(configured)
    assert not configured.exists()


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


def test_ui_demo_replay_preserves_explicit_runs_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools import run_ui_demo_replay

    runs_dir = tmp_path / "explicit-recordings"
    commands: list[list[str]] = []
    monkeypatch.setattr(
        run_ui_demo_replay,
        "resolve_platform_paths",
        lambda: pytest.fail("explicit --runs-dir must not resolve ambient paths"),
    )
    monkeypatch.setattr(
        run_ui_demo_replay,
        "run_step",
        lambda _label, command: commands.append(command),
    )

    assert run_ui_demo_replay.main(["--runs-dir", str(runs_dir)]) == 0
    sentinel_command = commands[0]
    assert sentinel_command[sentinel_command.index("--runs-dir") + 1] == str(
        runs_dir.resolve()
    )


def test_ui_demo_replay_generates_a_unique_safe_run_id_each_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools import run_ui_demo_replay

    commands: list[list[str]] = []
    generated = iter(("metriplane_demo_001", "metriplane_demo_002"))
    monkeypatch.setattr(run_ui_demo_replay, "generate_run_id", lambda _prefix: next(generated))
    monkeypatch.setattr(
        run_ui_demo_replay,
        "run_step",
        lambda _label, command: commands.append(command),
    )

    for _ in range(2):
        assert run_ui_demo_replay.main(["--runs-dir", str(tmp_path / "runs")]) == 0

    sentinel_commands = commands[::3]
    run_ids = [command[command.index("--run-id") + 1] for command in sentinel_commands]
    assert run_ids == ["metriplane_demo_001", "metriplane_demo_002"]
    assert len(set(run_ids)) == 2


def test_ui_demo_replay_whitespace_runs_dir_uses_platform_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools import run_ui_demo_replay

    paths = _platform_paths(tmp_path / "injected")
    commands: list[list[str]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_ui_demo_replay, "resolve_platform_paths", lambda: paths)
    monkeypatch.setattr(
        run_ui_demo_replay,
        "run_step",
        lambda _label, command: commands.append(command),
    )

    assert run_ui_demo_replay.main(["--runs-dir", " \t "]) == 0
    sentinel_command = commands[0]
    assert sentinel_command[sentinel_command.index("--runs-dir") + 1] == str(paths.runs_dir)
    assert not (tmp_path / " \t ").exists()


@pytest.mark.parametrize("run_id", ["CON", "nul.txt", "COM1.capture", "LPT9.log"])
def test_ui_demo_replay_rejects_windows_device_run_ids_before_writing(
    run_id: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools import run_ui_demo_replay

    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(
        run_ui_demo_replay,
        "run_step",
        lambda *_args: pytest.fail("invalid run ID reached a demo writer"),
    )

    assert run_ui_demo_replay.main(["--runs-dir", str(runs_dir), "--run-id", run_id]) == 2
    assert not runs_dir.exists()


def test_latency_benchmark_whitespace_runs_dir_uses_platform_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from benchmarks import run_latency_breakdown

    paths = _platform_paths(tmp_path / "injected")
    run_id = "latency.valid-01"
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, command: list[str]) -> None:
            captured["command"] = command
            run_dir = paths.runs_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "latency.csv").write_text("stage,ms\nall,1\n", encoding="utf-8")

        def send_signal(self, _signal: int) -> None:
            return None

        def wait(self, *, timeout: int) -> int:
            return 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_latency_breakdown, "resolve_platform_paths", lambda: paths)
    monkeypatch.setattr(run_latency_breakdown.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(run_latency_breakdown.time, "sleep", lambda _seconds: None)

    assert (
        run_latency_breakdown.main(
            [
                "--out",
                str(tmp_path / "latency.csv"),
                "--runs-dir",
                " \t ",
                "--run-id",
                run_id,
            ]
        )
        == 0
    )
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--runs-dir") + 1] == str(paths.runs_dir)
    assert not (tmp_path / " \t ").exists()


@pytest.mark.parametrize("run_id", ["CON", "nul.txt", "COM1.capture", "LPT9.log"])
def test_latency_benchmark_rejects_windows_device_run_ids_before_writing(
    run_id: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from benchmarks import run_latency_breakdown

    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(
        run_latency_breakdown.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("invalid run ID reached benchmark process"),
    )

    assert (
        run_latency_breakdown.main(
            [
                "--out",
                str(tmp_path / "latency.csv"),
                "--runs-dir",
                str(runs_dir),
                "--run-id",
                run_id,
            ]
        )
        == 2
    )
    assert not runs_dir.exists()


def test_metriplane_run_help_retains_frozen_legacy_default(capsys) -> None:
    from metriplane.run import main as run_main

    with pytest.raises(SystemExit) as exc_info:
        run_main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert "default: /data/runs in docker, ./runs on host" in normalized


def test_primary_run_help_names_platform_runs_directory(capsys) -> None:
    from metriplane import cli

    with pytest.raises(SystemExit) as exc_info:
        cli._main_run(["--help"])

    assert exc_info.value.code == 0
    normalized = " ".join(capsys.readouterr().out.split())
    assert "default: platform runs directory" in normalized
    assert "default: platform data directory" not in normalized


@pytest.mark.parametrize(
    ("argv", "configured_runs_dir"),
    [
        ([], None),
        (["--runs-dir", " \t "], None),
        ([], " \t "),
    ],
)
def test_metriplane_run_console_retains_legacy_default_for_blank_overrides(
    argv: list[str],
    configured_runs_dir: str | None,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane import run

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "metriplane.config.load_config",
        lambda _path: Config(runs_dir=configured_runs_dir),
    )
    monkeypatch.setattr(run, "data_dir", lambda: tmp_path)

    def fake_run_loop(_cfg, **kwargs):
        captured.update(kwargs)
        return 31

    monkeypatch.setattr(run, "run_loop", fake_run_loop)

    assert run.main(argv) == 31
    assert captured["runs_dir"] == str(tmp_path / "runs")
    assert captured["paths"] is None


def test_shell_run_writers_use_canonical_defaults_and_preserve_overrides() -> None:
    root = Path(__file__).resolve().parents[1]
    mp_script = (root / "tools" / "mp.sh").read_text(encoding="utf-8")
    demo_script = (root / "scripts" / "DEMO_ALL.sh").read_text(encoding="utf-8")
    vt_script = (root / "scripts" / "_vt_env.sh").read_text(encoding="utf-8")
    sd4_script = (root / "scripts" / "sd4_demo.sh").read_text(encoding="utf-8")

    assert 'RUNS="${RUNS:-$ROOT/runs}"' not in mp_script
    assert "resolve_platform_paths().runs_dir" in mp_script
    assert 'if [[ ! "${RUNS:-}" =~ [^[:space:]] ]]' in mp_script
    assert 'LOG_DIR="$ROOT/runs/$RUN_ID"' not in demo_script
    assert 'if [[ "${RUNS:-}" =~ [^[:space:]] ]]' in demo_script
    assert 'LOG_DIR="$RUNS_DIR/$RUN_ID"' in demo_script
    assert 'if [[ ! "${RUNS:-}" =~ [^[:space:]] ]]' in vt_script
    assert 'if [[ ! "${RUNS_DIR:-}" =~ [^[:space:]] ]]' in sd4_script


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


@pytest.mark.parametrize(
    "run_id",
    [
        "../escape",
        "nested/run",
        "..",
        "bad id",
        "CON",
        "nul.txt",
        "COM1.capture",
        "LPT9.log",
    ],
)
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


@pytest.mark.parametrize(
    "run_id",
    ["run", "CONSOLE", "nulled.txt", "COM10.capture", "LPT10.log", "a.b-c_d"],
)
def test_portable_run_id_validator_preserves_valid_names(run_id: str) -> None:
    assert validate_portable_run_id(run_id) == run_id
