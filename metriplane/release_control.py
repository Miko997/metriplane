# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Deterministic, fail-closed release qualification primitives.

The module owns the cumulative release state machine.  Command-line tools are
thin adapters around these primitives; publication remains a consumer of a
closed qualification record and never creates release authority itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

MILESTONES: Final[tuple[str, ...]] = (
    "v0.4",
    "v0.5",
    "v0.6",
    "v0.7",
    "v0.8",
    "v0.9",
    "v1.0",
)
STAGES: Final[tuple[str, ...]] = (
    "roles",
    "task-state",
    "staging",
    "targets",
    "predecessor",
    "source-freeze",
    "candidate",
    "qualification",
    "approval",
    "prepromotion",
    "promotion",
    "reconciliation",
    "retention",
    "closed",
)
TERMINAL_RESULTS: Final[frozenset[str]] = frozenset(
    {"PASS", "FAIL", "BLOCKED", "CANCELLED", "SKIPPED"}
)
RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "data",
        "invocation_id",
        "payload_digest",
        "record_id",
        "record_type",
        "schema_version",
        "sequence",
        "signatures",
        "status",
        "synthetic",
    }
)
RECORD_VERSION: Final[str] = "metriplane.release-record.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_INVOCATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")


class ReleaseControlError(ValueError):
    """A release operation cannot proceed without weakening its contract."""


def canonical_json(value: object) -> bytes:
    """Return the one canonical JSON representation used for release identity."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseControlError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ReleaseControlError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_invocation(value: object) -> str:
    if not isinstance(value, str) or _INVOCATION.fullmatch(value) is None:
        raise ReleaseControlError("invocation_id is missing or invalid")
    return value


def read_json(path: Path) -> dict[str, Any]:
    """Read one regular JSON object without following a symlink."""

    if not path.is_file() or path.is_symlink():
        raise ReleaseControlError(f"input is missing or not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseControlError(f"cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseControlError(f"JSON input must be an object: {path}")
    return value


def write_immutable_json(path: Path, value: object) -> str:
    """Create canonical JSON exactly once and return its byte digest."""

    payload = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as exc:
        raise ReleaseControlError(f"refusing to overwrite retained output: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return sha256_bytes(payload)


def make_record(
    record_type: str,
    data: Mapping[str, Any],
    *,
    invocation_id: str,
    sequence: int,
    synthetic: bool,
    status: str = "PASS",
    signatures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Create a digest-bound release record with no implicit clock input."""

    if not record_type.startswith("release-") and record_type not in {
        "linear-release-snapshot",
        "provider-run-termination",
    }:
        raise ReleaseControlError(f"invalid release record type: {record_type!r}")
    _require_invocation(invocation_id)
    if isinstance(sequence, bool) or sequence < 1:
        raise ReleaseControlError("sequence must be a positive integer")
    if status not in TERMINAL_RESULTS | {"OPEN", "READY", "INVALIDATED"}:
        raise ReleaseControlError(f"invalid release status: {status!r}")
    normalized_signatures = [dict(signature) for signature in signatures]
    body: dict[str, Any] = {
        "data": dict(data),
        "invocation_id": invocation_id,
        "payload_digest": sha256_json(data),
        "record_type": record_type,
        "schema_version": RECORD_VERSION,
        "sequence": sequence,
        "signatures": normalized_signatures,
        "status": status,
        "synthetic": synthetic,
    }
    body["record_id"] = sha256_json(body)
    return body


