# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ros2_mcap_adapter.core as core
import ros2_mcap_adapter.finalize as finalizer
from ros2_mcap_adapter.canonical import pretty_json_bytes, sha256_bytes
from ros2_mcap_adapter.constants import DEFAULT_CONFIG, DEFAULT_LOCK
from ros2_mcap_adapter.decoder import decode_source_file, load_config
from ros2_mcap_adapter.finalize import FinalizationError, finalize_conversion_equivalence
from ros2_mcap_adapter.fixture import write_conversion
from ros2_mcap_adapter.generator import SourceGenerationError, generate_source
from ros2_mcap_adapter.path_safety import (
    PathSafetyError,
    publish_directory,
    reject_overlap,
    require_regular_file,
)


def _three_conversions(
    tmp_path: Path, source_path: Path, commits: list[str] | None = None
) -> list[Path]:
    source = decode_source_file(source_path)
    config = load_config(DEFAULT_CONFIG)
    roots = [tmp_path / f"run-{index}" for index in range(3)]
    commits = commits or ["1" * 40] * 3
    for root, adapter_commit in zip(roots, commits, strict=True):
        write_conversion(
            config=config,
            adapter_commit=adapter_commit,
            source=source,
            output_root=root,
            config_bytes=DEFAULT_CONFIG.read_bytes(),
            lock_bytes=DEFAULT_LOCK.read_bytes(),
        )
    return roots


@pytest.fixture(autouse=True)
def _permit_synthetic_commit_identity(monkeypatch) -> None:
    monkeypatch.setattr(finalizer, "verify_adapter_commit", lambda _commit: None)


def _recompute_variant_checksums(root: Path, variant: str) -> None:
    variant_root = root / variant
    files = {
        path.relative_to(variant_root).as_posix(): path.read_bytes()
        for path in variant_root.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    }
    (variant_root / "CHECKSUMS.sha256").write_bytes(
        "".join(f"{sha256_bytes(files[name])}  {name}\n" for name in sorted(files)).encode()
    )


