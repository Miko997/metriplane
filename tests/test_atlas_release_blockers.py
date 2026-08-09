# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import zipfile

import pytest
import yaml

import metriplane.atlas.bundles as atlas_bundles
from metriplane.atlas.bundles import export_bundle, verify_bundle
from metriplane.atlas.domain_packs import load_domain_pack, validate_domain_pack
from metriplane.atlas.privacy import anonymize_run, privacy_report
from metriplane.atlas.regression import run_regression
from metriplane.atlas.runtime import run_atlas
from metriplane.atlas.process_model import AssetObservation, ProcessEvaluator
from metriplane.sentinel.bundles import verify_checksums
from metriplane.sentinel.events import IncidentRecord, RuleAlert
from metriplane.testing.compare import compare_events, compare_incidents
from metriplane.testing.models import ExpectedEventSpec, ExpectedIncidentSpec
from metriplane.cli import main as metriplane_main


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


def _resign_atlas_bundle(bundle: Path) -> None:
    checksum = bundle / "checksums.sha256"
    lines = [
        f"{atlas_bundles.sha256_file(path)}  {path.relative_to(bundle).as_posix()}"
        for path in sorted(bundle.rglob("*"))
        if path.is_file() and path.name != "checksums.sha256"
    ]
    checksum.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def test_atlas_verifier_rejects_required_symlink_before_reading(
    tmp_path: Path,
    atlas_run: Path,
) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    outside = tmp_path / "outside-manifest.json"
    outside.write_text('{"required_files": []}', encoding="utf-8")
    manifest = bundle / "manifest.json"
    manifest.unlink()
    manifest.symlink_to(outside)

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any("symlink" in error for error in result["errors"])


