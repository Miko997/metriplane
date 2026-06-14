# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

import pytest

from integrations.isaac.metriplane_to_usd import (
    load_incidents,
    load_traces,
    write_usda_replay,
)

BUNDLE = "evidence/incidents/INC-0001"


def test_load_traces_from_bundle():
    tracks, run_id = load_traces(BUNDLE)
    assert run_id == "INC-0001"
    assert any(t.object_id == "cart_01" for t in tracks)
    cart = next(t for t in tracks if t.object_id == "cart_01")
    assert len(cart.samples) >= 2
    assert cart.type == "cart"


def test_load_incidents_from_bundle():
    incidents = load_incidents(BUNDLE)
    assert len(incidents) >= 1
    assert incidents[0]["rule_id"] == "no_cart_in_exit_lane"


def test_export_writes_file(tmp_path):
    out = tmp_path / "replay.usda"
    manifest = write_usda_replay(run_dir=BUNDLE, output_path=out)
    assert out.exists()
    assert manifest["object_ids"] == ["cart_01"]
    assert (tmp_path / "metriplane_replay_manifest.json").exists()


def test_usda_contains_object_names(tmp_path):
    out = tmp_path / "replay.usda"
    write_usda_replay(run_dir=BUNDLE, output_path=out)
    text = out.read_text()
    assert 'def Sphere "cart_01"' in text


def test_usda_contains_time_samples(tmp_path):
    out = tmp_path / "replay.usda"
    write_usda_replay(run_dir=BUNDLE, output_path=out)
    text = out.read_text()
    assert "xformOp:translate.timeSamples" in text
    assert "0: (0.0, 0.0, 0)" in text


def test_usda_contains_incident_marker(tmp_path):
    out = tmp_path / "replay.usda"
    write_usda_replay(run_dir=BUNDLE, output_path=out)
    text = out.read_text()
    assert 'def Xform "Incidents"' in text
    assert "metriplane:incident_id" in text


def test_usda_documents_coordinate_mapping(tmp_path):
    out = tmp_path / "replay.usda"
    write_usda_replay(run_dir=BUNDLE, output_path=out)
    assert "metriplane_coordinate_mapping" in out.read_text()


def test_missing_session_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_traces(tmp_path)


def test_manifest_structure(tmp_path):
    out = tmp_path / "replay.usda"
    write_usda_replay(run_dir=BUNDLE, output_path=out)
    manifest = json.loads((tmp_path / "metriplane_replay_manifest.json").read_text())
    assert manifest["run_id"] == "INC-0001"
    assert manifest["coordinate_mapping"].startswith("USD_X=X")
    assert manifest["frames"] >= 2
