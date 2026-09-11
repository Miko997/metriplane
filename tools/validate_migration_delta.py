# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Validate an exact semantic/golden/obligation delta and non-author approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, canonical_json, sha256_json


class DeltaError(ValueError):
    """The proposed migration delta is malformed or violates policy."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise DeltaError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DeltaError(f"{path} must contain an object")
    return value


def _validate_schema(value: Mapping[str, Any], schema_path: Path, label: str) -> None:
    try:
        import jsonschema
    except ImportError:
        return

    schema = _read(schema_path)
    jsonschema.Draft202012Validator.check_schema(schema)
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as exc:
        raise DeltaError(f"{label} schema failure: {exc.message}") from exc


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise DeltaError(f"git {' '.join(args)} failed: {detail}") from exc


def _commit_json(root: Path, commit: str, path: str) -> dict[str, Any]:
    try:
        value = json.loads(_git(root, "show", f"{commit}:{path}"))
    except json.JSONDecodeError as exc:
        raise DeltaError(f"{commit}:{path} is not JSON") from exc
    if not isinstance(value, dict):
        raise DeltaError(f"{commit}:{path} must contain an object")
    return value


def _commit_bytes(root: Path, commit: str, path: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode == 0:
        return completed.stdout
    if completed.returncode == 128:
        return None
    raise DeltaError(f"cannot read {commit}:{path} from Git")


def _row_digest(value: object) -> str:
    return sha256_json(value)


def _protected_rows(functional: Mapping[str, Any], behavior: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for row in functional.get("rows", []):
        if not isinstance(row, Mapping):
            raise DeltaError("functional inventory row is invalid")
        claim = row.get("claim")
        if isinstance(claim, Mapping) and claim.get("classification") in {
            "supported",
            "compatibility",
        }:
            rows[str(row["id"])] = row
    for row in behavior.get("rows", []):
        if not isinstance(row, Mapping) or not isinstance(row.get("row_id"), str):
            raise DeltaError("behavior characterization row is invalid")
        if row.get("claim_classification") in {"supported", "compatibility"}:
            identity = str(row["row_id"])
            if identity in rows and rows[identity] != row:
                raise DeltaError(f"protected row identity collides: {identity}")
            rows[identity] = row
    return rows


_STRENGTH_FIELDS = (
    "capability_ids",
    "criterion_ids",
    "environment_ids",
    "family_ids",
    "profile_ids",
    "scenario_ids",
)


def _obligations(value: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = value.get("obligations")
    if not isinstance(rows, list):
        raise DeltaError("obligation registry is invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
            raise DeltaError("obligation row is invalid")
        if row["id"] in result:
            raise DeltaError(f"duplicate obligation {row['id']}")
        result[row["id"]] = row
    return result


def _equal_or_stronger(
    original: Mapping[str, Any], replacements: list[Mapping[str, Any]], identity: str
) -> None:
    if not replacements:
        raise DeltaError(f"{identity} has no replacement")
    for field in _STRENGTH_FIELDS:
        required = set(original.get(field, []))
        supplied = {item for row in replacements for item in row.get(field, [])}
        if not required <= supplied:
            raise DeltaError(f"{identity} replacement weakens {field}")


def validate(
    root: Path,
    *,
    manifest: Mapping[str, Any],
    approval: Mapping[str, Any],
    keyring_path: Path,
    functional_path: str,
    behavior_path: str,
    obligations_path: str,
) -> dict[str, Any]:
    base = str(manifest["base_sha"])
    head = str(manifest["head_sha"])
    actual_head = _git(root, "rev-parse", "HEAD").decode().strip()
    if actual_head != head:
        raise DeltaError("manifest head is not the checked-out commit")
    _git(root, "merge-base", "--is-ancestor", base, head)
    changed_paths = sorted(
        line for line in _git(root, "diff", "--name-only", base, head).decode().splitlines() if line
    )
    if changed_paths != sorted(manifest["changed_paths"]):
        raise DeltaError("declared changed paths differ from the exact Git delta")

    subject_digest = sha256_json(manifest)
    if approval.get("subject_digest") != subject_digest:
        raise DeltaError("approval does not bind the exact migration delta")
    reviewer = approval.get("reviewer_id")
    if reviewer == manifest.get("author_id"):
        raise DeltaError("migration approval reviewer must be a non-author")
    signature = approval.get("signature")
    if not isinstance(signature, Mapping) or signature.get("actor_id") != reviewer:
        raise DeltaError("approval signature identity mismatch")
    if not ProviderAttestationVerifier.from_keyring(keyring_path).verify(
        signature, subject_digest=subject_digest
    ):
        raise DeltaError("migration approval signature is not trusted")

    changes = manifest["changes"]
    identities = [row["stable_id"] for row in changes]
    if len(identities) != len(set(identities)):
        raise DeltaError("migration change identities are duplicated")
    declared = set(identities)

    base_rows = _protected_rows(
        _commit_json(root, base, functional_path), _commit_json(root, base, behavior_path)
    )
    head_rows = _protected_rows(
        _commit_json(root, head, functional_path), _commit_json(root, head, behavior_path)
    )
    actual_row_changes = {
        identity
        for identity in set(base_rows) | set(head_rows)
        if base_rows.get(identity) != head_rows.get(identity)
    }
    if not actual_row_changes <= declared:
        raise DeltaError("supported or compatibility behavior changed outside the declared delta")

    base_obligations = _obligations(_commit_json(root, base, obligations_path))
    head_obligations = _obligations(_commit_json(root, head, obligations_path))
    actual_obligation_changes = {
        identity
        for identity in set(base_obligations) | set(head_obligations)
        if base_obligations.get(identity) != head_obligations.get(identity)
    }
    declared_obligations = {row["stable_id"] for row in changes if row["kind"] == "test_obligation"}
    if not actual_obligation_changes <= declared_obligations:
        raise DeltaError("test obligation changed outside the declared delta")

    for change in changes:
        identity = change["stable_id"]
        obligation_change = identity in base_obligations or identity in head_obligations
        row_change = identity in base_rows or identity in head_rows
        if change["kind"] == "test_obligation" and not obligation_change:
            raise DeltaError(f"{identity} is not a governed test obligation")
        if change["kind"] != "test_obligation" and obligation_change:
            raise DeltaError(f"{identity} obligation uses the wrong change kind")
        if obligation_change:
            before_digest = (
                None
                if identity not in base_obligations
                else _row_digest(base_obligations[identity])
            )
            after_digest = (
                None
                if identity not in head_obligations
                else _row_digest(head_obligations[identity])
            )
        elif row_change:
            before_digest = None if identity not in base_rows else _row_digest(base_rows[identity])
            after_digest = None if identity not in head_rows else _row_digest(head_rows[identity])
        else:
            if identity not in manifest["changed_paths"]:
                raise DeltaError(f"{identity} is not a governed row or exact changed path")
            before_bytes = _commit_bytes(root, base, identity)
            after_bytes = _commit_bytes(root, head, identity)
            before_digest = (
                None if before_bytes is None else hashlib.sha256(before_bytes).hexdigest()
            )
            after_digest = None if after_bytes is None else hashlib.sha256(after_bytes).hexdigest()
        if change["before_sha256"] != before_digest:
            raise DeltaError(f"{identity} before digest mismatch")
        if change["after_sha256"] != after_digest:
            raise DeltaError(f"{identity} after digest mismatch")
        supersedes = change["supersedes"]
        replacements = change["replacements"]
        if supersedes or replacements:
            if change["kind"] != "test_obligation" or supersedes != [identity]:
                raise DeltaError(f"{identity} has an invalid supersession declaration")
            original = base_obligations.get(identity)
            current = head_obligations.get(identity)
            if original is None or current is None:
                raise DeltaError(f"{identity} supersession lacks original/current custody")
            if current.get("lifecycle") != "retired_with_reviewed_supersession":
                raise DeltaError(f"{identity} is not retired with reviewed supersession")
            if current.get("superseded_by") != replacements or not current.get(
                "supersession_authority"
            ):
                raise DeltaError(f"{identity} retained supersession does not match approval")
            replacement_rows = [head_obligations.get(item) for item in replacements]
            if any(row is None or row.get("lifecycle") != "active" for row in replacement_rows):
                raise DeltaError(f"{identity} replacement is missing or inactive")
            _equal_or_stronger(original, replacement_rows, identity)  # type: ignore[arg-type]

    result: dict[str, Any] = {
        "approval_digest": hashlib.sha256(canonical_json(approval)).hexdigest(),
        "base_sha": base,
        "changed_path_count": len(changed_paths),
        "change_count": len(changes),
        "head_sha": head,
        "schema_version": "metriplane.migration-delta-validation.v1",
        "subject_digest": subject_digest,
        "task_id": "MP2-017",
        "verdict": "READY",
    }
    result["validation_id"] = sha256_json(result)
    return result


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--approval-schema", type=Path, required=True)
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--functional-inventory", required=True)
    parser.add_argument("--behavior-characterization", required=True)
    parser.add_argument("--obligations", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.repository_root.resolve(strict=True)
        manifest = _read(args.manifest.resolve(strict=True))
        approval = _read(args.approval.resolve(strict=True))
        _validate_schema(manifest, args.schema.resolve(strict=True), "migration delta")
        _validate_schema(approval, args.approval_schema.resolve(strict=True), "approval")
        result = validate(
            root,
            manifest=manifest,
            approval=approval,
            keyring_path=args.keyring.resolve(strict=True),
            functional_path=args.functional_inventory,
            behavior_path=args.behavior_characterization,
            obligations_path=args.obligations,
        )
        _write_new(args.out, result)
        return 0
    except (DeltaError, KeyError, OSError, TypeError, ValueError) as exc:
        print(f"migration delta validation failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