def validate_record(record: Mapping[str, Any], expected_type: str | None = None) -> None:
    """Validate the closed record envelope and all digest bindings."""

    if set(record) != RECORD_KEYS:
        missing = sorted(RECORD_KEYS - set(record))
        extra = sorted(set(record) - RECORD_KEYS)
        raise ReleaseControlError(
            f"release record shape mismatch; missing={missing}; extra={extra}"
        )
    if record["schema_version"] != RECORD_VERSION:
        raise ReleaseControlError("unsupported release record schema version")
    if expected_type is not None and record["record_type"] != expected_type:
        raise ReleaseControlError(
            f"record type is {record['record_type']!r}, expected {expected_type!r}"
        )
    if not isinstance(record["data"], dict):
        raise ReleaseControlError("release record data must be an object")
    if record["payload_digest"] != sha256_json(record["data"]):
        raise ReleaseControlError("release record payload digest mismatch")
    _require_invocation(record["invocation_id"])
    if isinstance(record["sequence"], bool) or not isinstance(record["sequence"], int):
        raise ReleaseControlError("release record sequence must be an integer")
    if record["sequence"] < 1:
        raise ReleaseControlError("release record sequence must be positive")
    if not isinstance(record["synthetic"], bool):
        raise ReleaseControlError("release record synthetic flag must be boolean")
    if not isinstance(record["signatures"], list):
        raise ReleaseControlError("release record signatures must be an array")
    if record["status"] not in TERMINAL_RESULTS | {"OPEN", "READY", "INVALIDATED"}:
        raise ReleaseControlError("release record has an invalid status")
    claimed_id = _require_digest(record["record_id"], "record_id")
    unsigned = dict(record)
    del unsigned["record_id"]
    if claimed_id != sha256_json(unsigned):
        raise ReleaseControlError("release record identity mismatch")


def _validated_signature(signature: Mapping[str, Any], *, subject_digest: str, live: bool) -> str:
    exact = {"actor_id", "algorithm", "provider", "signature", "subject_digest", "synthetic"}
    if set(signature) != exact:
        raise ReleaseControlError("signature shape is not closed")
    if signature["subject_digest"] != subject_digest:
        raise ReleaseControlError("signature is not bound to the record payload")
    actor_id = signature["actor_id"]
    if not isinstance(actor_id, str) or not actor_id:
        raise ReleaseControlError("signature actor is missing")
    if signature["algorithm"] not in {"provider-attestation-v1", "test-sha256-v1"}:
        raise ReleaseControlError("signature algorithm is not allowed")
    signature_value = signature["signature"]
    if not isinstance(signature_value, str) or len(signature_value) < 16:
        raise ReleaseControlError("signature value is missing")
    if live:
        if signature["synthetic"] is not False:
            raise ReleaseControlError("synthetic signatures cannot authorize live release work")
        if signature["provider"] not in {"github", "linear"}:
            raise ReleaseControlError("live signatures require provider authority")
        if signature["algorithm"] != "provider-attestation-v1":
            raise ReleaseControlError("test signatures cannot authorize live release work")
    return actor_id


def validate_role_assignments(record: Mapping[str, Any], *, live: bool) -> dict[str, str]:
    validate_record(record, "release-role-assignments")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic role assignments cannot authorize a live release")
    data = record["data"]
    expected = {
        "author_id",
        "authorized_executor_id",
        "non_author_reviewer_id",
        "publisher_id",
        "task_id",
    }
    if set(data) != expected or data["task_id"] != "MP2-007":
        raise ReleaseControlError("release role assignment shape or task binding is invalid")
    actors: dict[str, str] = {}
    for key in expected - {"task_id"}:
        actor = data[key]
        if not isinstance(actor, str) or not actor:
            raise ReleaseControlError(f"role {key} has no actor")
        actors[key] = actor
    if actors["author_id"] == actors["non_author_reviewer_id"]:
        raise ReleaseControlError("the release author cannot be the non-author reviewer")
    signers = {
        _validated_signature(signature, subject_digest=record["payload_digest"], live=live)
        for signature in record["signatures"]
    }
    if live and actors["authorized_executor_id"] not in signers:
        raise ReleaseControlError("authorized executor lacks a digest-bound live delegation")
    return actors


