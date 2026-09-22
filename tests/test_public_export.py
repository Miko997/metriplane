# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import math
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import metriplane.public_export as public_export_module
import metriplane.publication as publication_module
from metriplane.public_export import (
    PROTECTED_DIAGNOSTICS_SCHEMA_VERSION,
    PUBLIC_EXPORT_NAME,
    PUBLIC_EXPORT_SCHEMA_VERSION,
    PublicExportError,
    PublicExportPolicy,
    build_public_export,
    canonical_public_bytes,
    publish_public_export,
    replace_private_file,
    write_private_file,
)
from metriplane.publication import PublicationError


POLICY = PublicExportPolicy(
    allowlist=(
        "event.actor_id",
        "event.asset",
        "event.location",
        "event.message",
        "event.nested.api_key",
        "event.nested.safe",
        "event.source_path",
    )
)


def _record() -> dict[str, object]:
    return {
        "event": {
            "actor_id": "operator-alice",
            "asset": "press-7",
            "location": "/home/alice/private/cell-a",
            "message": "cycle completed",
            "nested": {
                "api_key": "github_pat_PRIVATE_canary_1234",
                "safe": 7,
                "unlisted": "drop-this-value",
            },
            "source_path": "../secret/run.jsonl",
        },
        "not_public": "outside-allowlist",
    }


def test_closed_allowlist_redacts_identity_secret_and_paths_without_values() -> None:
    public, diagnostics = build_public_export(
        [_record()],
        policy=POLICY,
        canaries=(
            "operator-alice",
            "/home/alice/private/cell-a",
            "github_pat_PRIVATE_canary_1234",
            "../secret/run.jsonl",
            "drop-this-value",
            "outside-allowlist",
        ),
    )

    event = public["records"][0]["event"]  # type: ignore[index]
    assert public["schema_version"] == PUBLIC_EXPORT_SCHEMA_VERSION
    assert event == {
        "actor_id": "<redacted:identity>",
        "asset": "press-7",
        "location": "<redacted:path>",
        "message": "cycle completed",
        "nested": {"api_key": "<redacted:secret>", "safe": 7},
        "source_path": "<redacted:path>",
    }
    assert diagnostics["schema_version"] == PROTECTED_DIAGNOSTICS_SCHEMA_VERSION
    assert diagnostics["redaction_counts"] == {"identity": 1, "path": 2, "secret": 1}
    assert diagnostics["dropped_fields"] == ["event.nested.unlisted", "not_public"]
    retained = canonical_public_bytes(public) + canonical_public_bytes(diagnostics)
    for secret in (
        b"operator-alice",
        b"/home/alice",
        b"github_pat_PRIVATE",
        b"drop-this-value",
        b"outside-allowlist",
    ):
        assert secret not in retained


def test_generic_allowlisted_values_redact_real_github_tokens_and_relative_paths() -> None:
    policy = PublicExportPolicy(allowlist=("event.classic", "event.fine_grained", "event.relative"))
    classic = "ghp_AAAAAAAA11111111"
    fine_grained = "github_pat_AAAAAAAA11111111_BBBBBBBB22222222"
    relative = "private/run.json"

    public, diagnostics = build_public_export(
        [
            {
                "event": {
                    "classic": classic,
                    "fine_grained": fine_grained,
                    "relative": relative,
                }
            }
        ],
        policy=policy,
        canaries=(classic, fine_grained, relative),
    )

    assert public["records"] == [
        {
            "event": {
                "classic": public_export_module.REDACTED_SECRET,
                "fine_grained": public_export_module.REDACTED_SECRET,
                "relative": public_export_module.REDACTED_PATH,
            }
        }
    ]
    assert diagnostics["redaction_counts"] == {"identity": 0, "path": 1, "secret": 2}


def test_projection_is_deterministic_for_mapping_order_and_nested_lists() -> None:
    policy = PublicExportPolicy(allowlist=("items.code", "items.details.safe", "kind"))
    first = {
        "kind": "summary",
        "items": [
            {"details": {"safe": True, "private": "drop"}, "code": "A"},
            {"code": "B", "details": {"safe": False}},
        ],
    }
    second = {
        "items": [
            {"code": "A", "details": {"private": "drop", "safe": True}},
            {"details": {"safe": False}, "code": "B"},
        ],
        "kind": "summary",
    }
    public_a, diagnostics_a = build_public_export([first], policy=policy)
    public_b, diagnostics_b = build_public_export([second], policy=policy)
    assert canonical_public_bytes(public_a) == canonical_public_bytes(public_b)
    assert canonical_public_bytes(diagnostics_a) == canonical_public_bytes(diagnostics_b)


