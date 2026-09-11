# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from metriplane.release_control import canonical_json, sha256_json

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "materialize_task_work_order.py"
VALIDATOR = ROOT / "tools" / "validate_task_work_order.py"
CATALOG = json.loads((ROOT / "docs/status/task-work-orders.json").read_bytes())


def _write(path: Path, value: object) -> Path:
    path.write_bytes(canonical_json(value))
    return path


def _resolution() -> dict[str, object]:
    task = next(row for row in CATALOG["tasks"] if row["task_id"] == "MP2-016")

    def groups(rows: list[dict[str, object]], key: str, prefix: str) -> list[dict[str, object]]:
        return [
            {
                "destinations": [
                    {
                        "consumers": ["MP2-018"],
                        "owner": "MP2-016",
                        "path": f"resolved/{prefix}/{index}.json",
                        "schema_or_media_type": "application/json",
                        "state": "CREATE",
                        "validator": "fixture-validator",
                    }
                ],
                "locator": row[key],
            }
            for index, row in enumerate(rows)
        ]

    return {
        "anchors": groups(task["ownership"]["start_anchors"], "locator", "anchor"),
        "outputs": groups(task["ownership"]["planned_outputs"], "path_or_resolver", "output"),
        "status": "RESOLVED",
        "task_id": "MP2-016",
    }


def _inputs(tmp_path: Path) -> dict[str, Path]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    subject = {
        "actor_id": "fixture-actor",
        "authority": "disposable MP2-016 test assignment",
        "base_sha": head,
        "linear_issue": "MET-90",
        "task_id": "MP2-016",
    }
    subject_digest = sha256_json(subject)
    signed = canonical_json(
        {"actor_id": "fixture-actor", "provider": "linear", "subject_digest": subject_digest}
    )
    assignment = {
        "schema_version": "metriplane.task-assignment.v1",
        "signature": {
            "actor_id": "fixture-actor",
            "provider": "linear",
            "signature": private.sign(signed).hex(),
        },
        "subject": subject,
        "subject_digest": subject_digest,
    }
    issue = {row["task_id"]: row["linear_issue"] for row in CATALOG["tasks"]}
    edges = sorted(
        [
            {"blocked": row["linear_issue"], "blocker": issue[dependency]}
            for row in CATALOG["tasks"]
            for dependency in row["authoritative_blocked_by"]
        ],
        key=lambda row: (row["blocker"], row["blocked"]),
    )
    criteria = [f"MP2-016.A{index:02d}" for index in range(1, 9)]
    return {
        "assignment": _write(tmp_path / "assignment.json", assignment),
        "keyring": _write(
            tmp_path / "keyring.json",
            {
                "keys": [
                    {
                        "actor_id": "fixture-actor",
                        "provider": "linear",
                        "public_key_hex": public.hex(),
                    }
                ],
                "schema_version": "metriplane.provider-attestation-keyring.v1",
            },
        ),
        "linear": _write(
            tmp_path / "linear.json",
            {"edges": edges, "event_cursor": "fixture-cursor", "provider_status": "available"},
        ),
        "dependencies": _write(
            tmp_path / "dependencies.json",
            {
                "dependencies": [
                    {
                        "artifact_sha256": "1" * 64,
                        "merged_at_base": True,
                        "task_id": "MP2-014",
                        "validator": "fixture-validator",
                    }
                ]
            },
        ),
        "commands": _write(
            tmp_path / "commands.json",
            {
                "commands": [
                    {
                        "argv": [sys.executable, "-m", "pytest", "-q"],
                        "command_id": "MP2-016.CMD.ACCEPTANCE",
                        "criterion_ids": criteria,
                        "cwd": str(ROOT),
                        "environment": {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                        "expected_exit": 0,
                        "expected_outputs": [],
                        "resources": [],
                    }
                ],
                "task_id": "MP2-016",
            },
        ),
        "resolution": _write(tmp_path / "resolution.json", _resolution()),
    }


def _run(tmp_path: Path, inputs: dict[str, Path], *, out: str = "work-order.json"):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--repository-root",
            str(ROOT),
            "--task-id",
            "MP2-016",
            "--base-sha",
            head,
            "--catalog",
            "docs/status/task-work-orders.json",
            "--catalog-schema",
            "schemas/metriplane.mp2-work-order-set.v1.schema.json",
            "--assignment",
            str(inputs["assignment"]),
            "--assignment-schema",
            "schemas/metriplane.task-assignment.v1.schema.json",
            "--keyring",
            str(inputs["keyring"]),
            "--linear-snapshot",
            str(inputs["linear"]),
            "--dependency-evidence",
            str(inputs["dependencies"]),
            "--command-registry",
            str(inputs["commands"]),
            "--resolution",
            str(inputs["resolution"]),
            "--out",
            str(tmp_path / out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _validate(tmp_path: Path, inputs: dict[str, Path], work_order: Path):
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--work-order",
            str(work_order),
            "--schema",
            str(ROOT / "schemas/metriplane.task-work-order.v1.schema.json"),
            "--assignment-schema",
            str(ROOT / "schemas/metriplane.task-assignment.v1.schema.json"),
            "--catalog",
            str(ROOT / "docs/status/task-work-orders.json"),
            "--catalog-schema",
            str(ROOT / "schemas/metriplane.mp2-work-order-set.v1.schema.json"),
            "--keyring",
            str(inputs["keyring"]),
            "--out",
            str(tmp_path / "validation.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_materializes_exact_ready_work_order_deterministically(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    assert _run(tmp_path, inputs, out="first.json").returncode == 0
    assert _run(tmp_path, inputs, out="second.json").returncode == 0
    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()
    payload = json.loads((tmp_path / "first.json").read_bytes())
    assert payload["verdict"] == "READY"
    assert payload["task_id"] == "MP2-016"
    assert payload["materialization_id"] == sha256_json(
        {key: value for key, value in payload.items() if key != "materialization_id"}
    )


def test_rejects_missing_live_relation(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    snapshot = json.loads(inputs["linear"].read_bytes())
    snapshot["edges"].pop()
    _write(inputs["linear"], snapshot)
    assert _run(tmp_path, inputs).returncode == 3
    assert not (tmp_path / "work-order.json").exists()


def test_provider_outage_has_distinct_exit(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    snapshot = json.loads(inputs["linear"].read_bytes())
    snapshot["provider_status"] = "outage"
    _write(inputs["linear"], snapshot)
    assert _run(tmp_path, inputs).returncode == 4


def test_tampered_assignment_is_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    assignment = json.loads(inputs["assignment"].read_bytes())
    assignment["subject"]["actor_id"] = "substituted"
    _write(inputs["assignment"], assignment)
    assert _run(tmp_path, inputs).returncode == 2


def test_work_order_is_never_overwritten(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    assert _run(tmp_path, inputs).returncode == 0
    assert _run(tmp_path, inputs).returncode == 3


def test_independent_validator_rejects_substituted_manifest(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    assert _run(tmp_path, inputs).returncode == 0
    work_order = tmp_path / "work-order.json"
    assert _validate(tmp_path, inputs, work_order).returncode == 0
    assert json.loads((tmp_path / "validation.json").read_bytes())["verdict"] == "READY"

    changed = json.loads(work_order.read_bytes())
    changed["base_sha"] = "0" * 40
    _write(tmp_path / "substituted.json", changed)
    (tmp_path / "validation.json").unlink()
    assert _validate(tmp_path, inputs, tmp_path / "substituted.json").returncode == 2
    assert not (tmp_path / "validation.json").exists()
