# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest

from metriplane.atlas.bundles import export_bundle, verify_bundle
from metriplane.atlas.models import (
    EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH,
    EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
)
from metriplane.atlas.runtime import run_atlas

ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_PACK = ROOT / "configs" / "domain_packs" / "assembly_cell"
ASSEMBLY_SESSION = (
    ROOT / "datasets" / "demo" / "atlas" / "assembly_cell_missing_tool.jsonl"
)


def _external_provenance() -> dict[str, Any]:
    return {
        "schema_version": "metriplane.external_source_provenance.v1",
        "fixture_id": "synthetic-external-fixture-v1",
        "contract_schema_version": "metriplane.external_source_contract.v1",
        "contract_profile": "metriplane.atlas.complete_snapshot.v1",
        "fixture_distribution": "public",
        "source_project": {
            "name": "Synthetic source\n## forged heading `marker`",
            "canonical_uri": "https://example.invalid/source",
            "version": "1.0.0",
            "revision": {
                "kind": "git_commit",
                "value": "1" * 40,
            },
        },
        "source_artifacts": [],
        "selection": {"method": "episode", "episode_id": "episode-1"},
        "rights": {},
        "adapter": {
            "adapter_id": "org.example.synthetic_adapter",
            "name": "Synthetic adapter",
            "version": "1.2.3",
            "commit": "2" * 40,
        },
        "normalization": {},
        "artifacts": {},
        "reproducibility": {},
        "evaluation": {"metriplane_version": "0.3.0"},
        "limitations": ["Synthetic test provenance."],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_bundle_checksums(bundle: Path) -> None:
    checksum_path = bundle / "checksums.sha256"
    files = [
        path
        for path in sorted(bundle.rglob("*"))
        if path.is_file() and path != checksum_path
    ]
    checksum_path.write_text(
        "".join(
            f"{_sha256(path)}  {path.relative_to(bundle).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )


def test_external_provenance_reaches_run_report_and_evidence_bundle(
    tmp_path: Path,
) -> None:
    output = tmp_path / "external-run"
    provenance = _external_provenance()
    original = copy.deepcopy(provenance)

    manifest = run_atlas(
        ASSEMBLY_SESSION,
        ASSEMBLY_PACK,
        output,
        run_id="external_provenance_test",
        external_source_provenance=provenance,
    )

    assert provenance == original
    provenance_path = output / EXTERNAL_SOURCE_PROVENANCE_RUN_PATH
    assert json.loads(provenance_path.read_text(encoding="utf-8")) == provenance
    assert manifest.artifacts["external_source_provenance"] == (
        EXTERNAL_SOURCE_PROVENANCE_RUN_PATH
    )
    reference = manifest.external_source_provenance
    assert reference is not None
    assert reference.path == EXTERNAL_SOURCE_PROVENANCE_RUN_PATH
    assert reference.sha256 == _sha256(provenance_path)
    assert reference.source_revision == f"git_commit:{'1' * 40}"

    stored_manifest = json.loads(
        (output / "atlas_manifest.json").read_text(encoding="utf-8")
    )
    assert stored_manifest["external_source_provenance"] == reference.model_dump()
    report = (output / "cell_truth_report.md").read_text(encoding="utf-8")
    assert "## External fixture provenance" in report
    assert "Synthetic source ## forged heading 'marker'" in report
    assert "\n## forged heading" not in report

    bundle_dir = output / "evidence_bundles" / "INC-0001"
    bundle_zip = bundle_dir.with_suffix(".zip")
    bundled_provenance = bundle_dir / EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH
    assert bundled_provenance.read_bytes() == provenance_path.read_bytes()
    bundle_manifest = json.loads(
        (bundle_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH in bundle_manifest["required_files"]
    assert bundle_manifest["external_source_provenance"]["path"] == (
        EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH
    )
    assert bundle_manifest["external_source_provenance"]["sha256"] == reference.sha256
    assert verify_bundle(bundle_dir)["pass"] is True
    assert verify_bundle(bundle_zip)["pass"] is True
    with zipfile.ZipFile(bundle_zip) as archive:
        assert archive.read(EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH) == (
            provenance_path.read_bytes()
        )

    duplicate_key_bundle = tmp_path / "duplicate-key-bundle"
    shutil.copytree(bundle_dir, duplicate_key_bundle)
    duplicate_provenance = (
        duplicate_key_bundle / EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH
    )
    duplicate_provenance.write_text(
        duplicate_provenance.read_text(encoding="utf-8").replace(
            '  "fixture_id":',
            '  "fixture_id": "shadow",\n  "fixture_id":',
            1,
        ),
        encoding="utf-8",
    )
    duplicate_manifest_path = duplicate_key_bundle / "manifest.json"
    duplicate_manifest = json.loads(
        duplicate_manifest_path.read_text(encoding="utf-8")
    )
    duplicate_manifest["external_source_provenance"]["sha256"] = _sha256(
        duplicate_provenance
    )
    duplicate_manifest_path.write_text(
        json.dumps(duplicate_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_bundle_checksums(duplicate_key_bundle)
    duplicate_result = verify_bundle(duplicate_key_bundle)
    assert duplicate_result["pass"] is False
    assert any("duplicate JSON key" in error for error in duplicate_result["errors"])

    bundle_manifest["external_source_provenance"]["source_project"] = "other"
    (bundle_dir / "manifest.json").write_text(
        json.dumps(bundle_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_bundle_checksums(bundle_dir)
    tampered = verify_bundle(bundle_dir)
    assert tampered["pass"] is False
    assert any("identity does not match" in error for error in tampered["errors"])

    stored_manifest["external_source_provenance"]["sha256"] = "0" * 64
    (output / "atlas_manifest.json").write_text(
        json.dumps(stored_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sha256 does not match"):
        export_bundle(
            output,
            "INC-0001",
            tmp_path / "reexport.zip",
        )


def test_unknown_external_provenance_schema_fails_before_publish(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rejected-external-run"
    provenance = _external_provenance()
    provenance["schema_version"] = "metriplane.external_source_provenance.v2"

    with pytest.raises(ValueError, match="unsupported external source provenance"):
        run_atlas(
            ASSEMBLY_SESSION,
            ASSEMBLY_PACK,
            output,
            run_id="rejected_external_provenance_test",
            external_source_provenance=provenance,
        )

    assert not output.exists()


def test_ordinary_atlas_run_omits_external_provenance_everywhere(
    tmp_path: Path,
) -> None:
    output = tmp_path / "ordinary-run"

    manifest = run_atlas(
        ASSEMBLY_SESSION,
        ASSEMBLY_PACK,
        output,
        run_id="ordinary_provenance_test",
    )

    assert manifest.external_source_provenance is None
    assert "external_source_provenance" not in manifest.artifacts
    assert not (output / EXTERNAL_SOURCE_PROVENANCE_RUN_PATH).exists()
    stored_manifest = json.loads(
        (output / "atlas_manifest.json").read_text(encoding="utf-8")
    )
    assert "external_source_provenance" not in stored_manifest
    assert "external_source_provenance" not in stored_manifest["artifacts"]
    report = (output / "cell_truth_report.md").read_text(encoding="utf-8")
    assert "## External fixture provenance" not in report

    bundle_dir = output / "evidence_bundles" / "INC-0001"
    bundle_manifest = json.loads(
        (bundle_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert "external_source_provenance" not in bundle_manifest
    assert EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH not in bundle_manifest["required_files"]
    assert not (bundle_dir / EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH).exists()
    assert verify_bundle(bundle_dir)["pass"] is True
    assert verify_bundle(bundle_dir.with_suffix(".zip"))["pass"] is True
