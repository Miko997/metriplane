# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from metriplane import publication
from metriplane.publication import (
    MANIFEST_NAME,
    PublicationCrash,
    PublicationError,
    PublicationTarget,
    publication_namespace,
    publish_transaction,
    recover_publication,
)


def _stage_directory(parent: Path, name: str, value: str) -> Path:
    stage = parent / name
    stage.mkdir()
    (stage / "nested").mkdir()
    (stage / "nested" / "payload.txt").write_text(value, encoding="utf-8")
    return stage


def _value(path: Path) -> str:
    return (path / "nested" / "payload.txt").read_text(encoding="utf-8")


def _namespace(*destinations: Path) -> str:
    return publication_namespace(list(destinations))


def _namespace_root(parent: Path, namespace: str) -> Path:
    return parent / publication._STORE_NAME / "namespaces" / namespace


def _crash_at(selected: str):
    def failpoint(name: str) -> None:
        if name == selected:
            raise PublicationCrash(selected)

    return failpoint


def test_content_addressed_generation_manifest_pointer_and_opaque_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _stage_directory(tmp_path, "stage", "new")
    destination = tmp_path / "published"
    events: list[str] = []
    real_copy_regular = publication._copy_verified_regular
    real_write_new = publication._write_new

    def observed_copy_regular(source, target, expected, *, destination_mode):
        if Path(target).name.endswith(".blob"):
            events.append(f"blob:{Path(target).name}")
        return real_copy_regular(
            source,
            target,
            expected,
            destination_mode=destination_mode,
        )

    def observed_write_new(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        events.append(f"record:{path.name}")
        real_write_new(path, data, mode=mode)

    monkeypatch.setattr(publication, "_copy_verified_regular", observed_copy_regular)
    monkeypatch.setattr(publication, "_write_new", observed_write_new)

    result = publish_transaction([PublicationTarget(stage, destination)], overwrite=False)

    assert _value(destination) == "new"
    assert _value(stage) == "new"
    root = _namespace_root(tmp_path, result.namespace)
    generation = root / "generations" / result.generation_id
    manifest_path = generation / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pointer = json.loads(result.pointer_path.read_text(encoding="utf-8"))
    assert manifest["generation_id"] == result.generation_id
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result.manifest_sha256
    assert pointer == {
        "destinations": ["published"],
        "generation_id": result.generation_id,
        "manifest_sha256": result.manifest_sha256,
        "publication_id": result.namespace,
        "schema_version": "metriplane.publication.v1",
    }
    assert events.index("blob:00000000.blob") < events.index(f"record:{MANIFEST_NAME}")
    assert not list(generation.rglob("payload.txt"))
    blob = generation / "payload" / "0" / "00000000.blob"
    assert blob.read_text(encoding="utf-8") == "new"
    assert blob.stat().st_mode & 0o777 == 0o400
    assert recover_publication(tmp_path, result.namespace) == result


def test_identical_generation_is_reused_deterministically(tmp_path: Path) -> None:
    destination = tmp_path / "published"
    first = publish_transaction(
        [PublicationTarget(_stage_directory(tmp_path, "stage-a", "same"), destination)],
        overwrite=False,
    )
    second = publish_transaction(
        [PublicationTarget(_stage_directory(tmp_path, "stage-b", "same"), destination)],
        overwrite=True,
    )

    assert first.generation_id == second.generation_id
    generations = _namespace_root(tmp_path, first.namespace) / "generations"
    assert [path.name for path in generations.iterdir()] == [first.generation_id]
    assert _value(destination) == "same"


def test_no_overwrite_refuses_existing_destination(tmp_path: Path) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")

    with pytest.raises(PublicationError, match="without overwrite"):
        publish_transaction([PublicationTarget(stage, destination)], overwrite=False)

    assert _value(destination) == "old"
    assert _value(stage) == "new"


@pytest.mark.parametrize(
    ("failpoint", "committed"),
    [
        ("generation_committed", False),
        ("journal_committed", False),
        ("backup_0", False),
        ("publish_0", False),
        ("pointer_committed", True),
    ],
)
def test_single_target_failpoints_recover_exact_state(
    tmp_path: Path,
    failpoint: str,
    committed: bool,
) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)

    with pytest.raises(PublicationCrash, match=failpoint):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            failpoint=_crash_at(failpoint),
        )

    recovered = recover_publication(tmp_path, namespace)
    assert _value(destination) == ("new" if committed else "old")
    assert recovered is not None if committed else recovered is None
    assert not (_namespace_root(tmp_path, namespace) / "transactions" / "active.json").exists()


