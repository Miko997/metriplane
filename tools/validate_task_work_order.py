# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Independently validate an immutable MP2 task work order."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, canonical_json, sha256_json

try:
    from tools.check_work_order_catalog import validate_catalog
except ImportError:
    from check_work_order_catalog import validate_catalog

try:
    from tools.materialize_task_work_order import NotReady as MaterializationNotReady
    from tools.materialize_task_work_order import build as rebuild_work_order
    from tools.task_delegation import DelegationNotReady, parse_utc, validate_delegation
except ImportError:
    from materialize_task_work_order import NotReady as MaterializationNotReady
    from materialize_task_work_order import build as rebuild_work_order
    from task_delegation import DelegationNotReady, parse_utc, validate_delegation


class ValidationError(ValueError):
    """The work order cannot be validated exactly."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain an object")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def _validate_schema(value: Mapping[str, Any], path: Path, label: str) -> None:
    try:
        import jsonschema

        schema = _read(path)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(value)
    except ImportError:
        pass
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"{label} schema failure: {exc.message}") from exc


def _validate_identity(work_order: Mapping[str, Any]) -> None:
    claimed = work_order.get("materialization_id")
    unsigned = {key: value for key, value in work_order.items() if key != "materialization_id"}
    if claimed != sha256_json(unsigned):
        raise ValidationError("materialization identity mismatch")


def _validate_legacy(
    work_order: Mapping[str, Any],
    *,
    assignment_schema_path: Path,
    catalog_path: Path,
    catalog_schema_path: Path,
    keyring_path: Path,
) -> dict[str, Any]:
    _validate_identity(work_order)
    validate_catalog(catalog_path, schema_path=catalog_schema_path)
    catalog = _read(catalog_path)
    rows = [row for row in catalog["tasks"] if row["task_id"] == work_order["task_id"]]
    if len(rows) != 1 or work_order.get("catalog_row") != rows[0]:
        raise ValidationError("catalog row is missing or substituted")
    assignment = work_order.get("assignment")
    if not isinstance(assignment, Mapping) or not isinstance(assignment.get("subject"), Mapping):
        raise ValidationError("assignment is invalid")
    _validate_schema(assignment, assignment_schema_path, "assignment")
    subject = assignment["subject"]
    subject_digest = sha256_json(subject)
    if assignment.get("subject_digest") != subject_digest:
        raise ValidationError("assignment digest mismatch")
    signature = assignment.get("signature")
    verifier = ProviderAttestationVerifier.from_keyring(keyring_path)
    if not isinstance(signature, Mapping) or not verifier.verify(
        signature, subject_digest=subject_digest
    ):
        raise ValidationError("assignment signature is not trusted")
    return {
        "base_sha": work_order["base_sha"],
        "checks": {
            "assignment_trusted": True,
            "catalog_row_exact": True,
            "eligible_for_new_execution": False,
            "historical_v1_interpretable": True,
            "materialization_id_exact": True,
            "schema_valid": True,
        },
        "inputs": {
            "catalog": _digest(catalog_path),
            "keyring": _digest(keyring_path),
            "work_order": "pending",
        },
        "schema_version": "metriplane.validation-result.v1",
        "task_id": work_order["task_id"],
        "validator": "task_work_order",
        "verdict": "BLOCKED_NOT_READY",
    }


def validate(
    work_order_path: Path,
    *,
    schema_path: Path,
    assignment_schema_path: Path | None,
    catalog_path: Path,
    catalog_schema_path: Path,
    keyring_path: Path | None,
    repository_root: Path | None = None,
    delegation_path: Path | None = None,
    delegation_schema_path: Path | None = None,
    authority_keyring_path: Path | None = None,
    authority_keyring_schema_path: Path | None = None,
    linear_snapshot_path: Path | None = None,
    linear_snapshot_schema_path: Path | None = None,
    dependency_evidence_path: Path | None = None,
    command_registry_path: Path | None = None,
    resolution_path: Path | None = None,
    repository: str | None = None,
    project_id: str | None = None,
    grantor_id: str | None = None,
    executor_id: str | None = None,
    validated_at: str | None = None,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    work_order = _read(work_order_path)
    _validate_schema(work_order, schema_path, "work-order")
    if work_order.get("schema_version") == "metriplane.task-work-order.v1":
        if assignment_schema_path is None or keyring_path is None:
            raise ValidationError(
                "historical v1 validation requires its assignment schema and keyring"
            )
        result = _validate_legacy(
            work_order,
            assignment_schema_path=assignment_schema_path,
            catalog_path=catalog_path,
            catalog_schema_path=catalog_schema_path,
            keyring_path=keyring_path,
        )
        result["inputs"]["work_order"] = _digest(work_order_path)
        return result
    if work_order.get("schema_version") != "metriplane.task-work-order.v2":
        raise ValidationError("work-order schema version is unsupported")

    required = {
        "repository_root": repository_root,
        "delegation_path": delegation_path,
        "delegation_schema_path": delegation_schema_path,
        "authority_keyring_path": authority_keyring_path,
        "authority_keyring_schema_path": authority_keyring_schema_path,
        "linear_snapshot_path": linear_snapshot_path,
        "linear_snapshot_schema_path": linear_snapshot_schema_path,
        "dependency_evidence_path": dependency_evidence_path,
        "command_registry_path": command_registry_path,
        "resolution_path": resolution_path,
        "repository": repository,
        "project_id": project_id,
        "grantor_id": grantor_id,
        "executor_id": executor_id,
        "validated_at": validated_at,
    }
    missing = sorted(name for name, value in required.items() if value is None)
    if missing:
        raise ValidationError("v2 validation inputs are missing: " + ", ".join(missing))
    assert repository_root is not None
    assert delegation_path is not None
    assert delegation_schema_path is not None
    assert authority_keyring_path is not None
    assert authority_keyring_schema_path is not None
    assert linear_snapshot_path is not None
    assert linear_snapshot_schema_path is not None
    assert dependency_evidence_path is not None
    assert command_registry_path is not None
    assert resolution_path is not None
    assert repository is not None
    assert project_id is not None
    assert grantor_id is not None
    assert executor_id is not None
    assert validated_at is not None

    expected = rebuild_work_order(
        repository_root,
        task_id=work_order["task_id"],
        base_sha=work_order["base_sha"],
        repository=repository,
        project_id=project_id,
        grantor_id=grantor_id,
        executor_id=executor_id,
        evaluated_at=work_order["evaluated_at"],
        fixture_mode=fixture_mode,
        catalog_path=catalog_path,
        catalog_schema=catalog_schema_path,
        delegation_path=delegation_path,
        delegation_schema_path=delegation_schema_path,
        authority_keyring_path=authority_keyring_path,
        authority_keyring_schema_path=authority_keyring_schema_path,
        linear_snapshot_path=linear_snapshot_path,
        linear_snapshot_schema_path=linear_snapshot_schema_path,
        dependency_evidence_path=dependency_evidence_path,
        command_registry_path=command_registry_path,
        resolution_path=resolution_path,
    )
    if expected != work_order:
        raise ValidationError("work-order differs from independently reconstructed inputs")

    delegation = work_order.get("delegation")
    if not isinstance(delegation, Mapping):
        raise ValidationError("task delegation is invalid")
    authority = _read(authority_keyring_path)
    snapshot = _read(linear_snapshot_path)
    if parse_utc(validated_at, "validation time") < parse_utc(
        work_order["evaluated_at"], "materialization time"
    ):
        raise ValidationError("validation time precedes materialization")
    validate_delegation(
        delegation,
        authority,
        snapshot,
        task_id=work_order["task_id"],
        linear_issue=work_order["linear_issue"],
        repository=repository,
        project_id=project_id,
        base_sha=work_order["base_sha"],
        base_tree=work_order["base_tree"],
        grantor_id=grantor_id,
        executor_id=executor_id,
        evaluated_at=validated_at,
        live=not fixture_mode,
    )
    return {
        "base_sha": work_order["base_sha"],
        "checks": {
            "catalog_row_exact": True,
            "delegation_still_active": True,
            "delegation_trusted": True,
            "inputs_reconstructed": True,
            "materialization_id_exact": True,
            "schema_valid": True,
        },
        "inputs": {
            "authority_keyring": _digest(authority_keyring_path),
            "catalog": _digest(catalog_path),
            "work_order": _digest(work_order_path),
        },
        "schema_version": "metriplane.validation-result.v1",
        "task_id": work_order["task_id"],
        "validator": "task_work_order",
        "verdict": "READY",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-order", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--assignment-schema", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--catalog-schema", type=Path, required=True)
    parser.add_argument("--keyring", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--delegation", type=Path)
    parser.add_argument("--delegation-schema", type=Path)
    parser.add_argument("--authority-keyring", type=Path)
    parser.add_argument("--authority-keyring-schema", type=Path)
    parser.add_argument("--linear-snapshot", type=Path)
    parser.add_argument("--linear-snapshot-schema", type=Path)
    parser.add_argument("--dependency-evidence", type=Path)
    parser.add_argument("--command-registry", type=Path)
    parser.add_argument("--resolution", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--linear-project-id")
    parser.add_argument("--grantor-id")
    parser.add_argument("--executor-id")
    parser.add_argument("--validated-at")
    parser.add_argument("--fixture-mode", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(
            args.work_order.resolve(strict=True),
            schema_path=args.schema.resolve(strict=True),
            assignment_schema_path=(
                args.assignment_schema.resolve(strict=True) if args.assignment_schema else None
            ),
            catalog_path=args.catalog.resolve(strict=True),
            catalog_schema_path=args.catalog_schema.resolve(strict=True),
            keyring_path=args.keyring.resolve(strict=True) if args.keyring else None,
            repository_root=(
                args.repository_root.resolve(strict=True) if args.repository_root else None
            ),
            delegation_path=args.delegation.resolve(strict=True) if args.delegation else None,
            delegation_schema_path=(
                args.delegation_schema.resolve(strict=True) if args.delegation_schema else None
            ),
            authority_keyring_path=(
                args.authority_keyring.resolve(strict=True) if args.authority_keyring else None
            ),
            authority_keyring_schema_path=(
                args.authority_keyring_schema.resolve(strict=True)
                if args.authority_keyring_schema
                else None
            ),
            linear_snapshot_path=(
                args.linear_snapshot.resolve(strict=True) if args.linear_snapshot else None
            ),
            linear_snapshot_schema_path=(
                args.linear_snapshot_schema.resolve(strict=True)
                if args.linear_snapshot_schema
                else None
            ),
            dependency_evidence_path=(
                args.dependency_evidence.resolve(strict=True) if args.dependency_evidence else None
            ),
            command_registry_path=(
                args.command_registry.resolve(strict=True) if args.command_registry else None
            ),
            resolution_path=args.resolution.resolve(strict=True) if args.resolution else None,
            repository=args.repository,
            project_id=args.linear_project_id,
            grantor_id=args.grantor_id,
            executor_id=args.executor_id,
            validated_at=args.validated_at,
            fixture_mode=args.fixture_mode,
        )
        _write_new(args.out, result)
        return 0 if result["verdict"] == "READY" else 3
    except ConnectionError as exc:
        print(f"work-order validation provider unavailable: {exc}", file=sys.stderr)
        return 4
    except (DelegationNotReady, FileExistsError, MaterializationNotReady) as exc:
        print(f"work-order validation blocked: {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print(f"work-order validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
