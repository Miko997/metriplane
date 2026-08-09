# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import metriplane.run as runtime
import metriplane.run_fusion as fusion_runtime
from metriplane.camera.rtsp import RTSPCamera
from metriplane.camera.usb import USBCamera
from metriplane.config import Config
from metriplane.metrics import MetricsRegistry


class _Ws:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def send_frame(self, _frame) -> None:
        return None


class _Recorder:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)


class _Timing:
    def begin_frame(self, **_kwargs) -> None:
        return None

    def add_stage_ns(self, *_args) -> None:
        return None

    def stage(self, _name: str):
        return nullcontext()

    def end_frame(self) -> None:
        return None


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        run_id="test",
        config_hash="hash",
        git=SimpleNamespace(commit="deadbeef"),
    )


def _write_session(path: Path, frames: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(frame) + "\n" for frame in frames),
        encoding="utf-8",
    )
    return path


def _valid_frame(frame_id: int, ts: float, *, ts_sim_ns: int | None = None) -> dict:
    frame = {
        "source_backend": "test",
        "frame_id": frame_id,
        "ts": ts,
        "objects": [],
    }
    if ts_sim_ns is not None:
        frame["ts_sim_ns"] = ts_sim_ns
    return frame


def _run_replay(cfg: Config) -> int:
    return runtime._run_replay_mode(
        cfg,
        _ctx(),
        _Ws(),
        MetricsRegistry(),
        _Recorder(),
        runtime.HealthRegistry(enabled=True),
        _Timing(),
        ws_fail_after_s=0.0,
        t0=0.0,
    )


def test_replay_runtime_missing_and_header_only_inputs_fail(tmp_path: Path) -> None:
    assert _run_replay(Config(source_mode="replay", replay_input=None)) == 1

    header_only = _write_session(
        tmp_path / "header.jsonl",
        [{"type": "run_header", "run_id": "test"}],
    )
    assert _run_replay(
        Config(source_mode="replay", replay_input=str(header_only), replay_loop=False)
    ) == 1


def test_replay_runtime_primary_recording_failure_is_fatal(tmp_path: Path) -> None:
    session = _write_session(tmp_path / "session.jsonl", [_valid_frame(1, 0.0)])

    class FailingRecorder(_Recorder):
        def write(self, _record: dict) -> None:
            raise OSError("disk full")

    status = runtime._run_replay_mode(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_loop=False,
        ),
        _ctx(),
        _Ws(),
        MetricsRegistry(),
        FailingRecorder(),
        runtime.HealthRegistry(enabled=True),
        _Timing(),
        ws_fail_after_s=0.0,
        t0=0.0,
    )

    assert status == 1


def test_replay_runtime_rejects_nonmonotonic_authoritative_clock(tmp_path: Path) -> None:
    session = _write_session(
        tmp_path / "bad-time.jsonl",
        [
            _valid_frame(1, 1.0, ts_sim_ns=200),
            _valid_frame(2, 2.0, ts_sim_ns=100),
        ],
    )

    assert _run_replay(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_speed=0.0,
            replay_loop=False,
        )
    ) == 1


def test_replay_runtime_rejects_any_malformed_record(tmp_path: Path) -> None:
    session = tmp_path / "partially-malformed.jsonl"
    session.write_text(
        json.dumps(_valid_frame(1, 1.0)) + "\n{not-json}\n",
        encoding="utf-8",
    )

    assert _run_replay(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_speed=0.0,
            replay_loop=False,
        )
    ) == 1


@pytest.mark.parametrize("speed", [float("nan"), float("inf"), -1.0])
def test_replay_runtime_rejects_invalid_speed(tmp_path: Path, speed: float) -> None:
    session = _write_session(tmp_path / "session.jsonl", [_valid_frame(1, 1.0)])

    assert _run_replay(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_speed=speed,
            replay_loop=False,
        )
    ) == 1


@pytest.mark.parametrize(
    "frame",
    [
        _valid_frame(1, float("nan")),
        _valid_frame(1, 1.0, ts_sim_ns=-1),
        _valid_frame(1, 1.0, ts_sim_ns=10**400),
    ],
)
def test_replay_runtime_rejects_invalid_timestamps(
    tmp_path: Path,
    frame: dict,
) -> None:
    session = _write_session(tmp_path / "session.jsonl", [frame])

    assert _run_replay(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_speed=0.0,
            replay_loop=False,
        )
    ) == 1


def test_replay_runtime_rejects_nonfinite_pacing_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _write_session(
        tmp_path / "session.jsonl",
        [_valid_frame(1, 0.0), _valid_frame(2, 1.0)],
    )
    targets: list[float] = []

    def record_target(target: float) -> int:
        assert target == target and target != float("inf")
        targets.append(target)
        return 0

    monkeypatch.setattr(runtime, "_sleep_until_replay_deadline", record_target)

    assert _run_replay(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_speed=1e-300,
            replay_loop=False,
        )
    ) == 1
    assert len(targets) == 1


