# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import textwrap
import time
from contextlib import contextmanager
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


@pytest.mark.parametrize(
    "run_id",
    ["CON", "nul.txt", "PrN.log", "COM1", "com9.capture", "LPT9.log"],
)
def test_start_fusion_rejects_windows_device_run_ids_before_execution(
    tmp_path: Path,
    run_id: str,
) -> None:
    api = make_api(tmp_path)
    config = tmp_path / "configs" / "safe.yaml"
    config.parent.mkdir()
    config.write_text("source_mode: dummy\n", encoding="utf-8")

    status, payload = api._start_fusion(
        {"config": "configs/safe.yaml", "duration_s": 30, "run_id": run_id}
    )

    assert status == 400
    assert "Windows device basenames" in payload["error"]
    api.executor.execute.assert_not_called()


@pytest.mark.parametrize(
    "run_id",
    ["safe_run", "run.with-dots_1", "CONSOLE", "COM10.capture", "LPT10.log"],
)
def test_start_fusion_preserves_portable_run_ids(tmp_path: Path, run_id: str) -> None:
    api = make_api(tmp_path)
    config = tmp_path / "configs" / "safe.yaml"
    config.parent.mkdir()
    config.write_text("source_mode: dummy\n", encoding="utf-8")

    status, payload = api._start_fusion(
        {"config": "configs/safe.yaml", "duration_s": 30, "run_id": run_id}
    )

    assert status == 200
    assert payload["run_id"] == run_id
    command = api.executor.execute.call_args.kwargs["command"]
    assert command[command.index("--run-id") + 1] == run_id


@pytest.mark.parametrize("run_id", ["", " \t ", None])
def test_start_fusion_rejects_explicit_blank_or_null_run_id(
    tmp_path: Path,
    run_id: object,
) -> None:
    api = make_api(tmp_path)
    config = tmp_path / "configs" / "safe.yaml"
    config.parent.mkdir()
    config.write_text("source_mode: dummy\n", encoding="utf-8")

    status, payload = api._start_fusion(
        {"config": "configs/safe.yaml", "duration_s": 30, "run_id": run_id}
    )

    assert status == 400
    assert "run_id" in payload["error"]
    api.executor.execute.assert_not_called()


def test_start_fusion_generates_run_id_when_field_is_omitted(tmp_path: Path) -> None:
    api = make_api(tmp_path)
    config = tmp_path / "configs" / "safe.yaml"
    config.parent.mkdir()
    config.write_text("source_mode: dummy\n", encoding="utf-8")

    status, payload = api._start_fusion({"config": "configs/safe.yaml", "duration_s": 30})

    assert status == 200
    assert payload["run_id"].startswith("operator_run_")
    command = api.executor.execute.call_args.kwargs["command"]
    assert command[command.index("--run-id") + 1] == payload["run_id"]


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


def test_checksum_fails_closed_when_authorized_parent_is_swapped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import operator_api

    api = make_api(tmp_path)
    run = api._runs_root() / "authorized"
    parked = run.with_name("authorized-original")
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    artifact = run / "artifact.txt"
    artifact.write_text("authorized bytes\n", encoding="utf-8")
    (outside / artifact.name).write_text("outside bytes\n", encoding="utf-8")
    original_open = operator_api.open_pinned_file

    @contextmanager
    def swap_after_pin(allowed_roots, requested):
        with original_open(allowed_roots, requested) as pinned:
            run.rename(parked)
            run.symlink_to(outside, target_is_directory=True)
            yield pinned

    monkeypatch.setattr(operator_api, "open_pinned_file", swap_after_pin)

    status, payload = api._checksum({"path": str(artifact)})

    assert status == 400
    assert "regular files" in payload["error"]


