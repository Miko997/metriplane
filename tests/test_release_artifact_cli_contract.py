# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import gzip
import io
import json
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from metriplane.release_control import make_record, validate_record, write_immutable_json
from tools import build_release_artifacts as artifact_cli
from tools.release_artifacts import _REQUIRED_SDIST_PATHS

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "1" * 40
SOURCE_TREE = "2" * 40
DIGESTS = {
    "burn": "3" * 64,
    "freeze": "4" * 64,
    "gate": "5" * 64,
    "observations": "6" * 64,
    "release_notes": "7" * 64,
    "resolution": "8" * 64,
    "version": "9" * 64,
    "workflow": "a" * 64,
}


def _record_inputs(
    root: Path,
    *,
    target_synthetic: bool = True,
    source_synthetic: bool = True,
    source_overrides: dict[str, Any] | None = None,
    target_overrides: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    target_data: dict[str, Any] = {
        "burn_lineage_digest": DIGESTS["burn"],
        "burn_target_ids": [],
        "initial_package_version": "v0.4.0",
        "initial_release_tag": "v0.4.0",
        "milestone": "v0.4",
        "observations_digest": DIGESTS["observations"],
        "prior_burn_digests": [],
        "requires_new_burn": False,
        "resolution_digest": DIGESTS["resolution"],
        "resolution_rule": "next_unused_same_milestone_patch",
        "selected_package_version": "v0.4.0",
        "selected_release_tag": "v0.4.0",
    }
    source_data: dict[str, Any] = {
        "build_recipe_digest": artifact_cli.BUILD_RECIPE_DIGEST,
        "dirty": False,
        "freeze_digest": DIGESTS["freeze"],
        "frozen_at": "2026-08-27T00:00:00Z",
        "gate_input_digest": DIGESTS["gate"],
        "milestone": "v0.4",
        "registry_inputs": [
            {
                "path": "docs/status/release-targets.json",
                "schema_id": "metriplane.release-targets.v1",
                "sha256": DIGESTS["observations"],
            }
        ],
        "release_notes_digest": DIGESTS["release_notes"],
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "version_metadata_digest": DIGESTS["version"],
        "workflow_inputs": [
            {
                "path": ".github/workflows/release-required.yml",
                "schema_id": "metriplane.release-workflow.v1",
                "sha256": DIGESTS["workflow"],
            }
        ],
    }
    target_data.update(target_overrides or {})
    source_data.update(source_overrides or {})
    target = make_record(
        "release-target-resolution",
        target_data,
        invocation_id="fixture-target-resolution",
        sequence=1,
        synthetic=target_synthetic,
    )
    source = make_record(
        "release-source-freeze",
        source_data,
        invocation_id="fixture-source-freeze",
        sequence=1,
        synthetic=source_synthetic,
    )
    target_path = root / "target-resolution.json"
    source_path = root / "source-freeze.json"
    write_immutable_json(target_path, target)
    write_immutable_json(source_path, source)
    return target_path, source_path


def _write_deterministic_sdist(path: Path, version: str) -> None:
    uncompressed = io.BytesIO()
    with tarfile.open(fileobj=uncompressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(_REQUIRED_SDIST_PATHS):
            payload = name.encode("utf-8")
            info = tarfile.TarInfo(f"metriplane-{version}/{name}")
            info.mode = 0o644
            info.mtime = 0
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
    ):
        compressed.write(uncompressed.getvalue())


def _install_fake_build(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[Path],
) -> None:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    monkeypatch.setattr(artifact_cli, "_verify_frozen_source", lambda inputs: 1_700_000_000)

    def fake_archive(source_sha: str, temporary_root: Path) -> Path:
        assert source_sha == SOURCE_SHA
        source_dir = temporary_root / "source"
        source_dir.mkdir()
        return source_dir

    def fake_build(source_dir: Path, dist_dir: Path, *, source_date_epoch: int) -> None:
        assert source_dir.name == "source"
        assert source_date_epoch == 1_700_000_000
        calls.append(dist_dir)
        (dist_dir / "metriplane-0.4.0-py3-none-any.whl").write_bytes(b"wheel-v0.4.0")
        _write_deterministic_sdist(dist_dir / "metriplane-0.4.0.tar.gz", "0.4.0")

    monkeypatch.setattr(artifact_cli, "_archive_source", fake_archive)
    monkeypatch.setattr(artifact_cli, "_run_build", fake_build)


def _argv(target: Path, source: Path, out_dir: Path, manifest: Path) -> list[str]:
    return [
        "--target-resolution",
        str(target),
        "--source-freeze",
        str(source),
        "--out-dir",
        str(out_dir),
        "--manifest",
        str(manifest),
    ]


def test_section_9b_parser_accepts_only_the_exact_artifact_form(tmp_path: Path) -> None:
    parsed = artifact_cli._parse_args(
        _argv(
            tmp_path / "target.json",
            tmp_path / "source.json",
            tmp_path / "artifacts",
            tmp_path / "manifest.json",
        )
    )
    assert set(vars(parsed)) == {"manifest", "out_dir", "source_freeze", "target_resolution"}

    completed = subprocess.run(
        [sys.executable, "tools/build_release_artifacts.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    for flag in ("--target-resolution", "--source-freeze", "--out-dir", "--manifest"):
        assert flag in completed.stdout
    assert "intentionally unsupported" in completed.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--target-resolution", ""],
        ["--dist", "dist", "--version", "0.4.0", "--output", "manifest.json"],
        ["--not-a-section-9b-flag", "value"],
    ],
)
def test_section_9b_parser_rejects_missing_blank_legacy_and_unknown_flags(
    arguments: list[str],
) -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_release_artifacts.py", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2


def test_fixture_build_is_deterministic_digest_bound_and_no_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, source = _record_inputs(tmp_path / "inputs")
    calls: list[Path] = []
    _install_fake_build(monkeypatch, calls)
    outputs: list[tuple[Path, Path]] = []

    for name in ("first", "second"):
        out_dir = tmp_path / name / "artifacts"
        manifest = tmp_path / name / "artifact-manifest.json"
        assert artifact_cli.main(_argv(target, source, out_dir, manifest)) == 0
        outputs.append((out_dir, manifest))

    first_dir, first_manifest = outputs[0]
    second_dir, second_manifest = outputs[1]
    assert first_manifest.read_bytes() == second_manifest.read_bytes()
    assert {path.name: path.read_bytes() for path in first_dir.iterdir()} == {
        path.name: path.read_bytes() for path in second_dir.iterdir()
    }

    record = json.loads(first_manifest.read_text(encoding="utf-8"))
    validate_record(record, "release-artifact-manifest")
    assert record["synthetic"] is True
    assert set(record["data"]) == {
        "artifact_set_digest",
        "artifacts",
        "build_invocation_id",
        "build_recipe_digest",
        "milestone",
        "source_digest",
        "source_freeze_digest",
        "target_resolution_digest",
    }
    assert [item["path"] for item in record["data"]["artifacts"]] == [
        "metriplane-0.4.0-py3-none-any.whl",
        "metriplane-0.4.0.tar.gz",
    ]
    assert all(path.stat().st_mode & 0o222 == 0 for path in first_dir.iterdir())
    assert str(tmp_path) not in first_manifest.read_text(encoding="utf-8")

    original_manifest = first_manifest.read_bytes()
    original_artifacts = {path.name: path.read_bytes() for path in first_dir.iterdir()}
    assert artifact_cli.main(_argv(target, source, first_dir, first_manifest)) == 3
    assert len(calls) == 2
    assert first_manifest.read_bytes() == original_manifest
    assert {path.name: path.read_bytes() for path in first_dir.iterdir()} == original_artifacts
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == "BLOCKED_NOT_READY"


def test_synthetic_inputs_are_blocked_without_fixture_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, source = _record_inputs(tmp_path / "inputs")
    monkeypatch.delenv("METRIPLANE_RELEASE_FIXTURE_MODE", raising=False)
    monkeypatch.setattr(
        artifact_cli,
        "_verify_frozen_source",
        lambda inputs: pytest.fail("source inspection must not run"),
    )
    out_dir = tmp_path / "artifacts"
    manifest = tmp_path / "manifest.json"

    assert artifact_cli.main(_argv(target, source, out_dir, manifest)) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "BLOCKED_NOT_READY"
    assert "fixture mode" in result["reason"]
    assert not out_dir.exists()
    assert not manifest.exists()


@pytest.mark.parametrize(
    ("source_synthetic", "source_overrides", "target_overrides", "reason"),
    [
        (False, None, None, "authority modes differ"),
        (True, {"dirty": True}, None, "clean tree"),
        (True, {"milestone": "v0.5"}, None, "milestones differ"),
        (True, {"build_recipe_digest": "f" * 64}, None, "unsupported artifact build recipe"),
        (True, None, {"selected_package_version": ""}, "selected_package_version"),
        (
            True,
            None,
            {"selected_package_version": "v0.5.0"},
            "outside the resolved milestone",
        ),
    ],
)
def test_unresolved_or_cross_mode_inputs_block_before_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source_synthetic: bool,
    source_overrides: dict[str, Any] | None,
    target_overrides: dict[str, Any] | None,
    reason: str,
) -> None:
    target, source = _record_inputs(
        tmp_path / "inputs",
        source_synthetic=source_synthetic,
        source_overrides=source_overrides,
        target_overrides=target_overrides,
    )
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    monkeypatch.setattr(
        artifact_cli,
        "_verify_frozen_source",
        lambda inputs: pytest.fail("source inspection must not run"),
    )
    out_dir = tmp_path / "artifacts"
    manifest = tmp_path / "manifest.json"

    assert artifact_cli.main(_argv(target, source, out_dir, manifest)) == 3
    assert reason in json.loads(capsys.readouterr().out)["reason"]
    assert not out_dir.exists()
    assert not manifest.exists()


