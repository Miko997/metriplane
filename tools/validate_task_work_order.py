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


def validate(
    work_order_path: Path,
    *,
    schema_path: Path,
    assignment_schema_path: Path,
    catalog_path: Path,
    catalog_schema_path: Path,
    keyring_path: Path,
) -> dict[str, Any]:
    work_order = _read(work_order_path)
    schema = _read(schema_path)
    try:
        import jsonschema

        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(work_order)
    except ImportError:
        pass
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"work-order schema failure: {exc.message}") from exc
    claimed = work_order.get("materialization_id")
    unsigned = {key: value for key, value in work_order.items() if key != "materialization_id"}
    if claimed != sha256_json(unsigned):
        raise ValidationError("materialization identity mismatch")
    validate_catalog(catalog_path, schema_path=catalog_schema_path)
    catalog = _read(catalog_path)
    rows = [row for row in catalog["tasks"] if row["task_id"] == work_order["task_id"]]
    if len(rows) != 1 or work_order.get("catalog_row") != rows[0]:
        raise ValidationError("catalog row is missing or substituted")
    assignment = work_order.get("assignment")
    if not isinstance(assignment, Mapping) or not isinstance(assignment.get("subject"), Mapping):
        raise ValidationError("assignment is invalid")
    try:
        import jsonschema

        jsonschema.Draft202012Validator(_read(assignment_schema_path)).validate(assignment)
    except ImportError:
        pass
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"assignment schema failure: {exc.message}") from exc
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
    checks = {
        "assignment_trusted": True,
        "catalog_row_exact": True,
        "materialization_id_exact": True,
        "schema_valid": True,
    }
    return {
        "base_sha": work_order["base_sha"],
        "checks": checks,
        "inputs": {
            "catalog": _digest(catalog_path),
            "keyring": _digest(keyring_path),
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
    parser.add_argument("--assignment-schema", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--catalog-schema", type=Path, required=True)
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(
            args.work_order.resolve(strict=True),
            schema_path=args.schema.resolve(strict=True),
            assignment_schema_path=args.assignment_schema.resolve(strict=True),
            catalog_path=args.catalog.resolve(strict=True),
            catalog_schema_path=args.catalog_schema.resolve(strict=True),
            keyring_path=args.keyring.resolve(strict=True),
        )
        _write_new(args.out, result)
        return 0
    except (OSError, ValueError) as exc:
        print(f"work-order validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
