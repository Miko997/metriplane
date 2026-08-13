# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ros2_mcap_adapter.decoder as decoder
from ros2_mcap_adapter.canonical import sha256_bytes
from ros2_mcap_adapter.constants import DEFAULT_CONFIG, DEFAULT_LOCK, SOURCE_CLASSIFICATION
from ros2_mcap_adapter.decoder import DecodeError, decode_source_file, load_config
from ros2_mcap_adapter.fixture import normalize_frames, write_conversion


def test_exact_transform_and_projection(source_path: Path, config_path: Path) -> None:
    source = decode_source_file(source_path)
    first = source.frames[0]
    assert first.material_world == pytest.approx((0.2, 0.0, 0.02), abs=1e-14)
    assert first.tool_world == pytest.approx((0.1, -0.3, 0.12), abs=1e-14)
    session, summary = normalize_frames(source.frames, load_config(config_path))
    rows = [json.loads(line) for line in session.splitlines()]
    assert rows[0]["ts_sim_ns"] == 0
    assert rows[-1]["ts_sim_ns"] == 5_900_000_000
    assert rows[0]["objects"][0]["pos_world"] == [0.2, 0.0, 0.0]
    assert summary == {
        "material_inside_first_frame": 5,
        "material_inside_last_frame": 39,
        "shared_session_sha256": sha256_bytes(session),
        "tool_inside_first_frame": 15,
        "tool_inside_last_frame": 40,
    }


def test_config_hash_and_semantic_drift_reject(tmp_path: Path, config_path: Path) -> None:
    changed = tmp_path / "config.json"
    value = json.loads(config_path.read_text())
    value["materialization"]["carry_forward"] = "latest"
    changed.write_text(json.dumps(value))
    with pytest.raises(DecodeError, match="SHA-256"):
        load_config(changed)


def test_config_snapshot_rejects_replacement_between_read_and_parse(
    tmp_path: Path, config_path: Path, monkeypatch
) -> None:
    config_copy = tmp_path / "config.json"
    config_copy.write_bytes(config_path.read_bytes())

    def replace_after_snapshot(path: Path) -> None:
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(config_path.read_bytes())
        replacement.replace(path)

    monkeypatch.setattr(decoder, "_CONFIG_SNAPSHOT_TEST_HOOK", replace_after_snapshot)
    with pytest.raises(DecodeError, match="changed after its authenticated snapshot"):
        load_config(config_copy)


def test_conversion_builds_contract_bundle_and_native_capability(
    tmp_path: Path, source_path: Path, config_path: Path
) -> None:
    root = tmp_path / "conversion"
    summary = write_conversion(
        config=load_config(config_path),
        adapter_commit="1" * 40,
        source=decode_source_file(source_path),
        output_root=root,
        config_bytes=DEFAULT_CONFIG.read_bytes(),
        lock_bytes=DEFAULT_LOCK.read_bytes(),
    )
    assert summary["source_classification"] == SOURCE_CLASSIFICATION
    assert (
        summary["shared_session_sha256"]
        == "4404c092ef1d8940a115c68bcfde4f8f0ac1065a968aaa7e318f3fa8c61d2ee8"
    )
    capability = json.loads((root / "capability-record.json").read_text())
    assert capability["record"] == {
        "classification": "native",
        "evidence_classification": "synthetic_format_engineering",
        "statement": "Native capability declaration for one bounded Metriplane-authored synthetic format-engineering source.",
        "subject": "candidate_adapter",
    }
    rows = capability["capabilities"]["portable_evaluation"]["environments"]
    assert {(row["operating_system"], row["python_version"]) for row in rows} == {
        ("Ubuntu", "3.12"),
        ("Ubuntu", "3.13"),
        ("macOS", "3.12"),
        ("macOS", "3.13"),
    }
    assert {row["status"] for row in rows} == {"required"}
    assert capability["capabilities"]["portable_evaluation"]["status"] == "not_demonstrated"
    assert not any(path.suffix == ".mcap" for path in root.rglob("*"))


def test_capability_validates_against_shared_sdk(
    tmp_path: Path, source_path: Path, config_path: Path, monkeypatch
) -> None:
    sdk_source = Path(__file__).parents[2] / "source_adapter_sdk" / "src"
    monkeypatch.syspath_prepend(str(sdk_source))
    from metriplane_source_adapter_sdk import assess_capability, load_capability

    root = tmp_path / "conversion"
    write_conversion(
        config=load_config(config_path),
        adapter_commit="1" * 40,
        source=decode_source_file(source_path),
        output_root=root,
        config_bytes=DEFAULT_CONFIG.read_bytes(),
        lock_bytes=DEFAULT_LOCK.read_bytes(),
    )
    assessment = assess_capability(load_capability(root / "capability-record.json"))
    assert assessment.technically_permitted is False
    assert assessment.external_source_permitted is False
    assert assessment.reasons == ("portable_evaluation is not verified",)


def test_bundles_validate_with_external_source_contract(
    tmp_path: Path, source_path: Path, config_path: Path, monkeypatch
) -> None:
    repository_root = Path(__file__).parents[3]
    root = tmp_path / "conversion"
    write_conversion(
        config=load_config(config_path),
        adapter_commit="1" * 40,
        source=decode_source_file(source_path),
        output_root=root,
        config_bytes=DEFAULT_CONFIG.read_bytes(),
        lock_bytes=DEFAULT_LOCK.read_bytes(),
    )
    environment = {**os.environ, "PYTHONPATH": str(repository_root)}
    result = subprocess.run(
        [
            sys._base_executable,
            "-c",
            (
                "import sys; from metriplane.external_sources.contract import "
                "validate_external_fixture_bundle as v; "
                "assert len(v(sys.argv[1]).frames)==60; assert len(v(sys.argv[2]).frames)==60"
            ),
            str(root / "incident"),
            str(root / "control"),
        ],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_root_runtime_is_not_imported_by_adapter() -> None:
    imported_before = set(sys.modules)
    decode_source_file(
        Path(__file__).parents[1] / "source" / "metriplane-synthetic-recorded-state-v1.mcap"
    )
    imported = set(sys.modules) - imported_before
    assert not any(name == "metriplane" or name.startswith("metriplane.") for name in imported)
