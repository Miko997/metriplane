# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

import ros2_mcap_adapter.path_safety as path_safety
from ros2_mcap_adapter.canonical import sha256_file
from ros2_mcap_adapter.cli import main
from ros2_mcap_adapter.constants import SOURCE_SHA256, SOURCE_SIZE
from ros2_mcap_adapter.generator import SourceGenerationError, build_source_bytes, generate_source
from ros2_mcap_adapter.identity import AdapterIdentityError, verify_adapter_commit


def test_source_generation_is_byte_deterministic(tmp_path: Path) -> None:
    paths = [tmp_path / f"source-{index}.mcap" for index in range(3)]
    results = [generate_source(path) for path in paths]
    assert all(path.read_bytes() == paths[0].read_bytes() for path in paths[1:])
    assert all(result["size"] == SOURCE_SIZE for result in results)
    assert all(result["sha256"] == SOURCE_SHA256 for result in results)
    assert sha256_file(paths[0]) == SOURCE_SHA256


def test_source_generation_requires_explicit_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "source.mcap"
    path.write_text("old")
    with pytest.raises(SourceGenerationError, match="exists"):
        generate_source(path)
    with pytest.raises(SourceGenerationError, match="replacement is prohibited"):
        generate_source(path, overwrite=True)
    assert path.read_text() == "old"


def test_source_generation_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("old")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(SourceGenerationError, match="symlink"):
        generate_source(link, overwrite=True)


@pytest.mark.parametrize("commit", ["", "abc", "A" * 40, "g" * 40, "1" * 39, "1" * 41])
def test_adapter_identity_rejects_invalid_commit(commit: str) -> None:
    with pytest.raises(AdapterIdentityError, match="40-hex"):
        verify_adapter_commit(commit)


def test_cli_generate_and_inspect(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.mcap"
    assert main(["generate-source", "--out", str(source)]) == 0
    generated = json.loads(capsys.readouterr().out)
    assert generated["sha256"] == SOURCE_SHA256
    assert main(["inspect", "--source", str(source)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["frame_count"] == 60
    assert inspected["clock"]["domain"] == "ROS_TIME"


def test_cli_inspect_rejects_whole_excluded_stream_deletion(tmp_path: Path, capsys) -> None:
    source = tmp_path / "deleted-outcome.mcap"
    source.write_bytes(build_source_bytes(include_outcome_stream=False))
    assert main(["inspect", "--source", str(source)]) == 2
    assert "SHA-256 or byte count differs from frozen source" in capsys.readouterr().err


def test_cli_failure_is_compact(tmp_path: Path, capsys) -> None:
    assert main(["inspect", "--source", str(tmp_path / "missing.mcap")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "expected a regular" in captured.err


def test_packaged_third_party_notice_retains_tf2_bsd_identity() -> None:
    notice = files("ros2_mcap_adapter").joinpath("THIRD_PARTY_NOTICES.md").read_text()
    assert "Copyright (c) 2008, Willow Garage, Inc." in notice
    assert "f6053126926a38ffad5e81588054d793d87fc662" in notice
    assert "d79557eefaf84816a7ce5f6201fa32fac60a69b5" in notice


def test_source_generation_rejects_candidate_mutation_at_publish(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "source.mcap"
    original = path_safety._rename_noreplace

    def mutate_then_rename(parent: int, source: str, target: str) -> None:
        directory = Path(f"/proc/self/fd/{parent}")
        (directory / source).write_bytes(b"HOSTILE")
        original(parent, source, target)

    monkeypatch.setattr(path_safety, "_rename_noreplace", mutate_then_rename)
    with pytest.raises(SourceGenerationError, match="published output differs"):
        generate_source(output)
    assert not output.exists()


def test_source_generation_noreplace_rejects_late_destination(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "source.mcap"
    original = path_safety._rename_noreplace

    def create_then_rename(parent: int, source: str, target: str) -> None:
        output.write_bytes(b"intruder")
        original(parent, source, target)

    monkeypatch.setattr(path_safety, "_rename_noreplace", create_then_rename)
    with pytest.raises(SourceGenerationError, match="output exists"):
        generate_source(output)
    assert output.read_bytes() == b"intruder"
