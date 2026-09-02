# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
import copy
import fcntl
import json
import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools import discover_public_surface as scanner


ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def staged_snapshot() -> scanner.StagedSnapshot:
    return scanner.StagedSnapshot.capture(ROOT)


@pytest.fixture(scope="module")
def production_discovery(staged_snapshot: scanner.StagedSnapshot) -> scanner.Discovery:
    return scanner.discover(staged_snapshot)


@pytest.fixture(scope="module")
def production_candidates(
    staged_snapshot: scanner.StagedSnapshot,
) -> tuple[dict[str, Any], dict[str, Any], bytes, scanner.Discovery]:
    return scanner.build_candidates(staged_snapshot)


def _run_git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    return completed.stdout


def _git_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _run_git(root, "init", "--quiet")
    return root


def _transaction_fixture(tmp_path: Path) -> tuple[Path, dict[str, bytes], dict[str, bytes]]:
    root = tmp_path / "transaction-repository"
    status = root / "docs" / "status"
    status.mkdir(parents=True)
    old = {
        scanner.INVENTORY_PATH: b'{"old":"inventory"}',
        scanner.PROFILES_PATH: b'{"old":"profiles"}',
        scanner.REPORT_PATH: b"old report\n",
    }
    candidate = {
        scanner.INVENTORY_PATH: b'{"new":"inventory"}',
        scanner.PROFILES_PATH: b'{"new":"profiles"}',
        scanner.REPORT_PATH: b"new report\n",
    }
    for relative, payload in old.items():
        path = root / relative
        path.write_bytes(payload)
        path.chmod(0o640)
    return root, old, candidate


def _assert_payloads(root: Path, expected: dict[str, bytes]) -> None:
    assert {relative: (root / relative).read_bytes() for relative in expected} == expected


def _runtime_source_snapshot() -> tuple[scanner.StagedSnapshot, ModuleType]:
    kernel = scanner._load_provenance_kernel()
    kernel_file = Path(str(kernel.__file__))
    entries = []
    for relative, path in (
        (scanner.SCANNER_PATH, Path(scanner.__file__)),
        (scanner.PROVENANCE_PATH, kernel_file),
    ):
        data = path.read_bytes()
        entries.append(
            scanner.StageEntry(
                path=relative,
                mode="100644",
                oid=scanner._git_blob_oid(data),
                data=data,
            )
        )
    return scanner.StagedSnapshot(ROOT, entries), kernel


