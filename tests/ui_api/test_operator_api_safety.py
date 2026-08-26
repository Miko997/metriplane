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

    status, payload = api._start_fusion(
        {"config": "configs/safe.yaml", "duration_s": 30}
    )

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
            "zones": [
                {"name": "safe_zone", "polygon": [[0, 0], [1, 0], [0, 1]]}
            ],
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
