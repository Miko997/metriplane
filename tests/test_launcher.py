# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Tests for Metriplane launcher v2 (metriplane/launcher.py) and CLI subcommands.

Unit tests cover:
  - CLI help text for all subcommands (start/stop/restart/status/cleanup)
  - stop / status / cleanup with no state (safe no-ops)
  - State helpers: save/load/clear
  - _is_running with known-live and known-dead PIDs
  - _get_pgid returns a valid pgid for live process
  - _is_port_in_use with bound / unbound ports
  - _find_repo_root finds pyproject.toml
  - _is_vt_safe_to_kill pattern matching
  - _read_cmdline for current process
  - PGID stored in state (make_proc_entry)
  - _wait_for_port_free resolves when nothing holds the port

Integration test (TestStartStatusStop):
  - start --no-open brings up runner + dashboard on free ports
  - ports are reachable after start
  - status reports running
  - stop clears state AND releases ports
  - restart works immediately after stop
  - double start blocked
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from metriplane.cli import main as cli_main
from metriplane.launcher import (
    _DEFAULT_FUSION_CONFIG,
    _clear_state,
    _find_repo_root,
    _get_pgid,
    _has_listener,
    _is_port_in_use,
    _is_running,
    _is_vt_safe_to_kill,
    _load_state,
    _make_proc_entry,
    _print_log_tail,
    _read_cmdline,
    _runtime_module_for_config,
    _save_state,
    _start_fusion,
    _start_runner,
    _state_file,
    _wait_for_port_free,
    cmd_cleanup,
    cmd_start,
    cmd_status,
    cmd_stop,
)
from metriplane.paths import PlatformPaths

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _test_platform_paths(root: Path) -> PlatformPaths:
    return PlatformPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        state_dir=root / "state",
    )


# ---------------------------------------------------------------------------
# CLI --help smoke tests
# ---------------------------------------------------------------------------

class TestCLIHelp:
    def test_start_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["start", "--help"])
        assert exc_info.value.code == 0

    def test_stop_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["stop", "--help"])
        assert exc_info.value.code == 0

    def test_stop_help_mentions_force(self, capsys):
        with pytest.raises(SystemExit):
            cli_main(["stop", "--help"])
        out = capsys.readouterr().out
        assert "--force" in out

    def test_restart_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["restart", "--help"])
        assert exc_info.value.code == 0

    def test_status_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["status", "--help"])
        assert exc_info.value.code == 0

    def test_cleanup_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["cleanup", "--help"])
        assert exc_info.value.code == 0

    def test_start_help_mentions_live(self, capsys):
        with pytest.raises(SystemExit):
            cli_main(["start", "--help"])
        out = capsys.readouterr().out
        assert "--live" in out
        assert "default: off" in out
        assert "configs/local_demo_replay.yaml" in out

    def test_start_help_mentions_no_open(self, capsys):
        with pytest.raises(SystemExit):
            cli_main(["start", "--help"])
        out = capsys.readouterr().out
        assert "--no-open" in out

    def test_start_help_mentions_operator(self, capsys):
        with pytest.raises(SystemExit):
            cli_main(["start", "--help"])
        out = capsys.readouterr().out
        assert "--operator" in out

    @pytest.mark.parametrize(
        ("command", "launcher_function"),
        [
            ("start", "cmd_start"),
            ("stop", "cmd_stop"),
            ("restart", "cmd_restart"),
            ("status", "cmd_status"),
            ("cleanup", "cmd_cleanup"),
        ],
    )
    def test_launcher_commands_forward_injected_platform_paths(
        self,
        command,
        launcher_function,
        monkeypatch,
        tmp_path,
    ):
        paths = _test_platform_paths(tmp_path)
        captured = {}

        def fake_command(**kwargs):
            captured.update(kwargs)
            return 37

        monkeypatch.setattr(f"metriplane.launcher.{launcher_function}", fake_command)

        assert cli_main([command], paths=paths) == 37
        assert captured["paths"] is paths


# ---------------------------------------------------------------------------
# stop / status / cleanup with no state
# ---------------------------------------------------------------------------

