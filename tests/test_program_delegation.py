# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Synthetic keys exercise the program boundary; never production authority."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from metriplane.release_control import canonical_json, sha256_json
from tools.complete_delegated_task import complete
from tools.delegated_task_authority import validate_delegated_task
from tools.delegated_merge import DelegatedMergeError, merge_request_id, select_delegate_admission
from tools.materialize_task_work_order import (
    InputError,
    NotReady,
    _validate_live_program_grant,
    build,
)
from tools.main_health_broker import BrokerError, DurableSpool, digest as broker_digest
from tools.program_delegation import program_grant_id, validate_program_grant
from tools.task_attestation_builder import prepare_task_observation
from tools.task_delegation import (
    DelegationError,
    DelegationNotReady,
    delegation_id,
    key_id,
    tracker_snapshot_digest,
)
from tools.validate_task_work_order import validate as validate_work_order

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "docs/status/task-work-orders.json").read_bytes())
SCHEMA = json.loads((ROOT / "schemas/metriplane.program-delegation.v1.schema.json").read_bytes())
OWNER = "96778fbb-c8ff-42b3-9217-7cac45dcd097"
EXECUTOR = "01a096e0-4e21-7a11-9f0f-fb303387c5c0"
PROJECT = "cf53f98f-0965-4360-a66e-530457e40354"
REPOSITORY = "Miko997/metriplane"
NOW = "2026-09-18T12:00:00Z"
_KEYGEN = r"""
const crypto = require("node:crypto");
const {privateKey, publicKey} = crypto.generateKeyPairSync("ed25519");
const der = publicKey.export({format: "der", type: "spki"});
process.stdout.write(JSON.stringify({
  private_key: privateKey.export({format: "der", type: "pkcs8"}).toString("base64"),
  public_key_hex: der.subarray(12).toString("hex"),
}));
"""
_SIGN = r"""
const crypto = require("node:crypto");
const fs = require("node:fs");
const value = JSON.parse(fs.readFileSync(0, "utf8"));
const key = crypto.createPrivateKey({
  key: Buffer.from(value.private_key, "base64"), format: "der", type: "pkcs8"
});
process.stdout.write(crypto.sign(null, Buffer.from(value.message, "base64"), key).toString("hex"));
"""


def _run_node(script: str, payload: dict[str, str] | None = None) -> dict[str, str] | str:
    result = subprocess.run(
        ["node", "--eval", script],
        input=json.dumps(payload) if payload else None,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout) if script == _KEYGEN else result.stdout


