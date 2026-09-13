# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from metriplane.release_control import canonical_json, sha256_json
from tools.task_delegation import delegation_id, key_id, tracker_snapshot_digest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "materialize_task_work_order.py"
VALIDATOR = ROOT / "tools" / "validate_task_work_order.py"
CATALOG = json.loads((ROOT / "docs/status/task-work-orders.json").read_bytes())
REPOSITORY = "Miko997/metriplane"
PROJECT_ID = "cf53f98f-0965-4360-a66e-530457e40354"
GRANTOR = "miko"
EXECUTOR = "01a096e0-4e21-7a11-9f0f-fb303387c5c0"
OTHER_EXECUTOR = "11111111-1111-4111-8111-111111111111"
EVALUATED_AT = "2026-09-13T00:30:00Z"
VALIDATED_AT = "2026-09-13T00:31:00Z"
_NODE_KEYGEN = r"""
const crypto = require("node:crypto");
const {privateKey, publicKey} = crypto.generateKeyPairSync("ed25519");
const publicDer = publicKey.export({format: "der", type: "spki"});
const privateDer = privateKey.export({format: "der", type: "pkcs8"});
const prefix = Buffer.from("302a300506032b6570032100", "hex");
if (!publicDer.subarray(0, prefix.length).equals(prefix) || publicDer.length !== prefix.length + 32) {
  process.exit(2);
}
process.stdout.write(JSON.stringify({
  private_key_pkcs8: privateDer.toString("base64"),
  public_key_hex: publicDer.subarray(prefix.length).toString("hex"),
}));
"""
_NODE_SIGN = r"""
const crypto = require("node:crypto");
const fs = require("node:fs");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const privateKey = crypto.createPrivateKey({
  key: Buffer.from(input.private_key_pkcs8, "base64"),
  format: "der",
  type: "pkcs8",
});
process.stdout.write(crypto.sign(null, Buffer.from(input.message, "base64"), privateKey).toString("hex"));
"""


@dataclass
class Fixture:
    paths: dict[str, Path]
    private_key_pkcs8: str


def _write(path: Path, value: object) -> Path:
    path.write_bytes(canonical_json(value))
    return path


