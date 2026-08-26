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
from dataclasses import dataclass
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
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ReleaseControlError("sequence must be a positive integer")
    if not isinstance(status, str) or status not in TERMINAL_RESULTS | {
        "OPEN",
        "READY",
        "INVALIDATED",
    }:
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
    status = record["status"]
    if not isinstance(status, str) or status not in TERMINAL_RESULTS | {
        "OPEN",
        "READY",
        "INVALIDATED",
    }:
        raise ReleaseControlError("release record has an invalid status")
    claimed_id = _require_digest(record["record_id"], "record_id")
    unsigned = dict(record)
    del unsigned["record_id"]
    if claimed_id != sha256_json(unsigned):
        raise ReleaseControlError("release record identity mismatch")


def _validated_signature(signature: Mapping[str, Any], *, subject_digest: str, live: bool) -> str:
    exact = {"actor_id", "algorithm", "provider", "signature", "subject_digest", "synthetic"}
    if not isinstance(signature, Mapping):
        raise ReleaseControlError("signature is not an object")
    if set(signature) != exact:
        raise ReleaseControlError("signature shape is not closed")
    if signature["subject_digest"] != subject_digest:
        raise ReleaseControlError("signature is not bound to the record payload")
    actor_id = signature["actor_id"]
    if not isinstance(actor_id, str) or not actor_id:
        raise ReleaseControlError("signature actor is missing")
    algorithm = signature["algorithm"]
    if not isinstance(algorithm, str) or algorithm not in {
        "provider-attestation-v1",
        "test-sha256-v1",
    }:
        raise ReleaseControlError("signature algorithm is not allowed")
    provider = signature["provider"]
    if not isinstance(provider, str):
        raise ReleaseControlError("signature provider is invalid")
    synthetic = signature["synthetic"]
    if not isinstance(synthetic, bool):
        raise ReleaseControlError("signature synthetic flag must be boolean")
    signature_value = signature["signature"]
    if not isinstance(signature_value, str) or len(signature_value) < 16:
        raise ReleaseControlError("signature value is missing")
    if live:
        if synthetic is not False:
            raise ReleaseControlError("synthetic signatures cannot authorize live release work")
        if provider not in {"github", "linear"}:
            raise ReleaseControlError("live signatures require provider authority")
        if algorithm != "provider-attestation-v1":
            raise ReleaseControlError("test signatures cannot authorize live release work")
        raise ReleaseControlError(
            "live provider signature verification is not implemented; field shape is not authority"
        )
    if (
        synthetic is not True
        or provider != "test-fixture"
        or algorithm != "test-sha256-v1"
        or signature_value != sha256_json({"actor_id": actor_id, "subject_digest": subject_digest})
    ):
        raise ReleaseControlError("synthetic signature authentication failed")
    return actor_id


def _validated_record_signers(record: Mapping[str, Any], *, live: bool) -> set[str]:
    signatures = record["signatures"]
    if live and not signatures:
        raise ReleaseControlError("live release authority has no authenticated signature")
    return {
        _validated_signature(
            signature,
            subject_digest=record["payload_digest"],
            live=live,
        )
        for signature in signatures
    }


def validate_role_assignments(record: Mapping[str, Any], *, live: bool) -> dict[str, str]:
    validate_record(record, "release-role-assignments")
    if record["status"] != "PASS":
        raise ReleaseControlError("release role assignments are not passing authority")
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