def test_generate_report_transfers_a_pinned_session_fd(
    tmp_path: Path,
) -> None:
    class DeferredExecutor:
        command: list[str]
        pass_fds: tuple[int, ...]

        def execute(self, *, command_id, command, timeout_s, pass_fds=()):
            assert command_id == "generate-zones"
            assert timeout_s == 120
            self.command = command
            self.pass_fds = pass_fds
            return "job-pinned-report"

    executor = DeferredExecutor()
    api = make_api(tmp_path)
    api.executor = executor
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "zones_report_jsonl.py").write_text("# pinned report fixture\n")
    run = api._runs_root() / "authorized"
    parked = run.with_name("authorized-original")
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    session = run / "session.jsonl"
    session.write_text("authorized session\n", encoding="utf-8")
    (outside / session.name).write_text("outside session\n", encoding="utf-8")

    status, payload = api._generate_report(
        {"type": "zones", "session": str(session), "prefix": "secure"}
    )

    assert status == 200
    assert payload["job_id"] == "job-pinned-report"
    assert str(session) in payload["command_preview"]
    assert "/proc/self/fd/" not in payload["command_preview"]
    assert len(executor.pass_fds) == 1
    inherited_fd = executor.pass_fds[0]
    try:
        assert executor.command[2].endswith(f"/{inherited_fd}")
        run.rename(parked)
        run.symlink_to(outside, target_is_directory=True)
        assert Path(executor.command[2]).read_text() == "authorized session\n"
    finally:
        os.close(inherited_fd)


def test_generate_report_fails_closed_without_descriptor_backed_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import operator_api

    api = make_api(tmp_path)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "zones_report_jsonl.py").write_text("# report fixture\n")
    session = api._runs_root() / "authorized" / "session.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text("authorized session\n", encoding="utf-8")

    def unsupported(_file_fd: int) -> str:
        raise OSError(errno.ENOTSUP, "descriptor-backed input unavailable")

    monkeypatch.setattr(operator_api, "inherited_fd_path", unsupported)

    status, payload = api._generate_report(
        {"type": "zones", "session": str(session), "prefix": "secure"}
    )

    assert status == 503
    assert "cannot be opened safely" in payload["error"]
    api.executor.execute.assert_not_called()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc descriptor path")
def test_generate_report_async_child_reads_pinned_inode_after_parent_swap(
    tmp_path: Path,
) -> None:
    from metriplane.runner.executor import CommandExecutor

    api = make_api(tmp_path)
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    api.executor = executor
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "zones_report_jsonl.py").write_text(
        "import pathlib, sys, time\n"
        "time.sleep(0.2)\n"
        "print(pathlib.Path(sys.argv[1]).read_text(), end='')\n",
        encoding="utf-8",
    )
    run = api._runs_root() / "authorized"
    parked = run.with_name("authorized-original")
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    session = run / "session.jsonl"
    session.write_text("authorized session\n", encoding="utf-8")
    (outside / session.name).write_text("outside session\n", encoding="utf-8")

    status, payload = api._generate_report(
        {"type": "zones", "session": str(session), "prefix": "secure"}
    )
    assert status == 200
    run.rename(parked)
    run.symlink_to(outside, target_is_directory=True)

    deadline = time.monotonic() + 5
    job = executor.get_job(payload["job_id"])
    while job is not None and job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        job = executor.get_job(payload["job_id"])

    assert job is not None
    assert job["status"] == "succeeded"
    assert job["stdout"] == "authorized session\n"


@pytest.mark.parametrize("endpoint", ["start-fusion", "generate-report", "save-config"])
def test_operator_path_loops_are_deterministic_client_errors(
    tmp_path: Path,
    endpoint: str,
) -> None:
    api = make_api(tmp_path)
    if endpoint == "start-fusion":
        configs = tmp_path / "configs"
        configs.mkdir()
        configs.joinpath("loop").symlink_to("loop")
        body = {
            "config": "configs/loop/config.yaml",
            "duration_s": 30,
            "run_id": "safe_run",
        }
    elif endpoint == "generate-report":
        runs_root = api._runs_root()
        runs_root.mkdir(parents=True)
        loop = runs_root / "loop"
        loop.symlink_to(loop.name)
        body = {"type": "zones", "session": str(loop), "prefix": "safe"}
    else:
        calib = tmp_path / "calib"
        calib.mkdir()
        calib.joinpath("loop").symlink_to("loop")
        body = {
            "filename": "safe.yaml",
            "config": {
                "cameras": [
                    {
                        "device": "/dev/video0",
                        "mapping_file": "calib/loop/mapping.yaml",
                        "name": "cam0",
                    }
                ]
            },
        }

    status, payload = api.route("POST", f"/operator/{endpoint}", body)

    assert status == 400
    assert "Internal error" not in str(payload)
    api.executor.execute.assert_not_called()


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