def _fixture() -> tuple[dict, dict, str, str]:
    owner_key = _run_node(_KEYGEN)
    delegate_key = _run_node(_KEYGEN)
    attestor_key = _run_node(_KEYGEN)
    assert isinstance(owner_key, dict) and isinstance(delegate_key, dict)
    assert isinstance(attestor_key, dict)
    tasks = sorted(
        row["task_id"]
        for row in CATALOG["tasks"]
        if row["first_required_release"] == "v0.5" and row["role"] == "implementation"
    )
    subject = {
        "grantor": {"provider": "linear", "actor_id": OWNER, "role": "repository_owner"},
        "delegate": {
            "kind": "codex_goal",
            "executor_id": EXECUTOR,
            "key_id": key_id(delegate_key["public_key_hex"]),
            "public_key_hex": delegate_key["public_key_hex"],
        },
        "attestor": {
            "kind": "isolated_provider_attestor",
            "service": "metriplane-health",
            "key_id": key_id(attestor_key["public_key_hex"]),
            "public_key_hex": attestor_key["public_key_hex"],
        },
        "scope": {
            "repository": REPOSITORY,
            "project_id": PROJECT,
            "milestone": "v0.5",
            "task_ids": tasks,
            "permitted_actions": ["materialize_task_work_order", "request_owner_normal_merge"],
            "prohibited_actions": [
                "owner_emergency_repair",
                "publication",
                "release_decision",
                "repository_settings",
                "subdelegation",
            ],
        },
        "issued_at": "2026-09-18T11:00:00Z",
        "expires_at": "2026-09-19T11:00:00Z",
        "signing_key_id": key_id(owner_key["public_key_hex"]),
    }
    subject["grant_id"] = program_grant_id(subject)
    digest = sha256_json(subject)
    envelope = canonical_json({"actor_id": OWNER, "provider": "linear", "subject_digest": digest})
    signature = _run_node(
        _SIGN,
        {
            "private_key": owner_key["private_key"],
            "message": base64.b64encode(envelope).decode("ascii"),
        },
    )
    assert isinstance(signature, str)
    grant = {
        "schema_version": "metriplane.program-delegation.v1",
        "synthetic": True,
        "subject": subject,
        "subject_digest": digest,
        "signature": {
            "provider": "linear",
            "actor_id": OWNER,
            "key_id": key_id(owner_key["public_key_hex"]),
            "signature": signature,
        },
    }
    authority = {
        "schema_version": "metriplane.task-delegation-authority.v1",
        "keys": [
            {
                "key_id": key_id(owner_key["public_key_hex"]),
                "provider": "linear",
                "actor_id": OWNER,
                "public_key_hex": owner_key["public_key_hex"],
                "role": "repository_owner",
                "repository": REPOSITORY,
                "project_id": PROJECT,
                "not_before": "2026-09-18T00:00:00Z",
                "not_after": "2027-09-18T00:00:00Z",
                "status": "active",
                "trust_class": "fixture",
            }
        ],
        "revoked_delegation_ids": [],
    }
    return grant, authority, delegate_key["private_key"], attestor_key["private_key"]


def _validate(grant: dict, authority: dict, **overrides: object) -> dict:
    args = {
        "repository": REPOSITORY,
        "project_id": PROJECT,
        "grantor_id": OWNER,
        "executor_id": EXECUTOR,
        "evaluated_at": NOW,
        "live": False,
    }
    args.update(overrides)
    return validate_program_grant(grant, authority, CATALOG, **args)


def test_valid_owner_grant_is_bounded_and_schema_valid() -> None:
    grant, authority, _, _ = _fixture()
    assert SCHEMA["properties"]["schema_version"]["const"] == grant["schema_version"]
    result = _validate(grant, authority)
    assert result["grant_id"] == grant["subject"]["grant_id"]
    assert "MP2-020" in result["task_ids"]
    assert "MP2-049" not in result["task_ids"]


@pytest.mark.parametrize(
    "path,value,error",
    [
        (("subject", "grantor", "actor_id"), EXECUTOR, "owner"),
        (("subject", "delegate", "executor_id"), OWNER, "executor"),
        (("subject", "scope", "repository"), "other/repo", "scope"),
        (("subject", "scope", "project_id"), "00000000-0000-0000-0000-000000000000", "scope"),
        (("subject", "scope", "milestone"), "v0.6", "scope"),
        (("subject", "scope", "task_ids"), ["MP2-049"], "scope"),
        (("subject", "scope", "prohibited_actions"), [], "scope"),
        (("subject", "delegate", "public_key_hex"), "0" * 64, "key identity"),
        (("subject", "issued_at"), "2026-09-20T11:00:00Z", "future"),
        (("subject", "expires_at"), "2026-09-18T11:00:00Z", "active"),
    ],
)
def test_tampered_claim_rejected(path: tuple[str, ...], value: object, error: str) -> None:
    grant, authority, _, _ = _fixture()
    target = grant
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(DelegationError, match="digest mismatch"):
        _validate(grant, authority)


def test_wrong_actor_and_scope_arguments_rejected() -> None:
    grant, authority, _, _ = _fixture()
    for changed in (
        {"grantor_id": "wrong-owner"},
        {"executor_id": "wrong-executor"},
        {"repository": "wrong/repo"},
        {"project_id": "wrong-project"},
    ):
        with pytest.raises(DelegationError):
            _validate(grant, authority, **changed)


