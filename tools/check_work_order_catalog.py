# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Transcribe and validate the authoritative 93-row MP2 work-order catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

CATALOG_PATH: Final = Path("docs/status/task-work-orders.json")
SCHEMA_PATH: Final = Path("schemas/metriplane.mp2-work-order-set.v1.schema.json")
SOURCE_SHA256: Final = "f04a69658ae8c0c11c1ad96cb666b03d92cdf2d0a59a7520580487a61a43c161"
TASK_COUNT: Final = 93
RELEASES: Final = frozenset({"v0.4", "v0.5", "v0.6", "v0.7", "v0.8", "v0.9", "v1.0", "post-v1.0"})


class CatalogError(ValueError):
    """The governed work-order catalog is invalid or not authoritative."""


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CatalogError(f"{path} must contain an object")
    return raw, value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{label} must be non-empty text")
    return value


def validate_catalog(catalog_path: Path, *, schema_path: Path) -> dict[str, object]:
    raw, catalog = _load(catalog_path)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        raise CatalogError(f"catalog source digest {digest} does not match packet 12")
    if catalog.get("schema_version") != "metriplane.mp2-work-order-set.v1":
        raise CatalogError("unknown work-order catalog schema")
    tasks = catalog.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != TASK_COUNT:
        raise CatalogError(f"catalog must contain exactly {TASK_COUNT} tasks")
    ids: set[str] = set()
    issues: set[str] = set()
    dependencies: dict[str, tuple[str, ...]] = {}
    criterion_count = 0
    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            raise CatalogError(f"task {index} must be an object")
        task_id = _require_text(task.get("task_id"), f"task {index} id")
        issue = _require_text(task.get("linear_issue"), f"{task_id} Linear issue")
        if task_id in ids or issue in issues:
            raise CatalogError(f"duplicate task or Linear identity at {task_id}")
        ids.add(task_id)
        issues.add(issue)
        release = _require_text(task.get("first_required_release"), f"{task_id} release")
        if release not in RELEASES:
            raise CatalogError(f"{task_id} has unknown release membership {release}")
        blocked_by = task.get("authoritative_blocked_by")
        if not isinstance(blocked_by, list) or not all(isinstance(x, str) for x in blocked_by):
            raise CatalogError(f"{task_id} dependencies must be task IDs")
        dependencies[task_id] = tuple(blocked_by)
        ownership = task.get("ownership")
        if not isinstance(ownership, Mapping):
            raise CatalogError(f"{task_id} lacks typed ownership")
        anchors = ownership.get("start_anchors")
        outputs = ownership.get("planned_outputs")
        if (
            not isinstance(anchors, list)
            or not anchors
            or not isinstance(outputs, list)
            or not outputs
        ):
            raise CatalogError(f"{task_id} lacks anchors or planned outputs")
        for anchor in anchors:
            if not isinstance(anchor, Mapping):
                raise CatalogError(f"{task_id} has an invalid anchor")
            resolver = anchor.get("read_only_resolver_argv")
            if (
                not isinstance(resolver, list)
                or not resolver
                or not all(
                    isinstance(argv, list)
                    and argv
                    and all(isinstance(token, str) and token for token in argv)
                    for argv in resolver
                )
            ):
                raise CatalogError(f"{task_id} anchor lacks resolver-backed commands")
            for field in (
                "locator",
                "planning_status",
                "expected_resolution",
                "evidence_output",
                "stop_rule",
            ):
                _require_text(anchor.get(field), f"{task_id} anchor {field}")
        for output in outputs:
            if not isinstance(output, Mapping) or output.get("producer_task") != task_id:
                raise CatalogError(f"{task_id} has an output without unique producer ownership")
            if not isinstance(output.get("downstream_consumers"), list):
                raise CatalogError(f"{task_id} output lacks downstream consumers")
        predicates = task.get("task_specific_acceptance_predicates")
        if not isinstance(predicates, list) or len(predicates) < 2:
            raise CatalogError(f"{task_id} must have at least two acceptance predicates")
        seen_criteria: set[str] = set()
        for predicate in predicates:
            if not isinstance(predicate, Mapping):
                raise CatalogError(f"{task_id} has an invalid predicate")
            criterion = _require_text(predicate.get("criterion_id"), f"{task_id} criterion")
            if not criterion.startswith(f"{task_id}.A") or criterion in seen_criteria:
                raise CatalogError(f"{task_id} has a duplicate or foreign criterion {criterion}")
            seen_criteria.add(criterion)
            criterion_count += 1
            for field in ("predicate", "command_source", "result_schema", "evidence_path_template"):
                _require_text(predicate.get(field), f"{criterion} {field}")
        manual = task.get("manual_external_irreversible_actions")
        if not isinstance(manual, list) or not manual:
            raise CatalogError(f"{task_id} lacks manual-authority classification")
        handoff = task.get("downstream_handoff")
        if not isinstance(handoff, Mapping) or not isinstance(handoff.get("task_ids"), list):
            raise CatalogError(f"{task_id} lacks downstream handoff")
    for task_id, blocked_by in dependencies.items():
        unknown = set(blocked_by) - ids
        if unknown:
            raise CatalogError(f"{task_id} has unknown dependencies {sorted(unknown)}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise CatalogError(f"dependency cycle includes {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(ids):
        visit(task_id)
    try:
        import jsonschema

        _, schema = _load(schema_path)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(catalog)
    except ImportError:
        pass
    except jsonschema.ValidationError as exc:
        raise CatalogError(f"catalog schema failure: {exc.message}") from exc
    return {
        "criterion_count": criterion_count,
        "packet_revision": catalog.get("packet_revision"),
        "sha256": digest,
        "task_count": len(tasks),
        "verdict": "PASS",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_subparsers(dest="command", required=True)
    check = mode.add_parser("check")
    check.add_argument("--catalog", type=Path, required=True)
    check.add_argument("--schema", type=Path, required=True)
    transcribe = mode.add_parser("transcribe")
    transcribe.add_argument("--source", type=Path, required=True)
    transcribe.add_argument("--out", type=Path, required=True)
    transcribe.add_argument("--schema", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        candidate = args.catalog if args.command == "check" else args.source
        result = validate_catalog(candidate, schema_path=args.schema)
        if args.command == "transcribe":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(args.source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            validate_catalog(args.out, schema_path=args.schema)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (CatalogError, OSError) as exc:
        print(f"work-order catalog invalid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