def _keypair() -> tuple[str, str]:
    completed = subprocess.run(
        ["node", "--eval", _NODE_KEYGEN],
        capture_output=True,
        check=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    return value["private_key_pkcs8"], value["public_key_hex"]


def _signature(private_key_pkcs8: str, *, actor_id: str, subject_digest: str) -> str:
    message = canonical_json(
        {"actor_id": actor_id, "provider": "linear", "subject_digest": subject_digest}
    )
    completed = subprocess.run(
        ["node", "--eval", _NODE_SIGN],
        input=json.dumps(
            {
                "message": base64.b64encode(message).decode("ascii"),
                "private_key_pkcs8": private_key_pkcs8,
            }
        ),
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout


def _resolution() -> dict[str, object]:
    task = next(row for row in CATALOG["tasks"] if row["task_id"] == "MP2-016")

    def groups(rows: list[dict[str, Any]], key: str, prefix: str) -> list[dict[str, object]]:
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


def _relations() -> list[dict[str, str]]:
    issue = {row["task_id"]: row["linear_issue"] for row in CATALOG["tasks"]}
    return sorted(
        [
            {"blocked": row["linear_issue"], "blocker": issue[dependency]}
            for row in CATALOG["tasks"]
            for dependency in row["authoritative_blocked_by"]
        ],
        key=lambda row: (row["blocker"], row["blocked"]),
    )


def _snapshot(
    *, head: str, grantor: str, executor: str, synthetic: bool, delegation_id_value: str
) -> dict[str, Any]:
    return {
        "captured_at": "2026-09-13T00:29:30Z",
        "edges": _relations(),
        "event_cursor": "fixture-cursor-1",
        "project_id": PROJECT_ID,
        "provider_status": "available",
        "repository": REPOSITORY,
        "schema_version": "metriplane.linear-work-order-snapshot.v1",
        "synthetic": synthetic,
        "task": {
            "assignee_actor_id": grantor,
            "base_sha": head,
            "delegate_executor_id": executor,
            "delegation_event_id": "fixture-event-1",
            "delegation_id": delegation_id_value,
            "delegation_status": "active",
            "issue_state": "started",
            "linear_issue": "MET-90",
            "task_id": "MP2-016",
        },
    }


def _inputs(
    tmp_path: Path,
    *,
    grantor: str = GRANTOR,
    executor: str = EXECUTOR,
    synthetic: bool = True,
    trust_class: str = "fixture",
) -> Fixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    private_key_pkcs8, public_key_hex = _keypair()
    signing_key_id = key_id(public_key_hex)
    authority = {
        "keys": [
            {
                "actor_id": grantor,
                "key_id": signing_key_id,
                "not_after": "2026-09-14T00:00:00Z",
                "not_before": "2026-09-12T00:00:00Z",
                "project_id": PROJECT_ID,
                "provider": "linear",
                "public_key_hex": public_key_hex,
                "repository": REPOSITORY,
                "role": "repository_owner",
                "status": "active",
                "trust_class": trust_class,
            }
        ],
        "revoked_delegation_ids": [],
        "schema_version": "metriplane.task-delegation-authority.v1",
    }
    snapshot = _snapshot(
        head=head,
        grantor=grantor,
        executor=executor,
        synthetic=synthetic,
        delegation_id_value="0" * 64,
    )
    subject: dict[str, Any] = {
        "delegate": {"executor_id": executor, "kind": "codex_goal"},
        "expires_at": "2026-09-13T02:00:00Z",
        "grantor": {
            "actor_id": grantor,
            "provider": "linear",
            "role": "repository_owner",
        },
        "issued_at": "2026-09-13T00:00:00Z",
        "max_snapshot_age_seconds": 600,
        "scope": {
            "authority": "execute the bounded MP2-016 contract correction",
            "base_sha": head,
            "base_tree": tree,
            "linear_issue": "MET-90",
            "project_id": PROJECT_ID,
            "repository": REPOSITORY,
            "task_id": "MP2-016",
        },
        "signing_key_id": signing_key_id,
        "tracker_snapshot_digest": tracker_snapshot_digest(snapshot),
        "tracker": {
            "event_cursor": "fixture-cursor-1",
            "event_id": "fixture-event-1",
            "provider": "linear",
        },
    }
    subject["delegation_id"] = delegation_id(subject)
    snapshot["task"]["delegation_id"] = subject["delegation_id"]
    subject_digest = sha256_json(subject)
    delegation = {
        "schema_version": "metriplane.task-delegation.v1",
        "signature": {
            "actor_id": grantor,
            "key_id": signing_key_id,
            "provider": "linear",
            "signature": _signature(
                private_key_pkcs8, actor_id=grantor, subject_digest=subject_digest
            ),
        },
        "subject": subject,
        "subject_digest": subject_digest,
        "synthetic": synthetic,
    }
    task = next(row for row in CATALOG["tasks"] if row["task_id"] == "MP2-016")
    criteria = [row["criterion_id"] for row in task["task_specific_acceptance_predicates"]]
    paths = {
        "authority": _write(tmp_path / "authority.json", authority),
        "delegation": _write(tmp_path / "delegation.json", delegation),
        "linear": _write(tmp_path / "linear.json", snapshot),
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
    return Fixture(paths=paths, private_key_pkcs8=private_key_pkcs8)


def _resign(fixture: Fixture, mutate: Any) -> None:
    delegation = json.loads(fixture.paths["delegation"].read_bytes())
    mutate(delegation)
    subject = delegation["subject"]
    subject["delegation_id"] = delegation_id(subject)
    delegation["subject_digest"] = sha256_json(subject)
    delegation["signature"]["signature"] = _signature(
        fixture.private_key_pkcs8,
        actor_id=delegation["signature"]["actor_id"],
        subject_digest=delegation["subject_digest"],
    )
    _write(fixture.paths["delegation"], delegation)


def _bind_snapshot(fixture: Fixture) -> None:
    delegation = json.loads(fixture.paths["delegation"].read_bytes())
    snapshot = json.loads(fixture.paths["linear"].read_bytes())
    subject = delegation["subject"]
    subject["tracker_snapshot_digest"] = tracker_snapshot_digest(snapshot)
    subject["delegation_id"] = delegation_id(subject)
    snapshot["task"]["delegation_id"] = subject["delegation_id"]
    delegation["subject_digest"] = sha256_json(subject)
    delegation["signature"]["signature"] = _signature(
        fixture.private_key_pkcs8,
        actor_id=delegation["signature"]["actor_id"],
        subject_digest=delegation["subject_digest"],
    )
    _write(fixture.paths["linear"], snapshot)
    _write(fixture.paths["delegation"], delegation)


def _run(
    tmp_path: Path,
    fixture: Fixture,
    *,
    out: str = "work-order.json",
    base_sha: str | None = None,
    grantor: str = GRANTOR,
    executor: str = EXECUTOR,
    fixture_mode: bool = True,
) -> subprocess.CompletedProcess[str]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    argv = [
        sys.executable,
        str(TOOL),
        "--repository-root",
        str(ROOT),
        "--task-id",
        "MP2-016",
        "--base-sha",
        base_sha or head,
        "--repository",
        REPOSITORY,
        "--linear-project-id",
        PROJECT_ID,
        "--grantor-id",
        grantor,
        "--executor-id",
        executor,
        "--evaluated-at",
        EVALUATED_AT,
        "--catalog",
        "docs/status/task-work-orders.json",
        "--catalog-schema",
        "schemas/metriplane.mp2-work-order-set.v1.schema.json",
        "--delegation",
        str(fixture.paths["delegation"]),
        "--delegation-schema",
        "schemas/metriplane.task-delegation.v1.schema.json",
        "--authority-keyring",
        str(fixture.paths["authority"]),
        "--authority-keyring-schema",
        "schemas/metriplane.task-delegation-authority.v1.schema.json",
        "--linear-snapshot",
        str(fixture.paths["linear"]),
        "--linear-snapshot-schema",
        "schemas/metriplane.linear-work-order-snapshot.v1.schema.json",
        "--dependency-evidence",
        str(fixture.paths["dependencies"]),
        "--command-registry",
        str(fixture.paths["commands"]),
        "--resolution",
        str(fixture.paths["resolution"]),
        "--out",
        str(tmp_path / out),
    ]
    if fixture_mode:
        argv.append("--fixture-mode")
    return subprocess.run(argv, check=False, capture_output=True, text=True)


def _validate(
    tmp_path: Path,
    fixture: Fixture,
    work_order: Path,
    *,
    out: str = "validation.json",
    validated_at: str = VALIDATED_AT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--work-order",
            str(work_order),
            "--schema",
            str(ROOT / "schemas/metriplane.task-work-order.v2.schema.json"),
            "--catalog",
            str(ROOT / "docs/status/task-work-orders.json"),
            "--catalog-schema",
            str(ROOT / "schemas/metriplane.mp2-work-order-set.v1.schema.json"),
            "--repository-root",
            str(ROOT),
            "--delegation",
            str(fixture.paths["delegation"]),
            "--delegation-schema",
            str(ROOT / "schemas/metriplane.task-delegation.v1.schema.json"),
            "--authority-keyring",
            str(fixture.paths["authority"]),
            "--authority-keyring-schema",
            str(ROOT / "schemas/metriplane.task-delegation-authority.v1.schema.json"),
            "--linear-snapshot",
            str(fixture.paths["linear"]),
            "--linear-snapshot-schema",
            str(ROOT / "schemas/metriplane.linear-work-order-snapshot.v1.schema.json"),
            "--dependency-evidence",
            str(fixture.paths["dependencies"]),
            "--command-registry",
            str(fixture.paths["commands"]),
            "--resolution",
            str(fixture.paths["resolution"]),
            "--repository",
            REPOSITORY,
            "--linear-project-id",
            PROJECT_ID,
            "--grantor-id",
            GRANTOR,
            "--executor-id",
            EXECUTOR,
            "--validated-at",
            validated_at,
            "--fixture-mode",
            "--out",
            str(tmp_path / out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_valid_miko_to_codex_delegation_materializes_and_validates_ready(
    tmp_path: Path,
) -> None:
    fixture = _inputs(tmp_path)
    assert _run(tmp_path, fixture, out="first.json").returncode == 0
    assert _run(tmp_path, fixture, out="second.json").returncode == 0
    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()
    payload = json.loads((tmp_path / "first.json").read_bytes())
    assert payload["verdict"] == "READY"
    assert payload["grantor_id"] == GRANTOR
    assert payload["executor_id"] == EXECUTOR
    assert payload["materialization_id"] == sha256_json(
        {key: value for key, value in payload.items() if key != "materialization_id"}
    )
    assert _validate(tmp_path, fixture, tmp_path / "first.json").returncode == 0


def test_delegate_cannot_self_grant(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path, grantor=EXECUTOR)
    assert _run(tmp_path, fixture, grantor=EXECUTOR).returncode == 2


def test_wrong_grantor_and_wrong_delegate_are_rejected(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    assert _run(tmp_path, fixture, out="grantor.json", grantor="another-owner").returncode == 2
    assert _run(tmp_path, fixture, out="delegate.json", executor=OTHER_EXECUTOR).returncode == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "MP2-017"),
        ("repository", "Miko997/substituted"),
        ("base_sha", "0" * 40),
    ],
)
def test_wrong_signed_scope_is_rejected(tmp_path: Path, field: str, value: str) -> None:
    fixture = _inputs(tmp_path)
    _resign(fixture, lambda row: row["subject"]["scope"].__setitem__(field, value))
    assert _run(tmp_path, fixture).returncode == 2


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("expires_at", "2026-09-13T00:30:00Z", 3),
        ("issued_at", "2026-09-13T00:31:00Z", 2),
        ("issued_at", "2026-09-13T00:00:00+00:00", 2),
    ],
)
def test_invalid_or_inactive_delegation_time_is_rejected(
    tmp_path: Path, field: str, value: str, expected: int
) -> None:
    fixture = _inputs(tmp_path)
    _resign(fixture, lambda row: row["subject"].__setitem__(field, value))
    assert _run(tmp_path, fixture).returncode == expected


def test_altered_payload_is_rejected(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    delegation = json.loads(fixture.paths["delegation"].read_bytes())
    delegation["subject"]["scope"]["authority"] = "altered"
    _write(fixture.paths["delegation"], delegation)
    assert _run(tmp_path, fixture).returncode == 2

    fixture = _inputs(tmp_path / "snapshot-tamper")
    snapshot = json.loads(fixture.paths["linear"].read_bytes())
    snapshot["captured_at"] = "2026-09-13T00:29:31Z"
    _write(fixture.paths["linear"], snapshot)
    assert _run(tmp_path, fixture, out="snapshot-tamper.json").returncode == 2


def test_altered_signature_is_rejected(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    delegation = json.loads(fixture.paths["delegation"].read_bytes())
    signature = delegation["signature"]["signature"]
    delegation["signature"]["signature"] = ("0" if signature[0] != "0" else "1") + signature[1:]
    _write(fixture.paths["delegation"], delegation)
    assert _run(tmp_path, fixture).returncode == 2


@pytest.mark.parametrize("mode", ["unknown", "revoked", "untrusted-live"])
def test_key_fail_closed_modes(tmp_path: Path, mode: str) -> None:
    fixture = _inputs(tmp_path)
    authority = json.loads(fixture.paths["authority"].read_bytes())
    if mode == "unknown":
        authority["keys"][0]["actor_id"] = "unrelated-owner"
    elif mode == "revoked":
        authority["keys"][0]["status"] = "revoked"
    else:
        delegation = json.loads(fixture.paths["delegation"].read_bytes())
        delegation["synthetic"] = False
        _write(fixture.paths["delegation"], delegation)
        snapshot = json.loads(fixture.paths["linear"].read_bytes())
        snapshot["synthetic"] = False
        _write(fixture.paths["linear"], snapshot)
    _write(fixture.paths["authority"], authority)
    completed = _run(tmp_path, fixture, fixture_mode=mode != "untrusted-live")
    assert completed.returncode in {2, 3}


def test_revoked_delegation_is_not_ready(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    authority = json.loads(fixture.paths["authority"].read_bytes())
    delegation = json.loads(fixture.paths["delegation"].read_bytes())
    authority["revoked_delegation_ids"] = [delegation["subject"]["delegation_id"]]
    _write(fixture.paths["authority"], authority)
    assert _run(tmp_path, fixture).returncode == 3


def test_synthetic_fixture_cannot_supply_live_authority(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    assert _run(tmp_path, fixture, fixture_mode=False).returncode == 2


def test_arbitrary_production_keyring_cannot_bootstrap_live_authority(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path, synthetic=False, trust_class="production")
    assert _run(tmp_path, fixture, fixture_mode=False).returncode == 2


def test_stale_snapshot_and_missing_live_relation_are_not_ready(tmp_path: Path) -> None:
    stale = tmp_path / "stale"
    fixture = _inputs(stale)
    snapshot = json.loads(fixture.paths["linear"].read_bytes())
    snapshot["captured_at"] = "2026-09-13T00:00:00Z"
    _write(fixture.paths["linear"], snapshot)
    _bind_snapshot(fixture)
    assert _run(tmp_path, fixture, out="stale.json").returncode == 3

    missing = tmp_path / "missing"
    fixture = _inputs(missing)
    snapshot = json.loads(fixture.paths["linear"].read_bytes())
    snapshot["edges"].pop()
    _write(fixture.paths["linear"], snapshot)
    _bind_snapshot(fixture)
    assert _run(tmp_path, fixture, out="missing.json").returncode == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_cursor", "substituted-cursor"),
        ("delegation_event_id", "substituted-event"),
        ("base_sha", "0" * 40),
    ],
)
def test_linear_cursor_event_and_base_substitution_are_not_ready(
    tmp_path: Path, field: str, value: str
) -> None:
    fixture = _inputs(tmp_path)
    snapshot = json.loads(fixture.paths["linear"].read_bytes())
    target = snapshot if field == "event_cursor" else snapshot["task"]
    target[field] = value
    _write(fixture.paths["linear"], snapshot)
    _bind_snapshot(fixture)
    assert _run(tmp_path, fixture).returncode == 3


def test_provider_outage_has_distinct_exit(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    snapshot = json.loads(fixture.paths["linear"].read_bytes())
    snapshot["provider_status"] = "outage"
    _write(fixture.paths["linear"], snapshot)
    assert _run(tmp_path, fixture).returncode == 4


def test_work_order_is_never_overwritten(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    assert _run(tmp_path, fixture).returncode == 0
    assert _run(tmp_path, fixture).returncode == 3


def test_validator_rejects_substitution_and_does_not_mutate_inputs(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    assert _run(tmp_path, fixture).returncode == 0
    work_order = tmp_path / "work-order.json"
    before = {name: path.read_bytes() for name, path in fixture.paths.items()}
    status_before = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
    assert _validate(tmp_path, fixture, work_order).returncode == 0
    assert before == {name: path.read_bytes() for name, path in fixture.paths.items()}
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT) == status_before

    commands = json.loads(fixture.paths["commands"].read_bytes())
    commands["commands"][0]["cwd"] = "/substituted"
    _write(fixture.paths["commands"], commands)
    assert (
        _validate(tmp_path, fixture, work_order, out="substituted-validation.json").returncode == 2
    )


def test_validator_cannot_reuse_an_expired_ready_materialization(tmp_path: Path) -> None:
    fixture = _inputs(tmp_path)
    assert _run(tmp_path, fixture).returncode == 0
    assert (
        _validate(
            tmp_path,
            fixture,
            tmp_path / "work-order.json",
            validated_at="2026-09-13T02:00:00Z",
        ).returncode
        == 3
    )


def test_historical_v1_work_order_remains_interpretable(tmp_path: Path) -> None:
    private_key_pkcs8, public_key_hex = _keypair()
    actor = "historical-fixture-actor"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subject = {
        "actor_id": actor,
        "authority": "historical fixture",
        "base_sha": head,
        "linear_issue": "MET-90",
        "task_id": "MP2-016",
    }
    subject_digest = sha256_json(subject)
    assignment = {
        "schema_version": "metriplane.task-assignment.v1",
        "signature": {
            "actor_id": actor,
            "provider": "linear",
            "signature": _signature(
                private_key_pkcs8, actor_id=actor, subject_digest=subject_digest
            ),
        },
        "subject": subject,
        "subject_digest": subject_digest,
    }
    task = next(row for row in CATALOG["tasks"] if row["task_id"] == "MP2-016")
    work_order: dict[str, Any] = {
        "assignment": assignment,
        "base_sha": head,
        "catalog_row": task,
        "commands": [{"historical": True}],
        "dependencies": [],
        "input_digests": {str(index): "0" * 64 for index in range(6)},
        "linear_issue": "MET-90",
        "linear_relation_digest": "0" * 64,
        "resolution": {},
        "schema_version": "metriplane.task-work-order.v1",
        "task_id": "MP2-016",
        "verdict": "READY",
    }
    work_order["materialization_id"] = sha256_json(work_order)
    work_order_path = _write(tmp_path / "historical-work-order.json", work_order)
    keyring = _write(
        tmp_path / "historical-keyring.json",
        {
            "keys": [
                {
                    "actor_id": actor,
                    "provider": "linear",
                    "public_key_hex": public_key_hex,
                }
            ],
            "schema_version": "metriplane.provider-attestation-keyring.v1",
        },
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--work-order",
            str(work_order_path),
            "--schema",
            str(ROOT / "schemas/metriplane.task-work-order.v1.schema.json"),
            "--assignment-schema",
            str(ROOT / "schemas/metriplane.task-assignment.v1.schema.json"),
            "--catalog",
            str(ROOT / "docs/status/task-work-orders.json"),
            "--catalog-schema",
            str(ROOT / "schemas/metriplane.mp2-work-order-set.v1.schema.json"),
            "--keyring",
            str(keyring),
            "--out",
            str(tmp_path / "historical-validation.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 3, completed.stderr
    result = json.loads((tmp_path / "historical-validation.json").read_bytes())
    assert result["checks"]["historical_v1_interpretable"] is True
    assert result["checks"]["eligible_for_new_execution"] is False
    assert result["verdict"] == "BLOCKED_NOT_READY"