class TestLauncherDefaults:
    def test_start_defaults_to_runtime_idle(self):
        assert cmd_start.__kwdefaults__["live"] is False

    def test_default_config_is_camera_free_demo(self):
        assert _DEFAULT_FUSION_CONFIG == "configs/local_demo_replay.yaml"
        assert Path(_DEFAULT_FUSION_CONFIG).is_file()

    def test_demo_config_uses_replay_runtime(self):
        assert _runtime_module_for_config(_DEFAULT_FUSION_CONFIG, Path.cwd()) == "metriplane.run"

    def test_camera_config_uses_fusion_runtime(self):
        assert _runtime_module_for_config("configs/fusion_health_300fps.yaml", Path.cwd()) == "metriplane.run_fusion"

    def test_launcher_sets_supported_compute_backend_env(self, monkeypatch, tmp_path):
        captured = {}

        def fake_launch(cmd, log_file, repo_root, env=None):
            captured["cmd"] = cmd
            captured["env"] = env
            return object()

        monkeypatch.setattr("metriplane.launcher._launch", fake_launch)
        monkeypatch.setattr("metriplane.launcher._runtime_module_for_config", lambda config, repo_root: "metriplane.run")

        _start_fusion(
            config="configs/local_demo_replay.yaml",
            run_id="test",
            runs_dir=str(tmp_path),
            duration_s=1.0,
            backend="gpu",
            log_file=tmp_path / "fusion.log",
            repo_root=Path.cwd(),
        )

        assert captured["env"]["METRIPLANE_COMPUTE_BACKEND"] == "gpu"

    def test_dashboard_uses_no_dns_local_server(self, monkeypatch, tmp_path):
        import metriplane.launcher as lm

        captured = {}

        def fake_launch(cmd, log_file, repo_root, env=None):
            captured["cmd"] = cmd
            return object()

        monkeypatch.setattr(lm, "_launch", fake_launch)
        lm._start_dashboard(
            host="127.0.0.1",
            port=8088,
            log_file=tmp_path / "dashboard.log",
            repo_root=Path.cwd(),
        )

        assert captured["cmd"][1:3] == ["-m", "metriplane._local_http"]

    def test_runner_start_serializes_one_injected_platform_path_set(
        self,
        monkeypatch,
        tmp_path,
    ):
        captured = {}
        paths = _test_platform_paths(tmp_path).with_runs_dir(tmp_path / "recordings")

        def fake_launch(cmd, log_file, repo_root, env=None):
            captured["cmd"] = cmd
            return object()

        monkeypatch.setattr("metriplane.launcher._launch", fake_launch)

        _start_runner(
            host="127.0.0.1",
            port=9000,
            dashboard_host="127.0.0.1",
            dashboard_port=8088,
            log_file=tmp_path / "runner.log",
            repo_root=Path.cwd(),
            paths=paths,
        )

        command = captured["cmd"]
        assert command[command.index("--config-dir") + 1] == str(paths.config_dir)
        assert command[command.index("--data-dir") + 1] == str(paths.data_dir)
        assert command[command.index("--cache-dir") + 1] == str(paths.cache_dir)
        assert command[command.index("--state-dir") + 1] == str(paths.state_dir)
        assert command[command.index("--runs-dir") + 1] == str(paths.runs_dir)

    def test_start_canonicalizes_explicit_runs_dir_before_runner_start(
        self,
        monkeypatch,
        tmp_path,
    ):
        import metriplane.launcher as lm

        paths = _test_platform_paths(tmp_path / "platform")
        captured = {}
        processes = iter((SimpleNamespace(pid=101), SimpleNamespace(pid=102)))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(lm, "_find_repo_root", lambda: Path.cwd())
        monkeypatch.setattr(lm, "_is_port_in_use", lambda _host, _port: False)
        monkeypatch.setattr(lm, "_wait_for_port", lambda *_args, **_kwargs: True)
        monkeypatch.setattr(lm, "_get_pgid", lambda pid: pid)
        monkeypatch.setattr(
            lm,
            "_start_runner",
            lambda **kwargs: (captured.update(kwargs), next(processes))[1],
        )
        monkeypatch.setattr(lm, "_start_dashboard", lambda **_kwargs: next(processes))

        assert (
            lm.cmd_start(
                runs_dir="recordings",
                paths=paths,
                open_browser=False,
            )
            == 0
        )

        expected = tmp_path / "recordings"
        assert captured["paths"].runs_dir == expected
        assert lm._load_state(paths)["runs_dir"] == str(expected)

    def test_start_whitespace_runs_dir_keeps_injected_platform_default(
        self,
        monkeypatch,
        tmp_path,
    ):
        import metriplane.launcher as lm

        paths = _test_platform_paths(tmp_path / "platform")
        captured = {}
        processes = iter((SimpleNamespace(pid=101), SimpleNamespace(pid=102)))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(lm, "_find_repo_root", lambda: Path.cwd())
        monkeypatch.setattr(lm, "_is_port_in_use", lambda _host, _port: False)
        monkeypatch.setattr(lm, "_wait_for_port", lambda *_args, **_kwargs: True)
        monkeypatch.setattr(lm, "_get_pgid", lambda pid: pid)
        monkeypatch.setattr(
            lm,
            "_start_runner",
            lambda **kwargs: (captured.update(kwargs), next(processes))[1],
        )
        monkeypatch.setattr(lm, "_start_dashboard", lambda **_kwargs: next(processes))

        assert (
            lm.cmd_start(
                runs_dir=" \t ",
                paths=paths,
                open_browser=False,
            )
            == 0
        )

        assert captured["paths"].runs_dir == paths.runs_dir
        assert lm._load_state(paths)["runs_dir"] == str(paths.runs_dir)
        assert not (tmp_path / " \t ").exists()

    @pytest.mark.parametrize("run_id", ["CON", "nul.txt", "COM1.capture", "LPT9.log"])
    def test_live_start_rejects_windows_device_run_id_before_writing(
        self,
        run_id,
        monkeypatch,
        tmp_path,
    ):
        import metriplane.launcher as lm

        paths = _test_platform_paths(tmp_path / "platform")
        monkeypatch.setattr(
            lm,
            "_start_runner",
            lambda **_kwargs: pytest.fail("invalid run ID reached launcher process start"),
        )

        assert (
            lm.cmd_start(
                live=True,
                run_id=run_id,
                runs_dir=str(tmp_path / "runs"),
                paths=paths,
                open_browser=False,
            )
            == 2
        )
        assert not paths.state_dir.exists()
        assert not (tmp_path / "runs").exists()

    @pytest.mark.parametrize("run_id", ["", " \t "])
    def test_live_start_rejects_explicit_blank_run_id_before_writing(
        self,
        run_id,
        monkeypatch,
        tmp_path,
    ):
        import metriplane.launcher as lm

        paths = _test_platform_paths(tmp_path / "platform")
        monkeypatch.setattr(
            lm,
            "_start_runner",
            lambda **_kwargs: pytest.fail("blank run ID reached launcher process start"),
        )

        assert (
            lm.cmd_start(
                live=True,
                run_id=run_id,
                runs_dir=str(tmp_path / "runs"),
                paths=paths,
                open_browser=False,
            )
            == 2
        )
        assert not paths.state_dir.exists()
        assert not (tmp_path / "runs").exists()

    def test_live_start_generates_run_id_when_omitted(self, monkeypatch, tmp_path):
        import metriplane.launcher as lm

        validated: list[str] = []
        monkeypatch.setattr(
            lm,
            "validate_portable_run_id",
            lambda value: (validated.append(value), value)[1],
        )
        monkeypatch.setattr(
            lm,
            "_effective_paths",
            lambda _paths: (_ for _ in ()).throw(OSError("stop after run-ID validation")),
        )

        assert lm.cmd_start(live=True, run_id=None, open_browser=False) == 2
        assert len(validated) == 1
        assert validated[0].startswith("live_")

    @pytest.mark.parametrize("run_id", ["CON", "nul.txt", "COM1.capture", "LPT9.log"])
    def test_fusion_launcher_rejects_windows_device_run_id(
        self,
        run_id,
        monkeypatch,
        tmp_path,
    ):
        import metriplane.launcher as lm

        monkeypatch.setattr(
            lm,
            "_launch",
            lambda *_args, **_kwargs: pytest.fail("invalid run ID reached process launch"),
        )

        with pytest.raises(ValueError, match="Windows device basenames"):
            lm._start_fusion(
                config="configs/local_demo_replay.yaml",
                run_id=run_id,
                runs_dir=str(tmp_path),
                duration_s=1.0,
                backend="cpu",
                log_file=tmp_path / "fusion.log",
                repo_root=Path.cwd(),
            )