def test_latest_run_preserves_selected_run_metadata_response(tmp_path: Path) -> None:
    api = make_api(tmp_path)
    runs_root = api._runs_root()
    older = runs_root / "older"
    selected = runs_root / "selected"
    older.mkdir(parents=True)
    selected.mkdir()
    (older / "meta.json").write_text('{"run_id": "older"}\n', encoding="utf-8")
    (selected / "session.jsonl").write_text("{}\n", encoding="utf-8")
    (selected / "meta.json").write_text(
        '{"run_id": "selected", "git_commit": "abc123"}\n',
        encoding="utf-8",
    )
    os.utime(older, (1, 1))
    os.utime(selected, (2, 2))

    status, payload = api.route("GET", "/operator/latest-run", {})

    assert status == 200
    assert payload["runs_dir"] == str(runs_root)
    assert payload["latest_run"] == {
        "dir": str(selected),
        "name": "selected",
        "session_exists": True,
        "session_size_mb": 0.0,
        "meta_exists": True,
        "mtime": 2.0,
        "meta": {"run_id": "selected", "git_commit": "abc123"},
    }
    assert [run["name"] for run in payload["all_runs"]] == ["selected", "older"]


def test_latest_run_does_not_read_outside_meta_after_selected_parent_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metriplane.runner.safe_reads import PinnedFile

    api = make_api(tmp_path)
    run = api._runs_root() / "selected"
    parked = run.with_name("selected-original")
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    (run / "session.jsonl").write_text("{}\n", encoding="utf-8")
    (run / "meta.json").write_text('{"run_id": "authorized"}\n', encoding="utf-8")
    (outside / "meta.json").write_text('{"run_id": "outside"}\n', encoding="utf-8")
    original_read_text = PinnedFile.read_text
    swapped = False

    def swap_before_meta_read(
        artifact: PinnedFile,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        nonlocal swapped
        if artifact.name == "meta.json" and not swapped:
            run.rename(parked)
            run.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_read_text(artifact, encoding, errors)

    monkeypatch.setattr(PinnedFile, "read_text", swap_before_meta_read)

    status, payload = api.route("GET", "/operator/latest-run", {})

    assert swapped
    assert status == 200
    assert payload["latest_run"]["name"] == "selected"
    assert payload["latest_run"]["meta_exists"] is True
    assert "meta" not in payload["latest_run"]
    assert "outside" not in json.dumps(payload)


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


def test_command_center_fails_closed_when_selected_run_parent_is_swapped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import operator_api

    api = make_api(tmp_path)
    run = api._runs_root() / "authorized"
    parked = run.with_name("authorized-original")
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    (run / "incident.json").write_text(
        '{"incident_id": "authorized"}\n',
        encoding="utf-8",
    )
    (outside / "incident.json").write_text(
        '{"incident_id": "outside"}\n',
        encoding="utf-8",
    )
    original_open = operator_api.open_pinned_directory

    @contextmanager
    def swap_after_pin(allowed_roots, requested):
        with original_open(allowed_roots, requested) as pinned:
            run.rename(parked)
            run.symlink_to(outside, target_is_directory=True)
            yield pinned

    monkeypatch.setattr(operator_api, "open_pinned_directory", swap_after_pin)

    status, payload = api._cc_incidents({"run_dir": str(run)})

    assert status == 200
    assert payload["incidents"] == []


def test_secure_operator_writes_ignore_umask_zero(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        import json
        import os
        import stat
        import sys
        from pathlib import Path

        from metriplane.runner.safe_writes import open_secure_directory

        root = Path(sys.argv[1])
        os.umask(0)
        root.mkdir(mode=0o700)
        with open_secure_directory(root, Path("configs/local"), create=True) as directory:
            directory.atomic_write("new.yaml", b"new\\n", overwrite=False)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            existing_fd = os.open("existing.yaml", flags, 0o666, dir_fd=directory.fd)
            os.write(existing_fd, b"old\\n")
            os.close(existing_fd)
            directory.atomic_write("existing.yaml", b"replacement\\n", overwrite=True)
        paths = {
            "configs": root / "configs",
            "local": root / "configs" / "local",
            "new": root / "configs" / "local" / "new.yaml",
            "existing": root / "configs" / "local" / "existing.yaml",
        }
        print(json.dumps({name: stat.S_IMODE(path.stat().st_mode) for name, path in paths.items()}))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "repo")],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert json.loads(result.stdout) == {
        "configs": 0o700,
        "local": 0o700,
        "new": 0o600,
        "existing": 0o600,
    }


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")


