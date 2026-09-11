# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Create one exact, signed, dependency-complete MP2 task work order."""

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

try:
    from tools.check_work_order_catalog import CatalogError, validate_catalog
except ImportError:
    from check_work_order_catalog import CatalogError, validate_catalog

SCHEMA_VERSION = "metriplane.task-work-order.v1"


class MaterializationError(ValueError):
    """An assignment input is invalid or cannot produce READY."""


class InputError(MaterializationError):
    """An invocation input is malformed, substituted, or untrusted."""


class NotReady(MaterializationError):
    """Valid inputs establish that policy prerequisites are not ready."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError(f"{path} must contain an object")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_validate(value: Mapping[str, Any], schema_path: Path, label: str) -> None:
    try:
        import jsonschema

        schema = _read(schema_path)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(value)
    except ImportError:
        return
    except jsonschema.ValidationError as exc:
        raise InputError(f"{label} schema failure: {exc.message}") from exc


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def _validate_relations(catalog: Mapping[str, Any], snapshot: Mapping[str, Any]) -> str:
    status = snapshot.get("provider_status")
    if status == "outage":
        raise ConnectionError("Linear relation provider outage")
    if status != "available":
        raise InputError("Linear provider status is not evidenced")
    issue_by_task = {row["task_id"]: row["linear_issue"] for row in catalog["tasks"]}
    expected = {
        (issue_by_task[dependency], row["linear_issue"])
        for row in catalog["tasks"]
        for dependency in row["authoritative_blocked_by"]
    }
    edges = snapshot.get("edges")
    if not isinstance(edges, list):
        raise InputError("Linear snapshot edges must be a list")
    actual: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, Mapping) or set(edge) != {"blocked", "blocker"}:
            raise InputError("Linear relation edge shape is invalid")
        pair = (edge["blocker"], edge["blocked"])
        if not all(isinstance(value, str) for value in pair) or pair in actual:
            raise InputError("Linear relation edge is invalid or duplicated")
        actual.add(pair)
    if actual != expected:
        raise NotReady("live Linear dependency relations differ from the catalog")
    cursor = snapshot.get("event_cursor")
    if not isinstance(cursor, str) or not cursor:
        raise InputError("Linear snapshot lacks an event cursor")
    return sha256_json({"edges": sorted(actual), "event_cursor": cursor})


def build(
    root: Path,
    *,
    task_id: str,
    base_sha: str,
    catalog_path: Path,
    catalog_schema: Path,
    assignment_path: Path,
    assignment_schema_path: Path,
    keyring_path: Path,
    linear_snapshot_path: Path,
    dependency_evidence_path: Path,
    command_registry_path: Path,
    resolution_path: Path,
) -> dict[str, Any]:
    actual_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if actual_head != base_sha:
        raise NotReady("base SHA is not the checked-out source")
    validate_catalog(catalog_path, schema_path=catalog_schema)
    catalog = _read(catalog_path)
    matches = [row for row in catalog["tasks"] if row["task_id"] == task_id]
    if len(matches) != 1:
        raise InputError("task identity is absent or duplicated")
    task = matches[0]
    assignment = _read(assignment_path)
    _schema_validate(assignment, assignment_schema_path, "assignment")
    subject = assignment.get("subject")
    if not isinstance(subject, Mapping):
        raise InputError("assignment subject is invalid")
    expected_subject = {
        "actor_id": subject.get("actor_id"),
        "authority": subject.get("authority"),
        "base_sha": base_sha,
        "linear_issue": task["linear_issue"],
        "task_id": task_id,
    }
    if subject != expected_subject or not all(
        isinstance(expected_subject[key], str) and expected_subject[key]
        for key in ("actor_id", "authority")
    ):
        raise InputError("assignment does not bind the selected task and base")
    subject_digest = sha256_json(subject)
    if assignment.get("subject_digest") != subject_digest:
        raise InputError("assignment subject digest mismatch")
    signature = assignment.get("signature")
    if not isinstance(signature, Mapping) or signature.get("actor_id") != subject["actor_id"]:
        raise InputError("assignment signature identity mismatch")
    verifier = ProviderAttestationVerifier.from_keyring(keyring_path)
    if not verifier.verify(signature, subject_digest=subject_digest):
        raise InputError("assignment signature is not trusted")
    linear_snapshot = _read(linear_snapshot_path)
    relation_digest = _validate_relations(catalog, linear_snapshot)
    evidence = _read(dependency_evidence_path)
    dependencies = evidence.get("dependencies")
    if not isinstance(dependencies, list):
        raise InputError("dependency evidence is invalid")
    expected_dependencies = set(task["authoritative_blocked_by"])
    observed_dependencies = {row.get("task_id") for row in dependencies if isinstance(row, Mapping)}
    if observed_dependencies != expected_dependencies:
        raise NotReady("dependency evidence set is not exact")
    for row in dependencies:
        if (
            not isinstance(row, Mapping)
            or row.get("merged_at_base") is not True
            or not isinstance(row.get("artifact_sha256"), str)
            or len(row["artifact_sha256"]) != 64
            or not isinstance(row.get("validator"), str)
            or not row["validator"]
        ):
            raise InputError("dependency evidence is incomplete")
    commands = _read(command_registry_path)
    if commands.get("task_id") != task_id or not isinstance(commands.get("commands"), list):
        raise InputError("command registry does not bind the task")
    command_ids: set[str] = set()
    covered: set[str] = set()
    for row in commands["commands"]:
        if not isinstance(row, Mapping):
            raise InputError("command row is not an object")
        command_id = row.get("command_id")
        criteria = row.get("criterion_ids")
        argv = row.get("argv")
        if (
            not isinstance(command_id, str)
            or not command_id
            or command_id in command_ids
            or not isinstance(criteria, list)
            or not criteria
            or not all(isinstance(value, str) and value for value in criteria)
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(value, str) and value for value in argv)
            or not isinstance(row.get("cwd"), str)
            or not row["cwd"]
            or not isinstance(row.get("environment"), Mapping)
            or not isinstance(row.get("resources"), list)
            or row.get("expected_exit") not in {0, 2, 3, 4}
            or not isinstance(row.get("expected_outputs"), list)
        ):
            raise InputError("command row is incomplete or duplicated")
        command_ids.add(command_id)
        covered.update(criteria)
    expected_criteria = {row["criterion_id"] for row in task["task_specific_acceptance_predicates"]}
    if covered != expected_criteria:
        raise NotReady("commands do not cover every criterion exactly")
    resolution = _read(resolution_path)
    if resolution.get("task_id") != task_id or resolution.get("status") != "RESOLVED":
        raise NotReady("owned paths and anchors are not fully resolved")
    anchors = resolution.get("anchors")
    outputs = resolution.get("outputs")
    expected_anchors = {row["locator"] for row in task["ownership"]["start_anchors"]}
    expected_outputs = {row["path_or_resolver"] for row in task["ownership"]["planned_outputs"]}
    if not isinstance(anchors, list) or not isinstance(outputs, list):
        raise InputError("resolution lacks finite anchors or outputs")
    if {row.get("locator") for row in anchors if isinstance(row, Mapping)} != expected_anchors:
        raise NotReady("resolved anchors do not equal the catalog anchor set")
    if {row.get("locator") for row in outputs if isinstance(row, Mapping)} != expected_outputs:
        raise NotReady("resolved outputs do not equal the catalog output set")
    resolved_paths: dict[str, str] = {}
    for group in (*anchors, *outputs):
        if (
            not isinstance(group, Mapping)
            or not isinstance(group.get("destinations"), list)
            or not group["destinations"]
        ):
            raise InputError("resolution group is not a finite non-empty set")
        for destination in group["destinations"]:
            if not isinstance(destination, Mapping):
                raise InputError("resolved destination is not an object")
            path = destination.get("path")
            owner = destination.get("owner")
            if (
                not isinstance(path, str)
                or not path
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                or destination.get("state") not in {"EXISTING", "CREATE"}
                or not isinstance(owner, str)
                or not owner.startswith("MP2-")
                or not isinstance(destination.get("consumers"), list)
                or not isinstance(destination.get("validator"), str)
                or not destination["validator"]
                or not isinstance(destination.get("schema_or_media_type"), str)
                or not destination["schema_or_media_type"]
            ):
                raise InputError("resolved destination is incomplete or unsafe")
            previous = resolved_paths.setdefault(path, owner)
            if previous != owner:
                raise NotReady(f"resolved output ownership collision at {path}")
    inputs = {
        "assignment": assignment_path,
        "assignment_schema": assignment_schema_path,
        "catalog": catalog_path,
        "catalog_schema": catalog_schema,
        "commands": command_registry_path,
        "dependencies": dependency_evidence_path,
        "keyring": keyring_path,
        "linear_snapshot": linear_snapshot_path,
        "resolution": resolution_path,
    }
    result: dict[str, Any] = {
        "assignment": assignment,
        "base_sha": base_sha,
        "catalog_row": task,
        "commands": commands["commands"],
        "dependencies": dependencies,
        "input_digests": {name: _digest(path) for name, path in sorted(inputs.items())},
        "linear_issue": task["linear_issue"],
        "linear_relation_digest": relation_digest,
        "resolution": resolution,
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "verdict": "READY",
    }
    result["materialization_id"] = sha256_json(result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--catalog-schema", type=Path, required=True)
    parser.add_argument("--assignment", type=Path, required=True)
    parser.add_argument("--assignment-schema", type=Path, required=True)
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--linear-snapshot", type=Path, required=True)
    parser.add_argument("--dependency-evidence", type=Path, required=True)
    parser.add_argument("--command-registry", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.repository_root.resolve(strict=True)
        result = build(
            root,
            task_id=args.task_id,
            base_sha=args.base_sha,
            catalog_path=(root / args.catalog).resolve(strict=True),
            catalog_schema=(root / args.catalog_schema).resolve(strict=True),
            assignment_path=args.assignment.resolve(strict=True),
            assignment_schema_path=args.assignment_schema.resolve(strict=True),
            keyring_path=args.keyring.resolve(strict=True),
            linear_snapshot_path=args.linear_snapshot.resolve(strict=True),
            dependency_evidence_path=args.dependency_evidence.resolve(strict=True),
            command_registry_path=args.command_registry.resolve(strict=True),
            resolution_path=args.resolution.resolve(strict=True),
        )
        _write_new(args.out, result)
        return 0
    except ConnectionError as exc:
        print(f"work-order provider unavailable: {exc}", file=sys.stderr)
        return 4
    except FileExistsError as exc:
        print(f"work-order materialization blocked: {exc}", file=sys.stderr)
        return 3
    except NotReady as exc:
        print(f"work-order materialization blocked: {exc}", file=sys.stderr)
        return 3
    except (CatalogError, InputError, OSError, ValueError) as exc:
        print(f"work-order materialization invalid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
