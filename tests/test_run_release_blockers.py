# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import metriplane.run as runtime
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


def test_both_run_entrypoints_return_runtime_status(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("source_mode: replay\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "run_loop", lambda *_args, **_kwargs: 9)

    assert runtime.main(["--config", str(config)]) == 9

    from metriplane import cli

    assert cli._main_run(["--config", str(config)]) == 9