def test_create_profile_rejects_external_profile_symlink(tmp_path: Path) -> None:
    api = make_api(tmp_path)
    profiles = tmp_path / "calib" / "profiles"
    outside = tmp_path / "outside-profile"
    profiles.mkdir(parents=True)
    outside.mkdir()
    _symlink_or_skip(
        profiles / "local_escape",
        outside,
        target_is_directory=True,
    )

    status, payload = api.route(
        "POST",
        "/operator/create-profile",
        {"name": "escape", "width_m": 1.0, "height_m": 1.0},
    )

    assert status == 400
    assert "links are not allowed" in payload["error"]
    assert not (outside / "anchors.yaml").exists()
    assert not (outside / "cam0").exists()


def test_write_zones_rejects_external_profile_symlink(tmp_path: Path) -> None:
    api = make_api(tmp_path)
    profiles = tmp_path / "calib" / "profiles"
    outside = tmp_path / "outside-profile"
    profiles.mkdir(parents=True)
    outside.mkdir()
    _symlink_or_skip(
        profiles / "local_escape",
        outside,
        target_is_directory=True,
    )

    status, payload = api.route(
        "POST",
        "/operator/write-zones",
        {
            "profile": "local_escape",
            "zones": [{"name": "safe_zone", "polygon": [[0, 0], [1, 0], [0, 1]]}],
        },
    )

    assert status == 400
    assert "links are not allowed" in payload["error"]
    assert not (outside / "zones.yaml").exists()


def test_save_config_rejects_external_local_directory_symlink(tmp_path: Path) -> None:
    api = make_api(tmp_path)
    configs = tmp_path / "configs"
    outside = tmp_path / "outside-configs"
    configs.mkdir()
    outside.mkdir()
    _symlink_or_skip(
        configs / "local",
        outside,
        target_is_directory=True,
    )

    status, payload = api.route(
        "POST",
        "/operator/save-config",
        {"filename": "safe.yaml", "config": {"profile": "local_test"}},
    )

    assert status == 400
    assert "links are not allowed" in payload["error"]
    assert not (outside / "safe.yaml").exists()


def test_save_config_rejects_local_directory_symlink_loop_deterministically(
    tmp_path: Path,
) -> None:
    api = make_api(tmp_path)
    configs = tmp_path / "configs"
    configs.mkdir()
    _symlink_or_skip(
        configs / "local",
        Path("local"),
        target_is_directory=True,
    )

    status, payload = api.route(
        "POST",
        "/operator/save-config",
        {"filename": "safe.yaml", "config": {"profile": "local_test"}},
    )

    assert status == 400
    assert payload["error"].endswith("links are not allowed")
    assert "Internal error" not in str(payload)


