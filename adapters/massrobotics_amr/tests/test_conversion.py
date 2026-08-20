# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import file_inventory, fixture_root, jsonl_rows

import massrobotics_amr_adapter.core as core
from massrobotics_amr_adapter.constants import (
    AMR_1_UUID,
    AMR_2_UUID,
    DEFAULT_CONFIG,
    DEFAULT_SOURCE_ROOT,
    PLANAR_DATUM_UUID,
    SOURCE_BACKEND,
)
from massrobotics_amr_adapter.finalize import finalize_conversion_equivalence

ADAPTER_COMMIT = "a" * 40
EXPECTED_POSITIONS = {
    "incident": {
        AMR_1_UUID: [2.0, 3.0, 4.25, 4.75, 5.0, 5.0, 5.0, 5.0, 5.0],
        AMR_2_UUID: [8.0, 7.5, 7.0, 6.75, 6.5, 6.25, 5.75, 5.25, 5.0],
    },
    "control": {
        AMR_1_UUID: [2.0, 3.0, 4.25, 4.75, 5.0, 5.0, 5.0, 5.0, 5.0],
        AMR_2_UUID: [8.0, 7.5, 7.0, 6.5, 5.75, 5.25, 5.0, 5.0, 5.0],
    },
}


def _convert(source: Path, output: Path, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    return core.convert(
        source,
        config_path=config_path,
        output_root=output,
        adapter_commit=ADAPTER_COMMIT,
    )


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _pack(root: Path, name: str) -> dict[str, Any]:
    # Domain packs are intentionally emitted as JSON, which is a strict YAML subset.
    return _json(root / "domain-pack" / name)


def _semantic_fixture_bytes(root: Path) -> dict[str, bytes]:
    relative_paths = [
        "session.jsonl",
        "entity-mapping.json",
        "domain-pack/assets.yaml",
        "domain-pack/workspace.yaml",
        "domain-pack/process.yaml",
        "domain-pack/contracts.yaml",
        "domain-pack/work_orders.csv",
        "expected-outcome.json",
    ]
    return {relative: (root / relative).read_bytes() for relative in relative_paths}


def _atlas_semantics(fixture: Path, output: Path, run_id: str) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[3]
    program = r"""
import json
import sys
from pathlib import Path
from metriplane.external_sources.execution import run_external_fixture

fixture = Path(sys.argv[1])
output = Path(sys.argv[2])
summary = run_external_fixture(fixture, output, run_id=sys.argv[3])
if not summary.passed:
    raise RuntimeError(summary.errors)
def rows(name):
    path = output / name
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]
print(json.dumps({
    "counts": [summary.frame_count, summary.event_count, summary.deviation_count, summary.incident_count],
    "events": rows("physical_event_log.jsonl"),
    "deviations": rows("deviations.jsonl"),
    "incidents": rows("incidents.jsonl"),
    "bundle_verified": [item.verified for item in summary.evidence_bundles],
    "regression_passed": [item.passed for item in summary.generated_regressions],
}, sort_keys=True, separators=(",", ":")))
"""
    environment = {
        **os.environ,
        "METRIPLANE_GIT_COMMIT": "b" * 40,
        "PYTHONPATH": str(repository_root),
    }
    result = subprocess.run(
        [sys._base_executable, "-c", program, str(fixture), str(output), run_id],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_valid_identity_and_status_sequence_converts(tmp_path: Path, variant: str) -> None:
    output = tmp_path / "conversion"
    summary = _convert(DEFAULT_SOURCE_ROOT / variant, output)
    root = fixture_root(output, variant)
    assert isinstance(summary, dict)
    assert len(jsonl_rows(root / "session.jsonl")) == 9
    assert (root / "CHECKSUMS.sha256").is_file()


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_normalized_complete_snapshot_shape_and_exact_trajectory(
    tmp_path: Path, variant: str
) -> None:
    output = tmp_path / "conversion"
    _convert(DEFAULT_SOURCE_ROOT / variant, output)
    rows = jsonl_rows(fixture_root(output, variant) / "session.jsonl")
    assert len(rows) == 9
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
        assert row["schema_version"] == "1.0"
        assert row["source_backend"] == SOURCE_BACKEND
        assert row["frame_id"] == index
        assert row["ts_sim_ns"] == index * 1_000_000_000
        assert row["ts"] == float(index)
        assert row["events"] == []
        objects = row["objects"]
        assert isinstance(objects, list)
        assert [item["id"] for item in objects] == [AMR_1_UUID, AMR_2_UUID]
        for item in objects:
            assert set(item) == {"id", "pos_world", "zone"}
            assert item["pos_world"] == [
                EXPECTED_POSITIONS[variant][item["id"]][index],
                0.0,
                0.0,
            ]
            expected_zone = (
                "rendezvous_zone" if 4.0 <= item["pos_world"][0] <= 6.0 else "outside_workspace"
            )
            assert item["zone"] == expected_zone


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_normalized_events_are_empty_and_no_inferred_state_is_emitted(
    tmp_path: Path, variant: str
) -> None:
    output = tmp_path / "conversion"
    _convert(DEFAULT_SOURCE_ROOT / variant, output)
    session = (fixture_root(output, variant) / "session.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in session.splitlines()]
    assert all(row["events"] == [] for row in rows)
    for prohibited in (
        '"confidence"',
        '"fused"',
        '"raw_per_camera"',
        '"operationalState"',
        '"errorCodes"',
        '"path"',
        '"destinations"',
        '"velocity"',
        '"orientation"',
        '"angle"',
    ):
        assert prohibited not in session


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_path_predictions_do_not_create_frames(tmp_path: Path, variant: str) -> None:
    output = tmp_path / "conversion"
    _convert(DEFAULT_SOURCE_ROOT / variant, output)
    root = fixture_root(output, variant)
    rows = jsonl_rows(root / "session.jsonl")
    assert len(rows) == 9
    assert [row["frame_id"] for row in rows] == list(range(9))
    report = _json(root / "normalization-report.json")
    rendered = json.dumps(report, sort_keys=True)
    assert "prediction" in rendered.lower()
    assert 0 in [value for value in _all_scalars(report) if isinstance(value, int)]


def _all_scalars(value: object) -> list[object]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _all_scalars(child)]
    if isinstance(value, list):
        return [item for child in value for item in _all_scalars(child)]
    return [value]


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_operator_domain_pack_uses_exact_two_amr_rendezvous_rule(
    tmp_path: Path, variant: str
) -> None:
    output = tmp_path / "conversion"
    _convert(DEFAULT_SOURCE_ROOT / variant, output)
    root = fixture_root(output, variant)
    assets = _pack(root, "assets.yaml")
    assert [
        {key: asset[key] for key in ("asset_id", "asset_type", "label", "object_id")}
        for asset in assets["assets"]
    ] == [
        {
            "asset_id": "amr_1",
            "asset_type": "rendezvous_trigger_amr",
            "label": "Synthetic trigger AMR",
            "object_id": AMR_1_UUID,
        },
        {
            "asset_id": "amr_2",
            "asset_type": "rendezvous_required_amr",
            "label": "Synthetic required AMR",
            "object_id": AMR_2_UUID,
        },
    ]
    process = _pack(root, "process.yaml")
    assert process["steps"] == [
        {
            "expected_asset_types": ["rendezvous_trigger_amr"],
            "label": "Second AMR reaches the rendezvous zone",
            "max_wait_s": 3.0,
            "required_assets": ["amr_2"],
            "required_station": "rendezvous_station",
            "required_zone": "rendezvous_zone",
            "step_id": "two_amr_rendezvous",
        }
    ]
    contracts = json.dumps(_pack(root, "contracts.yaml"), sort_keys=True).lower()
    assert "operator" in contracts
    assert "massrobotics requirement" in contracts
    assert "safety" in contracts


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_mapping_and_provenance_separate_source_operator_and_adapter_facts(
    tmp_path: Path, variant: str
) -> None:
    output = tmp_path / "conversion"
    _convert(DEFAULT_SOURCE_ROOT / variant, output)
    root = fixture_root(output, variant)
    mapping = _json(root / "entity-mapping.json")
    rendered = json.dumps(mapping, sort_keys=True)
    assert AMR_1_UUID in rendered and AMR_2_UUID in rendered
    manifest = _json(root / "source-manifest.json")
    manifest_text = json.dumps(manifest, sort_keys=True)
    assert "Metriplane-authored synthetic MassRobotics-format engineering fixture" in manifest_text
    assert "synthetic_format_engineering" in manifest_text
    assert "operator_configured_fixture_binding" in manifest_text
    assert PLANAR_DATUM_UUID in manifest_text
    assert "reference_only" in manifest_text
    assert "MassRobotics-provided" not in manifest_text
    assert "external robot data" not in manifest_text.lower()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("operationalState", "idle"), ("errorCodes", ["MP-SYNTHETIC-NONPROCESS-001"])],
)
def test_nonprocess_source_fields_do_not_change_normalized_atlas_inputs(
    tmp_path: Path,
    copy_source: Callable[[str], Path],
    field: str,
    replacement: object,
) -> None:
    baseline_output = tmp_path / "baseline-output"
    _convert(DEFAULT_SOURCE_ROOT / "incident", baseline_output)
    source = copy_source("incident")
    status_path = source / "status.jsonl"
    rows = jsonl_rows(status_path)
    rows[0][field] = replacement
    status_path.write_text(
        "".join(
            json.dumps(row, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    altered_output = tmp_path / "altered-output"
    _convert(source, altered_output)
    baseline = fixture_root(baseline_output, "incident")
    altered = fixture_root(altered_output, "incident")
    assert _semantic_fixture_bytes(altered) == _semantic_fixture_bytes(baseline)
    assert _json(altered / "source-manifest.json") != _json(baseline / "source-manifest.json")
    baseline_atlas = _atlas_semantics(baseline, tmp_path / "baseline-atlas", "met55_metamorphic")
    altered_atlas = _atlas_semantics(altered, tmp_path / "altered-atlas", "met55_metamorphic")
    assert baseline_atlas == altered_atlas


def test_operational_state_does_not_change_normalized_atlas_inputs(
    tmp_path: Path, copy_source: Callable[[str], Path]
) -> None:
    test_nonprocess_source_fields_do_not_change_normalized_atlas_inputs(
        tmp_path, copy_source, "operationalState", "idle"
    )


def test_error_codes_do_not_change_normalized_atlas_inputs(
    tmp_path: Path, copy_source: Callable[[str], Path]
) -> None:
    test_nonprocess_source_fields_do_not_change_normalized_atlas_inputs(
        tmp_path, copy_source, "errorCodes", ["MP-SYNTHETIC-NONPROCESS-001"]
    )


def test_expected_outcome_is_not_conversion_input(
    tmp_path: Path, copy_source: Callable[[str], Path]
) -> None:
    assert "expected_outcome" not in inspect.signature(core.inspect_source).parameters
    assert "expected_outcome" not in inspect.signature(core.convert).parameters
    source = copy_source("incident")
    (source / "expected-outcome.json").write_bytes(b"not JSON and never an input")
    output = tmp_path / "conversion"
    _convert(source, output)
    assert len(jsonl_rows(fixture_root(output, "incident") / "session.jsonl")) == 9


def test_conversion_is_deterministic(tmp_path: Path) -> None:
    roots = [tmp_path / f"run-{index}" for index in range(3)]
    for root in roots:
        _convert(DEFAULT_SOURCE_ROOT / "incident", root)
    assert file_inventory(roots[0]) == file_inventory(roots[1]) == file_inventory(roots[2])


def test_six_clean_conversions_finalize_as_one_equivalent_profile(tmp_path: Path) -> None:
    conversion_roots: list[Path] = []
    run_ids: list[str] = []
    for variant in ("incident", "control"):
        for index in range(1, 4):
            root = tmp_path / f"{variant}-{index}"
            _convert(DEFAULT_SOURCE_ROOT / variant, root)
            conversion_roots.append(root)
            run_ids.append(f"{variant}-clean-{index}")
    final = tmp_path / "final"
    result = finalize_conversion_equivalence(
        conversion_roots,
        output_root=final,
        run_ids=run_ids,
    )
    assert result["equivalent"] is True
    for variant in ("incident", "control"):
        assert len(jsonl_rows(final / variant / "session.jsonl")) == 9
        report = _json(final / variant / "normalization-report.json")
        reproducibility = report["conversion_reproducibility"]
        assert reproducibility["equivalent"] is True
        assert len(reproducibility["runs"]) == 3


def test_output_directory_collision_is_rejected_and_preserved(tmp_path: Path) -> None:
    output = tmp_path / "conversion"
    _convert(DEFAULT_SOURCE_ROOT / "incident", output)
    before = file_inventory(output)
    with pytest.raises(core.AdapterError):
        _convert(DEFAULT_SOURCE_ROOT / "incident", output)
    with pytest.raises(core.AdapterError):
        core.convert(
            DEFAULT_SOURCE_ROOT / "incident",
            config_path=DEFAULT_CONFIG,
            output_root=output,
            adapter_commit=ADAPTER_COMMIT,
            overwrite=True,
        )
    assert file_inventory(output) == before


def test_source_output_path_overlap_is_rejected(copy_source: Callable[[str], Path]) -> None:
    source = copy_source("incident")
    with pytest.raises(core.AdapterError, match="overlap"):
        _convert(source, source)
    with pytest.raises(core.AdapterError, match="overlap"):
        _convert(source, source / "output")


def test_symlinked_source_root_is_rejected(
    tmp_path: Path, copy_source: Callable[[str], Path]
) -> None:
    source = copy_source("incident")
    link = tmp_path / "incident-link"
    link.symlink_to(source, target_is_directory=True)
    with pytest.raises(core.AdapterError, match="symlink"):
        _convert(link, tmp_path / "output")


def test_root_runtime_is_not_imported_by_adapter() -> None:
    imported_before = set(sys.modules)
    core.inspect_source(DEFAULT_SOURCE_ROOT / "incident", config_path=DEFAULT_CONFIG)
    imported = set(sys.modules) - imported_before
    assert not any(name == "metriplane" or name.startswith("metriplane.") for name in imported)


def test_upstream_artifacts_are_not_packaged(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["uv", "--no-config", "build", "--wheel", "--out-dir", str(tmp_path / "dist")],
        cwd=package_root,
        env={**os.environ, "UV_CACHE_DIR": str(tmp_path / "uv-cache")},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    wheel = next((tmp_path / "dist").glob("*.whl"))
    prohibited = {
        "AMR_Interop_Standard.json",
        "AMR_Interop_Standard.pdf",
        "identityReport1.json",
        "statusReport1.json",
    }
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert not any(Path(name).name in prohibited for name in names)
        assert not any(
            "sender" in name.casefold() or "receiver" in name.casefold() for name in names
        )


def test_installed_wheel_cli_uses_packaged_config_source_and_lock(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    sdk_root = package_root.parent / "source_adapter_sdk"
    distribution_root = tmp_path / "dist"
    build_environment = {**os.environ, "UV_CACHE_DIR": str(tmp_path / "uv-cache")}
    for root in (sdk_root, package_root):
        result = subprocess.run(
            [
                "uv",
                "--no-config",
                "build",
                "--wheel",
                "--out-dir",
                str(distribution_root),
            ],
            cwd=root,
            env=build_environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    environment_root = tmp_path / "installed"
    result = subprocess.run(
        [sys._base_executable, "-m", "venv", str(environment_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    installed_python = environment_root / "bin" / "python"
    wheels = sorted(distribution_root.glob("*.whl"))
    assert len(wheels) == 2
    clean_environment = dict(os.environ)
    clean_environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            str(installed_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            *(str(path) for path in wheels),
        ],
        cwd=tmp_path,
        env=clean_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    paths_program = (
        "import json; from massrobotics_amr_adapter.constants import "
        "DEFAULT_CONFIG, DEFAULT_LOCK, DEFAULT_SOURCE_ROOT; "
        "print(json.dumps({'config':str(DEFAULT_CONFIG),'lock':str(DEFAULT_LOCK),"
        "'source':str(DEFAULT_SOURCE_ROOT)}))"
    )
    result = subprocess.run(
        [str(installed_python), "-c", paths_program],
        cwd=tmp_path,
        env=clean_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    packaged = json.loads(result.stdout)
    assert "/site-packages/" in packaged["config"]
    assert Path(packaged["config"]).is_file()
    assert Path(packaged["lock"]).is_file()
    assert (Path(packaged["source"]) / "incident" / "status.jsonl").is_file()

    result = subprocess.run(
        [
            str(installed_python),
            "-m",
            "massrobotics_amr_adapter.cli",
            "inspect",
            "--source-root",
            str(Path(packaged["source"]) / "incident"),
        ],
        cwd=tmp_path,
        env=clean_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["frame_count"] == 9

    output = tmp_path / "installed-conversion"
    result = subprocess.run(
        [
            str(installed_python),
            "-m",
            "massrobotics_amr_adapter.cli",
            "convert",
            "--source-root",
            str(Path(packaged["source"]) / "control"),
            "--config",
            packaged["config"],
            "--adapter-commit",
            "a" * 40,
            "--out",
            str(output),
        ],
        cwd=tmp_path,
        env=clean_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["normalized_frame_count"] == 9
    assert len(jsonl_rows(output / "fixture" / "session.jsonl")) == 9