@pytest.mark.parametrize(
    ("failpoint", "committed"),
    [
        ("backup_0", False),
        ("backup_1", False),
        ("publish_0", False),
        ("publish_1", False),
        ("pointer_committed", True),
    ],
)
def test_multi_target_failpoints_are_all_or_nothing(
    tmp_path: Path,
    failpoint: str,
    committed: bool,
) -> None:
    first = _stage_directory(tmp_path, "first", "old-a")
    second = tmp_path / "second.txt"
    second.write_text("old-b", encoding="utf-8")
    stage_first = _stage_directory(tmp_path, "stage-first", "new-a")
    stage_second = tmp_path / "stage-second.txt"
    stage_second.write_text("new-b", encoding="utf-8")
    namespace = _namespace(first, second)

    with pytest.raises(PublicationCrash, match=failpoint):
        publish_transaction(
            [
                PublicationTarget(stage_first, first),
                PublicationTarget(stage_second, second),
            ],
            overwrite=True,
            failpoint=_crash_at(failpoint),
        )

    recovered = recover_publication(tmp_path, namespace)
    assert _value(first) == ("new-a" if committed else "old-a")
    assert second.read_text(encoding="utf-8") == ("new-b" if committed else "old-b")
    assert recovered is not None if committed else recovered is None


def test_changed_destination_blocks_recovery_without_losing_backup(tmp_path: Path) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)
    with pytest.raises(PublicationCrash):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            failpoint=_crash_at("publish_0"),
        )
    (destination / "nested" / "payload.txt").write_text("intervening", encoding="utf-8")

    with pytest.raises(PublicationError, match="modified publication destination"):
        recover_publication(tmp_path, namespace)

    assert _value(destination) == "intervening"
    transaction_root = _namespace_root(tmp_path, namespace) / "transactions"
    assert (transaction_root / "active.json").exists()
    assert any(path.name == "previous-0" for path in transaction_root.rglob("previous-0"))


def test_changed_first_publication_retains_journal_for_diagnosis(tmp_path: Path) -> None:
    destination = tmp_path / "published"
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)
    with pytest.raises(PublicationCrash):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=False,
            failpoint=_crash_at("publish_0"),
        )
    (destination / "nested" / "payload.txt").write_text("intervening", encoding="utf-8")

    with pytest.raises(PublicationError, match="modified publication destination"):
        recover_publication(tmp_path, namespace)

    assert _value(destination) == "intervening"
    assert (_namespace_root(tmp_path, namespace) / "transactions" / "active.json").exists()


def test_existing_destination_change_after_journal_fails_closed(tmp_path: Path) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)

    def mutate_destination(name: str) -> None:
        if name == "journal_committed":
            (destination / "nested" / "payload.txt").write_text("intervening", encoding="utf-8")

    with pytest.raises(PublicationError, match="modified publication destination"):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            failpoint=mutate_destination,
        )

    assert _value(destination) == "intervening"
    assert (_namespace_root(tmp_path, namespace) / "transactions" / "active.json").exists()


def test_absent_destination_appearing_after_journal_fails_closed(tmp_path: Path) -> None:
    destination = tmp_path / "published"
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)

    def create_destination(name: str) -> None:
        if name == "journal_committed":
            _stage_directory(tmp_path, "published", "external")

    with pytest.raises(PublicationError, match="modified publication destination"):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            failpoint=create_destination,
        )

    assert _value(destination) == "external"
    assert (_namespace_root(tmp_path, namespace) / "transactions" / "active.json").exists()