def test_write_zones_parent_swap_cannot_redirect_staged_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    api = make_api(tmp_path)
    profiles = tmp_path / "calib" / "profiles"
    profile_dir = profiles / "local_swap"
    parked_profile = profiles / "local_swap-original"
    outside = tmp_path / "outside-profile"
    profile_dir.mkdir(parents=True)
    outside.mkdir()
    original_content = "zones:\n- name: original\n"
    outside_content = "outside must remain unchanged\n"
    (profile_dir / "zones.yaml").write_text(original_content, encoding="utf-8")
    (outside / "zones.yaml").write_text(outside_content, encoding="utf-8")

    original_assert = safe_writes._assert_directory_chain
    calls = 0

    def swap_before_commit(links):
        nonlocal calls
        calls += 1
        if calls == 3:
            profile_dir.rename(parked_profile)
            profile_dir.symlink_to(outside, target_is_directory=True)
        return original_assert(links)

    monkeypatch.setattr(safe_writes, "_assert_directory_chain", swap_before_commit)

    status, payload = api.route(
        "POST",
        "/operator/write-zones",
        {
            "profile": "local_swap",
            "overwrite": True,
            "zones": [{"name": "replacement", "polygon": [[0, 0], [1, 0], [0, 1]]}],
        },
    )

    assert status == 400
    assert "changed during write" in payload["error"]
    assert (outside / "zones.yaml").read_text(encoding="utf-8") == outside_content
    assert (parked_profile / "zones.yaml").read_text(encoding="utf-8") == original_content
    assert not list(parked_profile.glob(".zones.yaml.tmp-*"))

    profile_dir.unlink()
    parked_profile.rename(profile_dir)
    assert (profile_dir / "zones.yaml").read_text(encoding="utf-8") == original_content


def test_create_profile_final_swap_cannot_redirect_atomic_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    api = make_api(tmp_path)
    profile_dir = tmp_path / "calib" / "profiles" / "local_swap"
    profile_dir.joinpath("cam0").mkdir(parents=True)
    anchors_path = profile_dir / "anchors.yaml"
    parked_anchors = profile_dir / "anchors-original.yaml"
    outside_anchors = tmp_path / "outside-anchors.yaml"
    original_content = "profile: original\n"
    outside_content = "outside must remain unchanged\n"
    anchors_path.write_text(original_content, encoding="utf-8")
    outside_anchors.write_text(outside_content, encoding="utf-8")

    original_exchange = safe_writes._exchange_entries
    injected = False

    def swap_at_atomic_install(directory_fd, staged_name, destination):
        nonlocal injected
        if not injected:
            injected = True
            anchors_path.rename(parked_anchors)
            anchors_path.symlink_to(outside_anchors)
        return original_exchange(directory_fd, staged_name, destination)

    monkeypatch.setattr(
        safe_writes,
        "_exchange_entries",
        swap_at_atomic_install,
    )

    status, payload = api.route(
        "POST",
        "/operator/create-profile",
        {
            "name": "swap",
            "overwrite": True,
            "width_m": 1.0,
            "height_m": 1.0,
        },
    )

    assert status == 400
    assert "changed during atomic replacement" in payload["error"]
    assert outside_anchors.read_text(encoding="utf-8") == outside_content
    assert parked_anchors.read_text(encoding="utf-8") == original_content
    assert not list(profile_dir.glob(".anchors.yaml.tmp-*"))

    anchors_path.unlink()
    parked_anchors.rename(anchors_path)
    assert anchors_path.read_text(encoding="utf-8") == original_content


def test_macos_without_atomic_exchange_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    destination = local_dir / "safe.yaml"
    destination.write_bytes(b"original\n")
    monkeypatch.setattr(safe_writes, "_use_portable_overwrite", lambda: True)

    def fail_exchange(_directory_fd: int, _left: str, _right: str) -> None:
        raise AssertionError("Linux renameat2 path must not run in the macOS simulation")

    monkeypatch.setattr(safe_writes, "_exchange_entries", fail_exchange)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(OSError, match="race-resistant atomic overwrite is unavailable"),
    ):
        directory.atomic_write("safe.yaml", b"replacement\n", overwrite=True)

    assert destination.read_bytes() == b"original\n"
    assert not list(local_dir.glob(".safe.yaml.tmp-*"))