def test_replay_deadline_waits_through_multiple_chunks(monkeypatch) -> None:
    now = [0.0]
    sleeps: list[float] = []

    monkeypatch.setattr(runtime.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(runtime.time, "perf_counter_ns", lambda: int(now[0] * 1e9))

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(runtime.time, "sleep", fake_sleep)

    slept_ns = runtime._sleep_until_replay_deadline(0.6)

    assert sleeps == pytest.approx([0.25, 0.25, 0.1])
    assert slept_ns == pytest.approx(600_000_000, abs=2)
    assert now[0] == pytest.approx(0.6)


def test_single_camera_resolver_honors_usb_device_and_rtsp_url() -> None:
    usb = runtime._resolve_single_camera(
        Config(camera_backend="usb", camera_device="/dev/video7")
    )
    assert isinstance(usb.camera, USBCamera)
    assert usb.camera.index == "/dev/video7"
    assert usb.source_backend == "aruco_usb"

    rtsp = runtime._resolve_single_camera(
        Config(camera_backend="rtsp", camera_device="rtsp://camera.local/stream")
    )
    assert isinstance(rtsp.camera, RTSPCamera)
    assert rtsp.camera.url == "rtsp://camera.local/stream"
    assert rtsp.source_backend == "aruco_rtsp"


@pytest.mark.parametrize(
    "cfg,match",
    [
        (Config(camera_backend="firewire"), "Unsupported camera_backend"),
        (Config(vision_backend="yolo"), "Unsupported vision_backend"),
        (Config(camera_backend="rtsp", camera_device="/dev/video0"), "requires camera_device"),
    ],
)
def test_single_camera_resolver_rejects_ignored_combinations(
    cfg: Config, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        runtime._resolve_single_camera(cfg)


def test_optional_mapping_and_zones_are_only_optional_when_omitted(tmp_path: Path) -> None:
    assert runtime._maybe_load_mapper(Config()) is None
    assert runtime._maybe_load_zones(Config()) is None

    with pytest.raises(ValueError, match="configured planar mapping"):
        runtime._maybe_load_mapper(Config(mapping_file=str(tmp_path / "missing.yaml")))
    assert runtime.run_loop(
        Config(mapping_file=str(tmp_path / "missing.yaml"), runs_dir=str(tmp_path / "runs"))
    ) == 1

    malformed_zones = tmp_path / "zones.yaml"
    malformed_zones.write_text("zones: [not-a-zone]", encoding="utf-8")
    with pytest.raises(ValueError, match="configured zones"):
        runtime._maybe_load_zones(Config(zones_file=str(malformed_zones)))


def test_explicit_missing_profile_fails_but_implicit_profile_is_optional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calib = tmp_path / "calib"
    calib.mkdir()
    (calib / "active_profile.yaml").write_text(
        "profile: unavailable\n", encoding="utf-8"
    )

    # A stale optional active-profile pointer must not make an unprofiled run fail.
    assert runtime._apply_runtime_profile_defaults(
        Config(), calib_root=calib
    ) == Config()

    monkeypatch.chdir(tmp_path)
    missing = Config(
        profile="does-not-exist",
        source_mode="dummy",
        runs_dir=str(tmp_path / "runs"),
    )
    with pytest.raises(ValueError, match="Configured profile not found"):
        runtime._apply_runtime_profile_defaults(missing)
    assert runtime.run_loop(missing) == 1
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize(
    "present_file,missing_message",
    [
        ("zones.yaml", "has no planar mapping"),
        ("mapping.yaml", "has no zones file"),
    ],
)
def test_explicit_profile_requires_its_derived_mapping_and_zones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    present_file: str,
    missing_message: str,
) -> None:
    profile = tmp_path / "calib" / "profiles" / "broken"
    profile.mkdir(parents=True)
    (profile / present_file).write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = Config(
        profile="broken",
        source_mode="dummy",
        runs_dir=str(tmp_path / "runs"),
    )
    with pytest.raises(ValueError, match=missing_message):
        runtime._apply_runtime_profile_defaults(cfg)
    assert runtime.run_loop(cfg) == 1
    assert not (tmp_path / "runs").exists()


def test_rtsp_credentials_are_not_written_to_runtime_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_url = "rtsp://camera-user:super-secret@camera.local/stream"

    class Capture:
        def isOpened(self) -> bool:
            return True

        def release(self) -> None:
            return None

    monkeypatch.setattr(
        "metriplane.camera.rtsp.cv2.VideoCapture", lambda _url: Capture()
    )
    with caplog.at_level(logging.INFO):
        camera = RTSPCamera(secret_url)
        camera.open()
        camera.close()

    assert "super-secret" not in caplog.text
    assert secret_url not in caplog.text
    assert "opening configured RTSP stream" in caplog.text

    config = tmp_path / "rtsp.yaml"
    config.write_text(
        f"camera_backend: rtsp\ncamera_device: {secret_url}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "run_loop", lambda *_args, **_kwargs: 0)
    from metriplane import cli

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert cli._main_run(["--config", str(config)]) == 0
    assert "super-secret" not in caplog.text
    assert secret_url not in caplog.text


def test_run_loop_propagates_ws_and_camera_startup_failures(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("METRIPLANE_NO_PIP_FREEZE", "1")
    session = _write_session(tmp_path / "session.jsonl", [_valid_frame(1, 0.0)])

    class FailingWs(_Ws):
        def start(self) -> None:
            raise RuntimeError("bind failed")

    monkeypatch.setattr(runtime, "WsServerThread", lambda **_kwargs: FailingWs())
    status = runtime.run_loop(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_loop=False,
            runs_dir=str(tmp_path / "ws-runs"),
        )
    )
    assert status == 1

    monkeypatch.setattr(runtime, "WsServerThread", lambda **_kwargs: _Ws())
    monkeypatch.setattr(
        runtime,
        "_start_observability_server",
        lambda **_kwargs: SimpleNamespace(shutdown=lambda: None),
    )
    monkeypatch.setattr(
        runtime.USBCamera,
        "open",
        lambda _self: (_ for _ in ()).throw(RuntimeError("camera unavailable")),
    )
    status = runtime.run_loop(
        Config(source_mode="camera", runs_dir=str(tmp_path / "camera-runs"))
    )
    assert status == 1


def test_observability_startup_failure_releases_started_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METRIPLANE_NO_PIP_FREEZE", "1")
    session = _write_session(tmp_path / "session.jsonl", [_valid_frame(1, 0.0)])

    class TrackingWs(_Ws):
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    class TrackingRecorder(_Recorder):
        closed = False

        def __init__(self) -> None:
            super().__init__()
            self.paths: list[Path] = []

        def close(self) -> None:
            self.closed = True

    class TrackingTiming(_Timing):
        closed = False

        def close(self) -> None:
            self.closed = True

    ws = TrackingWs()
    recorder = TrackingRecorder()
    timing = TrackingTiming()
    monkeypatch.setattr(runtime, "WsServerThread", lambda **_kwargs: ws)
    monkeypatch.setattr(runtime, "open_jsonl_writer", lambda **_kwargs: recorder)
    monkeypatch.setattr(runtime, "StageTiming", lambda **_kwargs: timing)
    monkeypatch.setattr(
        runtime,
        "_start_observability_server",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("metrics bind failed")),
    )

    status = runtime.run_loop(
        Config(
            source_mode="replay",
            replay_input=str(session),
            replay_loop=False,
            runs_dir=str(tmp_path / "observability-runs"),
        )
    )

    assert status == 1
    assert ws.stopped is True
    assert recorder.closed is True
    assert timing.closed is True


def test_camera_open_oserror_releases_all_resources_even_when_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METRIPLANE_NO_PIP_FREEZE", "1")
    closed: list[str] = []

    class Camera:
        def open(self) -> None:
            raise OSError("device disappeared")

        def close(self) -> None:
            closed.append("camera")
            raise RuntimeError("camera teardown failed")

    class Ws(_Ws):
        def stop(self) -> None:
            closed.append("websocket")
            raise RuntimeError("websocket teardown failed")

    class Observability:
        def shutdown(self) -> None:
            closed.append("observability.shutdown")
            raise RuntimeError("observability shutdown failed")

        def server_close(self) -> None:
            closed.append("observability.server_close")

    class Recorder(_Recorder):
        paths: list[Path] = []

        def close(self) -> None:
            closed.append("recorder")

    class Timing(_Timing):
        def close(self) -> None:
            closed.append("timing")

    camera = Camera()
    monkeypatch.setattr(
        runtime,
        "_resolve_single_camera",
        lambda _cfg: SimpleNamespace(
            camera=camera,
            camera_backend="usb",
            camera_source=0,
            vision_backend="aruco",
            source_backend="aruco_usb",
        ),
    )
    monkeypatch.setattr(runtime, "WsServerThread", lambda **_kwargs: Ws())
    monkeypatch.setattr(runtime, "open_jsonl_writer", lambda **_kwargs: Recorder())
    monkeypatch.setattr(runtime, "StageTiming", lambda **_kwargs: Timing())
    monkeypatch.setattr(
        runtime,
        "_start_observability_server",
        lambda **_kwargs: Observability(),
    )

    assert runtime.run_loop(
        Config(source_mode="camera", runs_dir=str(tmp_path / "runs"))
    ) == 1
    assert closed == [
        "camera",
        "websocket",
        "observability.shutdown",
        "observability.server_close",
        "recorder",
        "timing",
    ]


@pytest.mark.parametrize("fail_at", ["camera_constructor", "camera_open"])
def test_fusion_setup_failures_release_every_acquired_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_at: str,
) -> None:
    monkeypatch.setenv("METRIPLANE_SHOW_PREVIEW", "1")
    closed: list[str] = []

    class Preview:
        def __init__(self, **_kwargs) -> None:
            return None

        def close(self) -> None:
            closed.append("preview")
            raise RuntimeError("preview teardown failed")

    class Recorder(_Recorder):
        paths: list[Path] = []

        def close(self) -> None:
            closed.append("recorder")

    class Timing(_Timing):
        def close(self) -> None:
            closed.append("timing")

    class Ws(_Ws):
        def stop(self) -> None:
            closed.append("websocket")
            raise RuntimeError("websocket teardown failed")

    class MetricsServer:
        def shutdown(self) -> None:
            closed.append("metrics.shutdown")
            raise RuntimeError("metrics shutdown failed")

        def server_close(self) -> None:
            closed.append("metrics.server_close")

    class Camera:
        def open(self) -> None:
            raise OSError("camera unavailable")

        def close(self) -> None:
            closed.append("camera")
            raise RuntimeError("camera teardown failed")

    ctx = SimpleNamespace(
        run_id="test",
        config_hash="hash",
        git=SimpleNamespace(commit="deadbeef"),
        run_dir=tmp_path / "run",
        session_jsonl=tmp_path / "run" / "session.jsonl",
        header_record=lambda: {"type": "run_header"},
    )
    monkeypatch.setattr(fusion_runtime, "LivePreview", Preview)
    monkeypatch.setattr(fusion_runtime, "apply_profile_defaults", lambda cfg: cfg)
    monkeypatch.setattr(fusion_runtime, "create_run_context", lambda *_args, **_kwargs: ctx)
    monkeypatch.setattr(fusion_runtime, "open_jsonl_writer", lambda **_kwargs: Recorder())
    monkeypatch.setattr(fusion_runtime, "StageTiming", lambda **_kwargs: Timing())
    monkeypatch.setattr(
        fusion_runtime,
        "select_fusion_backend",
        lambda *_args, **_kwargs: SimpleNamespace(name="cpu"),
    )
    monkeypatch.setattr(fusion_runtime, "WsServerThread", lambda **_kwargs: Ws())
    monkeypatch.setattr(fusion_runtime, "MetricsRegistry", lambda: object())
    monkeypatch.setattr(
        fusion_runtime,
        "start_metrics_server",
        lambda **_kwargs: MetricsServer(),
    )
    monkeypatch.setattr(
        fusion_runtime,
        "_resolve_multi_mapper_from_cfg",
        lambda *_args, **_kwargs: ({"cam0": 0}, SimpleNamespace(), []),
    )
    monkeypatch.setattr(fusion_runtime, "ArUcoBackend", lambda: object())

    camera = Camera()
    if fail_at == "camera_constructor":
        monkeypatch.setattr(
            fusion_runtime,
            "USBMultiCamera",
            lambda **_kwargs: (_ for _ in ()).throw(ValueError("bad camera setup")),
        )
    else:
        monkeypatch.setattr(fusion_runtime, "USBMultiCamera", lambda **_kwargs: camera)
        fake_aruco = SimpleNamespace(
            DICT_4X4_100=0,
            getPredefinedDictionary=lambda _value: object(),
            DetectorParameters=lambda: object(),
            ArucoDetector=lambda *_args: object(),
        )
        monkeypatch.setattr(fusion_runtime.cv2, "aruco", fake_aruco)

    with pytest.raises((OSError, ValueError)):
        fusion_runtime.run_loop_fusion(Config(), runs_dir=str(tmp_path / "runs"))

    expected = ["preview"]
    if fail_at == "camera_open":
        expected.append("camera")
    expected.extend(
        [
            "websocket",
            "metrics.shutdown",
            "metrics.server_close",
            "recorder",
            "timing",
        ]
    )
    assert closed == expected


def test_both_run_entrypoints_return_runtime_status(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("source_mode: replay\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "run_loop", lambda *_args, **_kwargs: 9)

    assert runtime.main(["--config", str(config)]) == 9

    from metriplane import cli

    assert cli._main_run(["--config", str(config)]) == 9


def test_fusion_entrypoint_returns_runtime_status(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "fusion.yaml"
    config.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(fusion_runtime, "load_config", lambda _path: Config())
    monkeypatch.setattr(
        fusion_runtime,
        "run_loop_fusion",
        lambda *_args, **_kwargs: 9,
    )

    assert fusion_runtime.main(["--config", str(config)]) == 9