@pytest.mark.parametrize(
    ("policy", "records", "match"),
    [
        (PublicExportPolicy(allowlist=("event",)), [{"event": {"value": 1}}], "enumerate"),
        (PublicExportPolicy(allowlist=("value",)), [{"value": math.nan}], "non-finite"),
        (PublicExportPolicy(allowlist=("value",)), ["not-a-record"], "mapping"),
    ],
)
def test_malformed_or_ambiguous_public_inputs_fail_closed(
    policy: PublicExportPolicy,
    records: list[object],
    match: str,
) -> None:
    with pytest.raises(PublicExportError, match=match):
        build_public_export(records, policy=policy)  # type: ignore[arg-type]


def test_policy_and_canary_contracts_fail_closed() -> None:
    with pytest.raises(PublicExportError, match="sorted"):
        PublicExportPolicy(allowlist=("z", "a"))
    with pytest.raises(PublicExportError, match="invalid"):
        PublicExportPolicy(allowlist=("bad..path",))
    with pytest.raises(PublicExportError, match="at least four"):
        build_public_export(
            [{"value": "ok"}], policy=PublicExportPolicy(("value",)), canaries=("x",)
        )
    with pytest.raises(PublicExportError, match="survived"):
        build_public_export(
            [{"value": "public-canary"}],
            policy=PublicExportPolicy(("value",)),
            canaries=("public-canary",),
        )


@pytest.mark.parametrize(
    ("records", "policy"),
    [
        ([{"event": "TOP-SECRET"}], PublicExportPolicy(("event.safe",))),
        ([{"event": {"items": ["TOP-SECRET"]}}], PublicExportPolicy(("event.items.code",))),
    ],
)
def test_parent_only_allowlist_never_admits_a_scalar(
    records: list[dict[str, object]],
    policy: PublicExportPolicy,
) -> None:
    with pytest.raises(PublicExportError, match="allowlist parent"):
        build_public_export(records, policy=policy)