def test_darwin_atomic_exchange_uses_renameatx_np(monkeypatch) -> None:
    from metriplane.runner import safe_writes

    calls = []

    class FakeExchange:
        argtypes = None
        restype = None

        def __call__(self, *args):
            calls.append(args)
            return 0

    class FakeLibc:
        renameatx_np = FakeExchange()

    monkeypatch.setattr(safe_writes.sys, "platform", "darwin")
    monkeypatch.setattr(safe_writes.ctypes, "CDLL", lambda *_args, **_kwargs: FakeLibc())

    safe_writes._exchange_entries(17, "staged", "destination")

    assert calls == [(17, b"staged", 17, b"destination", 2)]


def test_darwin_mode_zero_destination_reports_operational_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    destination = local_dir / "safe.yaml"
    destination.write_bytes(b"original\n")
    destination.chmod(0)
    real_open = safe_writes.os.open
    observed_flags: list[int] = []

    def deny_evtonly(path, flags, mode=0o777, *, dir_fd=None):
        observed_flags.append(flags)
        if flags & safe_writes._DARWIN_O_EVTONLY:
            opened = safe_writes.os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
            assert opened.st_mode & 0o777 == 0
            raise PermissionError(errno.EACCES, "injected Darwin permission denial", path)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.delattr(safe_writes.os, "O_PATH", raising=False)
    monkeypatch.setattr(safe_writes.sys, "platform", "darwin")
    monkeypatch.setattr(safe_writes.os, "open", deny_evtonly)

    try:
        status, payload = make_api(tmp_path).route(
            "POST",
            "/operator/save-config",
            {
                "filename": "safe.yaml",
                "overwrite": True,
                "config": {"profile": "replacement"},
            },
        )
    finally:
        destination.chmod(0o600)

    assert status == 503
    assert payload["error"] == "Unable to write config 'safe.yaml'"
    assert any(flags & safe_writes._DARWIN_O_EVTONLY for flags in observed_flags)
    assert destination.read_bytes() == b"original\n"
    assert not list(local_dir.glob(".safe.yaml.tmp-*"))


def test_darwin_unsupported_atomic_exchange_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    destination = local_dir / "safe.yaml"
    destination.write_bytes(b"original\n")
    monkeypatch.setattr(safe_writes.sys, "platform", "darwin")
    monkeypatch.setattr(safe_writes, "_use_portable_overwrite", lambda: False)

    def unsupported_exchange(_directory_fd: int, _left: str, _right: str) -> None:
        raise OSError(errno.ENOTSUP, "injected unsupported exchange")

    monkeypatch.setattr(safe_writes, "_exchange_entries", unsupported_exchange)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(OSError, match="injected unsupported exchange"),
    ):
        directory.atomic_write("safe.yaml", b"replacement\n", overwrite=True)

    assert destination.read_bytes() == b"original\n"
    assert not list(local_dir.glob(".safe.yaml.tmp-*"))


def test_atomic_exchange_rejects_staged_name_substitution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    destination = local_dir / "safe.yaml"
    parked_staged = local_dir / "parked-staged.yaml"
    original = b"original\n"
    replacement = b"replacement\n"
    attacker = b"attacker\n"
    destination.write_bytes(original)
    original_exchange = safe_writes._exchange_entries
    calls = 0

    def substitute_staged(directory_fd, staged_name, destination_name) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            staged_path = local_dir / staged_name
            staged_path.rename(parked_staged)
            staged_path.write_bytes(attacker)
        original_exchange(directory_fd, staged_name, destination_name)

    monkeypatch.setattr(safe_writes, "_exchange_entries", substitute_staged)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(
            safe_writes.UnsafeWritePathError,
            match="exchange entries changed during atomic replacement",
        ),
    ):
        directory.atomic_write("safe.yaml", replacement, overwrite=True)

    assert destination.read_bytes() == original
    assert parked_staged.read_bytes() == replacement
    quarantines = [path for path in local_dir.iterdir() if ".quarantine-" in path.name]
    assert len(quarantines) == 1
    assert (quarantines[0] / "entry").read_bytes() == attacker