def test_tampered_input_is_invalid_not_release_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, source = _record_inputs(tmp_path / "inputs")
    target.chmod(0o644)
    record = json.loads(target.read_text(encoding="utf-8"))
    record["data"]["selected_release_tag"] = "v0.4.1"
    target.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")

    assert (
        artifact_cli.main(_argv(target, source, tmp_path / "artifacts", tmp_path / "manifest.json"))
        == 2
    )
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize("occupied", ["artifacts", "manifest"])
def test_existing_destination_is_never_changed_or_rebuilt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    occupied: str,
) -> None:
    target, source = _record_inputs(tmp_path / "inputs")
    out_dir = tmp_path / "artifacts"
    manifest = tmp_path / "manifest.json"
    if occupied == "artifacts":
        out_dir.mkdir()
        (out_dir / "retained.bin").write_bytes(b"retained")
    else:
        manifest.write_bytes(b"retained")
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    monkeypatch.setattr(artifact_cli, "_verify_frozen_source", lambda inputs: 1)
    build: Callable[..., None] = lambda *args, **kwargs: pytest.fail("build must not run")
    monkeypatch.setattr(artifact_cli, "_run_build", build)

    assert artifact_cli.main(_argv(target, source, out_dir, manifest)) == 3
    if occupied == "artifacts":
        assert (out_dir / "retained.bin").read_bytes() == b"retained"
    else:
        assert manifest.read_bytes() == b"retained"