def test_signature_replacement_and_revocation_fail_closed() -> None:
    grant, authority, _, _ = _fixture()
    grant["signature"]["signature"] = "0" * 128
    with pytest.raises(DelegationError, match="signature"):
        _validate(grant, authority)
    grant, authority, _, _ = _fixture()
    authority["revoked_delegation_ids"] = [grant["subject"]["grant_id"]]
    with pytest.raises(DelegationNotReady, match="revoked"):
        _validate(grant, authority)
    grant, authority, _, _ = _fixture()
    authority["keys"][0]["status"] = "revoked"
    with pytest.raises(DelegationNotReady, match="revoked"):
        _validate(grant, authority)


def test_fixture_and_expiry_cannot_authorize_live_execution() -> None:
    grant, authority, _, _ = _fixture()
    with pytest.raises(DelegationError, match="synthetic"):
        _validate(grant, authority, live=True)
    with pytest.raises(DelegationNotReady, match="active"):
        _validate(grant, authority, evaluated_at="2026-09-20T00:00:00Z")
    with pytest.raises(DelegationError, match="future"):
        _validate(grant, authority, evaluated_at="2026-09-17T00:00:00Z")


def test_signed_scope_cannot_be_rewritten_when_catalog_changes() -> None:
    grant, authority, _, _ = _fixture()
    changed = copy.deepcopy(CATALOG)
    row = next(row for row in changed["tasks"] if row["task_id"] == "MP2-049")
    row["role"] = "implementation"
    with pytest.raises(DelegationError, match="scope"):
        validate_program_grant(
            grant,
            authority,
            changed,
            repository=REPOSITORY,
            project_id=PROJECT,
            grantor_id=OWNER,
            executor_id=EXECUTOR,
            evaluated_at=NOW,
            live=False,
        )


def _task_fixture(
    *, base_sha: str = "a" * 40, base_tree: str = "b" * 40, edges: list[dict] | None = None
) -> tuple[dict, dict, dict, str]:
    grant, authority, delegate_private, attestor_private = _fixture()
    snapshot = {
        "schema_version": "metriplane.linear-work-order-snapshot.v1",
        "provider_status": "available",
        "repository": REPOSITORY,
        "project_id": PROJECT,
        "event_cursor": "linear-cursor-123",
        "captured_at": "2026-09-18T11:59:00Z",
        "synthetic": True,
        "task": {
            "task_id": "MP2-020",
            "linear_issue": "MET-87",
            "issue_state": "backlog",
            "assignee_actor_id": OWNER,
            "delegation_id": "0" * 64,
            "delegate_executor_id": EXECUTOR,
            "delegation_event_id": "linear-event-123",
            "base_sha": base_sha,
            "delegation_status": "active",
        },
        "edges": edges if edges is not None else [],
    }
    subject = {
        "program_grant_id": grant["subject"]["grant_id"],
        "grantor": grant["subject"]["grantor"],
        "delegate": {"kind": "codex_goal", "executor_id": EXECUTOR},
        "scope": {
            "authority": "implementation",
            "base_sha": base_sha,
            "base_tree": base_tree,
            "linear_issue": "MET-87",
            "project_id": PROJECT,
            "repository": REPOSITORY,
            "task_id": "MP2-020",
        },
        "tracker": {
            "provider": "linear",
            "event_id": "linear-event-123",
            "event_cursor": "linear-cursor-123",
        },
        "issued_at": "2026-09-18T11:58:00Z",
        "expires_at": "2026-09-18T12:08:00Z",
        "tracker_snapshot_digest": tracker_snapshot_digest(snapshot),
        "delegate_key_id": grant["subject"]["delegate"]["key_id"],
        "attestor_key_id": grant["subject"]["attestor"]["key_id"],
    }
    subject["delegation_id"] = delegation_id(subject)
    snapshot["task"]["delegation_id"] = subject["delegation_id"]
    digest = sha256_json(subject)

    def sign(private: str, provider: str, actor: str, signing_key_id: str) -> dict:
        envelope = canonical_json(
            {"actor_id": actor, "provider": provider, "subject_digest": digest}
        )
        signature = _run_node(
            _SIGN,
            {"private_key": private, "message": base64.b64encode(envelope).decode("ascii")},
        )
        return {
            "provider": provider,
            "actor_id": actor,
            "key_id": signing_key_id,
            "signature": signature,
        }

    delegated = {
        "schema_version": "metriplane.task-delegation.v2",
        "synthetic": True,
        "program_grant": grant,
        "subject": subject,
        "subject_digest": digest,
        "delegate_signature": sign(
            delegate_private, "codex_goal", EXECUTOR, subject["delegate_key_id"]
        ),
        "attestor_signature": sign(
            attestor_private,
            "metriplane-health",
            "metriplane-health",
            subject["attestor_key_id"],
        ),
    }
    return delegated, authority, snapshot, delegate_private