class TestNoState:
    def setup_method(self):
        _clear_state()

    def teardown_method(self):
        _clear_state()

    def test_stop_no_state_returns_zero(self, capsys):
        rc = cmd_stop()
        assert rc == 0

    def test_stop_no_state_prints_message(self, capsys):
        cmd_stop()
        out = capsys.readouterr().out
        assert "No launcher state" in out or "cleanup" in out.lower()

    def test_stop_force_no_state_returns_zero(self, capsys):
        rc = cmd_stop(force=True)
        assert rc == 0

    def test_status_no_state_returns_zero(self, capsys):
        rc = cmd_status()
        assert rc == 0

    def test_status_no_state_prints_port_scan(self, capsys):
        cmd_status()
        out = capsys.readouterr().out
        # Should always show port scan section even without state
        assert "Runner" in out or "Dashboard" in out or "port scan" in out.lower()

    def test_cleanup_no_state_returns_zero(self, capsys):
        rc = cmd_cleanup()
        assert rc == 0

    def test_cleanup_no_state_prints_message(self, capsys):
        cmd_cleanup()
        out = capsys.readouterr().out
        assert "orphan" in out.lower() or "No Metriplane orphans" in out

    def test_status_without_home_or_xdg_paths_fails_cleanly(self, monkeypatch, capsys):
        for name in (
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
        ):
            monkeypatch.delenv(name, raising=False)

        assert cmd_status() == 2
        assert "launcher state" in capsys.readouterr().out.lower()

    def test_start_with_read_only_run_root_fails_before_launch(self, tmp_path, monkeypatch, capsys):
        read_only = tmp_path / "read-only"
        read_only.mkdir()
        read_only.chmod(0o500)
        paths = PlatformPaths(
            config_dir=tmp_path / "config",
            data_dir=read_only,
            cache_dir=tmp_path / "cache",
            state_dir=tmp_path / "state",
        )
        monkeypatch.setattr("metriplane.launcher._find_repo_root", lambda: Path.cwd())
        try:
            assert cmd_start(paths=paths, open_browser=False) == 2
        finally:
            read_only.chmod(0o700)
        assert "run directory" in capsys.readouterr().out.lower()

    def test_start_with_symlink_loop_run_root_fails_before_launch(self, tmp_path, capsys):
        loop = tmp_path / "loop"
        loop.symlink_to(loop.name)

        assert (
            cmd_start(
                paths=_test_platform_paths(tmp_path),
                runs_dir=str(loop),
                open_browser=False,
            )
            == 2
        )
        assert "cannot resolve run-recording root" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

