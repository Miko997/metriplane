# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from robomimic_lowdim.fixture import (
    finalize_conversion_equivalence,
    normalize_frames,
    write_fixtures,
)
from robomimic_lowdim.hdf5_audit import SourceFrame


def _rows(raw: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in raw.splitlines()]


def test_position_only_complete_snapshots_use_integer_clock(
    source_frames: list[SourceFrame], frozen_config: dict[str, object]
) -> None:
    raw, summary = normalize_frames(source_frames, frozen_config)
    rows = _rows(raw)
    assert len(rows) == 118
    assert summary["can_inside_first_frame"] == 0
    assert summary["can_inside_last_frame"] == 63
    assert summary["tcp_inside_first_frame"] == 42
    assert summary["tcp_inside_last_frame"] == 64
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
        assert [item["id"] for item in objects] == ["can_1", "robot_tcp_1"]
        assert all(set(item) == {"id", "pos_world", "zone"} for item in objects)
        assert all(item["pos_world"][2] == 0.0 for item in objects)


def test_writer_emits_identical_state_and_only_declared_rule_difference(
    tmp_path: Path, source_frames: list[SourceFrame], config_path: Path
) -> None:
    output = tmp_path / "fixture"
    write_fixtures(
        source_frames,
        config_path=config_path,
        output_root=output,
        adapter_commit="a" * 40,
        allow_unbound_test_fixture=True,
    )
    incident = output / "incident"
    control = output / "control"
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
    incident_process = json.loads((incident / "domain-pack/process.yaml").read_text())
    control_process = json.loads((control / "domain-pack/process.yaml").read_text())
    assert incident_process["steps"][0]["max_wait_s"] == 2.0
    assert control_process["steps"][0]["max_wait_s"] == 2.5
    incident_manifest = json.loads((incident / "source-manifest.json").read_text())
    control_manifest = json.loads((control / "source-manifest.json").read_text())
    assert incident_manifest["adapter"] == control_manifest["adapter"]
    assert incident_manifest["normalization"] == control_manifest["normalization"]


def test_generated_bundle_validates_against_root_contract_when_available(
    tmp_path: Path, source_frames: list[SourceFrame], config_path: Path
) -> None:
    try:
        from metriplane.external_sources.contract import validate_external_fixture_bundle
    except ImportError:
        return
    output = tmp_path / "fixture"
    write_fixtures(
        source_frames,
        config_path=config_path,
        output_root=output,
        adapter_commit="a" * 40,
        allow_unbound_test_fixture=True,
    )
    assert len(validate_external_fixture_bundle(output / "incident").frames) == 118
    assert len(validate_external_fixture_bundle(output / "control").frames) == 118


def test_three_conversions_finalize_only_after_full_byte_identity(
    tmp_path: Path, source_frames: list[SourceFrame], config_path: Path
) -> None:
    roots = [tmp_path / f"clean-{index}" for index in range(3)]
    for root in roots:
        write_fixtures(
            source_frames,
            config_path=config_path,
            output_root=root,
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
        )
    result = finalize_conversion_equivalence(
        roots,
        output_root=tmp_path / "final",
        run_ids=["source-clean-1", "source-clean-2", "source-clean-3"],
        allow_unbound_test_fixture=True,
    )
    assert result["equivalent"] is True
    for variant in ("incident", "control"):
        report = json.loads(
            (tmp_path / "final" / variant / "normalization-report.json").read_text()
        )
        assert report["conversion_reproducibility"]["status"] == "demonstrated"
        assert report["conversion_reproducibility"]["equivalent"] is True


def test_polygon_boundary_is_inclusive(frozen_config: dict[str, object]) -> None:
    polygon = frozen_config["target_polygon"]
    assert isinstance(polygon, dict)
    boundary = polygon["vertices"][0]
    assert isinstance(boundary, list)
    frames = [
        SourceFrame(
            can_xyz=(float(boundary[0]), float(boundary[1]), 0.8),
            tcp_xyz=(0.4, 0.4, 1.0),
        )
        for _ in range(118)
    ]
    rows = _rows(normalize_frames(frames, frozen_config)[0])
    assert rows[0]["objects"][0]["zone"] == "target_xy_region"
