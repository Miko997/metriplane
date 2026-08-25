# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate the canonical release-blocker registry and enforce release blocking."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import stat
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, TypedDict, cast

SCHEMA_VERSION = "metriplane.blockers.v1"
POLICY_VERSION = "MP2-006.v1"
REPORT_VERSION = "metriplane.blocker-check.v1"
SCHEMA_ID = "https://metriplane.com/schemas/metriplane.blockers.v1.schema.json"
SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


class Evidence(TypedDict):
    path: str
    sha256: str
    kind: str
    producer_actor_id: str


class Approval(TypedDict):
    provider: str
    reviewer_actor_id: str
    reviewer_display_name: str
    approved_at: str
    decision: str
    subject_sha256: str


class Downgrade(TypedDict):
    from_severity: str
    to_severity: str
    from_security: bool
    to_security: bool
    changed_by_actor_id: str
    changed_at: str
    reproduction_evidence: list[Evidence]
    control_evidence: list[Evidence]
    approval: Approval


class Closure(TypedDict):
    closed_by_actor_id: str
    closed_at: str
    resolution_evidence: list[Evidence]
    control_evidence: list[Evidence]
    approval: Approval


class Blocker(TypedDict):
    id: str
    title: str
    owner: str
    reported_by_actor_id: str
    opened_at: str
    initial_severity: str
    severity: str
    initial_security: bool
    security: bool
    status: str
    source: str
    acceptance_ids: list[str]
    downgrade: Downgrade | None
    closure: Closure | None


class Registry(TypedDict):
    schema_version: str
    policy_version: str
    blockers: list[Blocker]


class PolicyInputError(Exception):
    """A stable fail-closed input error."""


def _fail(message: str) -> NoReturn:
    raise PolicyInputError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _strict_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _fail(f"cannot read {path}: {exc}")
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(f"{path}: UTF-8 BOM is prohibited")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        _fail(f"{path}: invalid UTF-8 at byte {exc.start}")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=lambda token: _fail(f"{path}: non-finite number {token}"),
        )
    except json.JSONDecodeError as exc:
        _fail(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}")


