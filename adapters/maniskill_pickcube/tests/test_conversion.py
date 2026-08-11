# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from maniskill_pickcube.core import (
    RestoredFrame,
    finalize_conversion_equivalence,
    normalize_frames,
    write_fixtures,
)


def _rows(raw: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in raw.splitlines()]


def test_position_only_normalization_uses_integer_clock_and_complete_snapshots(
    restored_frames: list[RestoredFrame], frozen_config: dict[str, object]
) -> None:
    raw, summary = normalize_frames(restored_frames, frozen_config)
    rows = _rows(raw)
    assert len(rows) == 75
    assert summary["cube_target_entry_frame"] == 66
    assert summary["tcp_target_entry_frame"] == 71
    assert summary["shared_session_sha256"] == hashlib.sha256(raw).hexdigest()
    for index, row in enumerate(rows):
        assert set(row) == {
            "schema_version",
            "source_backend",
            "ts",
            "ts_sim_ns",
            "frame_id",
            "objects",
            "events",
        }
        assert row["frame_id"] == index
        assert row["ts_sim_ns"] == index * 50_000_000
        assert row["ts"] == row["ts_sim_ns"] / 1_000_000_000
        assert row["events"] == []
        objects = row["objects"]
        assert isinstance(objects, list)
        assert [item["id"] for item in objects] == ["cube_1", "robot_tcp_1"]
        assert all(set(item) == {"id", "pos_world", "zone"} for item in objects)
        assert all(item["pos_world"][2] == 0.0 for item in objects)


def test_writer_emits_shared_state_and_only_declared_wait_difference(
    tmp_path: Path,
    restored_frames: list[RestoredFrame],
    config_path: Path,
) -> None:
    output = tmp_path / "fixture"
    summary = write_fixtures(
        restored_frames,
        config_path=config_path,
        output_root=output,
        adapter_commit="a" * 40,
    )
    incident = output / "incident"
    control = output / "control"
    assert summary["shared_session_sha256"] == hashlib.sha256(
        (incident / "session.jsonl").read_bytes()
    ).hexdigest()
    for relative in (
        "session.jsonl",
        "entity-mapping.json",
        "domain-pack/assets.yaml",
        "domain-pack/workspace.yaml",
        "domain-pack/work_orders.csv",
        "source/adapter-environment.txt",
        "source/frozen-config.json",
        "source/uv.lock",
    ):
        assert (incident / relative).read_bytes() == (control / relative).read_bytes()
    incident_process = yaml.safe_load((incident / "domain-pack/process.yaml").read_text())
    control_process = yaml.safe_load((control / "domain-pack/process.yaml").read_text())
    assert incident_process["steps"][0]["max_wait_s"] == 0.2
    assert control_process["steps"][0]["max_wait_s"] == 0.3
    incident_manifest = json.loads((incident / "source-manifest.json").read_text())
    control_manifest = json.loads((control / "source-manifest.json").read_text())
    assert incident_manifest["adapter"] == control_manifest["adapter"]
    assert incident_manifest["normalization"] == control_manifest["normalization"]
    assert incident_manifest["adapter"]["parameters"]["reference"]["path"] == (
        "source/frozen-config.json"
    )
    assert incident_manifest["adapter"]["environment"]["dependency_lock"]["path"] == (
        "source/uv.lock"
    )


def test_boundary_is_inclusive(frozen_config: dict[str, object]) -> None:
    polygon = frozen_config["target_polygon"]
    assert isinstance(polygon, dict)
    boundary = polygon["vertices"][0]
    outside = (0.25, 0.25, 0.0, 1.0, 0.0, 0.0, 0.0)
    on_boundary = (
        float(boundary[0]),
        float(boundary[1]),
        1.0,
        0.0,
        1.0,
        0.0,
        0.0,
    )
    frames = [
        RestoredFrame(
            cube_pose=on_boundary if index >= 66 else outside,
            tcp_pose=on_boundary if index >= 71 else outside,
            goal_pose=on_boundary,
        )
        for index in range(75)
    ]
    rows = _rows(normalize_frames(frames, frozen_config)[0])
    assert rows[66]["objects"][0]["zone"] == "target_xy_region"
    assert rows[71]["objects"][1]["zone"] == "target_xy_region"


def test_three_clean_roots_are_explicitly_finalized_as_demonstrated(
    tmp_path: Path,
    restored_frames: list[RestoredFrame],
    config_path: Path,
) -> None:
    roots = [tmp_path / f"conversion-{index}" for index in range(1, 4)]
    for root in roots:
        write_fixtures(
            restored_frames,
            config_path=config_path,
            output_root=root,
            adapter_commit="a" * 40,
        )
    final = tmp_path / "final"
    result = finalize_conversion_equivalence(
        roots,
        output_root=final,
        run_ids=["source-clean-1", "source-clean-2", "source-clean-3"],
    )
    assert result["equivalent"] is True
    for variant in ("incident", "control"):
        report = json.loads((final / variant / "normalization-report.json").read_text())
        reproducibility = report["conversion_reproducibility"]
        assert reproducibility["status"] == "demonstrated"
        assert reproducibility["equivalent"] is True
        assert [run["run_id"] for run in reproducibility["runs"]] == [
            "source-clean-1",
            "source-clean-2",
            "source-clean-3",
        ]