def test_backup_post_rename_mismatch_is_retained_fail_closed(tmp_path: Path) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)
    real_replace = os.replace

    def mutate_during_backup(source: Path, target: Path) -> None:
        if source == destination and target.name == "previous-0":
            (source / "nested" / "payload.txt").write_text("intervening", encoding="utf-8")
        real_replace(source, target)

    with pytest.raises(PublicationError, match="backup differs from recorded prior state"):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            replace_fn=mutate_during_backup,
        )

    transaction_root = _namespace_root(tmp_path, namespace) / "transactions"
    backup = next(transaction_root.rglob("previous-0"))
    assert _value(backup) == "intervening"
    assert not destination.exists()
    assert (transaction_root / "active.json").exists()
    with pytest.raises(PublicationError, match="backup differs from recorded prior state"):
        recover_publication(tmp_path, namespace)


def test_stage_mutation_after_generation_commit_publishes_generation_snapshot(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "published"
    stage = _stage_directory(tmp_path, "stage", "snapshot")

    def mutate_stage(name: str) -> None:
        if name == "generation_committed":
            (stage / "nested" / "payload.txt").write_text("changed", encoding="utf-8")

    publish_transaction(
        [PublicationTarget(stage, destination)],
        overwrite=False,
        failpoint=mutate_stage,
    )

    assert _value(destination) == "snapshot"
    assert _value(stage) == "changed"


def test_hardlink_mutation_after_generation_commit_publishes_generation_snapshot(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage.txt"
    stage.write_text("snapshot", encoding="utf-8")
    alias = tmp_path / "alias.txt"
    os.link(stage, alias)
    destination = tmp_path / "published.txt"

    def mutate_hardlink(name: str) -> None:
        if name == "generation_committed":
            alias.write_text("changed", encoding="utf-8")

    publish_transaction(
        [PublicationTarget(stage, destination)],
        overwrite=False,
        failpoint=mutate_hardlink,
    )

    assert destination.read_text(encoding="utf-8") == "snapshot"
    assert stage.read_text(encoding="utf-8") == "changed"


@pytest.mark.parametrize("mutation_point", ["publish_0", "pointer_committed"])
def test_hardlink_mutation_after_publication_does_not_change_public_snapshot(
    tmp_path: Path,
    mutation_point: str,
) -> None:
    stage = tmp_path / "stage.txt"
    stage.write_text("snapshot", encoding="utf-8")
    alias = tmp_path / "alias.txt"
    os.link(stage, alias)
    destination = tmp_path / "published.txt"

    def mutate_published_hardlink(name: str) -> None:
        if name == mutation_point:
            alias.write_text("changed", encoding="utf-8")

    publish_transaction(
        [PublicationTarget(stage, destination)],
        overwrite=False,
        failpoint=mutate_published_hardlink,
    )

    assert destination.read_text(encoding="utf-8") == "snapshot"
    assert stage.read_text(encoding="utf-8") == "changed"


def test_generation_and_pointer_tampering_fail_closed(tmp_path: Path) -> None:
    destination = tmp_path / "published.txt"
    stage = tmp_path / "stage.txt"
    stage.write_text("payload", encoding="utf-8")
    result = publish_transaction([PublicationTarget(stage, destination)], overwrite=False)
    generation = _namespace_root(tmp_path, result.namespace) / "generations" / result.generation_id
    blob = generation / "payload" / "0" / "00000000.blob"
    blob.chmod(0o600)
    blob.write_text("tampered", encoding="utf-8")

    with pytest.raises(PublicationError, match="generation"):
        recover_publication(tmp_path, result.namespace)

    blob.write_text("payload", encoding="utf-8")
    blob.chmod(0o400)
    pointer = json.loads(result.pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_sha256"] = "0" * 64
    result.pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(PublicationError, match="pointer"):
        recover_publication(tmp_path, result.namespace)


def test_tampered_journal_path_binding_cannot_escape_store(tmp_path: Path) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)
    with pytest.raises(PublicationCrash):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            failpoint=_crash_at("journal_committed"),
        )
    journal_path = _namespace_root(tmp_path, namespace) / "transactions" / "active.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["transaction_id"] = "../outside"
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with pytest.raises(PublicationError, match="transaction identity"):
        recover_publication(tmp_path, namespace)
    assert _value(destination) == "old"


def test_no_overwrite_race_preserves_the_external_destination(tmp_path: Path) -> None:
    destination = tmp_path / "published"
    stage = _stage_directory(tmp_path, "stage", "new")

    def competing_publish(_source: Path, target: Path) -> None:
        target.mkdir()
        (target / "external.txt").write_text("keep", encoding="utf-8")
        raise FileExistsError(target)

    with pytest.raises(PublicationError, match="created while staging"):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=False,
            rename_no_replace_fn=competing_publish,
        )

    assert (destination / "external.txt").read_text(encoding="utf-8") == "keep"
    assert not (
        _namespace_root(tmp_path, _namespace(destination)) / "transactions" / "active.json"
    ).exists()