@lru_cache(maxsize=1)
def _load_baseline_validator(
    repo_root: Path,
) -> tuple[Callable[[Any, dict[str, Any]], None], type[Exception]]:
    module_path = repo_root / "tools" / "baseline_snapshot.py"
    spec = importlib.util.spec_from_file_location("metriplane_blocker_schema_engine", module_path)
    if spec is None or spec.loader is None:
        _fail(f"cannot load schema engine: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    validator = getattr(module, "_internal_validate", None)
    error_type = getattr(module, "SnapshotError", None)
    if not callable(validator):
        _fail("baseline schema engine does not expose _internal_validate")
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("baseline schema engine does not expose SnapshotError")
    return (
        cast(Callable[[Any, dict[str, Any]], None], validator),
        error_type,
    )


def _validate_schema_contract(schema: dict[str, Any]) -> None:
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        _fail("schema draft identity is not exact")
    if schema.get("$id") != SCHEMA_ID:
        _fail("schema $id is not exact")
    if schema.get("additionalProperties") is not False:
        _fail("registry schema must reject unknown root fields")
    properties = schema.get("properties")
    definitions = schema.get("$defs")
    if not isinstance(properties, dict) or not isinstance(definitions, dict):
        _fail("schema properties and $defs must be objects")
    if set(schema.get("required", [])) != {"schema_version", "policy_version", "blockers"}:
        _fail("registry schema required field set is not exact")
    if properties.get("schema_version") != {"const": SCHEMA_VERSION}:
        _fail("schema_version const is not exact")
    if properties.get("policy_version") != {"const": POLICY_VERSION}:
        _fail("policy_version const is not exact")
    required_definitions = {
        "actor_id",
        "approval",
        "blocker",
        "closure",
        "downgrade",
        "evidence",
        "severity",
        "sha256",
        "timestamp",
    }
    if set(definitions) != required_definitions:
        _fail("schema $defs set is not exact")
    object_fields = {
        "approval": {
            "provider",
            "reviewer_actor_id",
            "reviewer_display_name",
            "approved_at",
            "decision",
            "subject_sha256",
        },
        "blocker": {
            "id",
            "title",
            "owner",
            "reported_by_actor_id",
            "opened_at",
            "initial_severity",
            "severity",
            "initial_security",
            "security",
            "status",
            "source",
            "acceptance_ids",
            "downgrade",
            "closure",
        },
        "closure": {
            "closed_by_actor_id",
            "closed_at",
            "resolution_evidence",
            "control_evidence",
            "approval",
        },
        "downgrade": {
            "from_severity",
            "to_severity",
            "from_security",
            "to_security",
            "changed_by_actor_id",
            "changed_at",
            "reproduction_evidence",
            "control_evidence",
            "approval",
        },
        "evidence": {"path", "sha256", "kind", "producer_actor_id"},
    }
    for name, expected_fields in object_fields.items():
        definition = definitions[name]
        if not isinstance(definition, dict) or definition.get("additionalProperties") is not False:
            _fail(f"schema definition {name!r} must reject unknown fields")
        defined_properties = definition.get("properties")
        if not isinstance(defined_properties, dict):
            _fail(f"schema definition {name!r} properties must be an object")
        if set(defined_properties) != expected_fields or set(definition.get("required", [])) != (
            expected_fields
        ):
            _fail(f"schema definition {name!r} field set is not exact")


def _schema_validate(instance: Any, schema: dict[str, Any]) -> None:
    validator, schema_error = _load_baseline_validator(Path(__file__).resolve().parents[1])
    try:
        validator(instance, schema)
    except schema_error as exc:
        code = getattr(exc, "code", "SCHEMA_VALIDATION_FAILED")
        message = getattr(exc, "message", str(exc))
        _fail(f"{code}: {message}")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _evidence_path(repo_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or relative != pure.as_posix()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        _fail(f"evidence path is not a clean repository-relative path: {relative!r}")
    root = repo_root.resolve(strict=True)
    current = root
    for part in pure.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            _fail(f"evidence path is unavailable: {relative!r}: {exc}")
        if stat.S_ISLNK(mode):
            _fail(f"evidence path contains a symlink: {relative!r}")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"evidence path escapes repository root: {relative!r}")
    if not resolved.is_file():
        _fail(f"evidence path is not a regular file: {relative!r}")
    return resolved


def _check_evidence(
    blocker_id: str,
    records: list[Evidence],
    expected_kind: str,
    repo_root: Path,
    errors: list[str],
) -> None:
    identities = [_canonical_bytes(record) for record in records]
    if len(identities) != len(set(identities)):
        errors.append(f"{blocker_id}: duplicate {expected_kind} evidence record")
    for record in records:
        if record["kind"] != expected_kind:
            errors.append(
                f"{blocker_id}: expected {expected_kind} evidence, found {record['kind']}"
            )
        try:
            path = _evidence_path(repo_root, record["path"])
        except PolicyInputError as exc:
            errors.append(f"{blocker_id}: {exc}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            errors.append(f"{blocker_id}: evidence SHA-256 mismatch: {record['path']}")


def _approval_errors(
    blocker: Blocker,
    approval: Approval,
    actor_id: str,
    subject: dict[str, Any],
    action_at: str,
) -> list[str]:
    prefix = blocker["id"]
    errors: list[str] = []
    reviewer = approval["reviewer_actor_id"]
    if reviewer in {actor_id, blocker["reported_by_actor_id"]}:
        errors.append(f"{prefix}: approval reviewer must be independent of author and reporter")
    if approval["subject_sha256"] != _sha256(subject):
        errors.append(f"{prefix}: approval subject SHA-256 does not bind the exact record")
    if _parse_timestamp(approval["approved_at"]) < _parse_timestamp(action_at):
        errors.append(f"{prefix}: approval predates the action")
    return errors


def _downgrade_subject(blocker_id: str, downgrade: Downgrade) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "action": "downgrade",
        "from_severity": downgrade["from_severity"],
        "to_severity": downgrade["to_severity"],
        "from_security": downgrade["from_security"],
        "to_security": downgrade["to_security"],
        "changed_by_actor_id": downgrade["changed_by_actor_id"],
        "changed_at": downgrade["changed_at"],
        "reproduction_evidence": downgrade["reproduction_evidence"],
        "control_evidence": downgrade["control_evidence"],
    }


def _closure_subject(blocker_id: str, closure: Closure) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "action": "closure",
        "closed_by_actor_id": closure["closed_by_actor_id"],
        "closed_at": closure["closed_at"],
        "resolution_evidence": closure["resolution_evidence"],
        "control_evidence": closure["control_evidence"],
    }


