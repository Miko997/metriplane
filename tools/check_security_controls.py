# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail-closed validation for the MP2-028 security-control registry."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

REGISTRY_PATH = Path("security-controls.json")
SCHEMA_PATH = Path("schemas/metriplane.security-controls.v1.schema.json")
LEDGER_PATH = Path("docs/status/capability-test-ledger.json")
CATALOG_PATH = Path("docs/status/task-work-orders.json")
THREAT_MODEL_PATH = Path("docs/security/THREAT_MODEL.md")


class SecurityControlError(Exception):
    """Stable validation failure."""


def _fail(message: str) -> NoReturn:
    raise SecurityControlError(message)


def _strict_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _fail(f"cannot read {path}: {exc}")
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(f"{path}: UTF-8 BOM is prohibited")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda token: _fail(f"{path}: non-finite number {token}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{path}: invalid JSON: {exc}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def registry_digest(registry: dict[str, Any]) -> str:
    subject = dict(registry)
    subject.pop("registry_digest", None)
    return hashlib.sha256(_canonical_bytes(subject)).hexdigest()


def _validate_schema(repo: Path, registry: Any, schema: Any) -> None:
    module_path = repo / "tools" / "baseline_snapshot.py"
    spec = importlib.util.spec_from_file_location("security_control_schema_engine", module_path)
    if spec is None or spec.loader is None:
        _fail("cannot load schema engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        module._internal_validate(registry, schema)
    except module.SnapshotError as exc:
        _fail(f"schema validation failed: {exc}")


def _index(rows: Any, kind: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        _fail(f"{kind} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row.get("id") if isinstance(row, dict) else None
        if not isinstance(identifier, str):
            _fail(f"{kind} contains a row without an id")
        if identifier in result:
            _fail(f"duplicate {kind} id: {identifier}")
        result[identifier] = row
    return result


def _tracked_tests(repo: Path) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--", "tests"],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        _fail(f"cannot read tracked test inventory: {completed.stderr.decode('utf-8', 'replace')}")
    try:
        return {value.decode("utf-8", "strict") for value in completed.stdout.split(b"\0") if value}
    except UnicodeDecodeError as exc:
        _fail(f"tracked test inventory is not UTF-8: {exc}")


def _validate_test_path(repo: Path, path_text: str, tracked_tests: set[str]) -> None:
    path = PurePosixPath(path_text)
    if (
        path.is_absolute()
        or path.as_posix() != path_text
        or not path.parts
        or path.parts[0] != "tests"
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail(f"test path is not a normalized repository-relative tests path: {path_text}")
    if path_text not in tracked_tests:
        _fail(f"test path is not tracked in the Git index: {path_text}")
    current = repo
    try:
        for part in path.parts:
            current /= part
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                _fail(f"test path contains a symlink component: {path_text}")
    except OSError as exc:
        _fail(f"cannot inspect test path {path_text}: {exc}")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"test path is not a regular file: {path_text}")


def validate(
    repo: Path,
    *,
    registry_path: Path = REGISTRY_PATH,
    schema_path: Path = SCHEMA_PATH,
    threat_model_path: Path = THREAT_MODEL_PATH,
) -> dict[str, Any]:
    registry = _strict_json(repo / registry_path)
    schema = _strict_json(repo / schema_path)
    ledger = _strict_json(repo / LEDGER_PATH)
    catalog = _strict_json(repo / CATALOG_PATH)
    if (
        not isinstance(registry, dict)
        or not isinstance(schema, dict)
        or not isinstance(ledger, dict)
        or not isinstance(catalog, dict)
    ):
        _fail("registry, schema, ledger and catalog roots must be objects")
    _validate_schema(repo, registry, schema)
    expected_digest = registry_digest(registry)
    if registry.get("registry_digest") != expected_digest:
        _fail("registry_digest does not match canonical registry content")

    boundaries = _index(registry["boundaries"], "boundary")
    assets = _index(registry["assets"], "asset")
    actors = _index(registry["actors"], "actor")
    abuses = _index(registry["abuse_cases"], "abuse case")
    controls = _index(registry["controls"], "control")
    catalog_owners = {
        row.get("task_id")
        for row in catalog.get("tasks", [])
        if isinstance(row, dict) and isinstance(row.get("task_id"), str)
    }
    for kind, rows in (
        ("boundary", boundaries),
        ("asset", assets),
        ("actor", actors),
        ("control", controls),
    ):
        for identifier, row in rows.items():
            if row["owner"] not in catalog_owners:
                _fail(f"{kind} {identifier}: unknown governed owner {row['owner']}")
    references: dict[str, set[str]] = {
        **{key: set() for key in boundaries | assets | actors | controls}
    }
    for abuse_id, abuse in abuses.items():
        for field, index in (
            ("boundary_ids", boundaries),
            ("asset_ids", assets),
            ("actor_ids", actors),
            ("control_ids", controls),
        ):
            for identifier in abuse[field]:
                if identifier not in index:
                    _fail(f"{abuse_id}: unknown {field} reference {identifier}")
                references[identifier].add(abuse_id)
    unused = sorted(identifier for identifier, users in references.items() if not users)
    if unused:
        _fail(f"unreferenced model rows: {', '.join(unused)}")

    ledger_ids = {
        row.get("capability_id")
        for row in ledger.get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("capability_id"), str)
    }
    tracked_tests = _tracked_tests(repo)
    for control_id, control in controls.items():
        missing_capabilities = sorted(set(control["capability_ids"]) - ledger_ids)
        if missing_capabilities:
            _fail(f"{control_id}: unknown capabilities: {', '.join(missing_capabilities)}")
        for path_text in control["test_paths"]:
            try:
                _validate_test_path(repo, path_text, tracked_tests)
            except SecurityControlError as exc:
                _fail(f"{control_id}: {exc}")

    try:
        document = (repo / threat_model_path).read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"cannot read threat model: {exc}")
    required_sections = (
        "## Scope and trust boundaries",
        "## Assets",
        "## Actors",
        "## Abuse cases",
        "## Controls, capabilities and tests",
        "## Residual risk and ownership",
    )
    for heading in required_sections:
        if heading not in document:
            _fail(f"threat model lacks required section {heading!r}")
    for identifier in sorted(boundaries | assets | actors | abuses | controls):
        if f"`{identifier}`" not in document:
            _fail(f"threat model does not reference {identifier}")

    return {
        "schema_version": "metriplane.security-control-check.v1",
        "criteria": registry["criteria"],
        "registry_digest": expected_digest,
        "counts": {
            "boundaries": len(boundaries),
            "assets": len(assets),
            "actors": len(actors),
            "abuse_cases": len(abuses),
            "controls": len(controls),
        },
        "verdict": "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    parser.add_argument("--threat-model", type=Path, default=THREAT_MODEL_PATH)
    args = parser.parse_args(argv)
    try:
        result = validate(
            args.repository_root.resolve(),
            registry_path=args.registry,
            schema_path=args.schema,
            threat_model_path=args.threat_model,
        )
    except SecurityControlError as exc:
        print(f"security-control validation failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
