# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import massrobotics_amr_adapter.finalize as finalizer
from massrobotics_amr_adapter.constants import DEFAULT_CONFIG, DEFAULT_SOURCE_ROOT
from massrobotics_amr_adapter.core import convert
from massrobotics_amr_adapter.finalize import (
    FinalizationError,
    finalize_conversion_equivalence,
)


def _six_conversions(
    tmp_path: Path,
    *,
    commits: list[str] | None = None,
) -> tuple[list[Path], list[str]]:
    roots: list[Path] = []
    run_ids: list[str] = []
    commits = commits or ["a" * 40] * 6
    position = 0
    for variant in ("incident", "control"):
        for index in range(1, 4):
            root = tmp_path / f"{variant}-{index}"
            convert(
                DEFAULT_SOURCE_ROOT / variant,
                config_path=DEFAULT_CONFIG,
                output_root=root,
                adapter_commit=commits[position],
            )
            position += 1
            roots.append(root)
            run_ids.append(f"{variant}-clean-{index}")
    return roots, run_ids


def _rewrite_root_checksums(root: Path) -> None:
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    (root / "SHA256SUMS").write_text(
        "".join(f"{hashlib.sha256(files[path]).hexdigest()}  {path}\n" for path in sorted(files)),
        encoding="ascii",
    )


def test_finalizer_requires_exactly_six_distinct_roots(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    with pytest.raises(FinalizationError, match="exactly six roots"):
        finalize_conversion_equivalence(
            roots[:5],
            output_root=tmp_path / "too-few",
            run_ids=run_ids[:5],
        )
    with pytest.raises(FinalizationError, match="must be distinct"):
        finalize_conversion_equivalence(
            [*roots[:5], roots[0]],
            output_root=tmp_path / "duplicate",
            run_ids=run_ids,
        )


def test_finalizer_requires_exactly_three_conversions_per_variant(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    replacement = tmp_path / "incident-fourth"
    convert(
        DEFAULT_SOURCE_ROOT / "incident",
        config_path=DEFAULT_CONFIG,
        output_root=replacement,
        adapter_commit="a" * 40,
    )
    with pytest.raises(FinalizationError, match="three conversions per variant"):
        finalize_conversion_equivalence(
            [*roots[:4], replacement, roots[5]],
            output_root=tmp_path / "wrong-mix",
            run_ids=run_ids,
        )


@pytest.mark.parametrize(
    "run_ids",
    [
        ["same", "same", "three", "four", "five", "six"],
        ["one", "../escape", "three", "four", "five", "six"],
        ["one", "/absolute", "three", "four", "five", "six"],
        ["one", "UPPER", "three", "four", "five", "six"],
    ],
)
def test_finalizer_rejects_duplicate_or_unsafe_run_ids(tmp_path: Path, run_ids: list[str]) -> None:
    roots, _ = _six_conversions(tmp_path)
    with pytest.raises(FinalizationError, match="run ID"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_requires_one_adapter_commit(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(
        tmp_path,
        commits=["a" * 40] * 5 + ["b" * 40],
    )
    with pytest.raises(FinalizationError, match="share one adapter commit"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_rejects_single_run_tampering(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    with (roots[1] / "fixture" / "session.jsonl").open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(FinalizationError, match="checksum mismatch"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_rejects_extra_conversion_artifact(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    (roots[0] / "unexpected-upstream-copy.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(FinalizationError, match="conversion inventory differs"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_rejects_identical_inventoried_extras_in_all_runs(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    for root in roots:
        (root / "unexpected-upstream-copy.json").write_text("{}\n", encoding="utf-8")
        _rewrite_root_checksums(root)
    with pytest.raises(FinalizationError, match="unexpected-upstream-copy"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_reconstructs_and_rejects_identical_rights_tampering(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    for root in roots:
        (root / "rights-record.json").write_text(
            '{"claim_classification":"external validation"}\n', encoding="utf-8"
        )
        _rewrite_root_checksums(root)
    with pytest.raises(FinalizationError, match="exact frozen adapter output"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_rejects_reference_only_upstream_byte_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    sentinel_digest = hashlib.sha256((roots[0] / "rights-record.json").read_bytes()).hexdigest()
    monkeypatch.setattr(finalizer, "UPSTREAM_RAW_SHA256", {"sentinel": sentinel_digest})
    with pytest.raises(FinalizationError, match="reference-only upstream bytes"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_enforces_final_machine_path_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    monkeypatch.setattr(finalizer, "find_path_leaks", lambda *args, **kwargs: ["sentinel"])
    with pytest.raises(FinalizationError, match="machine-local paths"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final",
            run_ids=run_ids,
        )


def test_finalizer_refuses_collision_even_with_overwrite(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    output = tmp_path / "final"
    output.mkdir()
    sentinel = output / "preserve.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    for overwrite in (False, True):
        with pytest.raises(FinalizationError, match="output collision"):
            finalize_conversion_equivalence(
                roots,
                output_root=output,
                run_ids=run_ids,
                overwrite=overwrite,
            )
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_finalizer_rejects_source_output_overlap(tmp_path: Path) -> None:
    roots, run_ids = _six_conversions(tmp_path)
    with pytest.raises(FinalizationError, match="overlap"):
        finalize_conversion_equivalence(
            roots,
            output_root=roots[0] / "final",
            run_ids=run_ids,
        )