def _check_downgrade(blocker: Blocker, repo_root: Path, errors: list[str]) -> None:
    initial_rank = SEVERITY_RANK[blocker["initial_severity"]]
    current_rank = SEVERITY_RANK[blocker["severity"]]
    needed = current_rank > initial_rank or (
        blocker["initial_security"] and not blocker["security"]
    )
    downgrade = blocker["downgrade"]
    if downgrade is None:
        if needed:
            errors.append(f"{blocker['id']}: downgrade requires a governed downgrade record")
        return
    if not needed:
        errors.append(
            f"{blocker['id']}: downgrade record exists without a classification downgrade"
        )
    expected = (
        blocker["initial_severity"],
        blocker["severity"],
        blocker["initial_security"],
        blocker["security"],
    )
    actual = (
        downgrade["from_severity"],
        downgrade["to_severity"],
        downgrade["from_security"],
        downgrade["to_security"],
    )
    if actual != expected:
        errors.append(
            f"{blocker['id']}: downgrade transition does not match blocker classifications"
        )
    if _parse_timestamp(downgrade["changed_at"]) < _parse_timestamp(blocker["opened_at"]):
        errors.append(f"{blocker['id']}: downgrade predates blocker creation")
    _check_evidence(
        blocker["id"], downgrade["reproduction_evidence"], "reproduction", repo_root, errors
    )
    _check_evidence(blocker["id"], downgrade["control_evidence"], "control", repo_root, errors)
    errors.extend(
        _approval_errors(
            blocker,
            downgrade["approval"],
            downgrade["changed_by_actor_id"],
            _downgrade_subject(blocker["id"], downgrade),
            downgrade["changed_at"],
        )
    )


def _check_closure(blocker: Blocker, repo_root: Path, errors: list[str]) -> None:
    closure = blocker["closure"]
    if blocker["status"] == "closed" and closure is None:
        errors.append(f"{blocker['id']}: closed status requires a governed closure record")
        return
    if blocker["status"] != "closed" and closure is not None:
        errors.append(f"{blocker['id']}: closure record requires closed status")
        return
    if closure is None:
        return
    if _parse_timestamp(closure["closed_at"]) < _parse_timestamp(blocker["opened_at"]):
        errors.append(f"{blocker['id']}: closure predates blocker creation")
    downgrade = blocker["downgrade"]
    if downgrade is not None and _parse_timestamp(closure["closed_at"]) < _parse_timestamp(
        downgrade["changed_at"]
    ):
        errors.append(f"{blocker['id']}: closure predates downgrade")
    _check_evidence(blocker["id"], closure["resolution_evidence"], "resolution", repo_root, errors)
    _check_evidence(blocker["id"], closure["control_evidence"], "control", repo_root, errors)
    errors.extend(
        _approval_errors(
            blocker,
            closure["approval"],
            closure["closed_by_actor_id"],
            _closure_subject(blocker["id"], closure),
            closure["closed_at"],
        )
    )


def validate_registry(registry: Registry, repo_root: Path) -> tuple[list[str], list[str]]:
    """Return sorted semantic errors and release-blocking IDs."""
    errors: list[str] = []
    blockers = registry["blockers"]
    ids = [blocker["id"] for blocker in blockers]
    if len(ids) != len(set(ids)):
        errors.append("registry contains duplicate blocker IDs")
    if ids != sorted(ids):
        errors.append("registry blocker IDs must be sorted lexicographically")
    for blocker in blockers:
        if blocker["acceptance_ids"] != sorted(blocker["acceptance_ids"]):
            errors.append(f"{blocker['id']}: acceptance_ids must be sorted")
        _check_downgrade(blocker, repo_root, errors)
        _check_closure(blocker, repo_root, errors)
    blocking_ids = sorted(
        blocker["id"]
        for blocker in blockers
        if blocker["status"] != "closed"
        and (blocker["severity"] in {"P0", "P1"} or blocker["security"])
    )
    return sorted(errors), blocking_ids


def _report(
    registry_path: Path,
    *,
    errors: list[str],
    blocking_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": REPORT_VERSION,
        "registry": registry_path.as_posix(),
        "valid": not errors,
        "release_blocked": bool(blocking_ids) if not errors else True,
        "blocking_ids": blocking_ids,
        "error_count": len(errors),
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("docs/status/blockers.json"))
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/metriplane.blockers.v1.schema.json")
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    registry_path = cast(Path, args.registry)
    schema_path = cast(Path, args.schema)
    repo_root = cast(Path, args.repo_root)
    try:
        raw_schema = _strict_json(schema_path)
        if not isinstance(raw_schema, dict):
            _fail("schema root must be an object")
        schema = cast(dict[str, Any], raw_schema)
        _validate_schema_contract(schema)
        raw_registry = _strict_json(registry_path)
        _schema_validate(raw_registry, schema)
        registry = cast(Registry, raw_registry)
        errors, blocking_ids = validate_registry(registry, repo_root)
    except (PolicyInputError, OSError) as exc:
        errors = [str(exc)]
        blocking_ids = []
    report = _report(registry_path, errors=errors, blocking_ids=blocking_ids)
    if args.json:
        print(_canonical_bytes(report).decode("utf-8"))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    elif blocking_ids:
        print("Release blocked by: " + ", ".join(blocking_ids))
    else:
        print("Release blocker policy passed.")
    if errors:
        return 2
    if blocking_ids:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