def validate_approval(
    record: Mapping[str, Any],
    roles: Mapping[str, str],
    *,
    live: bool,
) -> None:
    """Require a conflict-free, digest-bound decision by a distinct reviewer."""

    validate_record(record, "release-approval")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic approval cannot authorize a live release")
    data = record["data"]
    expected = {"author_id", "candidate_digest", "conflicts", "decision", "reviewer_id"}
    if set(data) != expected:
        raise ReleaseControlError("release approval shape is not closed")
    _require_digest(data["candidate_digest"], "candidate_digest")
    if data["decision"] != "APPROVED" or data["conflicts"] != []:
        raise ReleaseControlError("release approval is not conflict-free and approved")
    if data["author_id"] != roles["author_id"]:
        raise ReleaseControlError("approval author does not match the role assignment")
    reviewer = data["reviewer_id"]
    if reviewer == data["author_id"] or reviewer != roles["non_author_reviewer_id"]:
        raise ReleaseControlError("approval is not from the assigned non-author reviewer")
    signers = {
        _validated_signature(signature, subject_digest=record["payload_digest"], live=live)
        for signature in record["signatures"]
    }
    if reviewer not in signers:
        raise ReleaseControlError("approval lacks the reviewer's digest-bound signature")


def validate_task_state_observation(
    record: Mapping[str, Any], roles: Mapping[str, str], *, live: bool
) -> None:
    """Require the assigned live executor and an allowed implementation state."""

    validate_record(record, "release-task-state-observation")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic task state cannot authorize live release work")
    data = record["data"]
    if set(data) != {"assignee_id", "issue_id", "state", "task_id"}:
        raise ReleaseControlError("release task-state observation shape is not closed")
    if data["issue_id"] != "MET-154" or data["task_id"] != "MP2-007":
        raise ReleaseControlError("release task-state observation names the wrong task")
    if data["state"] != "In Progress":
        raise ReleaseControlError("release task is not in an executable state")
    if data["assignee_id"] != roles["authorized_executor_id"]:
        raise ReleaseControlError("release task assignee is not the authorized executor")
    signers = {
        _validated_signature(signature, subject_digest=record["payload_digest"], live=live)
        for signature in record["signatures"]
    }
    if live and data["assignee_id"] not in signers:
        raise ReleaseControlError("live task state lacks provider-authenticated assignee proof")


def validate_cumulative_milestones(milestones: Sequence[str]) -> None:
    if tuple(milestones) != MILESTONES:
        raise ReleaseControlError("release milestones must be the cumulative v0.4 through v1.0 set")


def new_attempt(
    *,
    milestone: str,
    version: str,
    candidate_digest: str,
    predecessor_digest: str,
) -> dict[str, Any]:
    if milestone not in MILESTONES:
        raise ReleaseControlError(f"unknown cumulative release milestone: {milestone}")
    if not version.startswith(f"{milestone}."):
        raise ReleaseControlError("candidate version must be a patch in its declared milestone")
    return {
        "candidate_digest": _require_digest(candidate_digest, "candidate_digest"),
        "events": [],
        "milestone": milestone,
        "predecessor_digest": _require_digest(predecessor_digest, "predecessor_digest"),
        "version": version,
    }


def advance_attempt(
    attempt: Mapping[str, Any],
    *,
    stage: str,
    result: str,
    evidence_digest: str,
) -> dict[str, Any]:
    """Advance exactly one stage; failed stages terminalize the attempt."""

    if stage not in STAGES:
        raise ReleaseControlError(f"unknown release stage: {stage}")
    if result not in TERMINAL_RESULTS:
        raise ReleaseControlError("release stage result is not terminal")
    events = attempt.get("events")
    if not isinstance(events, list):
        raise ReleaseControlError("release attempt events are invalid")
    if events and events[-1]["result"] != "PASS":
        raise ReleaseControlError("a terminalized failed release attempt cannot advance")
    expected = STAGES[len(events)] if len(events) < len(STAGES) else None
    if stage != expected:
        raise ReleaseControlError(f"release stage {stage!r} is out of order; expected {expected!r}")
    advanced = dict(attempt)
    advanced["events"] = [
        *events,
        {
            "evidence_digest": _require_digest(evidence_digest, "evidence_digest"),
            "result": result,
            "stage": stage,
        },
    ]
    return advanced


