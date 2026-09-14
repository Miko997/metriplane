# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Build and execute the MP2-015 supported/compatibility behavior registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

INVENTORY_PATH: Final = Path("docs/status/functional-inventory.json")
REGISTRY_PATH: Final = Path("docs/status/behavior-characterization.json")
SCHEMA_PATH: Final = Path("schemas/metriplane.behavior-characterization.v1.schema.json")
SCHEMA_VERSION: Final = "metriplane.behavior-characterization.v1"
INVALID_OPTION: Final = "--mp2-015-invalid-option"
CLAIM_CLASSES: Final = frozenset({"compatibility", "supported"})


class CharacterizationError(ValueError):
    """A deterministic registry or executable behavior check failed."""


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise CharacterizationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CharacterizationError(f"{path} must contain an object")
    return value


def _scenario(argv: list[str], *, success: bool) -> dict[str, Any]:
    return {
        "argv": argv,
        "exit_code": 0 if success else 2,
        "filesystem": {"created": [], "modified": [], "removed": []},
        "state": "unchanged",
        "stderr": {
            "contains": [] if success else ["usage:", "error:"],
            "empty": success,
            "format": "text",
        },
        "stdout": {
            "contains": ["usage:"] if success else [],
            "empty": not success,
            "format": "text",
        },
    }


def build_registry(root: Path) -> dict[str, Any]:
    inventory = _read(root / INVENTORY_PATH)
    rows: list[dict[str, Any]] = []
    for source in inventory.get("rows", []):
        claim = source.get("claim", {})
        if (
            source.get("status") not in {"active", "deprecated"}
            or claim.get("classification") not in CLAIM_CLASSES
        ):
            continue
        name = str(source["name"])
        argv = name.split()
        implicit = source["kind"] == "cli_implicit_config"
        if implicit:
            success = {
                "argv": ["metriplane", "--config", "{valid_config}"],
                "exit_code": 0,
                "filesystem": {
                    "created": ["{declared_run_outputs}"],
                    "modified": [],
                    "removed": [],
                },
                "state": "declared_outputs_only",
                "stderr": {"contains": [], "empty": True, "format": "text"},
                "stdout": {"contains": [], "empty": True, "format": "text"},
            }
            failure = _scenario(["metriplane", "--config", "{missing_config}"], success=False)
            failure["exit_code"] = 1
            failure["stderr"]["contains"] = ["traceback", "filenotfounderror"]
        else:
            success = _scenario([*argv, "--help"], success=True)
            failure = _scenario([*argv, INVALID_OPTION], success=False)
        rows.append(
            {
                "claim_classification": claim["classification"],
                "failure": failure,
                "kind": source["kind"],
                "profile_id": source["profile"],
                "retained_obligation_id": source["test"],
                "row_digest": _digest(source),
                "row_id": source["id"],
                "success": success,
            }
        )
    rows.sort(key=lambda item: item["row_id"])
    return {
        "criteria": ["MP2-015.A01", "MP2-015.A02"],
        "inventory_path": INVENTORY_PATH.as_posix(),
        "governed_rows_sha256": _digest(
            [
                source
                for source in inventory["rows"]
                if source.get("status") in {"active", "deprecated"}
                and source.get("claim", {}).get("classification") in CLAIM_CLASSES
            ]
        ),
        "obligations": [
            "MP2-015.OBL.CHARACTERIZATION",
            "MP2-015.OBL.COMPATIBILITY_RETENTION",
            "MP2-015.OBL.DETERMINISM",
            "MP2-015.OBL.NEGATIVE",
            "MP2-015.OBL.CLEAN",
        ],
        "owner": "MP2-015",
        "row_count": len(rows),
        "rows": rows,
        "rows_sha256": _digest(rows),
        "schema_path": SCHEMA_PATH.as_posix(),
        "schema_version": SCHEMA_VERSION,
    }


def validate_registry(root: Path, registry: Mapping[str, Any]) -> None:
    expected = build_registry(root)
    if _canonical(registry) != _canonical(expected):
        raise CharacterizationError("behavior characterization is stale or incomplete")
    try:
        import jsonschema

        schema = _read(root / SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(registry)
    except ImportError:
        return
    except jsonschema.ValidationError as exc:
        raise CharacterizationError(
            f"behavior characterization schema failure: {exc.message}"
        ) from exc


def _files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }


def execute_programs(
    root: Path,
    programs: Mapping[str, Path],
    *,
    registry: Mapping[str, Any] | None = None,
) -> int:
    document = dict(registry or _read(root / REGISTRY_PATH))
    validate_registry(root, document)
    executed = 0
    for row in document["rows"]:
        if row["kind"] == "cli_implicit_config":
            continue
        program_name = row["success"]["argv"][0]
        program = programs.get(program_name)
        if program is None:
            continue
        for scenario_name in ("success", "failure"):
            expected = row[scenario_name]
            with tempfile.TemporaryDirectory(prefix="mp2015-characterization-") as temporary:
                scratch = Path(temporary)
                env = {**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"}
                for name in (
                    "HOME",
                    "TMPDIR",
                    "XDG_CACHE_HOME",
                    "XDG_CONFIG_HOME",
                    "XDG_DATA_HOME",
                    "XDG_STATE_HOME",
                ):
                    env[name] = str(scratch / name.lower())
                before = _files(scratch)
                process = subprocess.run(
                    [str(program), *expected["argv"][1:]],
                    cwd=scratch,
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                after = _files(scratch)
            if process.returncode != expected["exit_code"]:
                raise CharacterizationError(
                    f"{row['row_id']} {scenario_name} exit {process.returncode}; "
                    f"expected {expected['exit_code']}"
                )
            for channel_name, actual in (("stdout", process.stdout), ("stderr", process.stderr)):
                channel = expected[channel_name]
                if bool(actual) == bool(channel["empty"]):
                    raise CharacterizationError(
                        f"{row['row_id']} {scenario_name} {channel_name} emptiness drift"
                    )
                lowered = actual.lower()
                if any(fragment not in lowered for fragment in channel["contains"]):
                    raise CharacterizationError(
                        f"{row['row_id']} {scenario_name} {channel_name} content drift"
                    )
            if before != after:
                raise CharacterizationError(
                    f"{row['row_id']} {scenario_name} wrote unexpected files: {sorted(after - before)}"
                )
            executed += 1
    return executed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repository_root.resolve(strict=True)
    candidate = build_registry(root)
    if args.write:
        (root / REGISTRY_PATH).write_bytes(_canonical(candidate))
    else:
        validate_registry(root, _read(root / REGISTRY_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
