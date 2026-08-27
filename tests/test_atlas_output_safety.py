# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from metriplane.atlas.run_references import resolve_run_reference
from metriplane.atlas.runtime import _safe_generated_out_dir, run_atlas
from metriplane.atlas.usd import export_usda

ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_PACK = ROOT / "configs" / "domain_packs" / "assembly_cell"
ASSEMBLY_SESSION = ROOT / "datasets" / "demo" / "atlas" / "assembly_cell_missing_tool.jsonl"


def _assert_no_private_paths(root: Path, forbidden: tuple[str, ...]) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    data = archive.read(member)
                    for value in forbidden:
                        assert value.encode() not in data, (path, member.filename, value)
                    assert (
                        re.search(
                            rb"(?:/home/[^/\s\"']+|/Users/[^/\s\"']+|(?<![A-Za-z0-9.+-])[A-Za-z]:[\\/])",
                            data,
                        )
                        is None
                    ), (path, member.filename)
            continue
        data = path.read_bytes()
        for value in forbidden:
            assert value.encode() not in data, (path, value)
        assert (
            re.search(
                rb"(?:/home/[^/\s\"']+|/Users/[^/\s\"']+|(?<![A-Za-z0-9.+-])[A-Za-z]:[\\/])",
                data,
            )
            is None
        ), path


def test_existing_system_temp_output_requires_explicit_overwrite() -> None:
    with TemporaryDirectory(dir="/tmp", prefix="metriplane-atlas-safety-") as temp_dir:
        out_dir = Path(temp_dir)
        sentinel = out_dir / "unrelated-user-data.txt"
        sentinel.write_text("keep", encoding="utf-8")

        assert _safe_generated_out_dir(out_dir) is False
        with pytest.raises(ValueError, match="without --overwrite"):
            run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, out_dir)
        assert sentinel.read_text(encoding="utf-8") == "keep"

        manifest = run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, out_dir, overwrite=True)
        assert manifest.event_count == 6
        assert not sentinel.exists()


def test_new_run_references_are_portable_and_do_not_leak_input_paths(tmp_path: Path) -> None:
    sentinels = (
        "PRIVATE_USER_HOME_SENTINEL",
        "PRIVATE_FIXTURE_ROOT_SENTINEL",
        "PRIVATE_PACK_ROOT_SENTINEL",
        "PRIVATE_OUTPUT_ROOT_SENTINEL",
    )
    fixture_root = tmp_path / sentinels[1] / sentinels[0]
    pack_root = tmp_path / sentinels[2]
    output_root = tmp_path / sentinels[3]
    fixture_root.mkdir(parents=True)
    session = fixture_root / "session.jsonl"
    shutil.copyfile(ASSEMBLY_SESSION, session)
    shutil.copytree(ASSEMBLY_PACK, pack_root)

    run_dir = output_root / "run"
    run_atlas(session, pack_root, run_dir, run_id="portable_paths")
    manifest = json.loads((run_dir / "atlas_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_session_jsonl"] == "state_segment.jsonl"
    assert manifest["domain_pack"] == "configs"
    forbidden = (
        *sentinels,
        str(tmp_path.resolve()),
        str(fixture_root.resolve()),
        str(pack_root.resolve()),
        str(output_root.resolve()),
        str(ROOT.resolve()),
    )
    _assert_no_private_paths(run_dir, forbidden)

    moved = tmp_path / "moved_run"
    shutil.move(run_dir, moved)
    shutil.rmtree(fixture_root.parent)
    shutil.rmtree(pack_root)
    regenerated = export_usda(moved, moved / "moved_replay.usda")
    assert regenerated.is_file()
    assert "torque_driver_1" in regenerated.read_text(encoding="utf-8")


def test_run_reference_resolver_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe run-relative reference"):
        resolve_run_reference(
            tmp_path / "run",
            "../private/session.jsonl",
            contained_reference="state_segment.jsonl",
        )


def test_run_reference_resolver_prefers_contained_copy_for_legacy_manifest(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    contained = run / "state_segment.jsonl"
    contained.write_text("{}\n", encoding="utf-8")
    legacy = tmp_path / "legacy" / "source.jsonl"

    assert (
        resolve_run_reference(
            run,
            str(legacy.resolve()),
            contained_reference="state_segment.jsonl",
        )
        == contained
    )

    contained.unlink()
    assert (
        resolve_run_reference(
            run,
            str(legacy.resolve()),
            contained_reference="state_segment.jsonl",
        )
        == legacy.resolve()
    )