def record_target_burn(
    *, target: str, milestone: str, version: str, reason: str, observation_digest: str
) -> dict[str, str]:
    if milestone not in MILESTONES or not version.startswith(f"{milestone}."):
        raise ReleaseControlError("burn target version is outside its milestone")
    if not target or not reason:
        raise ReleaseControlError("a target burn requires target and reason")
    return {
        "milestone": milestone,
        "observation_digest": _require_digest(observation_digest, "observation_digest"),
        "reason": reason,
        "target": target,
        "version": version,
    }


def resolve_burn_with_patch(burn: Mapping[str, str], patch_version: str) -> dict[str, str]:
    milestone = burn["milestone"]
    if patch_version == burn["version"] or not patch_version.startswith(f"{milestone}."):
        raise ReleaseControlError("a burn requires a new patch in the same milestone")
    resolved = dict(burn)
    resolved["resolution"] = "NEW_PATCH_REQUIRED"
    resolved["resolved_by"] = patch_version
    return resolved


def validate_predecessor(record: Mapping[str, Any], *, first_milestone: bool) -> None:
    validate_record(record, "release-predecessor")
    data = record["data"]
    required = {"candidate_milestone", "closed_decision_digest", "lkg_digest", "version"}
    if set(data) != required:
        raise ReleaseControlError("predecessor shape is not closed")
    _require_digest(data["lkg_digest"], "lkg_digest")
    _require_digest(data["closed_decision_digest"], "closed_decision_digest")
    if first_milestone and data["version"] != "v0.3.0":
        raise ReleaseControlError("v0.4 must resolve the actual v0.3.0 predecessor")
    if not first_milestone and data["candidate_milestone"] not in MILESTONES[1:]:
        raise ReleaseControlError("later release predecessor milestone is invalid")


def candidate_identity(
    *, source_digest: str, artifacts: Mapping[str, str], build_invocation_id: str
) -> dict[str, Any]:
    _require_invocation(build_invocation_id)
    source = _require_digest(source_digest, "source_digest")
    if not artifacts:
        raise ReleaseControlError("candidate identity requires immutable artifacts")
    normalized = {
        name: _require_digest(digest, f"artifact {name}")
        for name, digest in sorted(artifacts.items())
    }
    value: dict[str, Any] = {
        "artifacts": normalized,
        "build_invocation_id": build_invocation_id,
        "source_digest": source,
    }
    value["candidate_digest"] = sha256_json(value)
    return value


