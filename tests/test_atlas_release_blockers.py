# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path
import shutil
import zipfile

import pytest
import yaml

import metriplane.atlas.bundles as atlas_bundles
from metriplane.atlas.bundles import export_bundle, verify_bundle
from metriplane.atlas.domain_packs import validate_domain_pack
from metriplane.atlas.privacy import anonymize_run
from metriplane.atlas.regression import run_regression
from metriplane.atlas.runtime import run_atlas
from metriplane.sentinel.bundles import verify_checksums
from metriplane.sentinel.events import IncidentRecord, RuleAlert
from metriplane.testing.compare import compare_events, compare_incidents
from metriplane.testing.models import ExpectedEventSpec, ExpectedIncidentSpec


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_PACK = ROOT / "configs" / "domain_packs" / "assembly_cell"
ASSEMBLY_SESSION = (
    ROOT / "datasets" / "demo" / "atlas" / "assembly_cell_missing_tool.jsonl"
)
FROZEN_ATLAS_BUNDLE = (
    ROOT
    / "evidence"
    / "paper_v2_0"
    / "atlas_run"
    / "evidence_bundles"
    / "INC-0001.zip"
)


@pytest.fixture
def atlas_run(tmp_path: Path) -> Path:
    output = tmp_path / "run"
    run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, output, run_id="release_blockers")
    return output


def _atlas_bundle_dir(run: Path) -> Path:
    return run / "evidence_bundles" / "INC-0001"


def test_frozen_atlas_and_sentinel_checksums_remain_valid() -> None:
    assert verify_bundle(FROZEN_ATLAS_BUNDLE)["pass"] is True
    sentinel_bundle = ROOT / "evidence" / "incidents" / "INC-DIST-001"
    assert verify_checksums(sentinel_bundle) == []


def test_atlas_rejects_omitted_checksum_and_unsigned_file(atlas_run: Path) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    checksum = bundle / "checksums.sha256"
    lines = checksum.read_text(encoding="utf-8").splitlines()
    checksum.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    (bundle / "unsigned.txt").write_text("not covered", encoding="utf-8")

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any("missing checksum entry" in error for error in result["errors"])
    assert any("unsigned.txt" in error for error in result["errors"])


@pytest.mark.parametrize(
    "entry",
    [
        "not-a-digest  incident.json",
        f"{'0' * 64}  ../outside.txt",
    ],
)
def test_atlas_rejects_malformed_or_unsafe_checksum_entries(
    atlas_run: Path,
    entry: str,
) -> None:
    checksum = _atlas_bundle_dir(atlas_run) / "checksums.sha256"
    checksum.write_text(
        checksum.read_text(encoding="utf-8") + entry + "\n",
        encoding="utf-8",
    )

    result = verify_bundle(checksum.parent)

    assert result["pass"] is False
    assert any(
        token in " ".join(result["errors"])
        for token in ("malformed checksum", "unsafe bundle path")
    )


def test_atlas_rejects_duplicate_checksum_entry(atlas_run: Path) -> None:
    checksum = _atlas_bundle_dir(atlas_run) / "checksums.sha256"
    first = checksum.read_text(encoding="utf-8").splitlines()[0]
    checksum.write_text(
        checksum.read_text(encoding="utf-8") + first + "\n",
        encoding="utf-8",
    )

    result = verify_bundle(checksum.parent)

    assert result["pass"] is False
    assert any("duplicate checksum entry" in error for error in result["errors"])


def test_atlas_verifier_returns_structured_failures(tmp_path: Path, atlas_run: Path) -> None:
    missing = verify_bundle(tmp_path / "missing.zip")
    assert missing["pass"] is False
    assert missing["errors"]

    nonzip = tmp_path / "not-a-bundle.zip"
    nonzip.write_text("plain text", encoding="utf-8")
    assert verify_bundle(nonzip)["pass"] is False

    bundle = _atlas_bundle_dir(atlas_run)
    (bundle / "manifest.json").write_text("{", encoding="utf-8")
    malformed = verify_bundle(bundle)
    assert malformed["pass"] is False
    assert malformed["errors"]


def test_atlas_zip_preflight_rejects_duplicate_and_oversized_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("manifest.json", "one")
            archive.writestr("manifest.json", "two")
    assert any("duplicate zip member" in e for e in verify_bundle(duplicate)["errors"])

    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as archive:
        archive.writestr("payload.bin", b"12345")
    monkeypatch.setattr(atlas_bundles, "MAX_ZIP_MEMBER_BYTES", 4)
    assert any("too large" in e for e in verify_bundle(oversized)["errors"])