def test_atomic_exchange_quarantines_cleanup_substitution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    destination = local_dir / "safe.yaml"
    parked_original = local_dir / "parked-original.yaml"
    victim = local_dir / "victim.yaml"
    original = b"original\n"
    replacement = b"replacement\n"
    victim_content = b"victim must be retained\n"
    destination.write_bytes(original)
    victim.write_bytes(victim_content)
    original_rename = safe_writes.os.rename
    original_unlink = safe_writes.os.unlink
    shared_unlinks: list[str] = []
    substituted = False

    def substitute_before_quarantine(
        source,
        target,
        *,
        src_dir_fd=None,
        dst_dir_fd=None,
    ) -> None:
        nonlocal substituted
        if (
            not substituted
            and isinstance(source, str)
            and source.startswith(".safe.yaml.tmp-")
            and target == "entry"
            and src_dir_fd != dst_dir_fd
        ):
            substituted = True
            original_rename(local_dir / source, parked_original)
            original_rename(victim, local_dir / source)
        original_rename(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def record_unlink(path, *, dir_fd=None) -> None:
        if dir_fd is not None and isinstance(path, str) and path.startswith(".safe.yaml.tmp-"):
            shared_unlinks.append(path)
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(safe_writes.os, "rename", substitute_before_quarantine)
    monkeypatch.setattr(safe_writes.os, "unlink", record_unlink)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(safe_writes.UnsafeWritePathError, match="entry retained as"),
    ):
        directory.atomic_write("safe.yaml", replacement, overwrite=True)

    assert substituted is True
    assert shared_unlinks == []
    assert destination.read_bytes() == replacement
    assert parked_original.read_bytes() == original
    assert not victim.exists()
    quarantines = [path for path in local_dir.iterdir() if ".quarantine-" in path.name]
    assert len(quarantines) == 1
    assert (quarantines[0] / "entry").read_bytes() == victim_content


def test_atomic_exchange_pins_displaced_inode_through_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    destination = local_dir / "safe.yaml"
    destination.write_bytes(b"original\n")
    original_cleanup = safe_writes._quarantine_owned_entry
    observed_unlinked_pin = False

    def replace_displaced_entry(
        directory_fd,
        name,
        display_path,
        expected,
        pinned_fd,
    ):
        nonlocal observed_unlinked_pin
        if not observed_unlinked_pin and name.startswith(".safe.yaml.tmp-"):
            safe_writes.os.unlink(name, dir_fd=directory_fd)
            substitute_fd = safe_writes.os.open(
                name,
                safe_writes.os.O_WRONLY | safe_writes.os.O_CREAT | safe_writes.os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            safe_writes.os.write(substitute_fd, b"unrelated substitute\n")
            safe_writes.os.close(substitute_fd)
            observed_unlinked_pin = safe_writes.os.fstat(pinned_fd).st_nlink == 0
        return original_cleanup(
            directory_fd,
            name,
            display_path,
            expected,
            pinned_fd,
        )

    monkeypatch.setattr(safe_writes, "_quarantine_owned_entry", replace_displaced_entry)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(safe_writes.UnsafeWritePathError, match="entry retained as"),
    ):
        directory.atomic_write("safe.yaml", b"replacement\n", overwrite=True)

    assert observed_unlinked_pin is True
    assert destination.read_bytes() == b"replacement\n"
    quarantines = [path for path in local_dir.iterdir() if ".quarantine-" in path.name]
    assert len(quarantines) == 1
    assert (quarantines[0] / "entry").read_bytes() == b"unrelated substitute\n"


def test_installed_cleanup_failure_does_not_replace_primary_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    original_destination_identity = safe_writes._destination_identity
    calls = 0

    def fail_installed_verification(directory_fd, name, display_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise safe_writes.UnsafeWritePathError("PRIMARY-VERIFY")
        return original_destination_identity(directory_fd, name, display_path)

    def fail_cleanup(*_args, **_kwargs):
        raise OSError("CLEANUP-FAILURE")

    monkeypatch.setattr(safe_writes, "_destination_identity", fail_installed_verification)
    monkeypatch.setattr(safe_writes, "_quarantine_owned_entry", fail_cleanup)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(safe_writes.UnsafeWritePathError, match="PRIMARY-VERIFY") as captured,
    ):
        directory.atomic_write("safe.yaml", b"replacement\n", overwrite=False)

    assert any("CLEANUP-FAILURE" in note for note in captured.value.__notes__)