def finalize_cells(
    required_cells: Sequence[str], results: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    if not required_cells or len(required_cells) != len(set(required_cells)):
        raise ReleaseControlError("required release cells must be a nonempty unique list")
    if set(required_cells) != set(results):
        raise ReleaseControlError("release cell matrix is incomplete or contains extras")
    cells: list[dict[str, str]] = []
    for cell in required_cells:
        result = results[cell]
        if set(result) != {"evidence_digest", "result"}:
            raise ReleaseControlError(f"release cell {cell} shape is not closed")
        if result["result"] not in TERMINAL_RESULTS:
            raise ReleaseControlError(f"release cell {cell} is not terminal")
        cells.append(
            {
                "cell": cell,
                "evidence_digest": _require_digest(
                    result["evidence_digest"], f"release cell {cell} evidence"
                ),
                "result": result["result"],
            }
        )
    return {"cells": cells, "ready": all(cell["result"] == "PASS" for cell in cells)}


def build_promotion_plan(
    *,
    candidate_digest: str,
    approval_digest: str,
    controls_digest: str,
    target_state_digest: str,
    attempt_index_epoch: int,
    publisher_id: str,
    publisher_actions: Sequence[str],
    expires_at: int,
) -> dict[str, Any]:
    """Bind every promotion input before any publisher action can run."""

    if attempt_index_epoch < 0 or expires_at < 1:
        raise ReleaseControlError("promotion checkpoint and expiry are invalid")
    if (
        not publisher_id
        or not publisher_actions
        or len(publisher_actions) != len(set(publisher_actions))
    ):
        raise ReleaseControlError("promotion publisher actions must be nonempty and unique")
    plan: dict[str, Any] = {
        "approval_digest": _require_digest(approval_digest, "approval_digest"),
        "attempt_index_epoch": attempt_index_epoch,
        "candidate_digest": _require_digest(candidate_digest, "candidate_digest"),
        "controls_digest": _require_digest(controls_digest, "controls_digest"),
        "expires_at": expires_at,
        "publisher_actions": list(publisher_actions),
        "publisher_id": publisher_id,
        "target_state_digest": _require_digest(target_state_digest, "target_state_digest"),
    }
    plan["plan_digest"] = sha256_json(plan)
    return plan


def validate_promotion_plan(
    plan: Mapping[str, Any],
    *,
    now: int,
    candidate_digest: str,
    approval_digest: str,
    publisher_id: str,
) -> None:
    exact = {
        "approval_digest",
        "attempt_index_epoch",
        "candidate_digest",
        "controls_digest",
        "expires_at",
        "plan_digest",
        "publisher_actions",
        "publisher_id",
        "target_state_digest",
    }
    if set(plan) != exact:
        raise ReleaseControlError("promotion plan shape is not closed")
    unsigned = dict(plan)
    claimed = unsigned.pop("plan_digest")
    if claimed != sha256_json(unsigned):
        raise ReleaseControlError("promotion plan digest mismatch")
    if plan["candidate_digest"] != candidate_digest or plan["approval_digest"] != approval_digest:
        raise ReleaseControlError("promotion plan is bound to different release authority")
    if plan["publisher_id"] != publisher_id:
        raise ReleaseControlError("promotion plan names a different publisher")
    if not isinstance(plan["expires_at"], int) or plan["expires_at"] <= now:
        raise ReleaseControlError("promotion plan is expired")


def validate_lkg_invalidation(
    record: Mapping[str, Any],
    roles: Mapping[str, str],
    *,
    live: bool,
    candidate_digest: str,
) -> None:
    """Fence an LKG only through a signed non-author contradiction decision."""

    validate_record(record, "release-approval-decision")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic invalidation cannot fence a live LKG")
    data = record["data"]
    required = {"author_id", "candidate_digest", "decision", "reason", "reviewer_id"}
    if set(data) != required or data["decision"] != "INVALIDATED" or not data["reason"]:
        raise ReleaseControlError("LKG invalidation decision is incomplete")
    if data["candidate_digest"] != candidate_digest:
        raise ReleaseControlError("LKG invalidation names a different candidate")
    if data["author_id"] != roles["author_id"]:
        raise ReleaseControlError("LKG invalidation author does not match assigned roles")
    reviewer = data["reviewer_id"]
    if reviewer != roles["non_author_reviewer_id"] or reviewer == data["author_id"]:
        raise ReleaseControlError("LKG invalidation is not a non-author decision")
    signers = {
        _validated_signature(signature, subject_digest=record["payload_digest"], live=live)
        for signature in record["signatures"]
    }
    if reviewer not in signers:
        raise ReleaseControlError("LKG invalidation lacks the reviewer's signature")


def append_cas_event(
    journal: Path,
    event: Mapping[str, Any],
    *,
    expected_epoch: int,
) -> dict[str, Any]:
    """Append one immutable journal event with an epoch compare-and-swap fence."""

    if expected_epoch < 0:
        raise ReleaseControlError("expected epoch cannot be negative")
    journal.mkdir(parents=True, exist_ok=True)
    existing = sorted(journal.glob("*.json"))
    actual_epoch = len(existing)
    record = dict(event)
    record["epoch"] = expected_epoch + 1
    if actual_epoch == expected_epoch + 1:
        committed = read_json(existing[-1])
        if committed == record:
            return committed
    if actual_epoch != expected_epoch:
        raise ReleaseControlError(
            f"compare-and-swap failed: expected epoch {expected_epoch}, actual {actual_epoch}"
        )
    path = journal / f"{expected_epoch + 1:08d}.json"
    write_immutable_json(path, record)
    return record


def acquire_promotion_lock(
    journal: Path,
    *,
    owner: str,
    expected_epoch: int,
    now: int,
    lease_seconds: int,
    dead_owner_proof: str | None = None,
) -> dict[str, Any]:
    if not owner or lease_seconds < 1:
        raise ReleaseControlError("promotion lock owner and positive lease are required")
    existing = sorted(journal.glob("*.json")) if journal.exists() else []
    if existing:
        latest = read_json(existing[-1])
        if int(latest["lease_until"]) > now:
            raise ReleaseControlError("promotion lock is still leased")
        if dead_owner_proof is None:
            raise ReleaseControlError("expired promotion lock requires dead-owner proof")
        _require_digest(dead_owner_proof, "dead_owner_proof")
    event: dict[str, Any] = {
        "dead_owner_proof": dead_owner_proof,
        "lease_until": now + lease_seconds,
        "owner": owner,
    }
    return append_cas_event(journal, event, expected_epoch=expected_epoch)


def require_lock_owner(journal: Path, *, owner: str, epoch: int, now: int) -> None:
    path = journal / f"{epoch:08d}.json"
    latest = sorted(journal.glob("*.json"))
    if not latest or latest[-1] != path:
        raise ReleaseControlError("promotion lock epoch is stale")
    record = read_json(path)
    if record["owner"] != owner or int(record["lease_until"]) <= now:
        raise ReleaseControlError("promotion lock does not authorize this mutation")


def reconcile_publication(
    candidate_artifacts: Mapping[str, str], observations: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    if set(candidate_artifacts) != set(observations):
        missing = sorted(set(candidate_artifacts) - set(observations))
        extra = sorted(set(observations) - set(candidate_artifacts))
        return {
            "conflicts": [{"extra": extra, "missing": missing, "type": "TARGET_SET"}],
            "ok": False,
        }
    conflicts: list[dict[str, str]] = []
    for target, expected_digest in sorted(candidate_artifacts.items()):
        _require_digest(expected_digest, f"candidate target {target}")
        observation = observations[target]
        if set(observation) != {"digest", "state"}:
            conflicts.append({"target": target, "type": "OBSERVATION_SHAPE"})
            continue
        if observation["state"] != "IMMUTABLE" or observation["digest"] != expected_digest:
            conflicts.append(
                {
                    "actual": observation["digest"],
                    "expected": expected_digest,
                    "state": observation["state"],
                    "target": target,
                    "type": "BYTE_MISMATCH",
                }
            )
    return {"conflicts": conflicts, "ok": not conflicts}


def retain_two_store_evidence(
    record: Mapping[str, Any],
    *,
    store_a: Path,
    store_b: Path,
    index_journal: Path,
    expected_index_epoch: int,
    recovery_output: Path | None = None,
    recovery_invocation_id: str | None = None,
    recovery_sequence: int = 1,
) -> dict[str, Any]:
    """Write, read, and hash-verify both stores before indexing the receipt."""

    validate_record(record)
    record_id = str(record["record_id"])
    receipts: list[dict[str, str]] = []
    try:
        for store_name, store in (("store-a", store_a), ("store-b", store_b)):
            path = store / f"{record_id}.json"
            expected_digest = sha256_json(record)
            if path.exists():
                if path.is_symlink() or sha256_json(read_json(path)) != expected_digest:
                    raise ReleaseControlError(f"{store_name} contains conflicting retained bytes")
                digest = expected_digest
            else:
                digest = write_immutable_json(path, record)
            if sha256_json(read_json(path)) != digest:
                raise ReleaseControlError(f"{store_name} read-back digest mismatch")
            receipts.append({"digest": digest, "store": store_name})
        if receipts[0]["digest"] != receipts[1]["digest"]:
            raise ReleaseControlError("independent evidence stores retained different bytes")
        index = append_cas_event(
            index_journal,
            {"receipts": receipts, "record_id": record_id},
            expected_epoch=expected_index_epoch,
        )
    except (OSError, ReleaseControlError) as exc:
        if recovery_output is not None:
            if recovery_invocation_id is None:
                raise ReleaseControlError("recovery output requires a new invocation id") from exc
            envelope = recovery_envelope(
                operation="retain-two-store-evidence",
                invocation_id=recovery_invocation_id,
                sequence=recovery_sequence,
                committed_digest=receipts[0]["digest"] if receipts else None,
                failure=str(exc),
            )
            write_immutable_json(recovery_output, envelope)
        raise
    return {"index": index, "receipts": receipts}


def recovery_envelope(
    *,
    operation: str,
    invocation_id: str,
    sequence: int,
    committed_digest: str | None,
    failure: str,
) -> dict[str, Any]:
    _require_invocation(invocation_id)
    if sequence < 1 or not operation or not failure:
        raise ReleaseControlError("recovery envelope fields are incomplete")
    if committed_digest is not None:
        _require_digest(committed_digest, "committed_digest")
    value: dict[str, Any] = {
        "committed_digest": committed_digest,
        "failure": failure,
        "invocation_id": invocation_id,
        "operation": operation,
        "sequence": sequence,
    }
    value["recovery_digest"] = sha256_json(value)
    return value


def audit_release_repository(repository: Path, *, live: bool) -> dict[str, Any]:
    """Audit the framework; live mode always names unresolved external authority."""

    required = [
        repository / ".github/workflows/release-required.yml",
        repository / "docs/status/release-readiness.json",
        repository / "docs/status/release-targets.json",
        repository / "docs/status/release-evidence-stores.json",
        repository / "metriplane/release_control.py",
    ]
    missing = [path.relative_to(repository).as_posix() for path in required if not path.is_file()]
    schemas = sorted((repository / "schemas").glob("metriplane.release-*.v1.schema.json"))
    blockers: list[dict[str, Any]] = []
    if missing:
        blockers.append({"code": "MISSING_FRAMEWORK_FILE", "paths": missing})
    if len(schemas) < 47:
        blockers.append({"code": "INCOMPLETE_RELEASE_SCHEMAS", "observed": len(schemas)})
    if live:
        blockers.extend(
            [
                {"code": "LIVE_NON_AUTHOR_APPROVAL_REQUIRED"},
                {"code": "EXTERNAL_TWO_STORE_READBACK_AND_CAS_PROOF_REQUIRED"},
                {"code": "HOSTED_PROTECTION_AND_REAL_MERGE_PROOF_REQUIRED"},
            ]
        )
    return {
        "blockers": blockers,
        "mode": "live" if live else "fixture",
        "schema_count": len(schemas),
        "status": "BLOCKED_NOT_READY" if blockers else "READY",
    }


def _record_type_from_tool(tool: str) -> str:
    stem = Path(tool).stem
    for prefix in (
        "validate_",
        "capture_",
        "record_",
        "build_",
        "finalize_",
        "prepare_",
        "resolve_",
        "collect_",
        "export_",
        "update_",
        "retain_",
        "execute_",
        "plan_",
        "promote_",
        "freeze_",
        "aggregate_",
        "check_",
    ):
        if stem.startswith(prefix):
            stem = stem.removeprefix(prefix)
            break
    aliases = {
        "release_delta": "release-capability-delta",
        "release_blocker_attempt": "release-prepublication-blocker-attempt",
        "publication_reconciliation": "release-publication-reconciliation",
        "last_known_good": "release-last-known-good",
        "linear_release_snapshot": "linear-release-snapshot",
        "release_run_statuses": "release-run-status-snapshot",
        "release_task_state_observation": "release-task-state-observation",
        "release_target_observations": "release-target-observations",
        "release_evidence_stores": "release-evidence-store-preflight",
        "release_retention": "release-retention-receipts",
        "release_evidence": "release-retention-receipts",
        "release_artifacts": "release-artifact-manifest",
        "release_attempt_cells": "release-cell-result",
        "release_candidate": "release-promotion",
        "release_qualification": "release-qualification",
    }
    if Path(tool).stem == "plan_release_qualification":
        return "release-qualification-plan"
    return aliases.get(
        stem,
        stem.replace("_", "-")
        if stem.startswith("release_")
        else f"release-{stem.replace('_', '-')}",
    )


def tool_main(tool: str, argv: Sequence[str] | None = None) -> int:
    """Run one stable tool adapter without granting it provider mutation authority."""

    parser = argparse.ArgumentParser(prog=Path(tool).name)
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--roles", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--invocation-id", default="local-fixture-invocation")
    parser.add_argument("--sequence", type=int, default=1)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    args = parser.parse_args(argv)
    name = Path(tool).stem
    try:
        if name == "check_release_readiness":
            result: dict[str, Any] = audit_release_repository(
                args.repository.resolve(), live=args.mode == "live"
            )
            if result["status"] != "READY":
                print(canonical_json(result).decode("utf-8"))
                return 2
        elif name.startswith("validate_"):
            if len(args.input) != 1:
                raise ReleaseControlError("validator requires exactly one --input")
            result = read_json(args.input[0])
            expected_type = _record_type_from_tool(tool)
            validate_record(result, expected_type)
            live = args.mode == "live"
            if name == "validate_release_role_assignments":
                validate_role_assignments(result, live=live)
            elif name == "validate_release_approval":
                if args.roles is None:
                    raise ReleaseControlError("approval validation requires --roles")
                role_record = read_json(args.roles)
                roles = validate_role_assignments(role_record, live=live)
                validate_approval(result, roles, live=live)
            elif live and result["synthetic"] is not False:
                raise ReleaseControlError(
                    "synthetic records cannot satisfy a live release validator"
                )
        else:
            if args.mode == "live":
                raise ReleaseControlError(
                    "generic local producers cannot create provider-authenticated live authority"
                )
            inputs = []
            for path in args.input:
                payload = read_json(path)
                inputs.append({"path": path.as_posix(), "sha256": sha256_json(payload)})
            result = make_record(
                _record_type_from_tool(tool),
                {"inputs": inputs, "tool": name},
                invocation_id=args.invocation_id,
                sequence=args.sequence,
                synthetic=args.mode == "fixture",
            )
            if args.output is None:
                raise ReleaseControlError("record producer requires --output")
            write_immutable_json(args.output, result)
        print(canonical_json(result).decode("utf-8"))
    except (OSError, ReleaseControlError) as exc:
        raise SystemExit(f"release control failed: {exc}") from exc
    return 0


__all__ = [
    "MILESTONES",
    "STAGES",
    "ReleaseControlError",
    "acquire_promotion_lock",
    "advance_attempt",
    "append_cas_event",
    "audit_release_repository",
    "build_promotion_plan",
    "candidate_identity",
    "canonical_json",
    "finalize_cells",
    "make_record",
    "new_attempt",
    "read_json",
    "reconcile_publication",
    "record_target_burn",
    "recovery_envelope",
    "require_lock_owner",
    "resolve_burn_with_patch",
    "retain_two_store_evidence",
    "sha256_json",
    "tool_main",
    "validate_approval",
    "validate_cumulative_milestones",
    "validate_lkg_invalidation",
    "validate_predecessor",
    "validate_promotion_plan",
    "validate_record",
    "validate_role_assignments",
    "validate_task_state_observation",
    "write_immutable_json",
]