def _validate_task(delegated: dict, authority: dict, snapshot: dict, **overrides: object) -> dict:
    args = {
        "task_id": "MP2-020",
        "linear_issue": "MET-87",
        "repository": REPOSITORY,
        "project_id": PROJECT,
        "base_sha": "a" * 40,
        "base_tree": "b" * 40,
        "grantor_id": OWNER,
        "executor_id": EXECUTOR,
        "evaluated_at": NOW,
        "live": False,
    }
    args.update(overrides)
    return validate_delegated_task(delegated, authority, CATALOG, snapshot, **args)


def test_exact_delegated_task_requires_both_distinct_signers() -> None:
    delegated, authority, snapshot, _ = _task_fixture()
    assert _validate_task(delegated, authority, snapshot)["signature_trusted"] is True
    assert delegated["delegate_signature"]["key_id"] != delegated["attestor_signature"]["key_id"]


def test_task_instance_rejects_wrong_base_task_cursor_and_snapshot() -> None:
    delegated, authority, snapshot, _ = _task_fixture()
    for changed in (
        {"base_sha": "c" * 40},
        {"base_tree": "c" * 40},
        {"task_id": "MP2-049"},
        {"executor_id": "wrong-executor"},
    ):
        with pytest.raises(DelegationError):
            _validate_task(delegated, authority, snapshot, **changed)
    changed_snapshot = copy.deepcopy(snapshot)
    changed_snapshot["event_cursor"] = "later-cursor"
    with pytest.raises(DelegationError, match="snapshot"):
        _validate_task(delegated, authority, changed_snapshot)


def test_task_instance_rejects_altered_machine_signature_and_expiry() -> None:
    delegated, authority, snapshot, _ = _task_fixture()
    delegated["attestor_signature"]["signature"] = "0" * 128
    with pytest.raises(DelegationError, match="attestor signature"):
        _validate_task(delegated, authority, snapshot)
    delegated, authority, snapshot, _ = _task_fixture()
    delegated["delegate_signature"]["signature"] = "0" * 128
    with pytest.raises(DelegationError, match="delegate signature"):
        _validate_task(delegated, authority, snapshot)
    delegated, authority, snapshot, _ = _task_fixture()
    with pytest.raises(DelegationNotReady, match="expired"):
        _validate_task(delegated, authority, snapshot, evaluated_at="2026-09-18T12:09:00Z")