class TestStateHelpers:
    def test_load_empty_when_no_file(self, tmp_path):
        assert _load_state(_test_platform_paths(tmp_path)) == {}

    def test_save_and_load(self, tmp_path):
        paths = _test_platform_paths(tmp_path)
        _save_state({"runner": {"pid": 99999, "pgid": 99999, "port": 9000}}, paths)
        loaded = _load_state(paths)
        assert loaded["runner"]["pid"] == 99999
        assert loaded["runner"]["pgid"] == 99999

    def test_clear_removes_file(self, tmp_path):
        paths = _test_platform_paths(tmp_path)
        _save_state({"x": 1}, paths)
        assert _state_file(paths).exists()
        _clear_state(paths)
        assert not _state_file(paths).exists()

    def test_load_returns_empty_on_corrupt(self, tmp_path):
        paths = _test_platform_paths(tmp_path)
        paths.state_dir.mkdir(parents=True)
        paths.launcher_state_file.write_text("{NOT JSON}}")
        assert _load_state(paths) == {}


# ---------------------------------------------------------------------------
# _is_running
# ---------------------------------------------------------------------------

class TestIsRunning:
    def test_current_process(self):
        assert _is_running(os.getpid()) is True

    def test_none(self):
        assert _is_running(None) is False

    def test_dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        pid = proc.pid
        proc.kill()
        proc.wait()
        time.sleep(0.1)
        assert _is_running(pid) is False


# ---------------------------------------------------------------------------
# _get_pgid
# ---------------------------------------------------------------------------