def test_namespace_is_order_independent_and_cannot_be_overridden(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert _namespace(first, second) == _namespace(second, first)

    with pytest.raises(PublicationError, match="does not bind destination set"):
        publish_transaction(
            [PublicationTarget(_stage_directory(tmp_path, "stage", "new"), first)],
            overwrite=False,
            namespace="caller-selected",
        )


def test_overlapping_destination_sets_have_one_publication_owner(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    first_only = tmp_path / "first-only"
    second_only = tmp_path / "second-only"
    first = publish_transaction(
        [
            PublicationTarget(_stage_directory(tmp_path, "stage-shared-a", "shared-a"), shared),
            PublicationTarget(_stage_directory(tmp_path, "stage-first", "first"), first_only),
        ],
        overwrite=False,
    )

    with pytest.raises(PublicationError, match="belongs to another publication"):
        publish_transaction(
            [
                PublicationTarget(_stage_directory(tmp_path, "stage-shared-b", "shared-b"), shared),
                PublicationTarget(
                    _stage_directory(tmp_path, "stage-second", "second"), second_only
                ),
            ],
            overwrite=True,
        )

    assert _value(shared) == "shared-a"
    assert _value(first_only) == "first"
    assert not second_only.exists()
    assert recover_publication(tmp_path, first.namespace) == first


def test_backup_rename_without_progress_update_recovers_from_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)
    real_journal_write = publication._journal_write

    def fail_after_backup(path: Path, journal) -> None:
        if journal.get("previous") == [0] and journal.get("operation") is None:
            raise PublicationCrash("backup progress")
        real_journal_write(path, journal)

    monkeypatch.setattr(publication, "_journal_write", fail_after_backup)
    with pytest.raises(PublicationCrash, match="backup progress"):
        publish_transaction([PublicationTarget(stage, destination)], overwrite=True)
    monkeypatch.setattr(publication, "_journal_write", real_journal_write)

    assert recover_publication(tmp_path, namespace) is None
    assert _value(destination) == "old"


def test_publish_rename_without_progress_update_recovers_from_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)
    real_journal_write = publication._journal_write

    def fail_after_publish(path: Path, journal) -> None:
        if journal.get("published") == [0] and journal.get("operation") is None:
            raise PublicationCrash("publish progress")
        real_journal_write(path, journal)

    monkeypatch.setattr(publication, "_journal_write", fail_after_publish)
    with pytest.raises(PublicationCrash, match="publish progress"):
        publish_transaction([PublicationTarget(stage, destination)], overwrite=True)
    monkeypatch.setattr(publication, "_journal_write", real_journal_write)

    assert recover_publication(tmp_path, namespace) is None
    assert _value(destination) == "old"