def test_v2_task_instance_materializes_full_ready_work_order_in_fixture_mode(
    tmp_path: Path,
) -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    issue_by_task = {row["task_id"]: row["linear_issue"] for row in CATALOG["tasks"]}
    edges = sorted(
        (
            {"blocker": issue_by_task[dependency], "blocked": row["linear_issue"]}
            for row in CATALOG["tasks"]
            for dependency in row["authoritative_blocked_by"]
            if not (
                row["task_id"] == "MP2-018"
                and dependency in {"MP2-007", "MP2-014", "MP2-015", "MP2-016", "MP2-017"}
            )
        ),
        key=lambda row: (row["blocker"], row["blocked"]),
    )
    delegated, authority, snapshot, _ = _task_fixture(base_sha=head, base_tree=tree, edges=edges)
    task = next(row for row in CATALOG["tasks"] if row["task_id"] == "MP2-020")

    def write(name: str, value: object) -> Path:
        path = tmp_path / name
        path.write_bytes(canonical_json(value))
        return path

    def resolved(rows: list[dict], field: str, prefix: str) -> list[dict]:
        return [
            {
                "locator": row[field],
                "destinations": [
                    {
                        "path": f"resolved/{prefix}-{index}.json",
                        "owner": "MP2-020",
                        "consumers": ["MP2-026"],
                        "validator": "fixture-validator",
                        "schema_or_media_type": "application/json",
                        "state": "CREATE",
                    }
                ],
            }
            for index, row in enumerate(rows)
        ]

    resolution = {
        "task_id": "MP2-020",
        "status": "RESOLVED",
        "anchors": resolved(task["ownership"]["start_anchors"], "locator", "anchor"),
        "outputs": resolved(task["ownership"]["planned_outputs"], "path_or_resolver", "output"),
    }
    dependencies = {
        "dependencies": [
            {
                "task_id": "MP2-006",
                "artifact_sha256": "1" * 64,
                "merged_at_base": True,
                "validator": "fixture-validator",
            }
        ]
    }
    commands = {
        "task_id": "MP2-020",
        "commands": [
            {
                "command_id": "MP2-020.CMD.ACCEPTANCE",
                "criterion_ids": [
                    row["criterion_id"] for row in task["task_specific_acceptance_predicates"]
                ],
                "argv": ["python", "-m", "pytest"],
                "cwd": str(ROOT),
                "environment": {},
                "resources": [],
                "expected_exit": 0,
                "expected_outputs": [],
            }
        ],
    }
    catalog_path = ROOT / "docs/status/task-work-orders.json"
    catalog_schema = ROOT / "schemas/metriplane.mp2-work-order-set.v1.schema.json"
    delegation_path = write("delegation.json", delegated)
    delegation_schema = ROOT / "schemas/metriplane.task-delegation.v2.schema.json"
    authority_path = write("authority.json", authority)
    authority_schema = ROOT / "schemas/metriplane.task-delegation-authority.v1.schema.json"
    snapshot_path = write("snapshot.json", snapshot)
    snapshot_schema = ROOT / "schemas/metriplane.linear-work-order-snapshot.v1.schema.json"
    dependencies_path = write("dependencies.json", dependencies)
    commands_path = write("commands.json", commands)
    resolution_path = write("resolution.json", resolution)
    result = build(
        ROOT,
        task_id="MP2-020",
        base_sha=head,
        repository=REPOSITORY,
        project_id=PROJECT,
        grantor_id=OWNER,
        executor_id=EXECUTOR,
        evaluated_at=NOW,
        fixture_mode=True,
        catalog_path=catalog_path,
        catalog_schema=catalog_schema,
        delegation_path=delegation_path,
        delegation_schema_path=delegation_schema,
        authority_keyring_path=authority_path,
        authority_keyring_schema_path=authority_schema,
        linear_snapshot_path=snapshot_path,
        linear_snapshot_schema_path=snapshot_schema,
        dependency_evidence_path=dependencies_path,
        command_registry_path=commands_path,
        resolution_path=resolution_path,
    )
    assert result["verdict"] == "READY"
    assert result["task_id"] == "MP2-020"
    assert result["delegation"]["schema_version"] == "metriplane.task-delegation.v2"
    work_order_path = write("work-order.json", result)
    validation = validate_work_order(
        work_order_path,
        schema_path=ROOT / "schemas/metriplane.task-work-order.v2.schema.json",
        assignment_schema_path=None,
        catalog_path=catalog_path,
        catalog_schema_path=catalog_schema,
        keyring_path=None,
        repository_root=ROOT,
        delegation_path=delegation_path,
        delegation_schema_path=delegation_schema,
        authority_keyring_path=authority_path,
        authority_keyring_schema_path=authority_schema,
        linear_snapshot_path=snapshot_path,
        linear_snapshot_schema_path=snapshot_schema,
        dependency_evidence_path=dependencies_path,
        command_registry_path=commands_path,
        resolution_path=resolution_path,
        repository=REPOSITORY,
        project_id=PROJECT,
        grantor_id=OWNER,
        executor_id=EXECUTOR,
        validated_at="2026-09-18T12:01:00Z",
        fixture_mode=True,
    )
    assert validation["verdict"] == "READY"
    commands_path.write_bytes(canonical_json(commands) + b"\n")
    with pytest.raises(InputError, match="v2 commands input is not exact canonical JSON"):
        build(
            ROOT,
            task_id="MP2-020",
            base_sha=head,
            repository=REPOSITORY,
            project_id=PROJECT,
            grantor_id=OWNER,
            executor_id=EXECUTOR,
            evaluated_at=NOW,
            fixture_mode=True,
            catalog_path=catalog_path,
            catalog_schema=catalog_schema,
            delegation_path=delegation_path,
            delegation_schema_path=delegation_schema,
            authority_keyring_path=authority_path,
            authority_keyring_schema_path=authority_schema,
            linear_snapshot_path=snapshot_path,
            linear_snapshot_schema_path=snapshot_schema,
            dependency_evidence_path=dependencies_path,
            command_registry_path=commands_path,
            resolution_path=resolution_path,
        )