def test_publication_is_atomic_private_path_neutral_and_no_overwrite(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "shareable"
    result = publish_public_export(
        [_record()],
        destination,
        policy=POLICY,
        canaries=("operator-alice", "github_pat_PRIVATE_canary_1234"),
    )

    public_path = destination / PUBLIC_EXPORT_NAME
    diagnostics_path = tmp_path / ".shareable.diagnostics.json"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE(public_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(diagnostics_path.stat().st_mode) == 0o600
    assert (
        json.loads(public_path.read_text(encoding="utf-8"))["schema_version"]
        == PUBLIC_EXPORT_SCHEMA_VERSION
    )
    assert (
        json.loads(diagnostics_path.read_text(encoding="utf-8"))["schema_version"]
        == PROTECTED_DIAGNOSTICS_SCHEMA_VERSION
    )
    assert result.destination_name == "shareable"
    assert result.diagnostics_name == ".shareable.diagnostics.json"
    assert str(tmp_path) not in repr(result)
    assert len(result.public_sha256) == len(result.diagnostics_sha256) == 64

    with pytest.raises(PublicationError, match="without overwrite"):
        publish_public_export([_record()], destination, policy=POLICY)


def test_overwrite_updates_public_and_diagnostics_in_one_transaction(tmp_path: Path) -> None:
    destination = tmp_path / "shareable"
    first = publish_public_export(
        [{"event": {"message": "first"}}],
        destination,
        policy=POLICY,
    )
    second = publish_public_export(
        [{"event": {"message": "second"}}],
        destination,
        policy=POLICY,
        overwrite=True,
    )
    assert first.generation_id != second.generation_id
    value = json.loads((destination / PUBLIC_EXPORT_NAME).read_text(encoding="utf-8"))
    assert value["records"] == [{"event": {"message": "second"}}]


def test_diagnostics_must_be_a_distinct_sibling(tmp_path: Path) -> None:
    destination = tmp_path / "shareable"
    with pytest.raises(PublicExportError, match="distinct siblings"):
        publish_public_export(
            [{"event": {"message": "ok"}}],
            destination,
            policy=POLICY,
            diagnostics_path=tmp_path / "nested" / "diagnostics.json",
        )


def test_symlinked_destination_parent_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(PublicExportError, match="unsafe directory"):
        publish_public_export(
            [{"event": {"message": "ok"}}],
            link / "shareable",
            policy=POLICY,
        )


def test_intermediate_symlink_is_rejected_for_publication_and_private_file(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    nested = real / "nested"
    nested.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(PublicExportError, match="unsafe directory"):
        publish_public_export(
            [{"event": {"message": "ok"}}],
            link / "nested" / "shareable",
            policy=POLICY,
        )
    with pytest.raises(PublicExportError, match="unsafe directory"):
        replace_private_file(link / "nested" / "private.json", b"private\n")
    with pytest.raises(PublicExportError, match="unsafe directory"):
        write_private_file(link / "nested" / "create.json", b"private\n")
    assert list(nested.iterdir()) == []


def test_parent_swap_is_detected_before_pinned_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    moved = tmp_path / "moved"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_publish = public_export_module.publish_transaction

    def swap_then_publish(targets, **kwargs):  # type: ignore[no-untyped-def]
        parent.rename(moved)
        parent.symlink_to(outside, target_is_directory=True)
        return real_publish(targets, **kwargs)

    monkeypatch.setattr(public_export_module, "publish_transaction", swap_then_publish)
    with pytest.raises(PublicationError, match="parent identity differs"):
        publish_public_export(
            [{"event": {"message": "ok"}}],
            parent / "shareable",
            policy=POLICY,
        )
    assert list(outside.iterdir()) == []
    assert list(moved.iterdir()) == []


def test_darwin_worker_publishes_from_inherited_directory_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(publication_module.sys, "platform", "darwin")
    destination = tmp_path / "shareable"

    result = publish_public_export(
        [{"event": {"message": "portable"}}],
        destination,
        policy=POLICY,
    )

    assert json.loads((destination / PUBLIC_EXPORT_NAME).read_bytes())["records"] == [
        {"event": {"message": "portable"}}
    ]
    assert result.destination_name == "shareable"


def test_darwin_private_output_root_alias_accepts_direct_directory_and_checks_symlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=stat.S_IFDIR | 0o777,
        st_uid=0,
        st_ctime_ns=3,
    )
    symlink = SimpleNamespace(
        st_dev=4,
        st_ino=5,
        st_mode=stat.S_IFLNK | 0o777,
        st_uid=0,
        st_ctime_ns=6,
    )
    alias_info = direct
    real_lstat = Path.lstat
    real_readlink = public_export_module.os.readlink

    def root_alias_lstat(path: Path):
        if path == Path("/tmp"):
            return alias_info
        return real_lstat(path)

    def root_alias_readlink(path: str | Path) -> str:
        if Path(path) == Path("/tmp"):
            return "private/tmp"
        return real_readlink(path)

    monkeypatch.setattr(public_export_module.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "lstat", root_alias_lstat)
    monkeypatch.setattr(public_export_module.os, "readlink", root_alias_readlink)
    assert public_export_module._canonical_parent(Path("/tmp/run")) == Path("/tmp/run")

    alias_info = symlink
    assert public_export_module._canonical_parent(Path("/tmp/run")) == Path("/private/tmp/run")
    monkeypatch.setattr(public_export_module.os, "readlink", lambda _path: "attacker/tmp")
    with pytest.raises(PublicExportError, match="root alias differs"):
        public_export_module._canonical_parent(Path("/tmp/run"))


def test_private_file_replace_is_atomic_private_and_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "privacy.json"
    replace_private_file(target, b"first\n")
    replace_private_file(target, b"second\n")
    assert target.read_bytes() == b"second\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    target.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    target.symlink_to(outside)
    with pytest.raises(PublicExportError, match="regular file"):
        replace_private_file(target, b"must-not-follow\n")
    assert outside.read_bytes() == b"unchanged"
