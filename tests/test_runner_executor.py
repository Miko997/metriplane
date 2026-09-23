# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import select
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from metriplane.paths import PlatformPaths
from metriplane.runner.executor import CommandExecutor, _MAX_CAPTURE_CHARS


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _process_is_gone_or_zombie(pid: int) -> bool:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text().split()
    except (FileNotFoundError, ProcessLookupError):
        return True
    return len(fields) > 2 and fields[2] == "Z"


def test_process_disappearance_during_proc_read_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def vanished(_path: Path) -> str:
        raise ProcessLookupError

    monkeypatch.setattr(Path, "read_text", vanished)
    assert _process_is_gone_or_zombie(12345) is True


def test_cancelled_job_remains_cancelled_after_process_exits(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "cancel-test",
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_s=60,
    )
    assert _wait_until(
        lambda: executor.current_job is not None and executor.current_job.get("process") is not None
    )

    assert executor.cancel(job_id) is True
    assert _wait_until(lambda: executor.get_job(job_id)["exit_code"] is not None)  # type: ignore[index]
    time.sleep(0.05)

    job = executor.get_job(job_id)
    assert job is not None
    assert job["status"] == "cancelled"
    assert "CANCELLED by user" in job["stderr"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_cancel_terminates_child_process_group(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    code = (
        "import pathlib, subprocess, sys, time; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute("group-cancel-test", [sys.executable, "-c", code], timeout_s=60)
    assert _wait_until(child_pid_file.exists)
    child_pid = int(child_pid_file.read_text())

    assert executor.cancel(job_id) is True
    assert _wait_until(lambda: _process_is_gone_or_zombie(child_pid))
    assert executor.get_job(job_id)["status"] == "cancelled"  # type: ignore[index]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_cancel_force_kills_stubborn_child_after_group_leader_exits(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "stubborn-child.pid"
    child_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        f"p=subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "stubborn-group-cancel",
        [sys.executable, "-c", parent_code],
        timeout_s=60,
    )
    assert _wait_until(child_pid_file.exists)
    child_pid = int(child_pid_file.read_text())

    assert executor.cancel(job_id) is True
    assert _wait_until(lambda: _process_is_gone_or_zombie(child_pid))


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
@pytest.mark.parametrize("inherit_pipes", [False, True])
def test_normal_leader_exit_force_cleans_residual_descendant(
    tmp_path: Path,
    inherit_pipes: bool,
) -> None:
    child_pid_file = tmp_path / f"normal-leak-{inherit_pipes}.pid"
    child_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    streams = "" if inherit_pipes else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    parent_code = (
        "import pathlib, subprocess, sys; "
        f"p=subprocess.Popen([sys.executable, '-c', {child_code!r}]{streams}); "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid))"
    )
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        f"normal-leak-{inherit_pipes}",
        [sys.executable, "-c", parent_code],
        timeout_s=15,
    )

    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running", timeout=20)  # type: ignore[index]
    child_pid = int(child_pid_file.read_text())
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "failed"
    assert "PROCESS LEAK" in job["stderr"]
    assert _wait_until(lambda: _process_is_gone_or_zombie(child_pid))


def test_executor_never_uses_thread_unsafe_preexec_fn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    real_popen = executor_module.subprocess.Popen
    observed: list[dict[str, object]] = []

    def recording_popen(*args, **kwargs):
        observed.append(dict(kwargs))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(executor_module.subprocess, "Popen", recording_popen)
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute("no-preexec", [sys.executable, "-c", "pass"], timeout_s=10)
    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]

    assert observed
    assert all("preexec_fn" not in kwargs for kwargs in observed)


@pytest.mark.skipif(os.name != "posix", reason="POSIX identity gate")
def test_missing_supervisor_identity_never_releases_user_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    marker = tmp_path / "user-code-started"
    monkeypatch.setattr(executor_module, "_process_identity", lambda _pid: None)
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "missing-identity-gate",
        [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        timeout_s=10,
    )

    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "failed"
    assert "could not retain child birth/executable/argv identity" in job["stderr"]
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX identity gate")
def test_supervisor_acknowledges_before_identity_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    acknowledged = False
    real_ready = executor_module._await_supervisor_ready
    real_identity = executor_module._process_identity

    def observe_ready(ready_fd, *, timeout=2.0):
        nonlocal acknowledged
        real_ready(ready_fd, timeout=timeout)
        acknowledged = True

    def observe_identity(pid):
        assert acknowledged
        return real_identity(pid)

    monkeypatch.setattr(executor_module, "_await_supervisor_ready", observe_ready)
    monkeypatch.setattr(executor_module, "_process_identity", observe_identity)
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute("ready-before-identity", [sys.executable, "-c", "pass"], 10)

    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "succeeded"
    assert acknowledged