def test_attestor_builder_binds_complete_graph_and_current_base() -> None:
    grant, authority, _, _ = _fixture()
    issue_by_task = {row["task_id"]: row["linear_issue"] for row in CATALOG["tasks"]}
    edges = sorted(
        (
            {"blocker": issue_by_task[dependency], "blocked": row["linear_issue"]}
            for row in CATALOG["tasks"]
            for dependency in row["authoritative_blocked_by"]
            if not (
                row["task_id"] == "MP2-018"
                and dependency in {"MP2-007", "MP2-014", "MP2-015", "MP2-016", "MP2-017"}
            )
        ),
        key=lambda row: (row["blocker"], row["blocked"]),
    )
    graph = {
        "captured_at": NOW,
        "cursor": "f" * 64,
        "edges": edges,
        "issues": {
            "MET-87": {
                "identifier": "MET-87",
                "assignee": {"id": OWNER},
                "state": {"type": "backlog"},
                "updatedAt": "2026-09-18T11:55:00.000Z",
            }
        },
    }
    kwargs = {
        "catalog": CATALOG,
        "authority": authority,
        "grant": grant,
        "graph": graph,
        "task_id": "MP2-020",
        "repository": REPOSITORY,
        "project_id": PROJECT,
        "grantor_id": OWNER,
        "executor_id": EXECUTOR,
        "base_sha": "a" * 40,
        "base_tree": "b" * 40,
        "live": False,
    }
    subject, snapshot = prepare_task_observation(**kwargs)
    assert subject["delegation_id"] == snapshot["task"]["delegation_id"]
    assert subject["scope"]["base_sha"] == "a" * 40
    assert snapshot["event_cursor"] == "f" * 64
    graph["edges"] = edges[1:]
    with pytest.raises(Exception, match="relations differ"):
        prepare_task_observation(**kwargs)


def test_live_program_grant_cannot_be_supplied_only_by_caller(tmp_path: Path) -> None:
    delegated, _, _, _ = _task_fixture()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "grantless base",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    with pytest.raises(NotReady, match="absent from the exact protected base"):
        _validate_live_program_grant(tmp_path, head, delegated)