class TestGetPgid:
    def test_current_process_has_pgid(self):
        pgid = _get_pgid(os.getpid())
        assert pgid is not None
        assert pgid > 0

    def test_dead_pid_returns_none(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        # Give a moment for OS to clean up
        time.sleep(0.05)
        pgid = _get_pgid(proc.pid)
        assert pgid is None

    def test_new_session_pgid_equals_pid(self):
        """start_new_session=True makes PGID == PID of the new process."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            pgid = _get_pgid(proc.pid)
            assert pgid == proc.pid, f"Expected pgid={proc.pid} but got pgid={pgid}"
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


class TestWindowsProcessLifecycle:
    @staticmethod
    def _tasklist_result(command, alive: set[int]):
        if command[0] != "tasklist":
            raise AssertionError(f"unexpected command: {command}")
        pid = int(command[command.index("/FI") + 1].split()[-1])
        stdout = (
            f'"python.exe","{pid}","Console","1","10,000 K"\n'
            if pid in alive
            else "INFO: No tasks are running which match the specified criteria.\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def test_windows_liveness_uses_non_terminating_tasklist(self, monkeypatch):
        import metriplane.launcher as lm

        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return self._tasklist_result(command, {41})

        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(lm.subprocess, "run", fake_run)
        monkeypatch.setattr(
            lm.os,
            "kill",
            lambda *_args: pytest.fail("Windows liveness must never call terminating os.kill"),
        )

        assert lm._is_running(41) is True
        assert lm._is_running(42) is False
        assert calls == [
            ["tasklist", "/FI", "PID eq 41", "/FO", "CSV", "/NH"],
            ["tasklist", "/FI", "PID eq 42", "/FO", "CSV", "/NH"],
        ]

    def test_windows_status_polling_never_calls_os_kill(self, tmp_path, monkeypatch):
        import metriplane.launcher as lm

        paths = _test_platform_paths(tmp_path)
        lm._save_state(
            {
                "runner": {"pid": 51, "port": 9000},
                "dashboard": {"pid": 52, "port": 8088},
            },
            paths,
        )
        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(
            lm.subprocess,
            "run",
            lambda command, **_kwargs: self._tasklist_result(command, {51, 52}),
        )
        monkeypatch.setattr(
            lm.os,
            "kill",
            lambda *_args: pytest.fail("Windows status must never call terminating os.kill"),
        )
        monkeypatch.setattr(lm, "_probe_http", lambda _url: False)
        monkeypatch.setattr(lm, "_find_port_owner", lambda _port: None)
        monkeypatch.setattr(lm, "_is_port_in_use", lambda _host, _port: False)

        assert lm.cmd_status(paths=paths) == 0

    def test_windows_start_polling_never_calls_os_kill(self, tmp_path, monkeypatch):
        import metriplane.launcher as lm

        paths = _test_platform_paths(tmp_path)
        lm._save_state({"runner": {"pid": 61}}, paths)
        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(
            lm.subprocess,
            "run",
            lambda command, **_kwargs: self._tasklist_result(command, {61}),
        )
        monkeypatch.setattr(
            lm.os,
            "kill",
            lambda *_args: pytest.fail("Windows start must never call terminating os.kill"),
        )
        monkeypatch.setattr(
            lm,
            "_start_runner",
            lambda **_kwargs: pytest.fail("already-running launcher must not start"),
        )

        assert lm.cmd_start(paths=paths, open_browser=False) == 1

    def test_windows_stop_polling_never_calls_os_kill(self, tmp_path, monkeypatch):
        import metriplane.launcher as lm

        paths = _test_platform_paths(tmp_path)
        alive = {71}
        calls: list[list[str]] = []
        lm._save_state({"runner": {"pid": 71, "pgid": 71, "port": 9000}}, paths)

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[0] == "taskkill":
                alive.discard(int(command[command.index("/PID") + 1]))
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            return self._tasklist_result(command, alive)

        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(lm.subprocess, "run", fake_run)
        monkeypatch.setattr(
            lm.os,
            "kill",
            lambda *_args: pytest.fail("Windows stop must never call terminating os.kill"),
        )
        monkeypatch.setattr(lm, "_is_port_in_use", lambda _host, _port: False)

        assert lm.cmd_stop(paths=paths) == 0
        assert [command for command in calls if command[0] == "taskkill"] == [
            ["taskkill", "/PID", "71", "/T"]
        ]

    def test_get_pgid_uses_pid_without_posix_api(self, monkeypatch):
        import metriplane.launcher as lm

        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(lm, "_is_running", lambda _pid: True)
        monkeypatch.setattr(
            lm.os,
            "getpgid",
            lambda _pid: pytest.fail("Windows must not call os.getpgid"),
        )

        assert lm._get_pgid(41) == 41

    def test_launch_uses_windows_process_group_flags(self, tmp_path, monkeypatch):
        import metriplane.launcher as lm

        captured = {}

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured.update(kwargs)
            return SimpleNamespace(pid=42)

        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(lm.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
        monkeypatch.setattr(lm.subprocess, "Popen", fake_popen)

        process = lm._launch(
            [sys.executable, "-c", "pass"],
            tmp_path / "child.log",
            tmp_path,
        )

        assert process.pid == 42
        assert captured["creationflags"] == 0x200
        assert "start_new_session" not in captured

    def test_stop_uses_taskkill_tree_without_posix_signals(self, monkeypatch):
        import metriplane.launcher as lm

        calls = []
        running = iter((True, False))
        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(lm, "_is_running", lambda _pid: next(running))
        monkeypatch.setattr(lm.subprocess, "run", lambda command, **_kwargs: calls.append(command))
        monkeypatch.setattr(
            lm.os,
            "killpg",
            lambda *_args: pytest.fail("Windows must not call os.killpg"),
        )

        lm._stop_pg(43, 43)

        assert calls == [["taskkill", "/PID", "43", "/T"]]

    def test_stop_forces_windows_process_tree_after_timeout(self, monkeypatch, capsys):
        import metriplane.launcher as lm

        calls = []
        monotonic = iter((0.0, 6.0, 10.0, 13.0))
        monkeypatch.setattr(lm, "_is_windows", lambda: True)
        monkeypatch.setattr(lm, "_is_running", lambda _pid: True)
        monkeypatch.setattr(lm.time, "monotonic", lambda: next(monotonic))
        monkeypatch.setattr(lm.subprocess, "run", lambda command, **_kwargs: calls.append(command))

        lm._stop_pg(44, 44, name="runner")

        assert calls == [
            ["taskkill", "/PID", "44", "/T"],
            ["taskkill", "/PID", "44", "/T", "/F"],
        ]
        assert "forced process-tree termination" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _make_proc_entry
# ---------------------------------------------------------------------------

class TestMakeProcEntry:
    def test_stores_pid_and_pgid(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            entry = _make_proc_entry(proc)
            assert entry["pid"] == proc.pid
            assert entry["pgid"] == proc.pid  # new session: pgid == pid
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


# ---------------------------------------------------------------------------
# _is_port_in_use / _wait_for_port_free
# ---------------------------------------------------------------------------

class TestPortHelpers:
    def test_free_port_not_in_use(self):
        port = _free_port()
        assert _is_port_in_use("127.0.0.1", port) is False

    def test_bound_port_in_use(self):
        """Port is considered in-use only when something is listening (LISTEN state).
        SO_REUSEADDR allows two sockets to both be in BOUND (non-listen) state,
        but blocks binding when one is in LISTEN state — matching real server behaviour.
        """
        port = _free_port()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)  # must be in LISTEN state to block new binds with SO_REUSEADDR
        try:
            assert _is_port_in_use("127.0.0.1", port) is True
        finally:
            srv.close()

    def test_wait_for_port_free_when_already_free(self):
        port = _free_port()
        assert _wait_for_port_free(port, timeout=1.0) is True

    def test_wait_for_port_free_after_release(self):
        port = _free_port()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))

        # Release in background
        def _release():
            time.sleep(0.3)
            srv.close()

        import threading
        t = threading.Thread(target=_release)
        t.start()
        result = _wait_for_port_free(port, timeout=3.0)
        t.join()
        assert result is True


# ---------------------------------------------------------------------------
# _is_vt_safe_to_kill
# ---------------------------------------------------------------------------

class TestIsVtSafeToKill:
    def test_runner_service_is_safe(self):
        assert _is_vt_safe_to_kill("python -m metriplane.runner.service --host 127.0.0.1") is True

    def test_run_fusion_is_safe(self):
        assert _is_vt_safe_to_kill("/home/user/.venv/bin/python -m metriplane.run_fusion") is True

    def test_replay_runtime_is_safe(self):
        assert _is_vt_safe_to_kill("/home/user/.venv/bin/python -m metriplane.run --config configs/local_demo_replay.yaml") is True

    def test_unknown_process_not_safe(self):
        assert _is_vt_safe_to_kill("nginx -g daemon off") is False
        assert _is_vt_safe_to_kill("postgres -D /var/lib/postgresql") is False
        assert _is_vt_safe_to_kill("node server.js") is False

    def test_empty_cmdline_not_safe(self):
        assert _is_vt_safe_to_kill("") is False


# ---------------------------------------------------------------------------
# _read_cmdline
# ---------------------------------------------------------------------------

class TestReadCmdline:
    def test_current_process_cmdline_nonempty(self):
        cmdline = _read_cmdline(os.getpid())
        assert len(cmdline) > 0
        assert "python" in cmdline.lower() or "pytest" in cmdline.lower()

    def test_falls_back_to_ps_without_proc(self, monkeypatch):
        def proc_unavailable(_path):
            raise OSError("/proc is unavailable")

        def fake_run(command, **kwargs):
            assert command == ["ps", "-ww", "-p", "123", "-o", "command="]
            assert kwargs["timeout"] == 3
            return subprocess.CompletedProcess(command, 0, stdout="python -m pytest\n")

        monkeypatch.setattr(Path, "read_bytes", proc_unavailable)
        monkeypatch.setattr(subprocess, "run", fake_run)

        assert _read_cmdline(123) == "python -m pytest"

    def test_dead_pid_returns_empty(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        time.sleep(0.05)
        assert _read_cmdline(proc.pid) == ""


# ---------------------------------------------------------------------------
# _find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_pyproject_toml(self):
        root = _find_repo_root()
        assert (root / "pyproject.toml").exists()

    def test_returns_path_object(self):
        assert isinstance(_find_repo_root(), Path)


def test_print_log_tail_reports_only_requested_lines(tmp_path, capsys):
    log_file = tmp_path / "runner.log"
    log_file.write_text("first\nsecond\nthird\n", encoding="utf-8")

    _print_log_tail(log_file, lines=2)

    output = capsys.readouterr().out
    assert "first" not in output
    assert "second" in output
    assert "third" in output


# ---------------------------------------------------------------------------
# Integration: start → status → stop → port free (no-live, no-open, free ports)
# ---------------------------------------------------------------------------

@pytest.fixture()
def launcher_env(tmp_path, monkeypatch):
    """
    Override state file to tmp_path, use free ports, cleanup on exit.
    """
    runner_port = _free_port()
    dash_port = _free_port()

    import metriplane.launcher as lm
    paths = _test_platform_paths(tmp_path)
    monkeypatch.setattr(lm, "resolve_platform_paths", lambda: paths)
    original_launch = lm._launch
    processes: list[subprocess.Popen] = []

    def tracked_launch(*args, **kwargs):
        process = original_launch(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(lm, "_launch", tracked_launch)
    monkeypatch.setattr(lm, "_log_dir_path", lambda _runs_dir, _timestamp: tmp_path)

    yield {
        "runner_port": runner_port,
        "dash_port": dash_port,
        "tmp_path": tmp_path,
        "paths": paths,
    }

    # Guaranteed cleanup: kill anything the test started
    state = lm._load_state()
    for key in ("runner", "dashboard", "fusion"):
        info = state.get(key) or {}
        pid = info.get("pid")
        pgid = info.get("pgid") or pid
        if pid and lm._is_running(pid):
            try:
                os.killpg(int(pgid), signal.SIGKILL)
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    lm._clear_state()


class TestStartStatusStop:
    def test_live_readiness_failure_stops_children_and_does_not_save_state(
        self, monkeypatch, tmp_path, capsys
    ):
        import types

        import metriplane.launcher as lm

        processes = iter(
            [types.SimpleNamespace(pid=101), types.SimpleNamespace(pid=102), types.SimpleNamespace(pid=103)]
        )
        paths = _test_platform_paths(tmp_path)
        monkeypatch.setattr(lm, "resolve_platform_paths", lambda: paths)
        monkeypatch.setattr(lm, "_find_repo_root", lambda: Path.cwd())
        monkeypatch.setattr(lm, "_log_dir_path", lambda runs_dir, timestamp: tmp_path)
        monkeypatch.setattr(lm, "_is_port_in_use", lambda host, port: False)
        monkeypatch.setattr(lm, "_start_runner", lambda **kwargs: next(processes))
        monkeypatch.setattr(lm, "_start_dashboard", lambda **kwargs: next(processes))
        monkeypatch.setattr(lm, "_start_fusion", lambda **kwargs: next(processes))
        monkeypatch.setattr(
            lm,
            "_wait_for_port",
            lambda host, port, timeout=8.0, interval=0.2: port not in {8000, 8765},
        )
        monkeypatch.setattr(lm, "_wait_for_port_free", lambda port, timeout=8.0, interval=0.15: True)
        monkeypatch.setattr(lm, "_get_pgid", lambda pid: pid)
        stopped: list[int] = []
        monkeypatch.setattr(
            lm,
            "_stop_pg",
            lambda pgid, pid, **kwargs: stopped.append(pid),
        )

        rc = lm.cmd_start(live=True, open_browser=False)

        assert rc == 1
        assert stopped == [103, 102, 101]
        assert not lm._state_file(paths).exists()
        assert "stack is running" not in capsys.readouterr().out.lower()

    def test_start_returns_zero(self, launcher_env):
        from metriplane.launcher import cmd_start
        rc = cmd_start(
            live=False,
            dashboard_port=launcher_env["dash_port"],
            runner_port=launcher_env["runner_port"],
            open_browser=False,
        )
        assert rc == 0

    def test_runner_reachable_after_start(self, launcher_env):
        from metriplane.launcher import cmd_start
        cmd_start(live=False, dashboard_port=launcher_env["dash_port"],
                  runner_port=launcher_env["runner_port"], open_browser=False)
        assert _wait_for_port("127.0.0.1", launcher_env["runner_port"], timeout=10.0)

    def test_dashboard_reachable_after_start(self, launcher_env):
        from metriplane.launcher import cmd_start
        cmd_start(live=False, dashboard_port=launcher_env["dash_port"],
                  runner_port=launcher_env["runner_port"], open_browser=False)
        assert _wait_for_port("127.0.0.1", launcher_env["dash_port"], timeout=10.0)

    def test_state_has_pgid(self, launcher_env):
        """State must record pgid for each started process."""
        import metriplane.launcher as lm
        from metriplane.launcher import cmd_start
        cmd_start(live=False, dashboard_port=launcher_env["dash_port"],
                  runner_port=launcher_env["runner_port"], open_browser=False)
        state = lm._load_state()
        assert "pgid" in state["runner"], f"runner state missing pgid: {state['runner']}"
        assert "pgid" in state["dashboard"], f"dashboard state missing pgid: {state['dashboard']}"
        # pgid == pid for new-session processes
        assert state["runner"]["pgid"] == state["runner"]["pid"]
        assert state["dashboard"]["pgid"] == state["dashboard"]["pid"]

    def test_status_shows_running(self, launcher_env, capsys):
        from metriplane.launcher import cmd_start, cmd_status
        cmd_start(live=False, dashboard_port=launcher_env["dash_port"],
                  runner_port=launcher_env["runner_port"], open_browser=False)
        capsys.readouterr()
        rc = cmd_status()
        assert rc == 0
        out = capsys.readouterr().out
        assert "running" in out.lower()

    def test_stop_clears_state(self, launcher_env):
        import metriplane.launcher as lm
        from metriplane.launcher import cmd_start, cmd_stop
        cmd_start(live=False, dashboard_port=launcher_env["dash_port"],
                  runner_port=launcher_env["runner_port"], open_browser=False)
        assert lm._state_file(launcher_env["paths"]).exists()
        cmd_stop()
        assert not lm._state_file(launcher_env["paths"]).exists()

    def test_stop_releases_runner_port(self, launcher_env):
        """After stop, runner port must be free (PGID kill works correctly)."""
        import metriplane.launcher as lm
        from metriplane.launcher import cmd_start, cmd_stop
        runner_port = launcher_env["runner_port"]

        cmd_start(live=False, dashboard_port=launcher_env["dash_port"],
                  runner_port=runner_port, open_browser=False)
        assert _wait_for_port("127.0.0.1", runner_port, timeout=5.0)

        cmd_stop()

        freed = _wait_for_port_free(runner_port, timeout=5.0)
        assert freed, f"Runner port {runner_port} still in use after stop"

    def test_stop_releases_dashboard_port(self, launcher_env):
        """After stop, dashboard port must be free."""
        import metriplane.launcher as lm
        from metriplane.launcher import cmd_start, cmd_stop
        dash_port = launcher_env["dash_port"]

        cmd_start(live=False, dashboard_port=dash_port,
                  runner_port=launcher_env["runner_port"], open_browser=False)
        assert _wait_for_port("127.0.0.1", dash_port, timeout=5.0)

        cmd_stop()

        freed = _wait_for_port_free(dash_port, timeout=5.0)
        assert freed, f"Dashboard port {dash_port} still in use after stop"

    def test_restart_works_after_stop(self, launcher_env):
        """Restart must succeed immediately after stop (no port residue)."""
        from metriplane.launcher import cmd_start, cmd_stop
        runner_port = launcher_env["runner_port"]
        dash_port = launcher_env["dash_port"]

        rc1 = cmd_start(live=False, dashboard_port=dash_port,
                        runner_port=runner_port, open_browser=False)
        assert rc1 == 0

        cmd_stop()

        # Wait for ports to be free
        _wait_for_port_free(runner_port, timeout=5.0)
        _wait_for_port_free(dash_port, timeout=5.0)

        rc2 = cmd_start(live=False, dashboard_port=dash_port,
                        runner_port=runner_port, open_browser=False)
        assert rc2 == 0, "Second start should succeed after stop"
        assert _wait_for_port("127.0.0.1", runner_port, timeout=10.0)

    def test_double_start_blocked(self, launcher_env, capsys):
        from metriplane.launcher import cmd_start
        runner_port = launcher_env["runner_port"]
        dash_port = launcher_env["dash_port"]

        rc1 = cmd_start(live=False, dashboard_port=dash_port,
                        runner_port=runner_port, open_browser=False)
        assert rc1 == 0

        capsys.readouterr()
        rc2 = cmd_start(live=False, dashboard_port=dash_port,
                        runner_port=runner_port, open_browser=False)
        assert rc2 != 0
        out = capsys.readouterr().out
        assert "already running" in out.lower() or "in use" in out.lower()

    def test_status_shows_port_owners_without_state(self, launcher_env, capsys):
        """status must report port info even with no state file."""
        import metriplane.launcher as lm
        from metriplane.launcher import cmd_start, cmd_stop
        cmd_start(live=False, dashboard_port=launcher_env["dash_port"],
                  runner_port=launcher_env["runner_port"], open_browser=False)

        # Remove state to simulate orphan scenario
        lm._clear_state()
        capsys.readouterr()

        rc = cmd_status()
        assert rc == 0
        out = capsys.readouterr().out
        # Status command should still output runner / port info
        assert "Runner" in out or "runner" in out.lower()