def test_restore_rename_crash_is_idempotently_recovered(tmp_path: Path) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    namespace = _namespace(destination)
    with pytest.raises(PublicationCrash, match="publish_0"):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            failpoint=_crash_at("publish_0"),
        )

    def crash_after_restore(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise PublicationCrash("restore rename completed")

    with pytest.raises(PublicationCrash, match="restore rename completed"):
        recover_publication(tmp_path, namespace, replace_fn=crash_after_restore)

    assert recover_publication(tmp_path, namespace) is None
    assert _value(destination) == "old"
    assert not (_namespace_root(tmp_path, namespace) / "transactions" / "active.json").exists()


def test_directory_remove_is_atomic_and_crash_idempotently_recovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    stage = _stage_directory(tmp_path, "stage", "new")
    (stage / "second.txt").write_text("second", encoding="utf-8")
    namespace = _namespace(destination)
    with pytest.raises(PublicationCrash, match="publish_0"):
        publish_transaction(
            [PublicationTarget(stage, destination)],
            overwrite=True,
            failpoint=_crash_at("publish_0"),
        )
    real_rename = publication.rename_no_replace
    interrupted = False

    def crash_after_quarantine(source: Path, target: Path) -> None:
        nonlocal interrupted
        real_rename(source, target)
        if source == destination and target.name == "discard-0" and not interrupted:
            interrupted = True
            raise PublicationCrash("published quarantine completed")

    monkeypatch.setattr(publication, "rename_no_replace", crash_after_quarantine)
    with pytest.raises(PublicationCrash, match="published quarantine completed"):
        recover_publication(tmp_path, namespace)
    quarantine = next((_namespace_root(tmp_path, namespace) / "transactions").rglob("discard-0"))
    assert _value(quarantine) == "new"
    assert (quarantine / "second.txt").read_text(encoding="utf-8") == "second"
    assert not destination.exists()
    monkeypatch.setattr(publication, "rename_no_replace", real_rename)

    assert recover_publication(tmp_path, namespace) is None
    assert _value(destination) == "old"


def test_source_symlink_swap_cannot_touch_victim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _stage_directory(tmp_path, "stage", "snapshot")
    source = stage / "nested" / "payload.txt"
    victim = tmp_path / "victim.txt"
    victim.write_text("private", encoding="utf-8")
    victim.chmod(0o600)
    destination = tmp_path / "published"
    real_copy_payload = publication._copy_generation_payload
    swapped = False

    def swap_before_copy(source_root: Path, target: Path, entries) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            source.unlink()
            source.symlink_to(victim)
        real_copy_payload(source_root, target, entries)

    monkeypatch.setattr(publication, "_copy_generation_payload", swap_before_copy)
    with pytest.raises(PublicationError, match="source path is unsafe"):
        publish_transaction([PublicationTarget(stage, destination)], overwrite=False)

    assert victim.read_text(encoding="utf-8") == "private"
    assert victim.stat().st_mode & 0o777 == 0o600
    assert not destination.exists()


def test_concurrent_publishers_serialize_without_recovering_live_transaction(
    tmp_path: Path,
) -> None:
    destination = _stage_directory(tmp_path, "published", "old")
    first_stage = _stage_directory(tmp_path, "stage-first", "first")
    second_stage = _stage_directory(tmp_path, "stage-second", "second")
    first_holds_lock = threading.Event()
    release_first = threading.Event()
    second_reached_generation = threading.Event()

    def hold_after_journal(name: str) -> None:
        if name == "journal_committed":
            first_holds_lock.set()
            assert release_first.wait(timeout=10)

    def observe_second(name: str) -> None:
        if name == "generation_committed":
            second_reached_generation.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            publish_transaction,
            [PublicationTarget(first_stage, destination)],
            overwrite=True,
            failpoint=hold_after_journal,
        )
        assert first_holds_lock.wait(timeout=10)
        second = executor.submit(
            publish_transaction,
            [PublicationTarget(second_stage, destination)],
            overwrite=True,
            failpoint=observe_second,
        )
        assert not second_reached_generation.wait(timeout=0.2)
        release_first.set()
        first_result = first.result(timeout=10)
        second_result = second.result(timeout=10)

    assert second_reached_generation.is_set()
    assert first_result.namespace == second_result.namespace
    assert first_result.generation_id != second_result.generation_id
    assert _value(destination) == "second"
    assert recover_publication(tmp_path, second_result.namespace) == second_result


def test_symlink_and_special_file_inputs_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    symlink = tmp_path / "symlink"
    symlink.symlink_to(source)
    with pytest.raises(PublicationError, match="symlink"):
        publish_transaction(
            [PublicationTarget(symlink, tmp_path / "symlink-output")],
            overwrite=False,
        )

    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(PublicationError, match="regular file or directory"):
            publish_transaction(
                [PublicationTarget(fifo, tmp_path / "fifo-output")],
                overwrite=False,
            )