def test_executor_can_only_complete_preexisting_machine_attestation(tmp_path: Path) -> None:
    delegated, authority, snapshot, private_der_b64 = _task_fixture()
    private_path = tmp_path / "synthetic-delegate.pem"
    wrapped = private_der_b64
    private_path.write_text(
        "-----BEGIN PRIVATE KEY-----\n" + wrapped + "\n-----END PRIVATE KEY-----\n"
    )
    private_path.chmod(0o600)
    partial = {key: value for key, value in delegated.items() if key != "delegate_signature"}
    completed = complete(
        partial=partial,
        snapshot=snapshot,
        authority=authority,
        catalog=CATALOG,
        private_key_path=private_path,
        evaluated_at=NOW,
        live=False,
    )
    assert completed["delegate_signature"] == delegated["delegate_signature"]
    partial["attestor_signature"]["signature"] = "0" * 128
    with pytest.raises(DelegationError, match="attestor signature"):
        complete(
            partial=partial,
            snapshot=snapshot,
            authority=authority,
            catalog=CATALOG,
            private_key_path=private_path,
            evaluated_at=NOW,
            live=False,
        )


def _merge_fixture(
    *, path_owner: str = "MP2-020"
) -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    grant, authority, delegate_private, _ = _fixture()
    grant["synthetic"] = False
    authority["keys"][0]["trust_class"] = "production"
    work_order = {
        "task_id": "MP2-020",
        "linear_issue": "MET-87",
        "materialization_id": "1" * 64,
        "verdict": "READY",
        "base_sha": "a" * 40,
        "repository": REPOSITORY,
        "project_id": PROJECT,
        "executor_id": EXECUTOR,
        "delegation": {"program_grant": grant},
        "resolution": {
            "anchors": [],
            "outputs": [{"destinations": [{"path": "tools/ambient_git.py", "owner": path_owner}]}],
        },
    }
    state = {
        "status": "green",
        "last_good_sha": "a" * 40,
        "state_commit": "b" * 40,
        "generation": 83,
    }
    context = {
        "changed_paths_digest": hashlib.sha256(
            canonical_json(["tools/ambient_git.py"]) + b"\n"
        ).hexdigest(),
        "collaboration_digest": "d" * 64,
        "ruleset_digests": {"1": "e" * 64},
    }
    pull = {
        "number": 135,
        "state": "open",
        "draft": False,
        "base": {"ref": "main", "sha": "a" * 40},
        "head": {"sha": "f" * 40, "repo": {"full_name": REPOSITORY}},
        "user": {"id": 997, "login": "Miko997"},
    }
    subject = {
        "grant_id": grant["subject"]["grant_id"],
        "repository": REPOSITORY,
        "project_id": PROJECT,
        "executor_id": EXECUTOR,
        "task_id": "MP2-020",
        "linear_issue": "MET-87",
        "work_order_id": work_order["materialization_id"],
        "work_order_digest": sha256_json(work_order),
        "pull_request": 135,
        "base_sha": "a" * 40,
        "head_sha": "f" * 40,
        "head_tree": "9" * 40,
        "changed_paths_digest": context["changed_paths_digest"],
        "collaboration_digest": context["collaboration_digest"],
        "ruleset_digests": context["ruleset_digests"],
        "state_commit": state["state_commit"],
        "health_generation": 83,
        "issued_at": "2026-09-18T11:59:00Z",
        "expires_at": "2026-09-18T12:09:00Z",
        "nonce": "7" * 64,
    }
    subject["request_id"] = merge_request_id(subject)
    digest = sha256_json(subject)
    envelope = canonical_json(
        {"actor_id": EXECUTOR, "provider": "codex_goal", "subject_digest": digest}
    )
    signature = _run_node(
        _SIGN,
        {
            "private_key": delegate_private,
            "message": base64.b64encode(envelope).decode("ascii"),
        },
    )
    request = {
        "schema_version": "metriplane.delegate-merge-request.v1",
        "subject": subject,
        "subject_digest": digest,
        "signature": {
            "provider": "codex_goal",
            "actor_id": EXECUTOR,
            "key_id": grant["subject"]["delegate"]["key_id"],
            "signature": signature,
        },
    }
    validation = {"verdict": "READY", "task_id": "MP2-020", "base_sha": "a" * 40}
    return request, grant, authority, work_order, validation, pull, (context, state)