def _release_input(path: Path, expected_type: str, *, live: bool) -> dict[str, Any]:
    record = read_json(path)
    validate_record(record, expected_type)
    if record["status"] not in {"PASS", "READY"}:
        raise ReleaseControlError(f"{expected_type} is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError(f"synthetic {expected_type} cannot satisfy a live release")
    _validated_record_signers(record, live=live)
    return record


def _release_data(
    record: Mapping[str, Any], expected_fields: set[str], label: str
) -> dict[str, Any]:
    data = record["data"]
    if not isinstance(data, dict) or set(data) != expected_fields:
        raise ReleaseControlError(f"{label} data shape is not closed")
    return data


def _passing_record(record: Mapping[str, Any], expected_type: str, *, live: bool) -> dict[str, Any]:
    validate_record(record, expected_type)
    if record["status"] != "PASS":
        raise ReleaseControlError(f"{expected_type} is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError(f"synthetic {expected_type} cannot authorize a live release")
    _validated_record_signers(record, live=live)
    data = record["data"]
    if not isinstance(data, dict):
        raise ReleaseControlError(f"{expected_type} data is not an object")
    return data


def _evidence_record_index(root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    if root.is_symlink() or not root.is_dir():
        raise ReleaseControlError("release evidence root is missing or unsafe")
    indexed: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(root)
        parent = root
        for part in relative.parts[:-1]:
            parent /= part
            if parent.is_symlink():
                raise ReleaseControlError(f"release evidence traverses a symlink: {path}")
        digest = _regular_file_digest(path)
        indexed.setdefault(digest, []).append((path, read_json(path)))
    return indexed


def _resolved_evidence_record(
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    digest: object,
    expected_type: str,
    label: str,
    *,
    live: bool,
) -> dict[str, Any]:
    required_digest = _require_digest(digest, label)
    matches = indexed.get(required_digest, ())
    if not matches:
        raise ReleaseControlError(f"{label} does not resolve to retained bytes")
    records: list[dict[str, Any]] = []
    for _path, candidate in matches:
        _passing_record(candidate, expected_type, live=live)
        records.append(candidate)
    first = records[0]
    if any(candidate != first for candidate in records[1:]):
        raise ReleaseControlError(f"{label} resolves ambiguously")
    return first


def _candidate_record_for_digest(
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    candidate_digest: str,
    *,
    live: bool,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for entries in indexed.values():
        for _path, record in entries:
            if record.get("record_type") != "release-candidate-identity":
                continue
            data = _passing_record(record, "release-candidate-identity", live=live)
            if data.get("candidate_digest") == candidate_digest:
                matches.append(record)
    if len(matches) != 1:
        raise ReleaseControlError("qualification candidate identity does not resolve exactly once")
    return matches[0]


def validate_release_qualification_record(
    record: Mapping[str, Any], *, evidence_root: Path, live: bool
) -> None:
    data = _passing_record(record, "release-qualification", live=live)
    expected_fields = {
        "attempt_digests",
        "attempt_index_receipt_digests",
        "attempt_retention_receipt_digests",
        "candidate_digest",
        "executed_cell_ids",
        "expected_cell_ids",
        "plan_digest",
        "qualification_digest",
        "result",
        "terminal_results",
        "unexpected_outcomes",
        "warning_summary_digest",
    }
    if set(data) != expected_fields:
        raise ReleaseControlError("release qualification data shape is not closed")
    if data["result"] != "PASS" or data["unexpected_outcomes"] != []:
        raise ReleaseControlError("release qualification is not a clean PASS")
    expected_cells = data["expected_cell_ids"]
    executed_cells = data["executed_cell_ids"]
    if (
        not isinstance(expected_cells, list)
        or not expected_cells
        or any(not isinstance(cell, str) or not cell for cell in expected_cells)
        or expected_cells != sorted(expected_cells)
        or len(expected_cells) != len(set(expected_cells))
        or executed_cells != expected_cells
    ):
        raise ReleaseControlError("release qualification cell inventory is incomplete")
    terminals = data["terminal_results"]
    if not isinstance(terminals, list) or len(terminals) != len(expected_cells):
        raise ReleaseControlError("release qualification terminal matrix is incomplete")
    terminal_ids: list[str] = []
    for row in terminals:
        if not isinstance(row, dict) or set(row) != {"cell_id", "result", "result_digest"}:
            raise ReleaseControlError("release qualification terminal row is malformed")
        terminal_ids.append(str(row["cell_id"]))
        if row["result"] != "PASS":
            raise ReleaseControlError("release qualification contains a non-passing terminal")
        _require_digest(row["result_digest"], "qualification terminal result")
    if terminal_ids != expected_cells:
        raise ReleaseControlError("release qualification terminals do not match expected cells")
    for field in (
        "attempt_digests",
        "attempt_index_receipt_digests",
        "attempt_retention_receipt_digests",
    ):
        values = data[field]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))
        ):
            raise ReleaseControlError(f"release qualification {field} is incomplete")
        for value in values:
            _require_digest(value, f"release qualification {field}")
    for field in (
        "candidate_digest",
        "plan_digest",
        "qualification_digest",
        "warning_summary_digest",
    ):
        _require_digest(data[field], f"release qualification {field}")

    indexed = _evidence_record_index(evidence_root)
    plan_record = _resolved_evidence_record(
        indexed,
        data["plan_digest"],
        "release-qualification-plan",
        "release qualification plan",
        live=live,
    )
    plan = _passing_record(plan_record, "release-qualification-plan", live=live)
    if plan.get("candidate_digest") != data["candidate_digest"]:
        raise ReleaseControlError("release qualification plan candidate binding mismatch")
    plan_cells = plan.get("cells")
    if not isinstance(plan_cells, list) or any(not isinstance(cell, dict) for cell in plan_cells):
        raise ReleaseControlError("release qualification plan cells are malformed")
    plan_cell_ids = [cell.get("cell_id") for cell in plan_cells]
    if plan_cell_ids != expected_cells:
        raise ReleaseControlError("release qualification plan cell inventory mismatch")
    _candidate_record_for_digest(indexed, data["candidate_digest"], live=live)

    attempts = [
        _resolved_evidence_record(
            indexed,
            digest,
            "release-attempt",
            "release qualification attempt",
            live=live,
        )
        for digest in data["attempt_digests"]
    ]
    attempt_count = plan.get("attempt_count")
    if (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count != len(attempts)
    ):
        raise ReleaseControlError("release qualification attempt count mismatch")
    observed_result_digests: set[str] = set()
    for attempt_record in attempts:
        attempt = _release_data(
            attempt_record,
            {
                "attempt_id",
                "candidate_digest",
                "cells",
                "coordination_digest",
                "index_receipt_digest",
                "milestone",
                "qualification_plan_digest",
                "result",
                "retention_receipts_digest",
                "warning_summary_digest",
            },
            "release qualification attempt",
        )
        if (
            attempt["result"] != "PASS"
            or attempt["candidate_digest"] != data["candidate_digest"]
            or attempt["qualification_plan_digest"] != data["plan_digest"]
        ):
            raise ReleaseControlError("release qualification attempt binding mismatch")
        attempt_cells = attempt["cells"]
        if not isinstance(attempt_cells, list) or len(attempt_cells) != len(expected_cells):
            raise ReleaseControlError("release qualification attempt cell matrix is incomplete")
        attempt_cell_ids: list[str] = []
        for cell in attempt_cells:
            if not isinstance(cell, dict) or set(cell) != {"cell_id", "result", "result_digest"}:
                raise ReleaseControlError("release qualification attempt cell is malformed")
            if cell["result"] != "PASS":
                raise ReleaseControlError("release qualification attempt cell is not passing")
            attempt_cell_ids.append(str(cell["cell_id"]))
            observed_result_digests.add(
                _require_digest(cell["result_digest"], "release qualification attempt cell")
            )
        if attempt_cell_ids != expected_cells:
            raise ReleaseControlError("release qualification attempt cell inventory mismatch")
        _require_digest(attempt["index_receipt_digest"], "release attempt index receipt")
        _require_digest(attempt["retention_receipts_digest"], "release attempt retention receipt")

    for digest in data["attempt_index_receipt_digests"]:
        _resolved_evidence_record(
            indexed,
            digest,
            "release-attempt-index",
            "release qualification index receipt",
            live=live,
        )
    for digest in data["attempt_retention_receipt_digests"]:
        _resolved_evidence_record(
            indexed,
            digest,
            "release-retention-receipts",
            "release qualification retention receipt",
            live=live,
        )
    for terminal in terminals:
        digest = terminal["result_digest"]
        if digest not in observed_result_digests:
            raise ReleaseControlError("release qualification terminal is absent from attempts")
        cell_record = _resolved_evidence_record(
            indexed,
            digest,
            "release-cell-result",
            "release qualification terminal result",
            live=live,
        )
        cell = _passing_record(cell_record, "release-cell-result", live=live)
        if (
            cell.get("cell_id") != terminal["cell_id"]
            or cell.get("candidate_digest") != data["candidate_digest"]
            or cell.get("plan_digest") != data["plan_digest"]
            or cell.get("result") != "PASS"
            or cell.get("unexpected_outcomes") != []
        ):
            raise ReleaseControlError("release qualification terminal result binding mismatch")
    warning_record = _resolved_evidence_record(
        indexed,
        data["warning_summary_digest"],
        "release-warning-summary",
        "release qualification warning summary",
        live=live,
    )
    warning = _passing_record(warning_record, "release-warning-summary", live=live)
    if (
        warning.get("candidate_digest") != data["candidate_digest"]
        or warning.get("result") != "PASS"
        or any(
            warning.get(field) != 0
            for field in (
                "deselection_count",
                "retry_count",
                "skip_count",
                "unexpected_warning_count",
                "xfail_count",
                "xpass_count",
            )
        )
    ):
        raise ReleaseControlError("release qualification warning summary is not clean")


def validate_publication_reconciliation_record(
    record: Mapping[str, Any], *, evidence_root: Path, live: bool
) -> None:
    data = _passing_record(record, "release-publication-reconciliation", live=live)
    expected_fields = {
        "approval_digest",
        "burn_required",
        "candidate_digest",
        "evidence_manifest_digest",
        "expected_artifacts",
        "lock_receipt_digest",
        "milestone",
        "observations_digest",
        "partial_targets",
        "promotion_digest",
        "qualification_digest",
        "reconciliation_digest",
        "result",
        "staged_retention_receipts_digest",
        "targets",
    }
    if set(data) != expected_fields:
        raise ReleaseControlError("publication reconciliation data shape is not closed")
    if data["result"] != "RECONCILED" or data["burn_required"] is not False:
        raise ReleaseControlError("publication reconciliation is not cleanly reconciled")
    if data["partial_targets"] != []:
        raise ReleaseControlError("publication reconciliation contains partial targets")
    for field in expected_fields - {
        "burn_required",
        "expected_artifacts",
        "milestone",
        "partial_targets",
        "result",
        "targets",
    }:
        _require_digest(data[field], f"publication reconciliation {field}")
    if data["milestone"] not in MILESTONES:
        raise ReleaseControlError("publication reconciliation milestone is invalid")
    artifacts = data["expected_artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) < 2:
        raise ReleaseControlError("publication reconciliation has no closed artifact set")
    artifact_names: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {
            "media_type",
            "path",
            "sha256",
            "size",
        }:
            raise ReleaseControlError("publication reconciliation artifact row is malformed")
        path = artifact["path"]
        if not isinstance(path, str) or not path or Path(path).name != path:
            raise ReleaseControlError("publication reconciliation artifact path is unsafe")
        if not isinstance(artifact["media_type"], str) or not artifact["media_type"]:
            raise ReleaseControlError("publication reconciliation artifact media type is missing")
        _require_digest(artifact["sha256"], f"publication reconciliation artifact {path}")
        size = artifact["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ReleaseControlError("publication reconciliation artifact size is invalid")
        artifact_names.append(path)
    if artifact_names != sorted(set(artifact_names)):
        raise ReleaseControlError("publication reconciliation artifacts are not canonical")
    targets = data["targets"]
    if not isinstance(targets, list) or not targets:
        raise ReleaseControlError("publication reconciliation has no target observations")
    target_ids: list[str] = []
    for target in targets:
        if not isinstance(target, dict) or set(target) != {
            "conflict_digest",
            "exact_match",
            "target_id",
        }:
            raise ReleaseControlError("publication reconciliation target row is malformed")
        target_id = target["target_id"]
        if not isinstance(target_id, str) or not target_id:
            raise ReleaseControlError("publication reconciliation target id is missing")
        if target["exact_match"] is not True or target["conflict_digest"] is not None:
            raise ReleaseControlError("publication reconciliation target is not an exact match")
        target_ids.append(target_id)
    if target_ids != sorted(set(target_ids)):
        raise ReleaseControlError("publication reconciliation targets are not canonical")

    indexed = _evidence_record_index(evidence_root)
    dependency_types = {
        "approval_digest": "release-approval",
        "evidence_manifest_digest": "release-evidence-manifest",
        "lock_receipt_digest": "release-promotion-lock",
        "observations_digest": "release-publication-observations",
        "promotion_digest": "release-promotion",
        "qualification_digest": "release-qualification",
        "staged_retention_receipts_digest": "release-retention-receipts",
    }
    dependencies = {
        field: _resolved_evidence_record(
            indexed,
            data[field],
            record_type,
            f"publication reconciliation {field}",
            live=live,
        )
        for field, record_type in dependency_types.items()
    }
    approval = _passing_record(dependencies["approval_digest"], "release-approval", live=live)
    evidence_manifest = _passing_record(
        dependencies["evidence_manifest_digest"],
        "release-evidence-manifest",
        live=live,
    )
    lock = _passing_record(dependencies["lock_receipt_digest"], "release-promotion-lock", live=live)
    observations = _passing_record(
        dependencies["observations_digest"],
        "release-publication-observations",
        live=live,
    )
    promotion = _passing_record(dependencies["promotion_digest"], "release-promotion", live=live)
    qualification = _passing_record(
        dependencies["qualification_digest"], "release-qualification", live=live
    )
    candidate_digest = data["candidate_digest"]
    candidate_bindings = {
        "approval": approval.get("candidate_digest"),
        "evidence manifest": evidence_manifest.get("candidate_digest"),
        "lock": lock.get("candidate_digest"),
        "observations": observations.get("candidate_digest"),
        "promotion": promotion.get("candidate_digest"),
        "qualification": qualification.get("candidate_digest"),
    }
    for label, observed_candidate in candidate_bindings.items():
        if observed_candidate != candidate_digest:
            raise ReleaseControlError(f"publication reconciliation {label} candidate mismatch")
    if (
        lock.get("approval_digest") != data["approval_digest"]
        or promotion.get("lock_receipt_digest") != data["lock_receipt_digest"]
        or observations.get("lock_receipt_digest") != data["lock_receipt_digest"]
        or observations.get("promotion_digest") != data["promotion_digest"]
    ):
        raise ReleaseControlError("publication reconciliation control binding mismatch")
    if (
        lock.get("state") != "COMMITTED"
        or lock.get("mutation_started") is not True
        or promotion.get("result") != "PUBLISHED"
        or promotion.get("mutation_started") is not True
        or observations.get("all_targets_observed") is not True
        or evidence_manifest.get("phase") != "qualified-publication"
    ):
        raise ReleaseControlError("publication reconciliation dependencies are not final")

    expected = {artifact["path"]: (artifact["sha256"], artifact["size"]) for artifact in artifacts}
    observation_targets = observations.get("targets")
    if not isinstance(observation_targets, list) or not observation_targets:
        raise ReleaseControlError("publication reconciliation observations have no targets")
    observed_target_ids: list[str] = []
    for target in observation_targets:
        if not isinstance(target, dict):
            raise ReleaseControlError("publication reconciliation observation target is malformed")
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ReleaseControlError("publication reconciliation observation target id is missing")
        if target.get("availability") != "present" or target.get("immutability") != "immutable":
            raise ReleaseControlError("publication reconciliation observed a non-final target")
        observed_artifacts = target.get("artifacts")
        if not isinstance(observed_artifacts, list) or len(observed_artifacts) != len(expected):
            raise ReleaseControlError(
                "publication reconciliation observed artifact set is incomplete"
            )
        observed_artifact_set: dict[str, tuple[object, object]] = {}
        for artifact in observed_artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {
                "expected_digest",
                "name",
                "observed_digest",
                "size",
            }:
                raise ReleaseControlError(
                    "publication reconciliation observed artifact is malformed"
                )
            name = artifact["name"]
            if not isinstance(name, str) or name in observed_artifact_set:
                raise ReleaseControlError(
                    "publication reconciliation observed artifact name is invalid"
                )
            if artifact["expected_digest"] != artifact["observed_digest"]:
                raise ReleaseControlError("publication reconciliation observed bytes differ")
            observed_artifact_set[name] = (artifact["observed_digest"], artifact["size"])
        if observed_artifact_set != expected:
            raise ReleaseControlError("publication reconciliation observed artifact set differs")
        observed_target_ids.append(target_id)
    if observed_target_ids != target_ids:
        raise ReleaseControlError("publication reconciliation observed target set differs")


def validate_release_gate_instance_record(
    record: Mapping[str, Any],
    *,
    candidate_identity_record: Mapping[str, Any],
    predecessor_record: Mapping[str, Any],
    task_state_policy: Mapping[str, Any],
    live: bool,
) -> None:
    gate = _passing_record(record, "release-gate-instance", live=live)
    candidate = _passing_record(candidate_identity_record, "release-candidate-identity", live=live)
    predecessor = _passing_record(predecessor_record, "release-predecessor", live=live)
    bindings = {
        "candidate identity": (
            gate.get("candidate_identity_digest"),
            sha256_json(candidate_identity_record),
        ),
        "candidate": (gate.get("candidate_digest"), candidate.get("candidate_digest")),
        "predecessor": (gate.get("predecessor_digest"), sha256_json(predecessor_record)),
        "candidate predecessor": (
            candidate.get("predecessor_digest"),
            sha256_json(predecessor_record),
        ),
        "milestone": (gate.get("milestone"), candidate.get("milestone")),
        "package version": (gate.get("package_version"), candidate.get("package_version")),
        "release tag": (gate.get("release_tag"), candidate.get("release_tag")),
        "gate input": (gate.get("gate_input_digest"), candidate.get("gate_input_digest")),
        "task-state policy": (
            gate.get("task_state_policy_digest"),
            sha256_json(task_state_policy),
        ),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"release gate {label} binding mismatch")
    if predecessor.get("candidate_milestone") != gate.get("milestone"):
        raise ReleaseControlError("release gate predecessor milestone mismatch")


def validate_release_qualification_plan_record(
    record: Mapping[str, Any], *, gate_instance: Mapping[str, Any], live: bool
) -> None:
    plan = _passing_record(record, "release-qualification-plan", live=live)
    gate = _passing_record(gate_instance, "release-gate-instance", live=live)
    expected_fields = {
        "attempt_count",
        "candidate_digest",
        "candidate_manifest_digest",
        "cells",
        "delta_digest",
        "delta_test_map_digest",
        "expected_terminal_result",
        "gate_instance_digest",
        "milestone",
        "plan_digest",
        "predecessor_digest",
        "readiness_digest",
        "scenario_catalog_digest",
    }
    if set(plan) != expected_fields:
        raise ReleaseControlError("release qualification plan data shape is not closed")
    bindings = {
        "gate instance": (plan["gate_instance_digest"], sha256_json(gate_instance)),
        "candidate": (plan["candidate_digest"], gate.get("candidate_digest")),
        "predecessor": (plan["predecessor_digest"], gate.get("predecessor_digest")),
        "milestone": (plan["milestone"], gate.get("milestone")),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"release qualification plan {label} binding mismatch")
    cells = plan["cells"]
    cell_identities = (
        [sha256_json(cell) if isinstance(cell, dict) else cell for cell in cells]
        if isinstance(cells, list)
        else []
    )
    if (
        plan["expected_terminal_result"] != "PASS"
        or not isinstance(cells, list)
        or not cells
        or any(not isinstance(cell, (str, dict)) for cell in cells)
        or len(cell_identities) != len(set(cell_identities))
        or plan["attempt_count"] != len(cells)
    ):
        raise ReleaseControlError("release qualification plan matrix is invalid")
    for field in expected_fields - {
        "attempt_count",
        "cells",
        "expected_terminal_result",
        "milestone",
    }:
        _require_digest(plan[field], f"release qualification plan {field}")


def validate_release_approval_record(
    record: Mapping[str, Any],
    *,
    gate_instance: Mapping[str, Any],
    qualification: Mapping[str, Any],
    no_prepublication_rubric: bool,
    live: bool,
) -> None:
    approval = _passing_record(record, "release-approval", live=live)
    gate = _passing_record(gate_instance, "release-gate-instance", live=live)
    qualification_data = _passing_record(qualification, "release-qualification", live=live)
    basic = {"author_id", "candidate_digest", "conflicts", "decision", "reviewer_id"}
    extended = {
        "approval_decision_digest",
        "gate_instance_digest",
        "qualification_digest",
        "rubric_result_digest",
    }
    if not basic <= set(approval) or not set(approval) <= basic | extended:
        raise ReleaseControlError("release approval data shape is not closed")
    if live and set(approval) != basic | extended:
        raise ReleaseControlError("live release approval lacks required authority bindings")
    if approval["decision"] != "APPROVED" or approval["conflicts"] != []:
        raise ReleaseControlError("release approval is not conflict-free and approved")
    author = approval["author_id"]
    reviewer = approval["reviewer_id"]
    if not isinstance(author, str) or not isinstance(reviewer, str) or author == reviewer:
        raise ReleaseControlError("release approval is not from a distinct non-author")
    if approval["candidate_digest"] != gate.get("candidate_digest") or approval[
        "candidate_digest"
    ] != qualification_data.get("candidate_digest"):
        raise ReleaseControlError("release approval candidate binding mismatch")
    if "gate_instance_digest" in approval and approval["gate_instance_digest"] != sha256_json(
        gate_instance
    ):
        raise ReleaseControlError("release approval gate-instance binding mismatch")
    if "qualification_digest" in approval and approval["qualification_digest"] != sha256_json(
        qualification
    ):
        raise ReleaseControlError("release approval qualification binding mismatch")
    if no_prepublication_rubric and approval.get("rubric_result_digest") is not None:
        raise ReleaseControlError("prepublication approval unexpectedly names a rubric result")
    if "approval_decision_digest" in approval:
        _require_digest(approval["approval_decision_digest"], "approval decision")
    signers = {
        _validated_signature(
            signature,
            subject_digest=record["payload_digest"],
            live=live,
        )
        for signature in record["signatures"]
    }
    if reviewer not in signers:
        raise ReleaseControlError("release approval lacks reviewer-authenticated authority")


def validate_release_candidate_identity_record(
    record: Mapping[str, Any],
    *,
    predecessor_record: Mapping[str, Any],
    candidate_dir: Path,
    no_evaluation_adoption: bool,
    live: bool,
) -> None:
    candidate = _passing_record(record, "release-candidate-identity", live=live)
    predecessor = _passing_record(predecessor_record, "release-predecessor", live=live)
    expected_fields = {
        "artifact_manifest_digest",
        "artifact_set_digest",
        "build_invocation_id",
        "candidate_digest",
        "evaluation_adoption_digest",
        "evaluation_adoption_mode",
        "gate_input_digest",
        "milestone",
        "package_version",
        "predecessor_digest",
        "release_tag",
        "source_freeze_digest",
    }
    if set(candidate) != expected_fields:
        raise ReleaseControlError("release candidate identity data shape is not closed")
    if candidate["predecessor_digest"] != sha256_json(predecessor_record):
        raise ReleaseControlError("release candidate predecessor binding mismatch")
    milestone = candidate["milestone"]
    if (
        milestone not in MILESTONES
        or predecessor.get("candidate_milestone") != milestone
        or not isinstance(candidate["package_version"], str)
        or not candidate["package_version"].startswith(f"{milestone}.")
        or candidate["release_tag"] != candidate["package_version"]
    ):
        raise ReleaseControlError("release candidate version bindings are invalid")
    if no_evaluation_adoption and (
        candidate["evaluation_adoption_mode"] != "none"
        or candidate["evaluation_adoption_digest"] is not None
    ):
        raise ReleaseControlError("release candidate adopts unapproved evaluation authority")
    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise ReleaseControlError("release candidate directory is missing or unsafe")
    entries = list(candidate_dir.iterdir())
    if len(entries) != 2 or any(path.is_symlink() or not path.is_file() for path in entries):
        raise ReleaseControlError("release candidate directory has no closed regular-file set")
    artifact_rows: list[dict[str, Any]] = []
    expected_media = {
        ".whl": "application/vnd.pypa.wheel+zip",
        ".tar.gz": "application/gzip",
    }
    observed_suffixes: set[str] = set()
    for path in sorted(entries, key=lambda item: item.name):
        suffix = ".tar.gz" if path.name.endswith(".tar.gz") else path.suffix
        if suffix not in expected_media or suffix in observed_suffixes:
            raise ReleaseControlError("release candidate directory is not one wheel and one sdist")
        observed_suffixes.add(suffix)
        artifact_rows.append(
            {
                "media_type": expected_media[suffix],
                "path": path.name,
                "sha256": _regular_file_digest(path),
                "size": path.stat().st_size,
            }
        )
    if candidate["artifact_set_digest"] != sha256_json(artifact_rows):
        raise ReleaseControlError("release candidate directory differs from its artifact set")
    for field in expected_fields - {
        "build_invocation_id",
        "evaluation_adoption_digest",
        "evaluation_adoption_mode",
        "milestone",
        "package_version",
        "release_tag",
    }:
        _require_digest(candidate[field], f"release candidate {field}")


def _regular_file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ReleaseControlError(f"artifact is missing or not a regular file: {path}")
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ReleaseControlError(f"cannot read artifact bytes: {path}") from exc


def validate_release_artifact_files(
    record: Mapping[str, Any], artifacts: Path, *, live: bool
) -> None:
    """Bind every publishable byte and filename to the frozen-source manifest."""

    validate_record(record, "release-artifact-manifest")
    if record["status"] != "PASS":
        raise ReleaseControlError("artifact manifest is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic artifact manifests cannot authorize live publication")
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise ReleaseControlError("artifact directory is missing or unsafe")
    data = _release_data(
        record,
        {
            "artifact_set_digest",
            "artifacts",
            "build_invocation_id",
            "build_recipe_digest",
            "milestone",
            "source_digest",
            "source_freeze_digest",
            "target_resolution_digest",
        },
        "release artifact manifest",
    )
    rows = data["artifacts"]
    if not isinstance(rows, list) or len(rows) != 2:
        raise ReleaseControlError("artifact manifest must name exactly one wheel and one sdist")
    expected_names: set[str] = set()
    expected_types = {
        ".whl": "application/vnd.pypa.wheel+zip",
        ".tar.gz": "application/gzip",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"media_type", "path", "sha256", "size"}:
            raise ReleaseControlError("artifact manifest row shape is not closed")
        name = row["path"]
        if not isinstance(name, str) or Path(name).name != name or name in expected_names:
            raise ReleaseControlError("artifact manifest contains an unsafe or duplicate filename")
        suffix = ".tar.gz" if name.endswith(".tar.gz") else Path(name).suffix
        if suffix not in expected_types or row["media_type"] != expected_types[suffix]:
            raise ReleaseControlError(f"artifact media type does not match filename: {name}")
        path = artifacts / name
        digest = _regular_file_digest(path)
        if digest != _require_digest(row["sha256"], f"artifact {name}"):
            raise ReleaseControlError(f"artifact digest differs from frozen manifest: {name}")
        if isinstance(row["size"], bool) or row["size"] != path.stat().st_size:
            raise ReleaseControlError(f"artifact size differs from frozen manifest: {name}")
        expected_names.add(name)
    if [row["path"] for row in rows] != sorted(expected_names):
        raise ReleaseControlError("artifact manifest rows are not canonically ordered")
    observed_entries = list(artifacts.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in observed_entries):
        raise ReleaseControlError("artifact directory contains an unsafe non-artifact entry")
    observed_names = {path.name for path in observed_entries}
    if observed_names != expected_names:
        raise ReleaseControlError("artifact directory membership differs from frozen manifest")
    if data["artifact_set_digest"] != sha256_json(rows):
        raise ReleaseControlError("artifact set digest does not bind the manifest rows")


def validate_release_retention_receipts(
    receipts: Mapping[str, Any],
    *,
    inputs: Sequence[Path],
    manifest: Path | None,
    invocation_root: Path | None,
    through_stage: str | None,
    live: bool,
) -> None:
    """Validate two independent read-backs against the supplied canonical input."""

    validate_record(receipts, "release-retention-receipts")
    if receipts["status"] != "PASS":
        raise ReleaseControlError("retention receipt set is not passing")
    if live and receipts["synthetic"] is not False:
        raise ReleaseControlError("synthetic retention receipts cannot authorize a live release")
    if live:
        raise ReleaseControlError(
            "live two-store read-back verification is not implemented; receipt claims are not authority"
        )
    data = _release_data(
        receipts,
        {
            "all_content_equal",
            "input_digest",
            "phase",
            "receipt_set_digest",
            "retained_at",
            "stores",
        },
        "release retention receipts",
    )
    if data["all_content_equal"] is not True:
        raise ReleaseControlError("retention stores did not report identical content")
    stores = data["stores"]
    if not isinstance(stores, list) or len(stores) != 2:
        raise ReleaseControlError("retention requires exactly two store receipts")
    if [row.get("store_id") for row in stores if isinstance(row, dict)] != [
        "payload-store-a",
        "payload-store-b",
    ]:
        raise ReleaseControlError("retention stores are missing or not canonically ordered")
    independence_groups: set[str] = set()
    input_digest = _require_digest(data["input_digest"], "retained input")
    required_store_fields = {
        "content_digest",
        "hold_receipt_digest",
        "independence_group",
        "namespace",
        "object_key",
        "put_receipt_digest",
        "read_back_digest",
        "store_id",
    }
    for row in stores:
        if not isinstance(row, dict) or set(row) != required_store_fields:
            raise ReleaseControlError("retention store receipt shape is not closed")
        group = row["independence_group"]
        if not isinstance(group, str) or not group.strip():
            raise ReleaseControlError("retention store independence group is missing")
        independence_groups.add(group)
        for field in (
            "content_digest",
            "hold_receipt_digest",
            "put_receipt_digest",
            "read_back_digest",
        ):
            _require_digest(row[field], f"retention {field}")
        if row["content_digest"] != input_digest or row["read_back_digest"] != input_digest:
            raise ReleaseControlError("retention read-back differs from the canonical input")
    if len(independence_groups) != 2:
        raise ReleaseControlError("retention stores are not independently administered")
    if data["receipt_set_digest"] != sha256_json(stores):
        raise ReleaseControlError("retention receipt-set digest mismatch")

    supplied_digests: list[str] = []
    for path in inputs:
        record = read_json(path)
        validate_record(record)
        supplied_digests.append(_regular_file_digest(path))
    if manifest is not None:
        manifest_record = _release_input(manifest, "release-evidence-manifest", live=live)
        manifest_digest = _regular_file_digest(manifest)
        entries = manifest_record["data"].get("entries")
        if not isinstance(entries, list):
            raise ReleaseControlError("evidence manifest entries are missing")
        listed = {
            entry.get("sha256")
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("sha256"), str)
        }
        if any(digest not in listed for digest in supplied_digests):
            raise ReleaseControlError("retained input is absent from the evidence manifest")
        expected_input_digest = manifest_digest
    elif len(supplied_digests) == 1:
        expected_input_digest = supplied_digests[0]
    elif supplied_digests:
        expected_input_digest = sha256_json(sorted(supplied_digests))
    else:
        raise ReleaseControlError("retention validation has no canonical input")
    if input_digest != expected_input_digest:
        raise ReleaseControlError("retention receipts bind a different canonical input")
    if (invocation_root is None) != (through_stage is None):
        raise ReleaseControlError("invocation-root and through-stage must be supplied together")
    if invocation_root is not None and (
        invocation_root.is_symlink() or not invocation_root.is_dir() or not through_stage
    ):
        raise ReleaseControlError("retention invocation journal is missing or unsafe")


def build_release_readiness_record(
    *,
    gate_input: Mapping[str, Any],
    gate_instance: Mapping[str, Any],
    candidate_identity_record: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    linear_snapshot: Mapping[str, Any],
    source_freeze: Mapping[str, Any],
    impact_manifest: Mapping[str, Any],
    artifact_manifest: Mapping[str, Any],
    delta: Mapping[str, Any],
    delta_test_map: Mapping[str, Any],
    readiness_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one deterministic readiness decision from exact, cross-bound inputs."""

    typed = (
        (gate_input, "release-gate-input"),
        (gate_instance, "release-gate-instance"),
        (candidate_identity_record, "release-candidate-identity"),
        (predecessor, "release-predecessor"),
        (linear_snapshot, "linear-release-snapshot"),
        (source_freeze, "release-source-freeze"),
        (impact_manifest, "release-impact-manifest"),
        (artifact_manifest, "release-artifact-manifest"),
        (delta, "release-capability-delta"),
        (delta_test_map, "release-delta-test-map"),
    )
    for record, expected_type in typed:
        validate_record(record, expected_type)
        if record["status"] not in {"PASS", "READY"}:
            raise ReleaseControlError(f"{expected_type} is not passing authority")
    synthetic_modes = {record["synthetic"] for record, _ in typed}
    if len(synthetic_modes) != 1:
        raise ReleaseControlError("readiness inputs mix live and synthetic authority")

    gate_input_data = gate_input["data"]
    gate = gate_instance["data"]
    candidate = candidate_identity_record["data"]
    predecessor_data = predecessor["data"]
    linear = linear_snapshot["data"]
    freeze = source_freeze["data"]
    impact = impact_manifest["data"]
    artifact = artifact_manifest["data"]
    delta_data = delta["data"]
    mapping = delta_test_map["data"]
    if not all(
        isinstance(value, dict)
        for value in (
            gate_input_data,
            gate,
            candidate,
            predecessor_data,
            linear,
            freeze,
            impact,
            artifact,
            delta_data,
            mapping,
        )
    ):
        raise ReleaseControlError("readiness subject data must be closed objects")
    exact_shapes = (
        (
            gate_input_data,
            {
                "environment_registry_digest",
                "evidence_store_registry_digest",
                "expected_predecessor_milestone",
                "gate_input_digest",
                "linear_snapshot_digest",
                "milestone",
                "obligation_registry_digest",
                "readiness_registry_digest",
                "role_assignments_digest",
                "run_id",
                "scenario_registry_digest",
                "target_burn_digest",
                "target_burn_index_receipt_digest",
                "target_registry_digest",
                "target_resolution_digest",
                "task_state_policy_digest",
            },
            "gate input",
        ),
        (
            gate,
            {
                "candidate_digest",
                "candidate_identity_digest",
                "environment_registry_digest",
                "evidence_store_preflight_digest",
                "evidence_store_registry_digest",
                "frozen_source_sha",
                "gate_input_digest",
                "instance_digest",
                "linear_snapshot_digest",
                "main_health_digest",
                "main_health_history_digest",
                "milestone",
                "obligation_registry_digest",
                "package_version",
                "predecessor_digest",
                "release_tag",
                "repository_protection_digest",
                "run_id",
                "scenario_registry_digest",
                "target_registry_digest",
                "task_state_policy_digest",
            },
            "gate instance",
        ),
        (
            candidate,
            {
                "artifact_manifest_digest",
                "artifact_set_digest",
                "build_invocation_id",
                "candidate_digest",
                "evaluation_adoption_digest",
                "evaluation_adoption_mode",
                "gate_input_digest",
                "milestone",
                "package_version",
                "predecessor_digest",
                "release_tag",
                "source_freeze_digest",
            },
            "candidate identity",
        ),
        (
            linear,
            {
                "required_bom_ids",
                "required_bom_snapshot_digest",
                "state",
                "task_id",
                "tool",
            },
            "Linear snapshot",
        ),
        (
            freeze,
            {
                "build_recipe_digest",
                "dirty",
                "freeze_digest",
                "frozen_at",
                "gate_input_digest",
                "milestone",
                "registry_inputs",
                "release_notes_digest",
                "source_sha",
                "source_tree",
                "version_metadata_digest",
                "workflow_inputs",
            },
            "source freeze",
        ),
        (
            impact,
            {
                "author_id",
                "base_sha",
                "changes",
                "head_sha",
                "manifest_digest",
                "milestone",
                "release_tag",
                "source_freeze_digest",
                "target_resolution_digest",
                "unclassified_paths",
            },
            "impact manifest",
        ),
        (
            artifact,
            {
                "artifact_set_digest",
                "artifacts",
                "build_invocation_id",
                "build_recipe_digest",
                "milestone",
                "source_digest",
                "source_freeze_digest",
                "target_resolution_digest",
            },
            "artifact manifest",
        ),
        (
            delta_data,
            {
                "added",
                "candidate_sha",
                "changed",
                "delta_digest",
                "impact_manifest_digest",
                "milestone",
                "predecessor_digest",
                "removed",
            },
            "capability delta",
        ),
        (
            mapping,
            {
                "delta_digest",
                "environment_registry_digest",
                "impact_manifest_digest",
                "map_digest",
                "mappings",
                "milestone",
                "obligation_registry_digest",
                "scenario_registry_digest",
                "unmapped_capabilities",
            },
            "delta test map",
        ),
    )
    for value, expected_fields, label in exact_shapes:
        if set(value) != expected_fields:
            raise ReleaseControlError(f"readiness {label} data shape is not closed")
    predecessor_required = {
        "candidate_milestone",
        "closed_decision_digest",
        "lkg_digest",
        "version",
    }
    predecessor_allowed = predecessor_required | {
        "chain_head",
        "completion_digest",
        "pointer_envelope_digest",
        "pointer_index_receipt_digest",
        "predecessor_milestone",
        "qualification_digest",
        "reconciliation_digest",
    }
    if not predecessor_required <= set(predecessor_data) <= predecessor_allowed:
        raise ReleaseControlError("readiness predecessor data shape is not closed")
    if freeze["dirty"] is not False:
        raise ReleaseControlError("readiness source freeze is dirty")
    for field in (
        "build_recipe_digest",
        "freeze_digest",
        "gate_input_digest",
        "release_notes_digest",
        "version_metadata_digest",
    ):
        _require_digest(freeze[field], f"readiness source freeze {field}")
    for field in ("source_sha", "source_tree"):
        value = freeze[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ReleaseControlError(f"readiness source freeze {field} is not a Git SHA")
    if (
        not isinstance(freeze["registry_inputs"], list)
        or not freeze["registry_inputs"]
        or not isinstance(freeze["workflow_inputs"], list)
        or not freeze["workflow_inputs"]
    ):
        raise ReleaseControlError("readiness source freeze input inventory is incomplete")
    if impact["unclassified_paths"] != []:
        raise ReleaseControlError("readiness impact manifest has unclassified paths")
    if not isinstance(impact["author_id"], str) or not impact["author_id"].strip():
        raise ReleaseControlError("readiness impact manifest author is missing")
    if not isinstance(impact["changes"], list):
        raise ReleaseControlError("readiness impact manifest changes are not an array")
    for field in ("manifest_digest", "source_freeze_digest", "target_resolution_digest"):
        _require_digest(impact[field], f"readiness impact manifest {field}")
    for field in ("base_sha", "head_sha"):
        value = impact[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ReleaseControlError(f"readiness impact manifest {field} is not a Git SHA")
    task_id = linear["task_id"]
    tool = linear["tool"]
    if linear["state"] != "In Progress":
        raise ReleaseControlError("readiness Linear decision is not open and running")
    if not isinstance(task_id, str) or not task_id:
        raise ReleaseControlError("readiness Linear task id is missing")
    if not isinstance(tool, str) or "linear" not in tool.lower():
        raise ReleaseControlError("readiness Linear snapshot tool is not provider-bound")
    artifact_rows = artifact["artifacts"]
    if not isinstance(artifact_rows, list) or len(artifact_rows) != 2:
        raise ReleaseControlError("readiness artifact manifest is not one wheel and one sdist")
    artifact_names: list[str] = []
    artifact_suffixes: set[str] = set()
    artifact_media = {
        ".whl": "application/vnd.pypa.wheel+zip",
        ".tar.gz": "application/gzip",
    }
    for row in artifact_rows:
        if not isinstance(row, dict) or set(row) != {"media_type", "path", "sha256", "size"}:
            raise ReleaseControlError("readiness artifact manifest row is malformed")
        name = row["path"]
        if not isinstance(name, str) or Path(name).name != name:
            raise ReleaseControlError("readiness artifact manifest path is unsafe")
        suffix = ".tar.gz" if name.endswith(".tar.gz") else Path(name).suffix
        if suffix not in artifact_media or row["media_type"] != artifact_media[suffix]:
            raise ReleaseControlError("readiness artifact media type is invalid")
        artifact_suffixes.add(suffix)
        artifact_names.append(name)
        _require_digest(row["sha256"], f"readiness artifact {name}")
        if isinstance(row["size"], bool) or not isinstance(row["size"], int) or row["size"] < 1:
            raise ReleaseControlError("readiness artifact manifest size is invalid")
    if artifact_names != sorted(set(artifact_names)):
        raise ReleaseControlError("readiness artifact manifest is not canonical")
    if artifact_suffixes != set(artifact_media):
        raise ReleaseControlError("readiness artifact manifest lacks a wheel or sdist")
    if artifact["artifact_set_digest"] != sha256_json(artifact_rows):
        raise ReleaseControlError("readiness artifact-set digest mismatch")

    bindings = {
        "gate input record": (gate.get("gate_input_digest"), sha256_json(gate_input)),
        "candidate identity": (
            gate.get("candidate_identity_digest"),
            sha256_json(candidate_identity_record),
        ),
        "gate candidate": (gate.get("candidate_digest"), candidate.get("candidate_digest")),
        "gate input": (gate.get("gate_input_digest"), candidate.get("gate_input_digest")),
        "package version": (gate.get("package_version"), candidate.get("package_version")),
        "release tag": (gate.get("release_tag"), candidate.get("release_tag")),
        "gate predecessor": (gate.get("predecessor_digest"), sha256_json(predecessor)),
        "candidate predecessor": (candidate.get("predecessor_digest"), sha256_json(predecessor)),
        "gate Linear snapshot": (gate.get("linear_snapshot_digest"), sha256_json(linear_snapshot)),
        "gate-input Linear snapshot": (
            gate_input_data.get("linear_snapshot_digest"),
            sha256_json(linear_snapshot),
        ),
        "gate-input milestone": (gate_input_data.get("milestone"), gate.get("milestone")),
        "gate-input run": (gate_input_data.get("run_id"), gate.get("run_id")),
        "gate-input environment registry": (
            gate_input_data.get("environment_registry_digest"),
            gate.get("environment_registry_digest"),
        ),
        "gate-input evidence-store registry": (
            gate_input_data.get("evidence_store_registry_digest"),
            gate.get("evidence_store_registry_digest"),
        ),
        "gate-input obligation registry": (
            gate_input_data.get("obligation_registry_digest"),
            gate.get("obligation_registry_digest"),
        ),
        "gate-input scenario registry": (
            gate_input_data.get("scenario_registry_digest"),
            gate.get("scenario_registry_digest"),
        ),
        "gate-input target registry": (
            gate_input_data.get("target_registry_digest"),
            gate.get("target_registry_digest"),
        ),
        "gate-input task-state policy": (
            gate_input_data.get("task_state_policy_digest"),
            gate.get("task_state_policy_digest"),
        ),
        "gate-input readiness registry": (
            gate_input_data.get("readiness_registry_digest"),
            sha256_json(readiness_registry),
        ),
        "source-freeze gate input": (
            freeze.get("gate_input_digest"),
            sha256_json(gate_input),
        ),
        "source-freeze source": (freeze.get("source_sha"), gate.get("frozen_source_sha")),
        "source-freeze milestone": (freeze.get("milestone"), gate.get("milestone")),
        "candidate artifact manifest": (
            candidate.get("artifact_manifest_digest"),
            sha256_json(artifact_manifest),
        ),
        "candidate artifact set": (
            candidate.get("artifact_set_digest"),
            artifact.get("artifact_set_digest"),
        ),
        "candidate build invocation": (
            candidate.get("build_invocation_id"),
            artifact.get("build_invocation_id"),
        ),
        "candidate source freeze": (
            candidate.get("source_freeze_digest"),
            sha256_json(source_freeze),
        ),
        "artifact source freeze": (
            artifact.get("source_freeze_digest"),
            sha256_json(source_freeze),
        ),
        "artifact source identity": (artifact.get("source_digest"), freeze.get("freeze_digest")),
        "impact source freeze": (impact.get("source_freeze_digest"), sha256_json(source_freeze)),
        "impact source": (impact.get("head_sha"), freeze.get("source_sha")),
        "impact milestone": (impact.get("milestone"), gate.get("milestone")),
        "impact release tag": (impact.get("release_tag"), candidate.get("release_tag")),
        "impact target resolution": (
            impact.get("target_resolution_digest"),
            artifact.get("target_resolution_digest"),
        ),
        "delta predecessor": (delta_data.get("predecessor_digest"), sha256_json(predecessor)),
        "delta source": (delta_data.get("candidate_sha"), gate.get("frozen_source_sha")),
        "delta map": (mapping.get("delta_digest"), delta_data.get("delta_digest")),
        "impact manifest": (
            delta_data.get("impact_manifest_digest"),
            sha256_json(impact_manifest),
        ),
        "mapped impact manifest": (
            mapping.get("impact_manifest_digest"),
            sha256_json(impact_manifest),
        ),
        "environment registry": (
            mapping.get("environment_registry_digest"),
            gate.get("environment_registry_digest"),
        ),
        "obligation registry": (
            mapping.get("obligation_registry_digest"),
            gate.get("obligation_registry_digest"),
        ),
        "scenario registry": (
            mapping.get("scenario_registry_digest"),
            gate.get("scenario_registry_digest"),
        ),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"readiness {label} binding mismatch")
    milestones = {
        gate_input_data.get("milestone"),
        gate.get("milestone"),
        candidate.get("milestone"),
        freeze.get("milestone"),
        impact.get("milestone"),
        artifact.get("milestone"),
        delta_data.get("milestone"),
        mapping.get("milestone"),
        predecessor_data.get("candidate_milestone"),
    }
    if len(milestones) != 1 or next(iter(milestones)) not in MILESTONES:
        raise ReleaseControlError("readiness milestone bindings disagree")
    milestone = next(iter(milestones))
    package_version = candidate.get("package_version")
    if (
        not isinstance(package_version, str)
        or re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", package_version) is None
        or not package_version.startswith(f"{milestone}.")
        or candidate.get("release_tag") != package_version
    ):
        raise ReleaseControlError("readiness package version or release tag is invalid")
    distribution_version = package_version.removeprefix("v")
    expected_sdist = f"metriplane-{distribution_version}.tar.gz"
    expected_wheel_prefix = f"metriplane-{distribution_version}-"
    if (
        expected_sdist not in artifact_names
        or sum(
            name.startswith(expected_wheel_prefix) and name.endswith(".whl")
            for name in artifact_names
        )
        != 1
    ):
        raise ReleaseControlError("readiness artifact filenames do not match the package version")
    if mapping.get("unmapped_capabilities") != []:
        raise ReleaseControlError("readiness has unmapped changed capabilities")
    required_bom_ids = linear.get("required_bom_ids")
    if (
        not isinstance(required_bom_ids, list)
        or not required_bom_ids
        or any(not isinstance(item, str) or not item.strip() for item in required_bom_ids)
        or len(set(required_bom_ids)) != len(required_bom_ids)
    ):
        raise ReleaseControlError("Linear snapshot has no exact required BOM identifiers")
    if required_bom_ids != sorted(required_bom_ids):
        raise ReleaseControlError("Linear snapshot required BOM identifiers are not canonical")
    if task_id not in required_bom_ids:
        raise ReleaseControlError("Linear decision task is absent from the required BOM")
    required_bom_snapshot_digest = _require_digest(
        linear.get("required_bom_snapshot_digest"),
        "Linear required BOM snapshot",
    )
    if required_bom_snapshot_digest != sha256_json(required_bom_ids):
        raise ReleaseControlError("Linear required BOM snapshot digest mismatch")

    blockers = sorted(
        {
            str(blocker.get("code"))
            for blocker in readiness_registry.get("blockers", [])
            if isinstance(blocker, dict) and blocker.get("code")
        }
    )
    evidence = readiness_registry.get("evidence_resolution")
    registry_ready = (
        readiness_registry.get("framework") == "READY"
        and readiness_registry.get("live_release") == "READY"
        and isinstance(evidence, dict)
        and evidence.get("status") == "READY"
    )
    if not registry_ready and not blockers:
        blockers = ["RELEASE_READINESS_REGISTRY_NOT_READY"]
    data = {
        "artifact_manifest_digest": candidate["artifact_manifest_digest"],
        "candidate_digest": candidate["candidate_digest"],
        "delta_digest": delta_data["delta_digest"],
        "delta_test_map_digest": mapping["map_digest"],
        "disposition": "READY" if registry_ready and not blockers else "BLOCKED_NOT_READY",
        "gate_instance_digest": gate["instance_digest"],
        "linear_snapshot_digest": gate["linear_snapshot_digest"],
        "main_health_digest": gate["main_health_digest"],
        "predecessor_digest": gate["predecessor_digest"],
        "readiness_digest": sha256_json(readiness_registry),
        "required_bom_ids": required_bom_ids,
        "required_bom_snapshot_digest": required_bom_snapshot_digest,
        "store_preflight_digest": gate["evidence_store_preflight_digest"],
        "unresolved_blockers": blockers,
    }
    invocation_id = f"release-readiness-{sha256_json(data)[:24]}"
    return make_record(
        "release-readiness",
        data,
        invocation_id=invocation_id,
        sequence=1,
        synthetic=bool(next(iter(synthetic_modes))),
        status="READY" if data["disposition"] == "READY" else "BLOCKED",
    )


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


@dataclass(frozen=True)
class CommandForm:
    """One allowed section-9B invocation shape."""

    required: frozenset[str]
    equals: tuple[tuple[str, frozenset[str]], ...]


@dataclass(frozen=True)
class ToolContract:
    """Declarative CLI surface for one stable release tool."""

    forms: tuple[CommandForm, ...]
    optional: frozenset[str]
    boolean: frozenset[str]
    repeatable: frozenset[str]
    integer: frozenset[str]
    choices: Mapping[str, tuple[str, ...]]
    output_flag: str | None
    fixture_producer: bool
    record_flag: str | None
    delegated_adapter: bool = False

    @property
    def flags(self) -> frozenset[str]:
        required = frozenset().union(*(form.required for form in self.forms))
        return required | self.optional | self.boolean | self.repeatable | frozenset(self.choices)


def _command_form(specification: str) -> CommandForm:
    required: set[str] = set()
    equals: list[tuple[str, frozenset[str]]] = []
    for token in specification.split():
        name, separator, raw_values = token.partition("=")
        required.add(name)
        if separator:
            equals.append((name, frozenset(raw_values.split(","))))
    return CommandForm(frozenset(required), tuple(equals))


def _tool_contract(
    *forms: str,
    optional: str = "",
    boolean: str = "",
    repeatable: str = "",
    integer: str = "",
    choices: Mapping[str, tuple[str, ...]] | None = None,
    output_flag: str | None = "out",
    fixture_producer: bool = True,
    record_flag: str | None = None,
    delegated_adapter: bool = False,
) -> ToolContract:
    return ToolContract(
        forms=tuple(_command_form(form) for form in forms),
        optional=frozenset(optional.split()),
        boolean=frozenset(boolean.split()),
        repeatable=frozenset(repeatable.split()),
        integer=frozenset(integer.split()),
        choices={} if choices is None else choices,
        output_flag=output_flag,
        fixture_producer=fixture_producer,
        record_flag=record_flag,
        delegated_adapter=delegated_adapter,
    )


_MILESTONE_CHOICES: Final[Mapping[str, tuple[str, ...]]] = {"milestone": MILESTONES}
_MANIFEST_PHASES: Final[tuple[str, ...]] = (
    "attempt",
    "index-recovery",
    "pointer-transition",
    "postpublication-conflict",
    "prepublication",
    "prepublication-blocker-attempt",
    "qualified-publication",
    "release-completion",
    "release-completion-task-state",
    "release-finalizing-observation",
    "release-task-finalizing",
    "staging-failure",
    "target-burn",
)
_RETENTION_PHASES: Final[tuple[str, ...]] = (
    "assurance-closure",
    "assurance-deliverable",
    "assurance-packet",
    "attempt",
    "final",
    "index-recovery",
    "pointer-transition",
    "pointer-transition-envelope",
    "postpublication-conflict",
    "prepublication",
    "prepublication-blocker-attempt",
    "release-completion",
    "release-completion-task-state",
    "release-finalizing-observation",
    "release-task-finalizing",
    "staging-failure",
    "target-burn",
)
_STAGING_STAGES: Final[tuple[str, ...]] = (
    "role-resource-resolution",
    "evidence-store-preflight",
    "snapshot",
    "release-metadata",
    "target-observation",
    "burn-lineage",
    "target-resolution",
    "target-burn",
    "gate-input",
    "source-freeze",
    "impact",
    "predecessor",
    "delta",
    "artifact-build",
    "artifact-manifest",
    "candidate-finalization",
    "evaluation-adoption",
    "attempt-index-update",
    "attempt-index-validation",
    "index-recovery",
)
_BLOCKER_STAGES: Final[tuple[str, ...]] = (
    "candidate-identity-validation",
    "gate-main-health",
    "main-health-history",
    "gate-instance",
    "readiness",
    "qualification-plan",
    "attempt",
    "qualification",
    "prepublication-rubric",
    "approval",
    "prepromotion-task-state-observation",
    "prepromotion-task-state-validation",
    "prepromotion-controls",
    "promotion-plan",
    "attempt-index-checkpoint",
    "prepublication-retention",
    "promotion-execution-pre-mutation",
    "promotion-lock-recovery",
    "attempt-index-update",
    "attempt-index-validation",
    "index-recovery",
)
_CONFLICT_STAGES: Final[tuple[str, ...]] = (
    "promotion-execution",
    "promotion-lock-recovery",
    "publication-observations",
    "qualified-publication-manifest",
    "publication-reconciliation",
    "final-retention",
    "final-retention-validation",
    "evidence-chain",
    "evidence-chain-validation",
    "last-known-good",
    "last-known-good-retention",
    "last-known-good-envelope",
    "last-known-good-index",
    "last-known-good-invalidation",
    "release-task-state-observation",
    "release-task-state-validation",
    "release-task-state-evidence-manifest",
    "release-task-state-retention",
    "attempt-index-update",
    "attempt-index-validation",
    "index-recovery",
    "attempt-index-final-checkpoint",
    "release-evidence-history",
    "release-evidence-history-validation",
    "assurance-packet",
    "packet-restore",
    "packet-scan",
    "core-verifier-attestation",
    "core-verifier-attestation-validation",
    "assurance-packet-retention",
    "final-score",
    "final-score-verification",
    "assurance-closure",
    "assurance-closure-retention",
    "assurance-deliverable",
    "assurance-deliverable-restore",
    "assurance-deliverable-scan",
    "deliverable-verifier-attestation",
    "deliverable-verifier-attestation-validation",
    "assurance-deliverable-retention",
    "release-completion",
    "release-completion-retention",
    "release-completion-index",
    "cleanup",
)


TOOL_CONTRACTS: Final[Mapping[str, ToolContract]] = {
    "aggregate_release_attempt.py": _tool_contract("plan coordination attempt-dir out"),
    "build_publication_reconciliation.py": _tool_contract(
        "qualification approval promotion-lock-receipt observations evidence-manifest "
        "retention-receipts out"
    ),
    # This established artifact adapter is direct rather than a tool_main wrapper.
    "build_release_artifacts.py": _tool_contract(
        "target-resolution source-freeze out-dir manifest",
        output_flag="manifest",
        delegated_adapter=True,
    ),
    "build_release_delta_test_map.py": _tool_contract(
        "milestone delta impact-manifest obligations scenarios environments out",
        choices=_MILESTONE_CHOICES,
    ),
    "build_release_evidence_manifest.py": _tool_contract(
        "phase=target-burn,staging-failure,attempt,index-recovery,pointer-transition,"
        "release-task-finalizing,release-finalizing-observation,release-completion-task-state,"
        "release-completion input invocation-root exclude-current-invocation out",
        "phase=prepublication-blocker-attempt candidate-dir blocker invocation-root "
        "exclude-current-invocation out",
        "phase=prepublication candidate-dir round-dir invocation-root "
        "exclude-current-invocation out",
        "phase=qualified-publication staged-manifest retention-receipts "
        "promotion-lock-receipt promotion observations invocation-root "
        "exclude-current-invocation out",
        "phase=postpublication-conflict candidate-dir no-assurance-round input "
        "invocation-root exclude-current-invocation "
        "require-lkg-disposition-and-applicable-invalidation-receipt out",
        optional="additional-invocation-root",
        boolean="exclude-current-invocation no-assurance-round "
        "require-lkg-disposition-and-applicable-invalidation-receipt",
        repeatable="input additional-invocation-root",
        choices={"phase": _MANIFEST_PHASES},
    ),
    "build_release_qualification.py": _tool_contract(
        "plan attempts require-attempt-retention require-attempt-index-receipts out",
        boolean="require-attempt-retention require-attempt-index-receipts",
    ),
    "capture_linear_release_snapshot.py": _tool_contract(
        "project-id registry out",
        optional="provider-auth-from-approved-environment",
        boolean="provider-auth-from-approved-environment",
    ),
    "capture_release_run_statuses.py": _tool_contract(
        "plan attempt-id provider-run-id out always-run", boolean="always-run"
    ),
    "capture_release_target_observations.py": _tool_contract(
        "targets provider-auth-from-approved-environment out",
        boolean="provider-auth-from-approved-environment",
    ),
    "capture_release_task_state_observation.py": _tool_contract(
        "phase=prepromotion project-id task-id require-open-running role-assignments "
        "gate-instance readiness-registry frozen-linear-snapshot out",
        "phase=finalizing project-id task-id require-open-finalizing "
        "protected-transition-event require-transition require-assigned-human-actor "
        "candidate-identity gate-instance readiness-registry frozen-linear-snapshot "
        "reconciliation lkg-index-receipt attempt-index-backend "
        "require-latest-resolved-pointer-state out",
        "phase=finalizing project-id task-id require-open-finalizing "
        "protected-transition-event require-transition require-assigned-human-actor "
        "candidate-identity gate-instance readiness-registry frozen-linear-snapshot "
        "reconciliation chain-receipt lkg-index-receipt core-receipts out",
        "phase=completion project-id task-id require-open-finalizing "
        "protected-transition-event require-transition require-assigned-human-actor "
        "candidate-identity gate-instance readiness-registry frozen-linear-snapshot "
        "completion-input cleanup-plan out",
        boolean="require-open-running require-open-finalizing require-assigned-human-actor "
        "require-latest-resolved-pointer-state",
        choices={
            "phase": ("prepromotion", "finalizing", "completion"),
            "require-transition": ("open_running:open_finalizing",),
        },
    ),
    "check_release_delta.py": _tool_contract(
        "milestone target-resolution predecessor candidate-sha impact-manifest out",
        choices=_MILESTONE_CHOICES,
    ),
    "check_release_readiness.py": _tool_contract(
        "gate-instance candidate-identity predecessor linear-snapshot artifact-manifest "
        "delta delta-test-map out",
        fixture_producer=False,
    ),
    "collect_publication_observations.py": _tool_contract(
        "promotion promotion-lock-receipt artifact-manifest targets out"
    ),
    "execute_release_qualification.py": _tool_contract("plan attempt-id cell artifacts out"),
    "export_release_attempt_index.py": _tool_contract(
        "index-backend genesis through-head stores read-back-all out",
        boolean="read-back-all",
    ),
    "export_release_burn_lineage.py": _tool_contract(
        "milestone attempt-index-backend genesis through-head read-back-all out",
        boolean="read-back-all",
        choices=_MILESTONE_CHOICES,
    ),
    "finalize_release_attempt_cells.py": _tool_contract(
        "plan attempt-id hosted-run-statuses attempt-dir out always-run",
        boolean="always-run",
    ),
    "finalize_release_candidate_identity.py": _tool_contract(
        "invocation-dir gate-input source-freeze predecessor artifact-manifest "
        "no-evaluation-adoption work-dir release-root identity-name",
        boolean="no-evaluation-adoption",
        output_flag="identity-name",
    ),
    "finalize_release_gate_instance.py": _tool_contract(
        "gate-input candidate-identity predecessor linear-snapshot obligations scenarios "
        "environments targets evidence-stores task-state-policy repository-protection "
        "main-health main-health-history store-preflight out"
    ),
    "freeze_release_source.py": _tool_contract("gate-input source-sha out"),
    "plan_release_qualification.py": _tool_contract(
        "gate-instance candidate-identity predecessor readiness delta delta-test-map "
        "scenarios candidate-manifest out"
    ),
    "prepare_release_gate_input.py": _tool_contract(
        "milestone target-resolution target-burn target-burn-index-receipt "
        "expected-predecessor-milestone predecessor-policy linear-snapshot "
        "readiness-registry obligations scenarios environments targets evidence-stores "
        "task-state-policy role-assignments out",
        "milestone target-resolution target-burn no-new-burn "
        "expected-predecessor-milestone predecessor-policy linear-snapshot "
        "readiness-registry obligations scenarios environments targets evidence-stores "
        "task-state-policy role-assignments out",
        boolean="no-new-burn",
        choices=_MILESTONE_CHOICES,
    ),
    "prepare_release_impact_manifest.py": _tool_contract(
        "milestone target-resolution base head source-freeze out",
        choices=_MILESTONE_CHOICES,
    ),
    "promote_release_candidate.py": _tool_contract(
        "dry-run gate-instance candidate-identity qualification approval "
        "prepromotion-controls prepromotion-linear-snapshot attempt-index-checkpoint "
        "artifact-manifest targets out",
        "execute invocation-dir plan prepromotion-controls prepromotion-linear-snapshot "
        "readiness-registry frozen-linear-snapshot attempt-index-checkpoint "
        "attempt-index-backend attempt-index-genesis expected-head operation-id "
        "task-state-observation task-state-policy project-id task-id "
        "provider-auth-from-approved-environment require-live-state "
        "require-live-full-release-bom-closed-except-current-decision "
        "require-live-exact-reciprocal-relations require-live-exact-milestone-assignments "
        "full-project-refetch-before-lock-and-before-first-mutation "
        "require-fresh-through-first-mutation bind-live-refetch-in-lock-receipt "
        "retention-receipts lock-receipt-out out",
        "recover-abandoned-lock invocation-dir attempt-index-backend attempt-index-genesis "
        "promotion-operation-id recovery-operation-id expected-active-head "
        "active-lock-record provider-run-termination signed-infrastructure-owner-recovery "
        "prelock-target-observations-from-lock refetch-all-targets targets out",
        boolean="dry-run execute recover-abandoned-lock "
        "provider-auth-from-approved-environment "
        "require-live-full-release-bom-closed-except-current-decision "
        "require-live-exact-reciprocal-relations require-live-exact-milestone-assignments "
        "full-project-refetch-before-lock-and-before-first-mutation "
        "require-fresh-through-first-mutation bind-live-refetch-in-lock-receipt "
        "prelock-target-observations-from-lock refetch-all-targets",
        choices={"require-live-state": ("open_running",)},
    ),
    "record_postpublication_conflict.py": _tool_contract(
        "stage candidate-identity failed-invocation-dir requires-lkg-invalidation "
        "no-assurance-round out",
        "stage candidate-identity failed-invocation-dir no-lkg-invalidation no-assurance-round out",
        optional="stage-record",
        boolean="no-assurance-round",
        choices={"stage": _CONFLICT_STAGES},
    ),
    "record_release_approval.py": _tool_contract(
        "gate-instance qualification no-prepublication-rubric signed-decision out",
        boolean="no-prepublication-rubric",
    ),
    "record_release_blocker_attempt.py": _tool_contract(
        "sequence stage disposition candidate-identity failed-invocation-dir out",
        optional="stage-record",
        integer="sequence",
        choices={"stage": _BLOCKER_STAGES, "disposition": ("recoverable", "terminal")},
    ),
    "record_release_index_recovery.py": _tool_contract(
        "scope-kind=release_staging,evaluation_staging milestone run-id "
        "original-entry-receipt failure-envelope-manifest failure-envelope-receipts "
        "failure-entry-receipt out",
        "scope-kind=release_candidate,evaluation_candidate release-tag candidate-id "
        "original-entry-receipt failure-envelope-manifest failure-envelope-receipts "
        "failure-entry-receipt out",
        "scope-kind=release_completion release-tag candidate-id assurance-round "
        "original-entry-receipt failure-envelope-manifest failure-envelope-receipts "
        "failure-entry-receipt out",
        "scope-kind=release_staging,evaluation_staging milestone run-id "
        "abandon-original-never-committed original-intent-invocation "
        "live-index-absence-proof original-task-state-observation "
        "failed-task-state-validation-invocation task-state-invalidation-reason "
        "task-state-policy project-id task-id provider-auth-from-approved-environment "
        "signed-infrastructure-owner-decision failure-envelope-manifest "
        "failure-envelope-receipts failure-entry-receipt out",
        "scope-kind=release_candidate,evaluation_candidate release-tag candidate-id "
        "abandon-original-never-committed original-intent-invocation "
        "live-index-absence-proof original-task-state-observation "
        "failed-task-state-validation-invocation task-state-invalidation-reason "
        "task-state-policy project-id task-id provider-auth-from-approved-environment "
        "signed-infrastructure-owner-decision failure-envelope-manifest "
        "failure-envelope-receipts failure-entry-receipt out",
        "scope-kind=release_completion release-tag candidate-id assurance-round "
        "abandon-original-never-committed original-intent-invocation "
        "live-index-absence-proof original-task-state-observation "
        "failed-task-state-validation-invocation task-state-invalidation-reason "
        "task-state-policy project-id task-id provider-auth-from-approved-environment "
        "signed-infrastructure-owner-decision failure-envelope-manifest "
        "failure-envelope-receipts failure-entry-receipt out",
        boolean="abandon-original-never-committed provider-auth-from-approved-environment",
        integer="assurance-round",
        choices={
            "scope-kind": (
                "release_staging",
                "release_candidate",
                "evaluation_staging",
                "evaluation_candidate",
                "release_completion",
            ),
            "task-state-invalidation-reason": ("expired", "state_changed"),
        },
    ),
    "record_release_role_assignments.py": _tool_contract(
        "milestone run-id signed-assignments policy out", choices=_MILESTONE_CHOICES
    ),
    "record_release_staging_attempt.py": _tool_contract(
        "work-dir stage failed-invocation-dir out",
        optional="stage-record",
        choices={"stage": _STAGING_STAGES},
    ),
    "record_release_target_burn.py": _tool_contract(
        "target-observations burn-lineage target-resolution out"
    ),
    "resolve_release_predecessor.py": _tool_contract(
        "milestone=v0.4 expected-predecessor-milestone chain-backend chain-genesis "
        "lkg-backend attempt-index-backend attempt-index-genesis stores v0.4-genesis "
        "genesis-only out",
        "milestone=v0.5,v0.6,v0.7,v0.8,v0.9 expected-predecessor-milestone "
        "chain-backend chain-genesis lkg-backend attempt-index-backend "
        "attempt-index-genesis stores v0.4-genesis require-prior-lkg project-id "
        "require-prior-decision-closed out",
        "milestone=v1.0 expected-predecessor-milestone chain-backend chain-genesis "
        "lkg-backend attempt-index-backend attempt-index-genesis stores v0.4-genesis "
        "require-prior-lkg require-prior-completion project-id "
        "require-prior-decision-closed out",
        boolean="genesis-only require-prior-lkg require-prior-completion "
        "require-prior-decision-closed",
        choices=_MILESTONE_CHOICES,
    ),
    "resolve_release_target.py": _tool_contract(
        "milestone initial-package-version initial-release-tag targets "
        "live-target-observations retained-burn-lineage out",
        choices=_MILESTONE_CHOICES,
    ),
    "retain_release_evidence.py": _tool_contract(
        "phase manifest stores out",
        "phase input stores out",
        "phase input manifest invocation-root through-stage exclude-current-invocation stores out",
        boolean="exclude-current-invocation",
        repeatable="input",
        choices={"phase": _RETENTION_PHASES},
    ),
    "update_last_known_good.py": _tool_contract(
        "reconciliation chain-receipt lkg-backend expected-generation "
        "expected-previous-release expected-chain-head operation-id prior-invocation-root "
        "require-prior-stages targets out",
        "invalidate current-receipt conflict signed-invalidation-decision lkg-backend "
        "expected-generation operation-id out",
        "validate-invalidation receipt lkg-backend read-back",
        boolean="invalidate validate-invalidation read-back",
        integer="expected-generation",
    ),
    "update_release_attempt_index.py": _tool_contract(
        "entry-manifest entry-receipts scope-kind=release_staging,evaluation_staging "
        "milestone run-id stage=target-burn,index-recovery sequence "
        "release-tag candidate-id-not-resolved index-backend expected-head operation-id out",
        "entry-manifest entry-receipts scope-kind=release_candidate,evaluation_candidate "
        "release-tag candidate-id stage=qualification-attempt,index-recovery,pointer-transition "
        "sequence "
        "index-backend expected-head operation-id out",
        "entry-manifest entry-receipts scope-kind=release_candidate release-tag candidate-id "
        "stage=release-task-finalizing sequence "
        "index-backend expected-head operation-id task-state-observation task-state-policy "
        "project-id task-id provider-auth-from-approved-environment require-live-state "
        "require-fresh-through-commit bind-live-refetch-in-receipt out",
        "entry-manifest entry-receipts scope-kind=release_completion release-tag candidate-id "
        "assurance-round completion-manifest-digest stage=release-completion sequence "
        "index-backend expected-head operation-id "
        "task-state-observation task-state-policy project-id task-id "
        "provider-auth-from-approved-environment require-live-state "
        "require-fresh-through-commit bind-live-refetch-in-receipt out",
        boolean="candidate-id-not-resolved provider-auth-from-approved-environment "
        "require-fresh-through-commit bind-live-refetch-in-receipt",
        integer="sequence assurance-round",
        choices={
            "scope-kind": (
                "release_staging",
                "release_candidate",
                "evaluation_staging",
                "evaluation_candidate",
                "release_completion",
            ),
            "stage": (
                "target-burn",
                "qualification-attempt",
                "index-recovery",
                "pointer-transition",
                "release-task-finalizing",
                "release-completion",
            ),
            "require-live-state": ("open_finalizing",),
        },
    ),
    "update_release_evidence_chain.py": _tool_contract(
        "reconciliation evidence-manifest final-receipts chain-backend expected-head "
        "operation-id prior-invocation-root require-prior-stages out"
    ),
    "validate_linear_release_snapshot.py": _tool_contract(
        "record registry",
        "record registry frozen-snapshot milestone current-decision "
        "require-full-release-bom-closed-except-current-decision "
        "require-exact-reciprocal-relations require-exact-milestone-assignments "
        "require-current-decision-state",
        boolean="require-full-release-bom-closed-except-current-decision "
        "require-exact-reciprocal-relations require-exact-milestone-assignments",
        choices={
            "milestone": MILESTONES,
            "require-current-decision-state": ("open_running",),
        },
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_publication_reconciliation.py": _tool_contract(
        "record", output_flag=None, fixture_producer=False, record_flag="record"
    ),
    "validate_release_approval.py": _tool_contract(
        "gate-instance qualification no-prepublication-rubric record",
        boolean="no-prepublication-rubric",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_artifact_manifest.py": _tool_contract(
        "record artifacts read-hash",
        boolean="read-hash",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_attempt.py": _tool_contract(
        "plan attempt-dir record", output_flag=None, fixture_producer=False, record_flag="record"
    ),
    "validate_release_attempt_index.py": _tool_contract(
        "index-backend genesis through-receipt read-back",
        "record index-backend genesis read-back",
        boolean="read-back",
        output_flag=None,
        fixture_producer=False,
        record_flag=None,
    ),
    "validate_release_candidate_identity.py": _tool_contract(
        "record predecessor no-evaluation-adoption candidate-dir",
        boolean="no-evaluation-adoption",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_evidence_chain.py": _tool_contract(
        "chain-backend expected-reconciliation receipt",
        output_flag=None,
        fixture_producer=False,
        record_flag="receipt",
    ),
    "validate_release_evidence_manifest.py": _tool_contract(
        "record",
        optional="require-lkg-disposition-and-applicable-invalidation-receipt",
        boolean="require-lkg-disposition-and-applicable-invalidation-receipt",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_evidence_stores.py": _tool_contract(
        "stores mode=preflight scope require-backends out",
        choices={"mode": ("preflight",)},
    ),
    "validate_release_gate_input.py": _tool_contract(
        "record", output_flag=None, fixture_producer=False, record_flag="record"
    ),
    "validate_release_gate_instance.py": _tool_contract(
        "record candidate-identity predecessor task-state-policy",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_predecessor.py": _tool_contract(
        "record milestone=v0.4 validate-genesis-only",
        "record milestone=v0.5,v0.6,v0.7,v0.8,v0.9 read-back-chain read-back-lkg "
        "read-back-pointer-index require-embedded-prior-decision-closed-observation",
        "record milestone=v1.0 read-back-chain read-back-lkg read-back-pointer-index "
        "read-back-required-completion require-embedded-prior-decision-closed-observation",
        boolean="validate-genesis-only read-back-chain read-back-lkg "
        "read-back-pointer-index read-back-required-completion "
        "require-embedded-prior-decision-closed-observation",
        choices=_MILESTONE_CHOICES,
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_prepromotion_controls.py": _tool_contract(
        "gate-instance release-task-state linear-snapshot main-health repository-protection out"
    ),
    "validate_release_qualification.py": _tool_contract(
        "record", output_flag=None, fixture_producer=False, record_flag="record"
    ),
    "validate_release_qualification_plan.py": _tool_contract(
        "record gate-instance", output_flag=None, fixture_producer=False, record_flag="record"
    ),
    "validate_release_retention.py": _tool_contract(
        "manifest receipts read-back",
        "input receipts read-back",
        "input manifest invocation-root through-stage receipts read-back",
        boolean="read-back",
        repeatable="input",
        output_flag=None,
        fixture_producer=False,
        record_flag=None,
    ),
    "validate_release_role_assignments.py": _tool_contract(
        "record milestone run-id check-conflicts check-freshness",
        boolean="check-conflicts check-freshness",
        choices=_MILESTONE_CHOICES,
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_source_freeze.py": _tool_contract(
        "record verify-tree-clean",
        boolean="verify-tree-clean",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_target_resolution.py": _tool_contract(
        "record targets read-back-lineage",
        boolean="read-back-lineage",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_task_state_observation.py": _tool_contract(
        "phase=prepromotion record task-id gate-instance readiness-registry "
        "frozen-linear-snapshot policy require-open-running require-assigned-authority "
        "check-freshness minimum-validity-seconds",
        "phase=finalizing record task-id gate-instance readiness-registry "
        "frozen-linear-snapshot policy require-open-finalizing "
        "require-no-other-open-required-task check-freshness minimum-validity-seconds",
        "phase=completion record task-id gate-instance readiness-registry "
        "frozen-linear-snapshot policy require-open-finalizing "
        "require-no-other-open-required-task check-freshness minimum-validity-seconds",
        boolean="require-open-running require-assigned-authority require-open-finalizing "
        "require-no-other-open-required-task check-freshness",
        integer="minimum-validity-seconds",
        choices={"phase": ("prepromotion", "finalizing", "completion")},
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
}


def _argument_destination(flag: str) -> str:
    return flag.replace(".", "_").replace("-", "_")


def _build_tool_parser(name: str, contract: ToolContract) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=name,
        description="Metriplane release qualification interface (contract section 9.B).",
        epilog="Required forms: "
        + " | ".join(
            " ".join(f"--{flag}" for flag in sorted(form.required)) for form in contract.forms
        ),
    )
    common_required = set.intersection(*(set(form.required) for form in contract.forms))
    for flag in sorted(contract.flags):
        kwargs: dict[str, Any] = {
            "dest": _argument_destination(flag),
            "required": flag in common_required,
        }
        if flag in contract.boolean:
            kwargs["action"] = "store_true"
        elif flag in contract.repeatable:
            kwargs["action"] = "append"
        elif flag not in contract.choices:
            kwargs["metavar"] = flag.upper().replace("-", "_").replace(".", "_")
        if flag in contract.integer:
            kwargs["type"] = int
        if flag in contract.choices:
            kwargs["choices"] = contract.choices[flag]
        parser.add_argument(f"--{flag}", **kwargs)
    return parser


def _present_flags(args: argparse.Namespace, contract: ToolContract) -> frozenset[str]:
    present = set()
    for flag in contract.flags:
        value = getattr(args, _argument_destination(flag))
        if value not in (None, False, []):
            present.add(flag)
    return frozenset(present)


def _matches_form(
    args: argparse.Namespace,
    present: frozenset[str],
    form: CommandForm,
    contract: ToolContract,
) -> bool:
    if not form.required <= present or not present <= form.required | contract.optional:
        return False
    for flag, allowed_values in form.equals:
        if getattr(args, _argument_destination(flag)) not in allowed_values:
            return False
    return True


def _normalized_arguments(args: argparse.Namespace, contract: ToolContract) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for flag in sorted(contract.flags):
        value = getattr(args, _argument_destination(flag))
        if value not in (None, False, []):
            result[flag] = value
    return result


def _blocked_result(name: str, reason: str) -> dict[str, Any]:
    return {"reason": reason, "status": "BLOCKED_NOT_READY", "tool": name}


def _legacy_internal_validator(tool: str, argv: Sequence[str]) -> int | None:
    """Keep one pre-contract unit seam; executable wrappers never enter it."""

    if Path(tool).parent != Path(".") or "--input" not in argv or "--mode" not in argv:
        return None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mode", choices=("fixture", "live"), required=True)
    args = parser.parse_args(argv)
    result = read_json(args.input)
    if Path(tool).stem != "validate_release_role_assignments":
        raise ReleaseControlError("legacy internal validation is not available for this tool")
    validate_role_assignments(result, live=args.mode == "live")
    return 0


def tool_main(tool: str, argv: Sequence[str] | None = None) -> int:
    """Run one exact section-9B adapter without inventing live authority."""

    arguments = list(argv) if argv is not None else None
    if arguments is not None:
        try:
            legacy_result = _legacy_internal_validator(tool, arguments)
        except ReleaseControlError as exc:
            raise SystemExit(f"release control failed: {exc}") from exc
        if legacy_result is not None:
            return legacy_result
    name = Path(tool).name
    contract = TOOL_CONTRACTS.get(name)
    if contract is None:
        raise ReleaseControlError(f"unknown release tool contract: {name}")
    if contract.delegated_adapter:
        raise ReleaseControlError(f"{name} owns its parser and must not call tool_main")
    parser = _build_tool_parser(name, contract)
    args = parser.parse_args(arguments)
    present = _present_flags(args, contract)
    for flag in present:
        value = getattr(args, _argument_destination(flag))
        values = value if isinstance(value, list) else [value]
        if any(isinstance(item, str) and not item.strip() for item in values):
            parser.error(f"--{flag} cannot be empty")
    if not any(_matches_form(args, present, form, contract) for form in contract.forms):
        parser.error("arguments do not satisfy any documented section-9B command form")

    fixture_mode = os.environ.get("METRIPLANE_RELEASE_FIXTURE_MODE") == "1"
    try:
        if name == "check_release_readiness.py":
            readiness_paths = [
                Path(args.gate_instance),
                Path(args.candidate_identity),
                Path(args.predecessor),
                Path(args.linear_snapshot),
                Path(args.artifact_manifest),
                Path(args.delta),
                Path(args.delta_test_map),
            ]
            candidate_root = readiness_paths[0].parent
            if candidate_root.is_symlink() or not candidate_root.is_dir():
                raise ReleaseControlError("release candidate directory is missing or unsafe")
            if any(path.parent != candidate_root for path in readiness_paths[1:]):
                raise ReleaseControlError("readiness inputs do not share one candidate directory")
            gate_input = _release_input(
                candidate_root / "gate-input.json",
                "release-gate-input",
                live=not fixture_mode,
            )
            gate_instance = _release_input(
                readiness_paths[0], "release-gate-instance", live=not fixture_mode
            )
            candidate = _release_input(
                readiness_paths[1],
                "release-candidate-identity",
                live=not fixture_mode,
            )
            predecessor = _release_input(
                readiness_paths[2], "release-predecessor", live=not fixture_mode
            )
            linear_snapshot = _release_input(
                readiness_paths[3], "linear-release-snapshot", live=not fixture_mode
            )
            source_freeze = _release_input(
                candidate_root / "source-freeze.json",
                "release-source-freeze",
                live=not fixture_mode,
            )
            impact_manifest = _release_input(
                candidate_root / "impact-manifest.json",
                "release-impact-manifest",
                live=not fixture_mode,
            )
            artifact_manifest = _release_input(
                readiness_paths[4],
                "release-artifact-manifest",
                live=not fixture_mode,
            )
            delta = _release_input(
                readiness_paths[5], "release-capability-delta", live=not fixture_mode
            )
            delta_test_map = _release_input(
                readiness_paths[6], "release-delta-test-map", live=not fixture_mode
            )
            readiness_registry = read_json(Path("docs/status/release-readiness.json"))
            result = build_release_readiness_record(
                gate_input=gate_input,
                gate_instance=gate_instance,
                candidate_identity_record=candidate,
                predecessor=predecessor,
                linear_snapshot=linear_snapshot,
                source_freeze=source_freeze,
                impact_manifest=impact_manifest,
                artifact_manifest=artifact_manifest,
                delta=delta,
                delta_test_map=delta_test_map,
                readiness_registry=readiness_registry,
            )
            write_immutable_json(Path(args.out), result)
            print(canonical_json(result).decode("utf-8"))
            return 0 if result["data"]["disposition"] == "READY" else 3
        if name == "validate_release_artifact_manifest.py":
            result = read_json(Path(args.record))
            validate_release_artifact_files(
                result,
                Path(args.artifacts),
                live=not fixture_mode,
            )
        elif name == "validate_release_retention.py":
            result = read_json(Path(args.receipts))
            raw_inputs = args.input if isinstance(args.input, list) else []
            validate_release_retention_receipts(
                result,
                inputs=[Path(value) for value in raw_inputs],
                manifest=Path(args.manifest) if args.manifest is not None else None,
                invocation_root=(
                    Path(args.invocation_root) if args.invocation_root is not None else None
                ),
                through_stage=args.through_stage,
                live=not fixture_mode,
            )
        elif name == "validate_release_qualification.py":
            record_path = Path(args.record)
            result = read_json(record_path)
            validate_release_qualification_record(
                result,
                evidence_root=record_path.parent,
                live=not fixture_mode,
            )
        elif name == "validate_publication_reconciliation.py":
            record_path = Path(args.record)
            result = read_json(record_path)
            validate_publication_reconciliation_record(
                result,
                evidence_root=record_path.parent,
                live=not fixture_mode,
            )
        elif name == "validate_release_gate_instance.py":
            result = read_json(Path(args.record))
            validate_release_gate_instance_record(
                result,
                candidate_identity_record=read_json(Path(args.candidate_identity)),
                predecessor_record=read_json(Path(args.predecessor)),
                task_state_policy=read_json(Path(args.task_state_policy)),
                live=not fixture_mode,
            )
        elif name == "validate_release_qualification_plan.py":
            result = read_json(Path(args.record))
            validate_release_qualification_plan_record(
                result,
                gate_instance=read_json(Path(args.gate_instance)),
                live=not fixture_mode,
            )
        elif name == "validate_release_approval.py":
            result = read_json(Path(args.record))
            validate_release_approval_record(
                result,
                gate_instance=read_json(Path(args.gate_instance)),
                qualification=read_json(Path(args.qualification)),
                no_prepublication_rubric=bool(args.no_prepublication_rubric),
                live=not fixture_mode,
            )
        elif name == "validate_release_candidate_identity.py":
            result = read_json(Path(args.record))
            validate_release_candidate_identity_record(
                result,
                predecessor_record=read_json(Path(args.predecessor)),
                candidate_dir=Path(args.candidate_dir),
                no_evaluation_adoption=bool(args.no_evaluation_adoption),
                live=not fixture_mode,
            )
        elif contract.fixture_producer:
            if not fixture_mode:
                result = _blocked_result(
                    name,
                    "live/provider/backend authority is not implemented; fixture mode is test-only",
                )
                print(canonical_json(result).decode("utf-8"))
                return 3
            normalized = _normalized_arguments(args, contract)
            if contract.output_flag is None:
                raise ReleaseControlError("fixture producer has no declared output flag")
            output_value = normalized.pop(contract.output_flag, None)
            if not isinstance(output_value, str) or not output_value:
                raise ReleaseControlError("fixture producer output is missing")
            seed = {"arguments": normalized, "tool": Path(name).stem}
            sequence_value = normalized.get("sequence", 1)
            sequence = sequence_value if isinstance(sequence_value, int) else 1
            result = make_record(
                _record_type_from_tool(name),
                seed,
                invocation_id=f"fixture-{sha256_json(seed)[:24]}",
                sequence=sequence,
                synthetic=True,
            )
            write_immutable_json(Path(output_value), result)
        elif contract.record_flag is not None:
            record_value = getattr(args, _argument_destination(contract.record_flag))
            if not isinstance(record_value, str):
                raise ReleaseControlError("validator record path is missing")
            result = read_json(Path(record_value))
            expected_type = _record_type_from_tool(name)
            if name == "validate_release_role_assignments.py":
                validate_role_assignments(result, live=not fixture_mode)
            else:
                _passing_record(result, expected_type, live=not fixture_mode)
                result = _blocked_result(
                    name,
                    "subject-specific dependency and read-back validation is not implemented",
                )
                print(canonical_json(result).decode("utf-8"))
                return 3
        else:
            result = _blocked_result(
                name,
                "subject-specific live read-back validation is not implemented",
            )
            print(canonical_json(result).decode("utf-8"))
            return 3
        print(canonical_json(result).decode("utf-8"))
    except (OSError, ReleaseControlError) as exc:
        result = _blocked_result(name, str(exc))
        print(canonical_json(result).decode("utf-8"))
        return 3
    return 0


__all__ = [
    "MILESTONES",
    "STAGES",
    "TOOL_CONTRACTS",
    "ReleaseControlError",
    "acquire_promotion_lock",
    "advance_attempt",
    "append_cas_event",
    "audit_release_repository",
    "build_promotion_plan",
    "build_release_readiness_record",
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
    "validate_publication_reconciliation_record",
    "validate_record",
    "validate_release_approval_record",
    "validate_release_artifact_files",
    "validate_release_candidate_identity_record",
    "validate_release_gate_instance_record",
    "validate_release_qualification_plan_record",
    "validate_release_qualification_record",
    "validate_release_retention_receipts",
    "validate_role_assignments",
    "validate_task_state_observation",
    "write_immutable_json",
]