def _filesystem_projection(root: Path) -> list[tuple[str, str, int, bytes | str]]:
    result: list[tuple[str, str, int, bytes | str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            result.append((relative, "symlink", mode, os.readlink(path)))
        elif stat.S_ISDIR(info.st_mode):
            result.append((relative, "directory", mode, b""))
        else:
            result.append((relative, "file", mode, path.read_bytes()))
    return result


def test_stage_zero_snapshot_ignores_unstaged_worktree_bytes(tmp_path: Path) -> None:
    root = _git_fixture(tmp_path)
    source = root / "source.py"
    source.write_bytes(b"staged = True\n")
    _run_git(root, "add", "source.py")
    staged_oid = _run_git(root, "rev-parse", ":source.py").decode("ascii").strip()
    source.write_bytes(b"worktree = True\n")

    snapshot = scanner.StagedSnapshot.capture(root)
    entry = snapshot.parser_entry("source.py")

    assert entry.data == b"staged = True\n"
    assert entry.oid == staged_oid
    assert entry.mode == "100644"
    assert source.read_bytes() == b"worktree = True\n"


def test_exact_symlink_index_representation_and_negative_identities(tmp_path: Path) -> None:
    root = _git_fixture(tmp_path)
    target = root / "target.txt"
    target.write_bytes(b"dereferenced target bytes\n")
    link = root / "mapping.yaml"
    link.symlink_to("target.txt")
    _run_git(root, "add", "mapping.yaml", "target.txt")
    snapshot = scanner.StagedSnapshot.capture(root)
    entry = snapshot.parser_entry("mapping.yaml")

    assert entry.mode == "120000"
    assert entry.data == b"target.txt"
    scanner.validate_index_identity(
        entry,
        mode="120000",
        oid=scanner._git_blob_oid(b"target.txt"),
        data=b"target.txt",
    )
    with pytest.raises(scanner.DiscoveryError, match="mode mismatch"):
        scanner.validate_index_identity(
            entry,
            mode="100644",
            oid=entry.oid,
            data=entry.data,
        )
    with pytest.raises(scanner.DiscoveryError, match="blob identity mismatch"):
        scanner.validate_index_identity(
            entry,
            mode="120000",
            oid=scanner._git_blob_oid(b"other-target.txt"),
            data=b"other-target.txt",
        )
    with pytest.raises(scanner.DiscoveryError, match="blob bytes mismatch"):
        scanner.validate_index_identity(
            entry,
            mode="120000",
            oid=entry.oid,
            data=target.read_bytes(),
        )


def test_executing_scanner_and_kernel_must_equal_exact_staged_blobs() -> None:
    snapshot, kernel = _runtime_source_snapshot()
    scanner._assert_executing_sources_match_snapshot(snapshot, kernel)

    for relative in (scanner.SCANNER_PATH, scanner.PROVENANCE_PATH):
        changed = [
            replace(
                entry,
                oid=scanner._git_blob_oid(entry.data + b"\n# staged difference\n"),
                data=entry.data + b"\n# staged difference\n",
            )
            if entry.path == relative
            else entry
            for entry in snapshot.entries
        ]
        mismatched = scanner.StagedSnapshot(ROOT, changed)
        with pytest.raises(scanner.DiscoveryError, match="bytes differ from the exact stage-0"):
            scanner._assert_executing_sources_match_snapshot(mismatched, kernel)


def test_production_census_is_exact_and_family_closed(
    production_discovery: scanner.Discovery,
) -> None:
    assert dict(production_discovery.family_counts) == scanner.EXPECTED_FAMILY_COUNTS
    assert len(production_discovery.rows) == 10_091
    assert sum(production_discovery.family_counts.values()) == 10_091
    assert production_discovery.family_counts["public_api"] == 2_293
    assert production_discovery.family_counts["manifest_keys"] == 3_580
    assert production_discovery.family_counts["resources"] == 1_556


def test_two_discovery_runs_are_byte_deterministic(
    staged_snapshot: scanner.StagedSnapshot,
    production_discovery: scanner.Discovery,
) -> None:
    repeated = scanner.discover(staged_snapshot)

    assert scanner._canonical_bytes(list(repeated.rows)) == scanner._canonical_bytes(
        list(production_discovery.rows)
    )
    assert dict(repeated.family_digests) == dict(production_discovery.family_digests)


def test_all_rows_use_exact_staged_blob_locators_and_modes(
    staged_snapshot: scanner.StagedSnapshot,
    production_discovery: scanner.Discovery,
) -> None:
    for row in production_discovery.rows:
        source = row["source"]
        entry = staged_snapshot.parser_entry(source["path"])
        prefix, separator, _semantic = source["locator"].partition(";")
        assert separator == ";"
        assert prefix == f"git-blob:{entry.oid}"
        assert source["digest_sha256"] == entry.sha256
        assert entry.mode in {"100644", "100755", "120000"}

    symlinks = {entry.path: entry for entry in staged_snapshot.entries if entry.mode == "120000"}
    assert set(symlinks) == {
        "calib/board_110x40",
        "calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping.yaml",
        "calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping.yaml",
    }
    for entry in symlinks.values():
        assert scanner._git_blob_oid(entry.data) == entry.oid
        matching = [row for row in production_discovery.rows if row["source"]["path"] == entry.path]
        assert matching
        assert all(
            row["source"]["locator"].startswith(f"git-blob:{entry.oid};") for row in matching
        )


def test_manifest_projection_is_exactly_json_csv_models_and_hook(
    production_discovery: scanner.Discovery,
) -> None:
    manifest = [
        item for item in production_discovery.observations if item.family == "manifest_keys"
    ]
    counts = {
        "json": sum(item.key.startswith("json:") for item in manifest),
        "csv": sum(item.key.startswith("csv:") for item in manifest),
        "model": sum(item.key.startswith("model:") for item in manifest),
        "hook": sum(not item.key.startswith(("json:", "csv:", "model:")) for item in manifest),
    }

    assert counts == {"json": 2450, "csv": 9, "model": 34, "hook": 1087}


def test_public_api_fixture_excludes_imports_and_methods_but_keeps_data() -> None:
    source = """
from external import dependency

__version__ = "1"
__all__ = ["Public", "__version__"]
CONSTANT = 1

def function():
    return None

class Public:
    field: int
    assigned = 1
    def method(self):
        return None
"""
    module = scanner.PythonModule("package/api.py", "package.api", ast.parse(source))

    names = {item.name for item in scanner._public_api_observations((module,))}

    assert names == {
        "package.api.CONSTANT",
        "package.api.Public",
        "package.api.Public.assigned",
        "package.api.Public.field",
        "package.api.__version__",
        "package.api.function",
    }


def test_model_fixture_tracks_pydantic_lineage_and_dataclass_fields() -> None:
    source = """
from dataclasses import dataclass
from typing import Protocol
from pydantic import BaseModel

class Root(BaseModel):
    root: int

class Child(Root):
    child: int

@dataclass
class Data:
    data: int

@dataclass
class DataImplementation(Data):
    implementation: int

class Surface(Protocol):
    name: str
"""
    module = scanner.PythonModule("package/models.py", "package.models", ast.parse(source))

    models, fields = scanner._model_observations((module,))

    assert {item.name for item in models} == {
        "package.models.Child",
        "package.models.Data",
        "package.models.Root",
    }
    assert {item.name for item in fields} == {
        "package.models.Child.child",
        "package.models.Data.data",
        "package.models.DataImplementation.implementation",
        "package.models.Root.root",
    }


def test_strict_json_parser_rejects_duplicates_and_nonfinite_values() -> None:
    with pytest.raises(scanner.DiscoveryError, match="duplicate JSON key"):
        scanner._parse_json(b'{"value":1,"value":2}', label="duplicate.json")
    with pytest.raises(scanner.DiscoveryError, match="non-finite JSON"):
        scanner._parse_json(b'{"value":NaN}', label="nonfinite.json")


def test_workflow_parser_rejects_duplicate_job_keys() -> None:
    document = (
        b"name: duplicate\njobs:\n  build:\n    runs-on: ubuntu\n  build:\n    runs-on: macos\n"
    )

    with pytest.raises(scanner.DiscoveryError, match="duplicate YAML key"):
        scanner._workflow_document(document, path=".github/workflows/duplicate.yml")


def test_config_selector_is_narrow_and_keeps_symlink_config_semantics() -> None:
    assert scanner._is_config_path("pyproject.toml")
    assert scanner._is_config_path("calib/profile/mapping.yaml")
    assert not scanner._is_config_path(".github/workflows/ci.yml")
    assert not scanner._is_config_path(".github/ISSUE_TEMPLATE/bug_report.yml")
    assert not scanner._is_config_path("evidence/result.yaml")
    assert not scanner._is_config_path("proofs/result.yaml")
    assert not scanner._is_config_path("config.json")


def test_committed_inventory_matches_current_public_surface(
    production_candidates: tuple[dict[str, Any], dict[str, Any], bytes, scanner.Discovery],
) -> None:
    inventory, profiles, report, _discovery = production_candidates

    assert scanner._document_bytes(inventory) == (ROOT / scanner.INVENTORY_PATH).read_bytes()
    assert scanner._document_bytes(profiles) == (ROOT / scanner.PROFILES_PATH).read_bytes()
    assert report == (ROOT / scanner.REPORT_PATH).read_bytes()


def test_check_mode_is_no_write_when_current(
    production_candidates: tuple[dict[str, Any], dict[str, Any], bytes, scanner.Discovery],
) -> None:
    del production_candidates
    targets = [ROOT / relative for relative in sorted(scanner.GENERATED_PATHS)]
    before = [(path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in targets]

    assert scanner.run("check", repository_root=ROOT) == 0

    after = [(path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in targets]
    assert after == before
    assert not (ROOT / scanner.TRANSACTION_DIRECTORY).exists()


def test_direct_script_loads_sibling_kernel_without_pythonpath() -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            "tools/discover_public_surface.py",
            "check",
            "--repository-root",
            ".",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["rows"] == 10_091
    assert summary["public_api"] == 2_293
    assert summary["manifest_keys"] == 3_580


def test_three_file_transaction_rolls_back_after_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, old, candidate = _transaction_fixture(tmp_path)
    real_replace = os.replace
    injected = False

    def fail_one_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        nonlocal injected
        destination_path = Path(destination)
        if not injected and destination_path == root / scanner.PROFILES_PATH:
            injected = True
            raise OSError("injected target replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_one_replace)
    with pytest.raises(OSError, match="injected target replace failure"):
        scanner._replace_three(root, candidate)

    assert injected
    _assert_payloads(root, old)
    assert not (root / scanner.TRANSACTION_DIRECTORY).exists()


def test_prepared_crash_recovers_old_three_file_generation(tmp_path: Path) -> None:
    root, old, candidate = _transaction_fixture(tmp_path)
    records = [
        scanner._journal_record(relative, old[relative], 0o640, candidate[relative])
        for relative in sorted(scanner.GENERATED_PATHS)
    ]
    journal = {
        "phase": "PREPARED",
        "schema_version": scanner.TRANSACTION_SCHEMA,
        "targets": records,
    }
    directory = root / scanner.TRANSACTION_DIRECTORY
    scanner._write_journal(directory, journal)
    scanner._apply_journal(root, journal, candidate=True)
    _assert_payloads(root, candidate)

    scanner._recover_transaction(root)

    _assert_payloads(root, old)
    assert not directory.exists()


def test_committed_crash_recovers_candidate_three_file_generation(tmp_path: Path) -> None:
    root, old, candidate = _transaction_fixture(tmp_path)
    records = [
        scanner._journal_record(relative, old[relative], 0o640, candidate[relative])
        for relative in sorted(scanner.GENERATED_PATHS)
    ]
    journal = {
        "phase": "COMMITTED",
        "schema_version": scanner.TRANSACTION_SCHEMA,
        "targets": records,
    }
    directory = root / scanner.TRANSACTION_DIRECTORY
    scanner._write_journal(directory, journal)
    (root / scanner.INVENTORY_PATH).write_bytes(b"partially replaced")

    scanner._recover_transaction(root)

    _assert_payloads(root, candidate)
    assert not directory.exists()


def test_repository_root_lock_is_exclusive_and_bounded(tmp_path: Path) -> None:
    root = tmp_path / "locked-repository"
    root.mkdir()
    descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(scanner.DiscoveryError, match="timed out"):
            with scanner._root_lock(root, timeout=0.0):
                pytest.fail("exclusive root lock was acquired twice")
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@pytest.mark.parametrize("relative", sorted(scanner.GENERATED_PATHS))
def test_target_comparison_rejects_symlinks_without_reading_through(
    tmp_path: Path,
    relative: str,
) -> None:
    root, _old, _candidate = _transaction_fixture(tmp_path)
    outside = tmp_path / "outside-target"
    outside.write_bytes(b"outside bytes must not become target authority")
    target = root / relative
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(scanner.DiscoveryError, match="regular non-symlink"):
        scanner._current_target_bytes(root, relative)


def test_check_mode_refuses_pending_recovery_without_writing(tmp_path: Path) -> None:
    root, old, candidate = _transaction_fixture(tmp_path)
    records = [
        scanner._journal_record(relative, old[relative], 0o640, candidate[relative])
        for relative in sorted(scanner.GENERATED_PATHS)
    ]
    journal = {
        "phase": "PREPARED",
        "schema_version": scanner.TRANSACTION_SCHEMA,
        "targets": records,
    }
    scanner._write_journal(root / scanner.TRANSACTION_DIRECTORY, journal)
    before = _filesystem_projection(root)

    with pytest.raises(scanner.DiscoveryError, match="check mode refuses"):
        scanner.run("check", repository_root=root, lock_timeout=0.0)

    assert _filesystem_projection(root) == before


def test_candidate_merge_preserves_every_foreign_row_and_profile(
    staged_snapshot: scanner.StagedSnapshot,
    production_candidates: tuple[dict[str, Any], dict[str, Any], bytes, scanner.Discovery],
) -> None:
    inventory, profiles, _report, discovery = production_candidates
    original_inventory = scanner._parse_json(
        staged_snapshot.parser_entry(scanner.INVENTORY_PATH).data,
        label=scanner.INVENTORY_PATH,
    )
    original_profiles = scanner._parse_json(
        staged_snapshot.parser_entry(scanner.PROFILES_PATH).data,
        label=scanner.PROFILES_PATH,
    )
    foreign_rows = [
        row for row in original_inventory["rows"] if row.get("owner") != scanner.TASK_ID
    ]
    foreign_profiles = [
        profile
        for profile in original_profiles["profiles"]
        if profile.get("owner") != scanner.TASK_ID
    ]

    assert [row for row in inventory["rows"] if row.get("owner") != scanner.TASK_ID] == foreign_rows
    assert [
        profile for profile in profiles["profiles"] if profile.get("owner") != scanner.TASK_ID
    ] == foreign_profiles
    assert len([row for row in inventory["rows"] if row.get("owner") == scanner.TASK_ID]) == len(
        discovery.rows
    )
    profile = next(
        profile for profile in profiles["profiles"] if profile["id"] == scanner.PROFILE_ID
    )
    assert profile["support_disposition"] == "not_measured"
    assert profile["claim"]["classification"] == "observed_not_supported"


def test_malformed_transaction_journal_fails_closed(tmp_path: Path) -> None:
    root, _old, _candidate = _transaction_fixture(tmp_path)
    directory = root / scanner.TRANSACTION_DIRECTORY
    directory.mkdir()
    (directory / "journal.json").write_text(
        '{"schema_version":"wrong","phase":"PREPARED","targets":[]}',
        encoding="utf-8",
    )

    with pytest.raises(scanner.DiscoveryError, match="schema version"):
        scanner._recover_transaction(root)


def test_report_binds_materialization_and_denies_runtime_claim(
    production_candidates: tuple[dict[str, Any], dict[str, Any], bytes, scanner.Discovery],
) -> None:
    _inventory, _profiles, report, _discovery = production_candidates
    text = report.decode("utf-8")

    assert "Task: `MP2-013` / `MET-78`" in text
    assert "Owned rows: `10091`" in text
    assert "Materialization SHA-256" in text
    assert "no runtime, compatibility, or support claim" in text
    assert "| `manifest_keys` | `artifact_manifest_key` | 3580 |" in text


def test_stable_ids_are_bounded_hashed_and_independent_of_input_order(
    production_discovery: scanner.Discovery,
) -> None:
    identifiers = [row["id"] for row in production_discovery.rows]
    reversed_rows = [
        scanner._row(
            scanner.StagedSnapshot.capture(ROOT),
            observation,
        )
        for observation in reversed(production_discovery.observations[:20])
    ]

    assert identifiers == sorted(set(identifiers))
    assert all(identifier.startswith(scanner.ROW_PREFIX) for identifier in identifiers)
    assert all(len(identifier.rsplit(".", 1)[-1]) == 12 for identifier in identifiers)
    assert {row["id"] for row in reversed_rows} == {
        scanner._row_id(item.family, item.key) for item in production_discovery.observations[:20]
    }


def test_generate_preserves_foreign_objects_in_memory(
    production_candidates: tuple[dict[str, Any], dict[str, Any], bytes, scanner.Discovery],
) -> None:
    inventory, profiles, report, discovery = production_candidates
    first = (
        scanner._document_bytes(copy.deepcopy(inventory)),
        scanner._document_bytes(copy.deepcopy(profiles)),
        bytes(report),
        scanner._canonical_bytes(list(discovery.rows)),
    )
    second = (
        scanner._document_bytes(inventory),
        scanner._document_bytes(profiles),
        report,
        scanner._canonical_bytes(list(discovery.rows)),
    )

    assert first == second