def test_staged_close_failure_does_not_replace_write_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    original_create = safe_writes._create_staged_file
    original_close = safe_writes.os.close
    staged_descriptor: int | None = None
    close_injected = False

    def capture_staged_descriptor(directory_fd, name, mode):
        nonlocal staged_descriptor
        staged_name, staged_descriptor = original_create(directory_fd, name, mode)
        return staged_name, staged_descriptor

    def fail_write(_file_fd, _content):
        raise OSError("PRIMARY-WRITE")

    def fail_staged_close(file_fd):
        nonlocal close_injected
        if file_fd == staged_descriptor and not close_injected:
            close_injected = True
            original_close(file_fd)
            raise OSError(errno.EIO, "CLOSE-FAILURE")
        original_close(file_fd)

    monkeypatch.setattr(safe_writes, "_create_staged_file", capture_staged_descriptor)
    monkeypatch.setattr(safe_writes, "_write_all", fail_write)
    monkeypatch.setattr(safe_writes.os, "close", fail_staged_close)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(OSError, match="PRIMARY-WRITE") as captured,
    ):
        directory.atomic_write("safe.yaml", b"replacement\n", overwrite=False)

    assert any("CLOSE-FAILURE" in note for note in captured.value.__notes__)
    assert not list(local_dir.glob(".safe.yaml.tmp-*"))


def test_atomic_exchange_recovers_trusted_destination_after_rollback_interference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    destination = local_dir / "safe.yaml"
    parked_destination = local_dir / "safe-original.yaml"
    outside = tmp_path / "outside.yaml"
    original = b"original\n"
    replacement = b"replacement\n"
    outside_content = b"outside must remain unchanged\n"
    late_substitute = b"late substitute\n"
    destination.write_bytes(original)
    outside.write_bytes(outside_content)
    original_exchange = safe_writes._exchange_entries
    calls = 0

    def interfere_with_rollback(directory_fd, staged_name, destination_name) -> None:
        nonlocal calls
        calls += 1
        staged_path = local_dir / staged_name
        if calls == 1:
            destination.rename(parked_destination)
            destination.symlink_to(outside)
        elif calls == 2:
            staged_path.unlink()
            staged_path.write_bytes(late_substitute)
        original_exchange(directory_fd, staged_name, destination_name)

    monkeypatch.setattr(safe_writes, "_exchange_entries", interfere_with_rollback)

    with (
        safe_writes.open_secure_directory(
            tmp_path,
            Path("configs/local"),
            create=False,
        ) as directory,
        pytest.raises(OSError, match="could not roll back atomic write"),
    ):
        directory.atomic_write("safe.yaml", replacement, overwrite=True)

    assert destination.read_bytes() == replacement
    assert parked_destination.read_bytes() == original
    assert outside.read_bytes() == outside_content
    quarantines = [path for path in local_dir.iterdir() if ".quarantine-" in path.name]
    assert len(quarantines) == 1
    assert (quarantines[0] / "entry").read_bytes() == late_substitute


def test_save_config_mid_write_failure_preserves_original_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from metriplane.runner import safe_writes

    api = make_api(tmp_path)
    local_dir = tmp_path / "configs" / "local"
    local_dir.mkdir(parents=True)
    config_path = local_dir / "safe.yaml"
    original_content = "profile: original\n"
    config_path.write_text(original_content, encoding="utf-8")

    def fail_after_partial_write(file_fd: int, content: bytes) -> None:
        safe_writes.os.write(file_fd, content[:7])
        raise OSError("injected staged write failure")

    monkeypatch.setattr(safe_writes, "_write_all", fail_after_partial_write)

    status, payload = api.route(
        "POST",
        "/operator/save-config",
        {
            "filename": "safe.yaml",
            "overwrite": True,
            "config": {"profile": "replacement"},
        },
    )

    assert status == 503
    assert payload["error"] == "Unable to write config 'safe.yaml'"
    assert config_path.read_text(encoding="utf-8") == original_content
    assert not list(local_dir.glob(".safe.yaml.tmp-*"))


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