@pytest.mark.skipif(os.name != "posix", reason="POSIX identity gate")
def test_missing_supervisor_acknowledgement_never_releases_user_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    marker = tmp_path / "user-code-started"
    observed: list[subprocess.Popen[str]] = []
    real_popen = executor_module.subprocess.Popen

    def recording_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        observed.append(process)
        return process

    monkeypatch.setattr(executor_module.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(executor_module.select, "select", lambda *_args: ([], [], []))
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "missing-ready-gate",
        [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        10,
    )

    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "failed"
    assert "did not reach its identity gate" in job["stderr"]
    assert observed and observed[0].returncode == 125
    assert not marker.exists()


@pytest.mark.parametrize(
    "failure",
    [OSError("forced readiness failure"), ValueError("descriptor out of range")],
)
def test_supervisor_acknowledgement_failure_closes_descriptor(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    ready_read, ready_write = os.pipe()
    os.close(ready_write)

    def fail_select(*_args):
        raise failure

    monkeypatch.setattr(executor_module.select, "select", fail_select)
    with pytest.raises(RuntimeError, match="readiness channel failed"):
        executor_module._await_supervisor_ready(ready_read)
    with pytest.raises(OSError):
        os.fstat(ready_read)


def test_second_supervisor_pipe_failure_closes_first_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    real_pipe = os.pipe
    allocated: list[tuple[int, int]] = []

    def fail_second_pipe():
        if allocated:
            raise OSError("forced second pipe failure")
        pair = real_pipe()
        allocated.append(pair)
        return pair

    monkeypatch.setattr(executor_module.os, "pipe", fail_second_pipe)
    with pytest.raises(OSError, match="forced second pipe failure"):
        executor_module._supervisor_pipes()
    assert allocated
    for descriptor in allocated[0]:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_linux_proc_stat_parser_preserves_comm_spaces_and_parentheses() -> None:
    import metriplane.runner.executor as executor_module

    tail = ["S", "1", "41", *(["0"] * 16), "987654", "0"]
    value = f"41 (worker name)) {' '.join(tail)}"

    assert executor_module._parse_linux_proc_stat(value) == ("S", 41, "987654")


def test_darwin_procargs_parser_preserves_exact_argument_boundaries() -> None:
    import metriplane.runner.executor as executor_module

    value = (
        struct.pack("=i", 3)
        + b"/usr/bin/python3\0\0"
        + b"/usr/bin/python3\0argument with spaces\0quote'argument\0ENV=value\0"
    )

    assert executor_module._parse_darwin_procargs(value) == [
        "/usr/bin/python3",
        "argument with spaces",
        "quote'argument",
    ]


def test_darwin_procargs_parser_preserves_empty_argument() -> None:
    import metriplane.runner.executor as executor_module

    value = (
        struct.pack("=i", 3)
        + b"/usr/bin/python3\0\0"
        + b"/usr/bin/python3\0metriplane-child-limit\0\0ENV=value\0"
    )

    assert executor_module._parse_darwin_procargs(value) == [
        "/usr/bin/python3",
        "metriplane-child-limit",
        "",
    ]


def test_darwin_process_argv_uses_kern_argmax_as_bounded_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    class FakeFunction:
        def __init__(self, implementation):
            self.implementation = implementation
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.implementation(*args)

    payload = struct.pack("=i", 2) + b"/usr/bin/python3\0\0/usr/bin/python3\0-c\0"
    observed: list[object] = []

    def sysctlbyname(name, value, value_size, replacement, replacement_size):
        observed.append((name, replacement, replacement_size))
        value._obj.value = 4096
        value_size._obj.value = 4
        return 0

    def sysctl(mib, mib_size, value, value_size, replacement, replacement_size):
        observed.append(([mib[index] for index in range(mib_size)], value_size._obj.value))
        assert value is not None
        assert replacement is None
        assert replacement_size == 0
        executor_module.ctypes.memmove(value, payload, len(payload))
        value_size._obj.value = len(payload)
        return 0

    class FakeLibc:
        pass

    fake_libc = FakeLibc()
    fake_libc.sysctlbyname = FakeFunction(sysctlbyname)
    fake_libc.sysctl = FakeFunction(sysctl)

    monkeypatch.setattr(executor_module.ctypes, "CDLL", lambda *_args, **_kwargs: fake_libc)

    assert executor_module._darwin_process_argv(41) == ["/usr/bin/python3", "-c"]
    assert observed == [(b"kern.argmax", None, 0), ([1, 49, 41], 4096)]


def test_darwin_identity_uses_native_kernel_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    monkeypatch.setattr(executor_module.os, "name", "posix")
    monkeypatch.setattr(executor_module.sys, "platform", "darwin")
    expected = {
        "pid": 41,
        "pgid": 41,
        "birth": "1780000000.123456",
        "executable": "/usr/bin/python3",
        "argv": ["/usr/bin/python3", "argument with spaces"],
    }
    monkeypatch.setattr(executor_module, "_darwin_process_identity", lambda _pid: expected)

    assert executor_module._process_identity(41) == expected


def test_darwin_process_count_uses_native_kernel_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    monkeypatch.setattr(executor_module.os, "name", "posix")
    monkeypatch.setattr(executor_module.sys, "platform", "darwin")
    monkeypatch.setattr(executor_module, "_darwin_process_group_size", lambda _pgid: 2)

    assert executor_module._process_group_size(41) == 2


def test_darwin_group_inventory_uses_exact_group_api_and_excludes_zombies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    class FakeFunction:
        def __init__(self, implementation):
            self.implementation = implementation
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.implementation(*args)

    calls: list[tuple[int, bool, int]] = []

    def list_group(pgid: int, pids, size: int) -> int:
        calls.append((pgid, pids is None, size))
        if pids is None:
            return 2
        pids[0] = 41
        pids[1] = 42
        return 2

    def read_info(pid: int, flavor: int, _arg: int, info_pointer, size: int) -> int:
        assert flavor == 3
        info = info_pointer._obj
        info.pbi_pid = pid
        info.pbi_pgid = 9
        info.pbi_status = 5 if pid == 42 else 2
        return size

    class FakeLibproc:
        proc_listpgrppids = FakeFunction(list_group)
        proc_pidinfo = FakeFunction(read_info)

    monkeypatch.setattr(executor_module.sys, "platform", "darwin")
    monkeypatch.setattr(executor_module.ctypes, "CDLL", lambda *_args, **_kwargs: FakeLibproc())

    assert executor_module._darwin_process_group_size(9) == 1
    assert calls[0] == (9, True, 0)
    assert calls[1][0] == 9
    assert calls[1][1] is False


def test_darwin_group_inventory_fails_closed_when_provider_fills_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    class FakeFunction:
        def __init__(self, implementation):
            self.implementation = implementation
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.implementation(*args)

    def list_group(_pgid: int, pids, _size: int) -> int:
        return 1 if pids is None else len(pids)

    class FakeLibproc:
        proc_listpgrppids = FakeFunction(list_group)
        proc_pidinfo = FakeFunction(
            lambda *_args: pytest.fail("truncated inventory must not be inspected")
        )

    monkeypatch.setattr(executor_module.sys, "platform", "darwin")
    monkeypatch.setattr(executor_module.ctypes, "CDLL", lambda *_args, **_kwargs: FakeLibproc())

    assert executor_module._darwin_process_group_size(9) is None


def test_unknown_posix_without_exact_provider_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    monkeypatch.setattr(executor_module.os, "name", "posix")
    monkeypatch.setattr(executor_module.sys, "platform", "freebsd")
    monkeypatch.setattr(executor_module.pathlib.Path, "is_dir", lambda _path: False)

    assert executor_module._process_identity(41) is None
    assert executor_module._process_group_size(41) is None


def test_injected_runner_paths_override_ambient_runs_for_subprocess(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PlatformPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
    ).with_runs_dir(tmp_path / "launcher-recordings")
    monkeypatch.setenv("RUNS", str(tmp_path / "ambient-recordings"))
    executor = CommandExecutor(paths=paths)
    executor.repo_root = tmp_path

    job_id = executor.execute(
        "print-runs",
        [sys.executable, "-c", "import os; print(os.environ['RUNS'])"],
        timeout_s=10,
    )

    assert _wait_until(
        lambda: (
            executor.get_job(job_id) is not None and executor.get_job(job_id)["status"] != "running"
        )  # type: ignore[index]
    )
    job = executor.get_job(job_id)
    assert job is not None
    assert job["status"] == "succeeded"
    assert job["stdout"].strip() == str(paths.runs_dir)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor inheritance")
def test_executor_inherits_owned_descriptor_and_closes_parent_copy(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "session.jsonl"
    artifact.write_text("pinned session\n", encoding="utf-8")
    file_fd = os.open(artifact, os.O_RDONLY)
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    code = (
        "import os, sys; "
        "fd=int(sys.argv[1]); "
        "os.lseek(fd, 0, os.SEEK_SET); "
        "print(os.read(fd, 4096).decode(), end='')"
    )

    job_id = executor.execute(
        "inherited-fd",
        [sys.executable, "-c", code, str(file_fd)],
        timeout_s=10,
        pass_fds=(file_fd,),
    )

    assert _wait_until(
        lambda: (
            executor.get_job(job_id) is not None and executor.get_job(job_id)["status"] != "running"
        )  # type: ignore[index]
    )
    job = executor.get_job(job_id)
    assert job is not None
    assert job["status"] == "succeeded"
    assert job["stdout"] == "pinned session\n"
    with pytest.raises(OSError):
        os.fstat(file_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor inheritance")
def test_supervisor_closes_inherited_writer_before_user_child_exits(tmp_path: Path) -> None:
    read_fd, write_fd = os.pipe()
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    code = "import os, sys, time; os.close(int(sys.argv[1])); time.sleep(2)"
    try:
        job_id = executor.execute(
            "inherited-fd-eof",
            [sys.executable, "-c", code, str(write_fd)],
            timeout_s=10,
            pass_fds=(write_fd,),
        )
        assert _wait_until(
            lambda: (
                executor.current_job is not None and executor.current_job.get("process") is not None
            )
        )
        readable, _, _ = select.select([read_fd], [], [], 1.0)
        assert readable == [read_fd]
        assert os.read(read_fd, 1) == b""
        job = executor.get_job(job_id)
        assert job is not None
        assert job["status"] == "running"
        assert _wait_until(lambda: executor.get_job(job_id)["status"] == "succeeded", timeout=5)
    finally:
        os.close(read_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor inheritance")
def test_executor_does_not_leak_internal_gate_descriptor(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    code = (
        "import json, os\n"
        "live = []\n"
        "for fd in range(3, 256):\n"
        "    try:\n"
        "        os.fstat(fd)\n"
        "        live.append(fd)\n"
        "    except OSError:\n"
        "        pass\n"
        "print(json.dumps(live))"
    )

    job_id = executor.execute("descriptor-boundary", [sys.executable, "-c", code], timeout_s=10)
    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "succeeded"
    assert job["stdout"].strip() == "[]"


@pytest.mark.skipif(os.name != "posix", reason="POSIX resource limits")
def test_executor_applies_open_file_and_cpu_limits(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    code = (
        "import json, resource; "
        "print(json.dumps({'nofile': resource.getrlimit(resource.RLIMIT_NOFILE)[0], "
        "'cpu': resource.getrlimit(resource.RLIMIT_CPU)[0]}))"
    )

    job_id = executor.execute("resource-limits", [sys.executable, "-c", code], timeout_s=10)
    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "succeeded"
    import json

    limits = json.loads(job["stdout"])
    assert limits == {"nofile": 512, "cpu": 11}


def test_executor_enforces_wall_clock_timeout(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "wall-timeout",
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_s=1,
    )

    assert _wait_until(
        lambda: executor.get_job(job_id)["status"] != "running",  # type: ignore[index]
        timeout=5,
    )
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "timed_out"
    assert "TIMEOUT" in job["stderr"]


def test_child_environment_is_allowlisted_and_home_is_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PlatformPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
    ).with_runs_dir(tmp_path / "runs")
    monkeypatch.setenv("MP2_027_AMBIENT_SECRET", "must-not-cross")
    executor = CommandExecutor(paths=paths)
    executor.repo_root = tmp_path
    code = (
        "import json, os; "
        "print(json.dumps({'ambient': os.getenv('MP2_027_AMBIENT_SECRET'), "
        "'home': os.environ['HOME'], 'cwd': os.getcwd()}))"
    )

    job_id = executor.execute("minimal-environment", [sys.executable, "-c", code], timeout_s=10)
    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "succeeded"
    import json

    observed = json.loads(job["stdout"])
    assert observed == {
        "ambient": None,
        "home": str(paths.state_dir / "runner-home"),
        "cwd": str(tmp_path),
    }
    assert (paths.state_dir / "runner-home").stat().st_mode & 0o777 == 0o700


def test_flood_output_is_drained_but_retained_output_is_capped(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    emitted = _MAX_CAPTURE_CHARS + 131_072
    code = f"import sys; sys.stdout.write('x' * {emitted}); sys.stderr.write('y' * {emitted})"

    job_id = executor.execute("flood", [sys.executable, "-c", code], timeout_s=15)
    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running", timeout=20)  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "succeeded"
    assert job["stdout"].startswith("x" * 1024)
    assert job["stderr"].startswith("y" * 1024)
    assert "OUTPUT TRUNCATED" in job["stdout"]
    assert "OUTPUT TRUNCATED" in job["stderr"]
    assert len(job["stdout"]) < emitted
    assert len(job["stderr"]) < emitted


def test_invalid_output_bytes_are_retained_with_deterministic_escapes(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    code = "import os; os.write(1, b'valid\\xffstdout'); os.write(2, b'valid\\xfestderr')"

    job_id = executor.execute("invalid-output-bytes", [sys.executable, "-c", code], timeout_s=10)
    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "succeeded"
    assert job["stdout"] == r"valid\xffstdout"
    assert job["stderr"] == r"valid\xfestderr"


def test_reader_failure_is_recorded_for_the_caller() -> None:
    import metriplane.runner.executor as executor_module

    class BrokenStream:
        def read(self, _size):
            raise UnicodeError("broken child stream")

        def close(self):
            return None

    errors: list[str] = []
    executor_module._drain_stream(
        BrokenStream(),
        executor_module._BoundedTextCapture(),
        errors,
    )

    assert errors == ["UnicodeError: broken child stream"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_process_limit_failure_terminates_the_retained_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    monkeypatch.setattr(
        executor_module,
        "_process_group_size",
        lambda _pgid: executor_module._MAX_CHILD_PROCESSES + 1,
    )
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "process-limit",
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_s=10,
    )
    assert _wait_until(lambda: executor.get_job(job_id)["status"] != "running")  # type: ignore[index]
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "failed"
    assert "PROCESS LIMIT" in job["stderr"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_unavailable_process_inventory_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    monkeypatch.setattr(executor_module, "_process_group_size", lambda _pgid: None)
    observed: list[subprocess.Popen[str]] = []
    real_popen = executor_module.subprocess.Popen

    def recording_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        observed.append(process)
        return process

    monkeypatch.setattr(executor_module.subprocess, "Popen", recording_popen)
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "inventory-unavailable",
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_s=10,
    )

    assert _wait_until(
        lambda: executor.get_job(job_id)["status"] != "running",  # type: ignore[index]
        timeout=10,
    )
    job = executor.get_job(job_id)
    assert job is not None and job["status"] == "failed"
    assert "PROCESS INVENTORY" in job["stderr"]
    assert "CLEANUP UNVERIFIED" in job["stderr"]
    assert observed and observed[0].poll() is not None
    assert observed[0].wait(timeout=1) is not None


def test_cancel_refuses_changed_process_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.runner.executor as executor_module

    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "identity-change",
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_s=60,
    )
    assert _wait_until(
        lambda: executor.current_job is not None and executor.current_job.get("process") is not None
    )
    process = executor.current_job["process"]  # type: ignore[index]
    monkeypatch.setattr(
        executor_module,
        "_process_identity",
        lambda pid: {
            "pid": pid,
            "pgid": pid,
            "birth": "reused",
            "executable": "/tmp/reused",
            "argv": ["reused"],
        },
    )

    assert executor.cancel(job_id) is True
    job = executor.get_job(job_id)
    assert job is not None
    assert "refusing numeric PID/PGID cleanup" in job["stderr"]
    monkeypatch.undo()
    process.kill()
    process.wait(timeout=5)