def test_sentinel_checksum_inventory_rejects_false_passes(tmp_path: Path) -> None:
    source = ROOT / "evidence" / "incidents" / "INC-DIST-001"
    bundle = tmp_path / "sentinel"
    shutil.copytree(source, bundle)
    checksum = bundle / "CHECKSUMS.sha256"
    lines = checksum.read_text(encoding="utf-8").splitlines()
    checksum.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    (bundle / "unsigned.txt").write_text("extra", encoding="utf-8")

    errors = verify_checksums(bundle)

    assert any("missing checksum entry" in error for error in errors)
    assert any("unsigned.txt" in error for error in errors)


@pytest.mark.parametrize(
    "suffix",
    [
        "not-a-checksum",
        f"{'0' * 64}  ../outside.txt",
    ],
)
def test_sentinel_rejects_malformed_and_unsafe_checksum_lines(
    tmp_path: Path,
    suffix: str,
) -> None:
    source = ROOT / "evidence" / "incidents" / "INC-DIST-001"
    bundle = tmp_path / "sentinel"
    shutil.copytree(source, bundle)
    checksum = bundle / "CHECKSUMS.sha256"
    checksum.write_text(
        checksum.read_text(encoding="utf-8") + suffix + "\n",
        encoding="utf-8",
    )
    assert verify_checksums(bundle)


def test_export_bundle_refuses_existing_outputs(atlas_run: Path, tmp_path: Path) -> None:
    output = tmp_path / "export.zip"
    sibling = output.with_suffix("")
    sibling.mkdir()
    sentinel = sibling / "unrelated.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="without --overwrite"):
        export_bundle(atlas_run, "INC-0001", output)
    assert sentinel.read_text(encoding="utf-8") == "keep"

    export_bundle(atlas_run, "INC-0001", output, overwrite=True)
    assert output.is_file()
    assert verify_bundle(output)["pass"] is True
    assert not sentinel.exists()


def test_export_bundle_cannot_replace_its_source_run(atlas_run: Path) -> None:
    output = atlas_run.with_suffix(".zip")
    with pytest.raises(ValueError, match="replace its source run"):
        export_bundle(atlas_run, "INC-0001", output, overwrite=True)
    assert (atlas_run / "incidents.jsonl").is_file()