def _merge(
    request: dict,
    grant: dict,
    authority: dict,
    work_order: dict,
    validation: dict,
    pull: dict,
    context_state: tuple[dict, dict],
) -> dict:
    context, state = context_state
    return select_delegate_admission(
        request,
        grant=grant,
        authority=authority,
        catalog=CATALOG,
        work_order=work_order,
        validated_work_order=validation,
        pull=pull,
        head_tree="9" * 40,
        changed_paths=["tools/ambient_git.py"],
        owner_context=context,
        state=state,
        provider_now=NOW,
        owner_id=997,
    )


def test_delegate_merge_admission_is_machine_distinct_and_exact(tmp_path: Path) -> None:
    values = _merge_fixture()
    admitted = _merge(*values)
    assert admitted["kind"] == "delegate-normal"
    assert admitted["work_order_id"] == "1" * 64
    assert "approval_review_id" not in admitted
    assert admitted["request_digest"] == broker_digest(admitted["request"])

    spool = DurableSpool(tmp_path / "spool")
    spool.record_request(
        request_digest=admitted["request_digest"],
        nonce=admitted["nonce"],
        pull_request=admitted["pull_request"],
        request=admitted["request"],
        status="merging",
        updated_at=NOW,
    )
    assert spool.request_status(admitted["request_digest"]) == "merging"
    assert spool.request_inventory() == [
        {
            "request_digest": admitted["request_digest"],
            "nonce": admitted["nonce"],
            "pull_request": admitted["pull_request"],
            "request": admitted["request"],
            "status": "merging",
        }
    ]
    assert spool.requests_with_status("merging") == [
        {
            "base_sha": admitted["base_sha"],
            "head_sha": admitted["head_sha"],
            "nonce": admitted["nonce"],
            "pull_request": admitted["pull_request"],
            "request": admitted["request"],
            "request_digest": admitted["request_digest"],
        }
    ]
    malformed = {**admitted["request"], "nonce": "7" * 32}
    with pytest.raises(BrokerError, match="identity is inconsistent"):
        spool.record_request(
            request_digest=broker_digest(malformed),
            nonce=malformed["nonce"],
            pull_request=malformed["pull_request"],
            request=malformed,
            status="merging",
            updated_at=NOW,
        )


def test_delegate_merge_rejects_state_scope_or_signature_change() -> None:
    request, grant, authority, work_order, validation, pull, context_state = _merge_fixture()
    context_state[0]["changed_paths_digest"] = "0" * 64
    with pytest.raises(DelegatedMergeError, match="provider/work-order"):
        _merge(request, grant, authority, work_order, validation, pull, context_state)
    request, grant, authority, work_order, validation, pull, context_state = _merge_fixture()
    request["signature"]["signature"] = "0" * 128
    with pytest.raises(DelegatedMergeError, match="signature"):
        _merge(request, grant, authority, work_order, validation, pull, context_state)
    request, grant, authority, work_order, validation, pull, context_state = _merge_fixture()
    validation["verdict"] = "BLOCKED_NOT_READY"
    with pytest.raises(DelegatedMergeError, match="READY"):
        _merge(request, grant, authority, work_order, validation, pull, context_state)


def test_delegate_merge_rejects_paths_outside_task_ownership() -> None:
    request, grant, authority, work_order, validation, pull, context_state = _merge_fixture(
        path_owner="MP2-021"
    )
    with pytest.raises(DelegatedMergeError, match="outside exact task ownership"):
        _merge(request, grant, authority, work_order, validation, pull, context_state)