def test_atlas_manifest_cannot_claim_missing_or_unsafe_required_files(
    atlas_run: Path,
) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["required_files"].extend(["missing.txt", "../outside.txt"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any(
        token in " ".join(result["errors"])
        for token in ("missing required file", "unsafe bundle path")
    )


def test_atlas_verifier_pydantic_validates_timeline_events(
    atlas_run: Path,
) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    timeline = bundle / "event_timeline.jsonl"
    rows = [json.loads(line) for line in timeline.read_text().splitlines() if line]
    rows[0]["severity"] = "not-a-severity"
    timeline.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    _resign_atlas_bundle(bundle)

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any("invalid timeline event on line 1" in error for error in result["errors"])


def test_atlas_verifier_rejects_duplicate_timeline_event_ids(
    atlas_run: Path,
) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    timeline = bundle / "event_timeline.jsonl"
    rows = timeline.read_text(encoding="utf-8").splitlines()
    timeline.write_text("\n".join([*rows, rows[0]]) + "\n", encoding="utf-8")
    _resign_atlas_bundle(bundle)

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any("duplicate timeline event ID" in error for error in result["errors"])


def test_atlas_verifier_rejects_duplicate_incident_event_ids(
    atlas_run: Path,
) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    incident_path = bundle / "incident.json"
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    incident["event_ids"].append(incident["event_ids"][0])
    incident_path.write_text(json.dumps(incident), encoding="utf-8")
    _resign_atlas_bundle(bundle)

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any("duplicate incident event ID" in error for error in result["errors"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("incident_id", "INC-WRONG", "manifest incident_id does not match incident"),
        ("run_id", "run-wrong", "manifest run_id does not match timeline event"),
    ],
)
def test_atlas_verifier_enforces_manifest_identifiers(
    atlas_run: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _resign_atlas_bundle(bundle)

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any(message in error for error in result["errors"])


def test_atlas_verifier_requires_exact_incident_timeline_event_set(
    atlas_run: Path,
) -> None:
    bundle = _atlas_bundle_dir(atlas_run)
    timeline = bundle / "event_timeline.jsonl"
    rows = [json.loads(line) for line in timeline.read_text().splitlines() if line]
    extra = dict(rows[-1])
    extra["event_id"] = "evt_extra"
    rows.append(extra)
    timeline.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    _resign_atlas_bundle(bundle)

    result = verify_bundle(bundle)

    assert result["pass"] is False
    assert any(
        "incident event IDs do not exactly match timeline" in error
        and "evt_extra" in error
        for error in result["errors"]
    )


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


def test_export_bundle_cannot_write_inside_its_source_run(atlas_run: Path) -> None:
    source = atlas_run / "incidents.jsonl"
    original = source.read_bytes()

    with pytest.raises(ValueError, match="replace its source run"):
        export_bundle(
            atlas_run,
            "INC-0001",
            atlas_run / "incidents.jsonl.zip",
            overwrite=True,
        )

    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "relative_path",
    ["incidents.jsonl", "configs/contracts.yaml"],
)
def test_export_bundle_rejects_symlinked_source_files_before_reading(
    atlas_run: Path,
    tmp_path: Path,
    relative_path: str,
) -> None:
    source = atlas_run / relative_path
    outside = tmp_path / f"outside-{source.name}"
    outside.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(outside)
    output = tmp_path / "export.zip"

    with pytest.raises(ValueError, match="source run path must not be a symlink"):
        export_bundle(atlas_run, "INC-0001", output)

    assert not output.exists()
    assert not output.with_suffix("").exists()


def test_failed_bundle_publish_restores_previous_outputs(
    atlas_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "export.zip"
    sibling = output.with_suffix("")
    output.write_text("old zip", encoding="utf-8")
    sibling.mkdir()
    sentinel = sibling / "important.txt"
    sentinel.write_text("keep", encoding="utf-8")
    real_replace = os.replace

    def fail_zip_publish(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == output and Path(source).name == output.name:
            raise OSError("simulated zip publish failure")
        real_replace(source, destination)

    monkeypatch.setattr("metriplane.atlas.bundles.os.replace", fail_zip_publish)

    with pytest.raises(OSError, match="simulated zip publish failure"):
        export_bundle(atlas_run, "INC-0001", output, overwrite=True)

    assert output.read_text(encoding="utf-8") == "old zip"
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_failed_second_bundle_backup_restores_the_first(
    atlas_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "export.zip"
    sibling = output.with_suffix("")
    output.write_text("old zip", encoding="utf-8")
    sibling.mkdir()
    sentinel = sibling / "important.txt"
    sentinel.write_text("keep", encoding="utf-8")
    real_replace = os.replace

    def fail_second_backup(source: str | Path, destination: str | Path) -> None:
        if Path(source) == output and Path(destination).name == "previous-1":
            raise OSError("simulated backup failure")
        real_replace(source, destination)

    monkeypatch.setattr("metriplane.atlas.bundles.os.replace", fail_second_backup)

    with pytest.raises(OSError, match="simulated backup failure"):
        export_bundle(atlas_run, "INC-0001", output, overwrite=True)

    assert output.read_text(encoding="utf-8") == "old zip"
    assert sentinel.read_text(encoding="utf-8") == "keep"


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


def test_anonymize_pseudonymizes_identity_and_asset_values_without_a_map(
    atlas_run: Path,
    tmp_path: Path,
) -> None:
    events_path = atlas_run / "physical_event_log.jsonl"
    source_before = events_path.read_bytes()
    rows = [json.loads(line) for line in source_before.decode().splitlines()]
    rows[0].update(
        {
            "Worker-ID": "Worker-ALICE-42",
            "Name": {"first": "AliceSecret", "last": "NgSecret"},
            "ASSET_ID": "Pump-SECRET-7",
            "asset_ids": ["Pump-SECRET-7", "OtherAsset-8"],
            "nested": {
                "Person_ID": "Person-PRIVATE-9",
                "faceId": "Face-PRIVATE-10",
                "Objects": [{"ID": "Camera-Asset-3"}],
                "note": (
                    "worker-alice-42 handled pump-secret-7; "
                    "ALICESECRET signed the record"
                ),
            },
        }
    )
    events_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    source_with_sensitive_values = events_path.read_bytes()

    output = tmp_path / "shareable"
    result = anonymize_run(atlas_run, output)

    assert events_path.read_bytes() == source_with_sensitive_values
    assert result["privacy_method"] == "deterministic_pseudonymization"
    assert result["mapping_exported"] is False
    assert not (output / "asset_proxy_map.json").exists()
    metadata = json.loads((output / "privacy_metadata.json").read_text(encoding="utf-8"))
    assert metadata["mapping_exported"] is False
    assert "not guaranteed anonymization" in " ".join(metadata["limitations"])

    pseudonymized = [
        json.loads(line)
        for line in (output / "physical_event_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    first = pseudonymized[0]
    assert first["Worker-ID"].startswith("person_")
    assert first["Name"]["first"].startswith("person_")
    assert first["ASSET_ID"].startswith("asset_")
    assert first["ASSET_ID"] == first["asset_ids"][0]
    assert first["nested"]["Person_ID"].startswith("person_")
    assert first["nested"]["faceId"].startswith("person_")
    assert first["nested"]["Objects"][0]["ID"].startswith("asset_")
    assert first["Worker-ID"] in first["nested"]["note"]
    assert first["ASSET_ID"] in first["nested"]["note"]
    assert first["Name"]["first"] in first["nested"]["note"]
    assert pseudonymized[2]["asset_id"] in pseudonymized[2]["message"]

    shareable_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.rglob("*")
        if path.is_file()
    ).casefold()
    for original in (
        "Worker-ALICE-42",
        "AliceSecret",
        "NgSecret",
        "Pump-SECRET-7",
        "OtherAsset-8",
        "Person-PRIVATE-9",
        "Face-PRIVATE-10",
        "Camera-Asset-3",
        "torque_driver_1",
    ):
        assert original.casefold() not in shareable_text


def test_failed_pseudonymized_publish_restores_previous_output(
    atlas_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "shareable"
    output.mkdir()
    sentinel = output / "important.txt"
    sentinel.write_text("keep", encoding="utf-8")
    real_replace = os.replace

    def fail_publish(source: str | Path, destination: str | Path) -> None:
        if Path(source).name == "pseudonymized" and Path(destination) == output:
            raise OSError("simulated pseudonymized publish failure")
        real_replace(source, destination)

    monkeypatch.setattr("metriplane.atlas.privacy.os.replace", fail_publish)

    with pytest.raises(OSError, match="simulated pseudonymized publish failure"):
        anonymize_run(atlas_run, output, overwrite=True)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_privacy_tools_reject_symlinked_run_inputs(
    atlas_run: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-incidents.jsonl"
    outside.write_text(
        (atlas_run / "incidents.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (atlas_run / "incidents.jsonl").unlink()
    (atlas_run / "incidents.jsonl").symlink_to(outside)

    with pytest.raises(ValueError, match="must not be a symlink"):
        anonymize_run(atlas_run, tmp_path / "pseudonymized")
    with pytest.raises(ValueError, match="must not be a symlink"):
        privacy_report(atlas_run)


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


def test_failed_atlas_overwrite_preserves_the_previous_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-run"
    output.mkdir()
    sentinel = output / "important.txt"
    sentinel.write_text("keep", encoding="utf-8")
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        run_atlas(malformed, ASSEMBLY_PACK, output, overwrite=True)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_failed_atlas_publish_restores_a_previous_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "existing-run"
    target = tmp_path / "missing-target"
    output.symlink_to(target, target_is_directory=True)
    real_replace = os.replace

    def fail_publish(source: str | Path, destination: str | Path) -> None:
        if Path(source).name == "run" and Path(destination) == output:
            raise OSError("simulated publish failure")
        real_replace(source, destination)

    monkeypatch.setattr("metriplane.atlas.runtime.os.replace", fail_publish)

    with pytest.raises(OSError, match="simulated publish failure"):
        run_atlas(
            ASSEMBLY_SESSION,
            ASSEMBLY_PACK,
            output,
            run_id="atomic_rollback",
            overwrite=True,
        )

    assert output.is_symlink()
    assert output.readlink() == target


def test_atlas_uses_authoritative_simulation_time(tmp_path: Path) -> None:
    session = tmp_path / "simulation-clock.jsonl"
    records: list[dict] = []
    for line in ASSEMBLY_SESSION.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("type") != "run_header":
            record["ts_sim_ns"] = int(float(record["ts"]) * 1_000_000_000)
            record["ts"] = 999.0
        records.append(record)
    session.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    output = tmp_path / "run"
    manifest = run_atlas(session, ASSEMBLY_PACK, output)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))

    assert manifest.event_count == 6
    assert manifest.incident_count == 1
    assert metrics["observed_duration_s"] == pytest.approx(70.0)


@pytest.mark.parametrize(
    "updates",
    [
        {"ts": float("nan")},
        {"ts_sim_ns": -1},
    ],
)
def test_atlas_rejects_invalid_frame_times(
    tmp_path: Path,
    updates: dict,
) -> None:
    record = {
        "source_backend": "test",
        "ts": 1.0,
        "frame_id": 1,
        "objects": [],
        **updates,
    }
    session = tmp_path / "invalid-time.jsonl"
    session.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="finite|must be|greater than or equal"):
        run_atlas(session, ASSEMBLY_PACK, tmp_path / "run")


def test_atlas_manifest_artifact_paths_remain_valid_after_atomic_move(
    atlas_run: Path,
) -> None:
    manifest = json.loads(
        (atlas_run / "atlas_manifest.json").read_text(encoding="utf-8")
    )

    for rel in manifest["artifacts"].values():
        assert not Path(rel).is_absolute()
        assert (atlas_run / rel).exists()
    privacy = json.loads(
        (atlas_run / "privacy_report.json").read_text(encoding="utf-8")
    )
    assert privacy["run_dir"] == "."
    dashboard = (atlas_run / "atlas_dashboard.html").read_text(encoding="utf-8")
    assert 'run_dir&quot;: &quot;.&quot;' in dashboard
    assert f".{atlas_run.name}-" not in dashboard


def test_generated_regression_moves_with_its_run(atlas_run: Path, tmp_path: Path) -> None:
    spec = atlas_run / "regression_tests" / "INC-0001.yaml"
    data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    assert not Path(data["source_bundle"]).is_absolute()

    moved = tmp_path / "moved"
    shutil.move(str(atlas_run), moved)
    assert run_regression(moved / "regression_tests" / "INC-0001.yaml")["pass"] is True


def test_cli_exported_bundle_contains_replayable_state(
    atlas_run: Path,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "cli-export.zip"
    spec = tmp_path / "cli-export.yaml"

    assert metriplane_main(
        [
            "atlas",
            "bundle",
            "export",
            "--incident-id",
            "INC-0001",
            "--run-dir",
            str(atlas_run),
            "--out",
            str(bundle),
        ]
    ) == 0
    assert verify_bundle(bundle)["pass"] is True
    assert metriplane_main(
        [
            "atlas",
            "regression",
            "create",
            "--bundle",
            str(bundle),
            "--out",
            str(spec),
        ]
    ) == 0
    assert run_regression(spec)["pass"] is True


def test_run_pack_requires_a_matching_session_for_other_domains(
    tmp_path: Path,
) -> None:
    output = tmp_path / "wrong-demo"

    assert metriplane_main(
        ["atlas", "run-pack", "robot_cell", "--out", str(output)]
    ) == 2
    assert not output.exists()


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


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("expected_events", "ts"),
        ("expected_incidents", "start_ts"),
        ("expected_incidents", "end_ts"),
        ("expected_incidents", "duration_s"),
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_atlas_regression_rejects_nonfinite_expected_times(
    atlas_run: Path,
    section: str,
    field: str,
    value: float,
) -> None:
    spec = atlas_run / "regression_tests" / "INC-0001.yaml"
    data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    data[section][0][field] = value
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
    assert any("invalid max_wait_s" in error for error in errors)
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


def test_domain_pack_validation_handles_unhashable_refs_and_nonfinite_waits(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)
    contracts_path = pack / "contracts.yaml"
    contracts = yaml.safe_load(contracts_path.read_text(encoding="utf-8"))
    contracts["contracts"][0]["station_id"] = ["station_a"]
    contracts["contracts"][0]["max_wait_s"] = float("inf")
    contracts_path.write_text(
        yaml.safe_dump(contracts, sort_keys=True), encoding="utf-8"
    )

    errors = validate_domain_pack(pack)

    assert any("invalid station_id" in error for error in errors)
    assert any("invalid max_wait_s" in error for error in errors)


def test_domain_pack_validation_reports_malformed_contract_yaml(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)
    (pack / "contracts.yaml").write_text("contracts: [\n", encoding="utf-8")

    errors = validate_domain_pack(pack)

    assert any("could not parse contracts file" in error for error in errors)


def test_domain_pack_rejects_ambiguous_stations_and_step_location(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)
    workspace_path = pack / "workspace.yaml"
    workspace = yaml.safe_load(workspace_path.read_text(encoding="utf-8"))
    workspace["stations"].append(
        {
            "station_id": "station_duplicate",
            "zone_id": "station_a_work",
            "label": "Ambiguous station",
        }
    )
    workspace_path.write_text(
        yaml.safe_dump(workspace, sort_keys=True), encoding="utf-8"
    )
    process_path = pack / "process.yaml"
    process = yaml.safe_load(process_path.read_text(encoding="utf-8"))
    process["steps"][1]["required_zone"] = "outbound_buffer"
    process_path.write_text(yaml.safe_dump(process, sort_keys=True), encoding="utf-8")

    errors = validate_domain_pack(pack)

    assert any("assigned to multiple stations" in error for error in errors)
    assert any("not outbound_buffer" in error for error in errors)


def test_domain_pack_rejects_multiple_work_orders_until_selection_is_explicit(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)
    work_orders = pack / "work_orders.csv"
    text = work_orders.read_text(encoding="utf-8")
    first = text.splitlines()[1].split(",")
    first[0] = "WO-ASM-002"
    work_orders.write_text(text + ",".join(first) + "\n", encoding="utf-8")

    assert any(
        "exactly one work order" in error for error in validate_domain_pack(pack)
    )


def test_process_evaluator_reports_the_actually_missing_required_asset() -> None:
    pack = load_domain_pack(ASSEMBLY_PACK)
    step = pack.process.steps[-1].model_copy(
        update={"required_assets": ["torque_driver_1", "quality_gauge_1"]}
    )
    process = pack.process.model_copy(update={"steps": [step]})
    evaluator = ProcessEvaluator(
        run_id="multi-required",
        process=process,
        work_order_id=pack.work_orders[0].work_order_id,
    )
    torque_driver = pack.assets.by_asset_id()["torque_driver_1"]
    events = evaluator.update(
        [
            AssetObservation(
                asset=torque_driver,
                ts=0.0,
                frame_id=1,
                zone_id="station_a_work",
                station_id="station_a",
            )
        ],
        ts=0.0,
        frame_id=1,
    )

    assert events[0].event_type == "required_asset_missing"
    assert events[0].asset_id == "quality_gauge_1"
    assert "quality_gauge_1" in events[0].message


def test_process_evaluator_resets_missing_evidence_when_asset_changes() -> None:
    pack = load_domain_pack(ASSEMBLY_PACK)
    step = pack.process.steps[-1].model_copy(
        update={
            "required_assets": ["torque_driver_1", "quality_gauge_1"],
            "max_wait_s": 1.0,
        }
    )
    evaluator = ProcessEvaluator(
        run_id="changing-missing",
        process=pack.process.model_copy(update={"steps": [step]}),
        work_order_id=pack.work_orders[0].work_order_id,
    )
    assets = pack.assets.by_asset_id()

    def observation(asset_id: str, ts: float, frame_id: int) -> AssetObservation:
        return AssetObservation(
            asset=assets[asset_id],
            ts=ts,
            frame_id=frame_id,
            zone_id="station_a_work",
            station_id="station_a",
        )

    first = evaluator.update(
        [observation("quality_gauge_1", 0.0, 1)], 0.0, 1
    )
    second = evaluator.update(
        [observation("torque_driver_1", 0.5, 2)], 0.5, 2
    )
    delayed = evaluator.update(
        [observation("torque_driver_1", 2.0, 3)], 2.0, 3
    )

    assert first[0].asset_id == "torque_driver_1"
    assert second[0].asset_id == "quality_gauge_1"
    assert [event.asset_id for event in delayed] == ["quality_gauge_1"]
    assert evaluator.incidents[0].asset_ids == ["quality_gauge_1"]
    assert evaluator.incidents[0].event_ids == [second[0].event_id, delayed[0].event_id]


def test_station_occupancy_excludes_time_away_from_station(tmp_path: Path) -> None:
    session = tmp_path / "leave-and-return.jsonl"
    frames = []
    for frame_id, ts, zone in (
        (1, 0.0, "station_a_work"),
        (2, 10.0, None),
        (3, 25.0, "station_a_work"),
        (4, 30.0, "station_a_work"),
    ):
        frames.append(
            {
                "source_backend": "test",
                "ts": ts,
                "frame_id": frame_id,
                "objects": [] if zone is None else [{"id": "7", "zone": zone}],
            }
        )
    session.write_text(
        "".join(json.dumps(frame) + "\n" for frame in frames),
        encoding="utf-8",
    )
    output = tmp_path / "run"

    run_atlas(session, ASSEMBLY_PACK, output)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))

    assert metrics["station_occupancy_s"]["station_a"] == pytest.approx(5.0)


def test_domain_pack_validation_rejects_unknown_asset_type_and_work_order_refs(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(ASSEMBLY_PACK, pack)

    process_path = pack / "process.yaml"
    process = yaml.safe_load(process_path.read_text(encoding="utf-8"))
    process["steps"][0]["expected_asset_types"] = ["kit_bni_typo"]
    process_path.write_text(
        yaml.safe_dump(process, sort_keys=True), encoding="utf-8"
    )

    assets_path = pack / "assets.yaml"
    assets = yaml.safe_load(assets_path.read_text(encoding="utf-8"))
    assets["assets"][0]["work_order_id"] = "WO-UNKNOWN"
    assets_path.write_text(yaml.safe_dump(assets, sort_keys=True), encoding="utf-8")

    errors = validate_domain_pack(pack)

    assert any("unknown asset type kit_bni_typo" in error for error in errors)
    assert any("unknown work order WO-UNKNOWN" in error for error in errors)