def test_anonymize_refuses_overlap_and_requires_overwrite(
    atlas_run: Path,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        anonymize_run(atlas_run, atlas_run, overwrite=True)
    with pytest.raises(ValueError, match="must not overlap"):
        anonymize_run(atlas_run, atlas_run / "anonymous", overwrite=True)
    assert (atlas_run / "incidents.jsonl").is_file()

    output = tmp_path / "anonymous"
    output.mkdir()
    sentinel = output / "unrelated.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="without --overwrite"):
        anonymize_run(atlas_run, output)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert anonymize_run(atlas_run, output, overwrite=True)["mapped_values"] > 0


def test_run_atlas_never_deletes_session_or_pack(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "session_root"
    session_root.mkdir()
    session = session_root / "session.jsonl"
    shutil.copyfile(ASSEMBLY_SESSION, session)
    keep_session = session.read_bytes()
    with pytest.raises(ValueError, match="contains the source session"):
        run_atlas(session, ASSEMBLY_PACK, session_root, overwrite=True)
    assert session.read_bytes() == keep_session

    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)
    nested_output = pack / "generated"
    nested_output.mkdir()
    sentinel = nested_output / "pack-data.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="overlaps the source domain pack"):
        run_atlas(ASSEMBLY_SESSION, pack, nested_output, overwrite=True)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_generated_regression_moves_with_its_run(atlas_run: Path, tmp_path: Path) -> None:
    spec = atlas_run / "regression_tests" / "INC-0001.yaml"
    data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    assert not Path(data["source_bundle"]).is_absolute()

    moved = tmp_path / "moved"
    shutil.move(str(atlas_run), moved)
    assert run_regression(moved / "regression_tests" / "INC-0001.yaml")["pass"] is True


@pytest.mark.parametrize(
    ("section", "field", "delta"),
    [
        ("expected_events", "ts", 10.0),
        ("expected_incidents", "duration_s", 10.0),
    ],
)
def test_atlas_regression_enforces_time_and_duration_tolerances(
    atlas_run: Path,
    section: str,
    field: str,
    delta: float,
) -> None:
    spec = atlas_run / "regression_tests" / "INC-0001.yaml"
    data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    data[section][0][field] += delta
    data["tolerances"]["event_time_s"] = 0.0
    data["tolerances"]["duration_s"] = 0.0
    spec.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    result = run_regression(spec)

    assert result["pass"] is False


def test_physical_regression_enforces_incident_and_event_types() -> None:
    incident = IncidentRecord(
        rule_id="zone_rule",
        severity="warning",
        opened_ts=1.0,
        closed_ts=2.0,
        duration_s=1.0,
        object_ids=["cart"],
        zones=["exit"],
        summary="test",
    )
    incident_checks = compare_incidents(
        [incident],
        [ExpectedIncidentSpec(type="speed_limit", rule_id="zone_rule")],
        rule_types={"zone_rule": "forbidden_zone"},
    )
    assert all(check["pass"] is False for check in incident_checks)

    alert = RuleAlert(
        rule_id="zone_rule",
        severity="warning",
        ts=1.0,
        object_ids=["cart"],
    )
    event_checks = compare_events(
        [alert],
        [ExpectedEventSpec(event_type="incident_open", min_count=1)],
    )
    assert all(check["pass"] is False for check in event_checks)


def test_domain_pack_validation_rejects_empty_work_orders_and_process(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)
    (pack / "work_orders.csv").write_text(
        "work_order_id,process_id,product\n", encoding="utf-8"
    )
    assert any("at least one work order" in error for error in validate_domain_pack(pack))
    with pytest.raises(ValueError, match="at least one work order"):
        run_atlas(ASSEMBLY_SESSION, pack, tmp_path / "run")

    process = yaml.safe_load((pack / "process.yaml").read_text(encoding="utf-8"))
    process["steps"] = []
    (pack / "process.yaml").write_text(
        yaml.safe_dump(process, sort_keys=True), encoding="utf-8"
    )
    assert any("at least one step" in error for error in validate_domain_pack(pack))


def test_domain_pack_validation_rejects_duplicate_and_bad_references(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)

    workspace_path = pack / "workspace.yaml"
    workspace = yaml.safe_load(workspace_path.read_text(encoding="utf-8"))
    workspace["zones"].append(dict(workspace["zones"][0]))
    workspace["stations"].append(dict(workspace["stations"][0]))
    workspace_path.write_text(yaml.safe_dump(workspace, sort_keys=True), encoding="utf-8")

    process_path = pack / "process.yaml"
    process = yaml.safe_load(process_path.read_text(encoding="utf-8"))
    duplicate_step = dict(process["steps"][0])
    duplicate_step["max_wait_s"] = -1
    process["steps"].append(duplicate_step)
    process_path.write_text(yaml.safe_dump(process, sort_keys=True), encoding="utf-8")

    assets_path = pack / "assets.yaml"
    assets = yaml.safe_load(assets_path.read_text(encoding="utf-8"))
    assets["assets"][0]["expected_zones"] = ["missing_zone"]
    assets["assets"][0]["expected_stations"] = ["missing_station"]
    assets_path.write_text(yaml.safe_dump(assets, sort_keys=True), encoding="utf-8")

    errors = validate_domain_pack(pack)
    assert any("duplicate zone_id" in error for error in errors)
    assert any("duplicate station_id" in error for error in errors)
    assert any("duplicate step_id" in error for error in errors)
    assert any("negative max_wait_s" in error for error in errors)
    assert any("unknown expected zone" in error for error in errors)
    assert any("unknown expected station" in error for error in errors)


def test_domain_pack_validation_rejects_bad_work_order_and_contract(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)
    work_orders = (pack / "work_orders.csv").read_text(encoding="utf-8")
    (pack / "work_orders.csv").write_text(
        work_orders.replace("assembly_cell_missing_tool_demo", "wrong_process"),
        encoding="utf-8",
    )
    assert any("expected assembly_cell_missing_tool_demo" in error
               for error in validate_domain_pack(pack))

    shutil.rmtree(pack)
    shutil.copytree(ASSEMBLY_PACK, pack)
    contracts = {
        "schema_version": "wrong",
        "contracts": [
            {
                "contract_id": "bad",
                "kind": "process_asset_presence",
                "process_step_id": "missing_step",
                "required_asset_id": "missing_asset",
                "station_id": "missing_station",
                "max_wait_s": -1,
            }
        ],
    }
    (pack / "contracts.yaml").write_text(
        yaml.safe_dump(contracts, sort_keys=True), encoding="utf-8"
    )
    errors = validate_domain_pack(pack)
    assert any("unsupported contracts schema_version" in error for error in errors)
    assert any("unknown step" in error for error in errors)
    assert any("unknown asset" in error for error in errors)
    assert any("unknown station" in error for error in errors)
    assert any("invalid max_wait_s" in error for error in errors)