def test_failed_build_leaves_no_canonical_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, source = _record_inputs(tmp_path / "inputs")
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    monkeypatch.setattr(artifact_cli, "_verify_frozen_source", lambda inputs: 1)

    def fake_archive(source_sha: str, temporary_root: Path) -> Path:
        source_dir = temporary_root / "source"
        source_dir.mkdir()
        return source_dir

    def fail_build(source_dir: Path, dist_dir: Path, *, source_date_epoch: int) -> None:
        raise artifact_cli.ArtifactBuildBlocked("build failed")

    monkeypatch.setattr(artifact_cli, "_archive_source", fake_archive)
    monkeypatch.setattr(artifact_cli, "_run_build", fail_build)
    out_dir = tmp_path / "artifacts"
    manifest = tmp_path / "manifest.json"

    assert artifact_cli.main(_argv(target, source, out_dir, manifest)) == 3
    assert not out_dir.exists()
    assert not manifest.exists()


def test_partial_install_and_manifest_failure_roll_back_owned_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, source = _record_inputs(tmp_path / "inputs")
    calls: list[Path] = []
    _install_fake_build(monkeypatch, calls)
    real_link = artifact_cli.os.link
    links = 0

    def fail_second_link(
        source_path: Path,
        destination_path: Path,
        *,
        follow_symlinks: bool,
    ) -> None:
        nonlocal links
        links += 1
        if links == 2:
            raise OSError("injected link failure")
        real_link(source_path, destination_path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(artifact_cli.os, "link", fail_second_link)
    out_dir = tmp_path / "partial" / "artifacts"
    manifest = tmp_path / "partial" / "manifest.json"
    assert artifact_cli.main(_argv(target, source, out_dir, manifest)) == 3
    assert not out_dir.exists()
    assert not manifest.exists()

    monkeypatch.setattr(artifact_cli.os, "link", real_link)

    def fail_manifest(path: Path, value: object) -> str:
        raise artifact_cli.ReleaseControlError("injected manifest failure")

    monkeypatch.setattr(artifact_cli, "write_immutable_json", fail_manifest)
    out_dir = tmp_path / "manifest-failure" / "artifacts"
    manifest = tmp_path / "manifest-failure" / "manifest.json"
    assert artifact_cli.main(_argv(target, source, out_dir, manifest)) == 3
    assert not out_dir.exists()
    assert not manifest.exists()