def test_three_conversions_finalize_and_remain_contract_valid(
    tmp_path: Path, source_path: Path, monkeypatch
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    output = tmp_path / "final"
    result = finalize_conversion_equivalence(roots, output_root=output)
    assert result["equivalent"] is True
    assert result["run_ids"] == ["clean-conversion-1", "clean-conversion-2", "clean-conversion-3"]
    assert (output / "SHA256SUMS").is_file()
    repository_root = Path(__file__).parents[3]
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
            str(output / "incident"),
            str(output / "control"),
        ],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("relative", "mutation", "message"),
    [
        ("incident/session.jsonl", lambda data: data + b"\n", "not exact adapter-produced"),
        (
            "capability-record.json",
            lambda data: data.replace(
                b'"subject": "candidate_adapter"', b'"subject": "frozen_adapter"'
            ),
            "not exact adapter-produced",
        ),
        (
            "conversion-summary.json",
            lambda data: data.replace(b'"source_size": 28735', b'"source_size": 28736'),
            "not exact adapter-produced",
        ),
    ],
)
def test_finalizer_rejects_tampering(
    tmp_path: Path, source_path: Path, relative: str, mutation, message: str
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    path = roots[1] / relative
    path.write_bytes(mutation(path.read_bytes()))
    with pytest.raises(FinalizationError, match=message):
        finalize_conversion_equivalence(roots, output_root=tmp_path / "final")


def test_finalizer_rejects_three_identically_tampered_rights_records(
    tmp_path: Path, source_path: Path
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    for root in roots:
        path = root / "rights-record.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["tampered_identically"] = True
        path.write_bytes(pretty_json_bytes(value))
    with pytest.raises(FinalizationError, match="not exact adapter-produced"):
        finalize_conversion_equivalence(roots, output_root=tmp_path / "final")


def test_finalizer_rejects_three_identically_tampered_expected_outcomes_with_checksums(
    tmp_path: Path, source_path: Path
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    for root in roots:
        path = root / "incident" / "expected-outcome.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["event_count"] = 99
        path.write_bytes(pretty_json_bytes(value))
        _recompute_variant_checksums(root, "incident")
    with pytest.raises(FinalizationError, match="not exact adapter-produced"):
        finalize_conversion_equivalence(roots, output_root=tmp_path / "final")


def test_finalizer_rejects_invalid_adapter_commit_identity(
    tmp_path: Path, source_path: Path
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    path = roots[0] / "conversion-summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["adapter_commit"] = "not-a-commit"
    path.write_bytes(pretty_json_bytes(value))
    with pytest.raises(FinalizationError, match="one exact 40-hex"):
        finalize_conversion_equivalence(roots, output_root=tmp_path / "final")


def test_finalizer_requires_one_adapter_commit_across_roots(
    tmp_path: Path, source_path: Path
) -> None:
    roots = _three_conversions(
        tmp_path,
        source_path,
        commits=["1" * 40, "1" * 40, "2" * 40],
    )
    with pytest.raises(FinalizationError, match="do not share one adapter commit"):
        finalize_conversion_equivalence(roots, output_root=tmp_path / "final")


@pytest.mark.parametrize("target_label", ["frozen config", "adapter lock"])
def test_finalizer_rejects_default_config_or_lock_swap_and_restore(
    tmp_path: Path,
    source_path: Path,
    monkeypatch,
    target_label: str,
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    original_verify = finalizer.verify_file_snapshot_current

    def swap_restore(snapshot, *, label: str) -> None:
        if label == target_label:
            original = snapshot.path.read_bytes()
            snapshot.path.write_bytes(b"hostile temporary bytes")
            snapshot.path.write_bytes(original)
        original_verify(snapshot, label=label)

    monkeypatch.setattr(finalizer, "verify_file_snapshot_current", swap_restore)
    with pytest.raises(FinalizationError, match="changed after its authenticated snapshot"):
        finalize_conversion_equivalence(roots, output_root=tmp_path / "final")


def test_finalizer_candidate_uses_validated_inventory_not_reread_root(
    tmp_path: Path,
    source_path: Path,
    monkeypatch,
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    original_rights = (roots[0] / "rights-record.json").read_bytes()
    original_write = finalizer._write_inventory_bytes

    def mutate_root_then_write(candidate: Path, files: dict[str, bytes]) -> None:
        (roots[0] / "rights-record.json").write_bytes(b"hostile post-validation replacement")
        original_write(candidate, files)

    monkeypatch.setattr(finalizer, "_write_inventory_bytes", mutate_root_then_write)
    output = tmp_path / "final"
    finalize_conversion_equivalence(roots, output_root=output)
    assert (output / "rights-record.json").read_bytes() == original_rights


@pytest.mark.parametrize(
    "run_ids",
    [
        ["same", "same", "third"],
        ["ok", "../escape", "third"],
        ["ok", "/absolute", "third"],
        ["ok", "UPPER", "third"],
    ],
)
def test_finalizer_rejects_unsafe_run_ids(
    tmp_path: Path, source_path: Path, run_ids: list[str]
) -> None:
    roots = _three_conversions(tmp_path, source_path)
    with pytest.raises(FinalizationError, match="run ID"):
        finalize_conversion_equivalence(roots, output_root=tmp_path / "final", run_ids=run_ids)


def test_finalizer_requires_exactly_three_distinct_roots(tmp_path: Path, source_path: Path) -> None:
    roots = _three_conversions(tmp_path, source_path)
    with pytest.raises(FinalizationError, match="exactly three"):
        finalize_conversion_equivalence(roots[:2], output_root=tmp_path / "final")
    with pytest.raises(FinalizationError, match="distinct"):
        finalize_conversion_equivalence(
            [roots[0], roots[0], roots[2]], output_root=tmp_path / "final"
        )


def test_source_mutation_never_replaces_existing_output(
    tmp_path: Path, source_path: Path, config_path: Path, monkeypatch
) -> None:
    source_copy = tmp_path / "source.mcap"
    source_copy.write_bytes(source_path.read_bytes())
    output = tmp_path / "output"
    output.mkdir()
    (output / "preserve.txt").write_text("old")
    monkeypatch.setattr(core, "verify_adapter_commit", lambda _commit: None)
    monkeypatch.setattr(
        core, "_SOURCE_MUTATION_TEST_HOOK", lambda path: path.write_bytes(path.read_bytes() + b"x")
    )
    with pytest.raises(core.AdapterError, match="source mutation"):
        core.convert(
            source_copy,
            config_path=config_path,
            output_root=output,
            adapter_commit="1" * 40,
            overwrite=True,
        )
    assert (output / "preserve.txt").read_text() == "old"


@pytest.mark.parametrize("label", ["frozen config", "adapter lock"])
def test_conversion_rejects_config_or_lock_swap_and_restore(
    tmp_path: Path,
    source_path: Path,
    config_path: Path,
    monkeypatch,
    label: str,
) -> None:
    monkeypatch.setattr(core, "verify_adapter_commit", lambda _commit: None)
    original_verify = core.verify_file_snapshot_current

    def swap_restore(snapshot, *, label: str) -> None:
        if label == target_label:
            original = snapshot.path.read_bytes()
            snapshot.path.write_bytes(b"hostile temporary bytes")
            snapshot.path.write_bytes(original)
        original_verify(snapshot, label=label)

    target_label = "config mutation" if label == "frozen config" else "adapter lock mutation"
    monkeypatch.setattr(core, "verify_file_snapshot_current", swap_restore)
    with pytest.raises(core.AdapterError, match="changed after its authenticated snapshot"):
        core.convert(
            source_path,
            config_path=config_path,
            output_root=tmp_path / "output",
            adapter_commit="1" * 40,
        )


def test_conversion_embeds_authenticated_config_and_lock_bytes(
    tmp_path: Path, source_path: Path, config_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(core, "verify_adapter_commit", lambda _commit: None)
    output = tmp_path / "output"
    core.convert(
        source_path,
        config_path=config_path,
        output_root=output,
        adapter_commit="1" * 40,
    )
    for variant in ("incident", "control"):
        assert (
            output / variant / "source/frozen-config.json"
        ).read_bytes() == config_path.read_bytes()
        assert (output / variant / "source/uv.lock").read_bytes() == DEFAULT_LOCK.read_bytes()


def test_generator_rejects_symlinked_parent_component(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(SourceGenerationError, match="symlink components"):
        generate_source(linked_parent / "source.mcap")


def test_publish_overwrite_preserves_old_tree_if_candidate_rename_fails(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "output"
    candidate = tmp_path / "candidate"
    output.mkdir()
    candidate.mkdir()
    (output / "old").write_text("old")
    (candidate / "new").write_text("new")
    original = Path.replace

    def fail_candidate(self: Path, target: Path):
        if self == candidate and target == output:
            raise OSError("injected rename failure")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", fail_candidate)
    with pytest.raises(OSError, match="injected"):
        publish_directory(candidate, output, overwrite=True)
    assert (output / "old").read_text() == "old"


def test_publish_rejects_existing_without_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "output"
    candidate = tmp_path / "candidate"
    output.mkdir()
    candidate.mkdir()
    with pytest.raises(PathSafetyError, match="overwrite"):
        publish_directory(candidate, output, overwrite=False)


def test_symlink_source_and_overlap_rejected(tmp_path: Path, source_path: Path) -> None:
    link = tmp_path / "source-link"
    link.symlink_to(source_path)
    with pytest.raises(PathSafetyError, match="symlink"):
        require_regular_file(link, label="source")
    source = source_path.resolve()
    with pytest.raises(PathSafetyError, match="overlap"):
        reject_overlap(source, source.parent)


def test_conversion_rejects_output_overlap(
    source_path: Path, config_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(core, "verify_adapter_commit", lambda _commit: None)
    with pytest.raises(core.AdapterError, match="overlap"):
        core.convert(
            source_path,
            config_path=config_path,
            output_root=source_path.parent,
            adapter_commit="1" * 40,
        )
