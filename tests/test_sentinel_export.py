# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metriplane.paths import PlatformPathError, PlatformPaths
from metriplane.schema import ObjectStateModel
from metriplane.sentinel.cli_runtime import main_sentinel
from metriplane.sentinel.config import SentinelConfig
from metriplane.sentinel.runtime import SentinelError, SentinelRuntime

CONTRACT = "configs/contracts/sentinel_demo.yaml"
OBJECTS = "configs/objects.example.yaml"
FIXTURE = "tests/fixtures/contracts/sentinel_minimal_session.jsonl"


def obj(marker, x, y, zone=None):
    return ObjectStateModel(id=str(marker), pos_world=(x, y, 0.0), zone=zone)


def _runtime(run_dir, run_id="t"):
    cfg = SentinelConfig(enabled=True, contracts_file=CONTRACT, objects_file=OBJECTS)
    return SentinelRuntime(cfg, run_dir=run_dir, run_id=run_id)


def _platform_paths(root):
    return PlatformPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        state_dir=root / "state",
    )


def test_close_writes_summary(tmp_path):
    rt = _runtime(tmp_path / "run")
    rt.update(0.0, 0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    out = rt.close()
    assert out is not None and out.exists()
    data = json.loads(out.read_text())
    assert data["phase"] == 17
    assert data["control_enabled"] is False
    assert data["run_id"] == "t"
    assert data["contract_id"] == "sentinel_demo_warehouse"


def test_summary_handles_no_alerts(tmp_path):
    rt = _runtime(tmp_path / "run")
    rt.update(0.0, 0, [obj(7, 5.0, 5.0, zone="main")])  # no violation
    out = rt.close()
    data = json.loads(out.read_text())
    assert data["alerts_total"] == 0
    assert data["incidents_total"] == 0


def test_fail_fast_on_missing_contract():
    cfg = SentinelConfig(enabled=True, contracts_file="does/not/exist.yaml",
                         fail_fast_on_contract_error=True)
    with pytest.raises(SentinelError):
        SentinelRuntime(cfg)


def test_no_fail_fast_marks_degraded():
    cfg = SentinelConfig(enabled=True, contracts_file="does/not/exist.yaml",
                         fail_fast_on_contract_error=False)
    rt = SentinelRuntime(cfg)
    assert rt.health == "DEGRADED"


def test_cli_run_end_to_end(tmp_path, capsys):
    injected = _platform_paths(tmp_path / "injected")
    rc = main_sentinel([
        "run", "--config", "configs/sentinel_demo.yaml",
        "--run-id", "sentinel_runtime_001", "--runs-dir", str(tmp_path),
    ], paths=injected)
    assert rc == 0
    out = capsys.readouterr().out
    assert "mode=shadow_auditor" in out
    assert "control_enabled=False" in out

    summary = tmp_path / "sentinel_runtime_001" / "sentinel_summary.json"
    assert summary.exists()
    data = json.loads(summary.read_text())
    assert data["alerts_total"] >= 1
    assert data["incidents_total"] >= 1
    assert not injected.runs_dir.exists()


def test_cli_run_uses_injected_platform_runs_dir_by_default(tmp_path, capsys):
    paths = _platform_paths(tmp_path)

    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            "sentinel_injected",
        ],
        paths=paths,
    )

    assert rc == 0
    capsys.readouterr()
    assert (paths.runs_dir / "sentinel_injected" / "sentinel_summary.json").is_file()


def test_cli_run_whitespace_runs_dir_uses_injected_platform_default(
    tmp_path,
    capsys,
):
    paths = _platform_paths(tmp_path / "injected")
    dangerous_cwd_path = Path.cwd() / " \t "
    assert not dangerous_cwd_path.exists()

    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            "sentinel_whitespace_root",
            "--runs-dir",
            " \t ",
        ],
        paths=paths,
    )

    assert rc == 0
    capsys.readouterr()
    assert (paths.runs_dir / "sentinel_whitespace_root" / "sentinel_summary.json").is_file()
    assert not dangerous_cwd_path.exists()


def test_cli_run_rejects_symlink_loop_runs_dir(tmp_path, capsys):
    loop = tmp_path / "loop"
    loop.symlink_to(loop.name)

    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            "sentinel_loop_root",
            "--runs-dir",
            str(loop),
        ],
        paths=_platform_paths(tmp_path / "injected"),
    )

    assert rc == 2
    assert "cannot resolve run-recording root" in capsys.readouterr().out


def test_cli_run_generates_unique_default_run_ids(tmp_path, capsys, monkeypatch):
    generated = iter(("sentinel_001", "sentinel_002"))
    monkeypatch.setattr(
        "metriplane.sentinel.cli_runtime.generate_run_id",
        lambda _prefix: next(generated),
    )

    for _ in range(2):
        assert main_sentinel([
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--runs-dir",
            str(tmp_path),
        ]) == 0

    capsys.readouterr()
    assert (tmp_path / "sentinel_001" / "sentinel_summary.json").is_file()
    assert (tmp_path / "sentinel_002" / "sentinel_summary.json").is_file()


def test_cli_run_reports_platform_path_failure_without_traceback(capsys, monkeypatch):
    monkeypatch.setattr(
        "metriplane.sentinel.cli_runtime.resolve_platform_paths",
        lambda: (_ for _ in ()).throw(PlatformPathError("home unavailable")),
    )

    assert main_sentinel([
        "run",
        "--config",
        "configs/sentinel_demo.yaml",
        "--run-id",
        "sentinel_path_failure",
    ]) == 2
    assert capsys.readouterr().out == "platform path error: home unavailable\n"


@pytest.mark.parametrize(
    "run_id",
    [
        "../escape",
        "nested/run",
        r"..\escape",
        r"C:\escape",
        r"\\server\share",
        "/absolute",
        "..",
        ".",
        "bad id",
        "CON",
        "con.txt",
        "CON..alias",
        "NUL.tar.gz",
        "PrN.log",
        "AUX.data",
        "COM1",
        "com9.capture",
        "LPT1",
        "lPt9.log",
        "run.",
        "run ",
    ],
)
def test_cli_run_rejects_unsafe_run_ids_without_writing(tmp_path, capsys, run_id):
    runs_dir = tmp_path / "runs"

    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            run_id,
            "--runs-dir",
            str(runs_dir),
        ]
    )

    assert rc == 2
    assert "run_id" in capsys.readouterr().out
    assert not runs_dir.exists()


def test_cli_run_refuses_to_overwrite_existing_run_directory(tmp_path, capsys):
    run_dir = tmp_path / "sentinel_existing"
    run_dir.mkdir()
    retained = run_dir / "sentinel_summary.json"
    retained.write_text('{"retained": true}\n', encoding="utf-8")

    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            "sentinel_existing",
            "--runs-dir",
            str(tmp_path),
        ]
    )

    assert rc == 2
    assert "already exists" in capsys.readouterr().out
    assert retained.read_text(encoding="utf-8") == '{"retained": true}\n'
    assert list(run_dir.iterdir()) == [retained]


def test_cli_status_prints_summary(tmp_path, capsys):
    main_sentinel([
        "run", "--config", "configs/sentinel_demo.yaml",
        "--run-id", "r1", "--runs-dir", str(tmp_path),
    ])
    capsys.readouterr()
    rc = main_sentinel(["status", str(tmp_path / "r1")])
    assert rc == 0
    assert "shadow_auditor" in capsys.readouterr().out
