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
import hmac
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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
RELEASE_TARGETS_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "docs/status/release-targets.json"
)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_INVOCATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")


class ReleaseControlError(ValueError):
    """A release operation cannot proceed without weakening its contract."""


@dataclass(frozen=True)
class ProviderAttestationVerifier:
    """Verify provider attestations against an independently supplied trust root."""

    keys: Mapping[tuple[str, str], bytes]

    @classmethod
    def from_keyring(cls, path: Path) -> ProviderAttestationVerifier:
        keyring = read_json(path)
        if set(keyring) != {"keys", "schema_version"} or keyring["schema_version"] != (
            "metriplane.provider-attestation-keyring.v1"
        ):
            raise ReleaseControlError("provider attestation keyring shape is not closed")
        rows = keyring["keys"]
        if not isinstance(rows, list) or not rows:
            raise ReleaseControlError("provider attestation keyring has no trusted keys")
        expected_fields = {"actor_id", "key_hex", "provider"}
        parsed: dict[tuple[str, str], bytes] = {}
        identities: list[tuple[str, str]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != expected_fields:
                raise ReleaseControlError("provider attestation key row shape is not closed")
            provider = row["provider"]
            actor_id = row["actor_id"]
            key_hex = row["key_hex"]
            if provider not in {"github", "linear"}:
                raise ReleaseControlError("provider attestation key names an unsupported provider")
            _require_nonempty_string(actor_id, "provider attestation key actor")
            if (
                not isinstance(key_hex, str)
                or re.fullmatch(r"[0-9a-f]{64,}", key_hex) is None
                or len(key_hex) % 2 != 0
            ):
                raise ReleaseControlError("provider attestation key is not canonical hex")
            identity = (provider, actor_id)
            if identity in parsed:
                raise ReleaseControlError("provider attestation key identity is duplicated")
            parsed[identity] = bytes.fromhex(key_hex)
            identities.append(identity)
        if identities != sorted(identities):
            raise ReleaseControlError("provider attestation keys are not canonically ordered")
        return cls(keys=parsed)

    def verify(self, signature: Mapping[str, Any], *, subject_digest: str) -> bool:
        provider = signature.get("provider")
        actor_id = signature.get("actor_id")
        if not isinstance(provider, str) or not isinstance(actor_id, str):
            return False
        key = self.keys.get((provider, actor_id))
        signature_value = signature.get("signature")
        if key is None or not isinstance(signature_value, str):
            return False
        message = canonical_json(
            {
                "actor_id": actor_id,
                "provider": provider,
                "subject_digest": subject_digest,
            }
        )
        expected = hmac.new(key, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature_value, expected)


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


def signature_subject_digest(record: Mapping[str, Any]) -> str:
    """Bind authority to the complete decision envelope, excluding signatures."""

    fields = (
        "data",
        "invocation_id",
        "payload_digest",
        "record_type",
        "schema_version",
        "sequence",
        "status",
        "synthetic",
    )
    if any(field not in record for field in fields):
        raise ReleaseControlError("signature subject record is incomplete")
    return sha256_json({field: record[field] for field in fields})


def _validated_signature(
    signature: Mapping[str, Any],
    *,
    subject_digest: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> str:
    exact = {"actor_id", "algorithm", "provider", "signature", "subject_digest", "synthetic"}
    if not isinstance(signature, Mapping):
        raise ReleaseControlError("signature is not an object")
    if set(signature) != exact:
        raise ReleaseControlError("signature shape is not closed")
    if signature["subject_digest"] != subject_digest:
        raise ReleaseControlError("signature is not bound to the decision envelope")
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
        if attestation_verifier is None:
            raise ReleaseControlError("live provider attestation has no trusted verifier")
        if not attestation_verifier.verify(signature, subject_digest=subject_digest):
            raise ReleaseControlError("live provider attestation authentication failed")
        return actor_id
    if (
        synthetic is not True
        or provider != "test-fixture"
        or algorithm != "test-sha256-v1"
        or signature_value != sha256_json({"actor_id": actor_id, "subject_digest": subject_digest})
    ):
        raise ReleaseControlError("synthetic signature authentication failed")
    return actor_id


def _validated_record_signers(
    record: Mapping[str, Any],
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> set[str]:
    signatures = record["signatures"]
    if live and not signatures:
        raise ReleaseControlError("live release authority has no authenticated signature")
    return {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in signatures
    }


def _parse_utc_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReleaseControlError(f"{label} is not a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReleaseControlError(f"{label} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ReleaseControlError(f"{label} is not a UTC timestamp")
    return parsed


def validate_role_assignments(
    record: Mapping[str, Any],
    *,
    live: bool,
    expected_milestone: str | None = None,
    expected_run_id: str | None = None,
    check_conflicts: bool = False,
    check_freshness: bool = False,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, str]:
    validate_record(record, "release-role-assignments")
    if record["status"] != "PASS":
        raise ReleaseControlError("release role assignments are not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic role assignments cannot authorize a live release")
    data = record["data"]
    required = {
        "author_id",
        "authorized_executor_id",
        "non_author_reviewer_id",
        "publisher_id",
        "task_id",
    }
    optional = {"milestone", "run_id", "valid_from", "valid_until"}
    if not required <= set(data) <= required | optional or data["task_id"] != "MP2-007":
        raise ReleaseControlError("release role assignment shape or task binding is invalid")
    actors: dict[str, str] = {}
    for key in required - {"task_id"}:
        actor = data[key]
        if not isinstance(actor, str) or not actor:
            raise ReleaseControlError(f"role {key} has no actor")
        actors[key] = actor
    if actors["author_id"] == actors["non_author_reviewer_id"]:
        raise ReleaseControlError("the release author cannot be the non-author reviewer")
    if expected_milestone is not None and data.get("milestone") != expected_milestone:
        raise ReleaseControlError("release role assignment milestone binding mismatch")
    if expected_run_id is not None and data.get("run_id") != expected_run_id:
        raise ReleaseControlError("release role assignment run binding mismatch")
    if check_conflicts and actors["non_author_reviewer_id"] in {
        actors["author_id"],
        actors["authorized_executor_id"],
        actors["publisher_id"],
    }:
        raise ReleaseControlError("release role assignment reviewer has an actor conflict")
    if check_freshness:
        valid_from = _parse_utc_timestamp(data.get("valid_from"), "role validity start")
        valid_until = _parse_utc_timestamp(data.get("valid_until"), "role validity end")
        now = datetime.now(UTC)
        if valid_until <= valid_from or not valid_from <= now < valid_until:
            raise ReleaseControlError("release role assignment is outside its validity window")
    signers = {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
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
    attestation_verifier: ProviderAttestationVerifier | None = None,
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
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in record["signatures"]
    }
    if reviewer not in signers:
        raise ReleaseControlError("approval lacks the reviewer's digest-bound signature")


def validate_task_state_observation(
    record: Mapping[str, Any],
    roles: Mapping[str, str],
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
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
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
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
    attestation_verifier: ProviderAttestationVerifier | None = None,
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
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
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


def _release_input(
    path: Path,
    expected_type: str,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    record = read_json(path)
    validate_record(record, expected_type)
    if record["status"] not in {"PASS", "READY"}:
        raise ReleaseControlError(f"{expected_type} is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError(f"synthetic {expected_type} cannot satisfy a live release")
    _validated_record_signers(record, live=live, attestation_verifier=attestation_verifier)
    return record


def _release_data(
    record: Mapping[str, Any], expected_fields: set[str], label: str
) -> dict[str, Any]:
    data = record["data"]
    if not isinstance(data, dict) or set(data) != expected_fields:
        raise ReleaseControlError(f"{label} data shape is not closed")
    return data


def _passing_record(
    record: Mapping[str, Any],
    expected_type: str,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    validate_record(record, expected_type)
    if record["status"] != "PASS":
        raise ReleaseControlError(f"{expected_type} is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError(f"synthetic {expected_type} cannot authorize a live release")
    _validated_record_signers(record, live=live, attestation_verifier=attestation_verifier)
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
        record = read_json(path)
        validate_record(record)
        indexed.setdefault(digest, []).append((path, record))
    return indexed


def _resolved_evidence_record(
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    digest: object,
    expected_type: str,
    label: str,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    required_digest = _require_digest(digest, label)
    matches = indexed.get(required_digest, ())
    if not matches:
        raise ReleaseControlError(f"{label} does not resolve to retained bytes")
    records: list[dict[str, Any]] = []
    for _path, candidate in matches:
        _passing_record(
            candidate,
            expected_type,
            live=live,
            attestation_verifier=attestation_verifier,
        )
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
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for entries in indexed.values():
        for _path, record in entries:
            if record.get("record_type") != "release-candidate-identity":
                continue
            data = _passing_record(
                record,
                "release-candidate-identity",
                live=live,
                attestation_verifier=attestation_verifier,
            )
            if data.get("candidate_digest") == candidate_digest:
                matches.append(record)
    if len(matches) != 1:
        raise ReleaseControlError("qualification candidate identity does not resolve exactly once")
    return matches[0]


def _role_assignment_record_for_gate(
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    milestone = gate.get("milestone")
    run_id = gate.get("run_id")
    if not isinstance(milestone, str) or milestone not in MILESTONES:
        raise ReleaseControlError("approval gate milestone is invalid")
    _require_nonempty_string(run_id, "approval gate run id")
    matches: list[dict[str, Any]] = []
    for entries in indexed.values():
        for _path, record in entries:
            if record.get("record_type") != "release-role-assignments":
                continue
            role_data = record.get("data")
            if (
                isinstance(role_data, dict)
                and role_data.get("milestone") == milestone
                and role_data.get("run_id") == run_id
            ):
                matches.append(record)
    if len(matches) != 1:
        raise ReleaseControlError(
            "approval role assignments do not resolve exactly once for the gate run"
        )
    return matches[0]


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseControlError(f"{label} must be a nonempty string")
    return value


def _require_canonical_string_inventory(
    value: object, label: str, *, nonempty: bool = True
) -> list[str]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or value != sorted(set(value))
    ):
        raise ReleaseControlError(f"{label} is not a canonical string inventory")
    return value


def _validate_candidate_identity_payload(
    candidate: Mapping[str, Any], *, expected_digest: str, expected_milestone: str
) -> None:
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
        raise ReleaseControlError("qualification candidate identity data shape is not closed")
    for field in expected_fields - {
        "build_invocation_id",
        "evaluation_adoption_digest",
        "evaluation_adoption_mode",
        "milestone",
        "package_version",
        "release_tag",
    }:
        _require_digest(candidate[field], f"qualification candidate {field}")
    adoption_digest = candidate["evaluation_adoption_digest"]
    if adoption_digest is not None:
        _require_digest(adoption_digest, "qualification candidate evaluation adoption")
    if (
        candidate["candidate_digest"] != expected_digest
        or candidate["milestone"] != expected_milestone
        or candidate["milestone"] not in MILESTONES
        or candidate["release_tag"] != candidate["package_version"]
        or not isinstance(candidate["package_version"], str)
        or re.fullmatch(r"v(?:0\.[3-9]|1\.0)\.[0-9]+", candidate["package_version"]) is None
        or not candidate["package_version"].startswith(f"{expected_milestone}.")
        or not isinstance(candidate["evaluation_adoption_mode"], str)
        or candidate["evaluation_adoption_mode"] not in {"none", "adopted"}
        or (candidate["evaluation_adoption_mode"] == "none")
        != (candidate["evaluation_adoption_digest"] is None)
    ):
        raise ReleaseControlError("qualification candidate identity bindings are invalid")
    _require_invocation(candidate["build_invocation_id"])


def _validate_artifact_manifest_payload(
    artifact: Mapping[str, Any], *, expected_milestone: str
) -> list[dict[str, Any]]:
    expected_fields = {
        "artifact_set_digest",
        "artifacts",
        "build_invocation_id",
        "build_recipe_digest",
        "milestone",
        "source_digest",
        "source_freeze_digest",
        "target_resolution_digest",
    }
    if set(artifact) != expected_fields:
        raise ReleaseControlError("qualified artifact manifest data shape is not closed")
    if artifact["milestone"] != expected_milestone:
        raise ReleaseControlError("qualified artifact manifest milestone binding mismatch")
    _require_invocation(artifact["build_invocation_id"])
    for field in expected_fields - {"artifacts", "build_invocation_id", "milestone"}:
        _require_digest(artifact[field], f"qualified artifact manifest {field}")
    rows = artifact["artifacts"]
    if not isinstance(rows, list) or len(rows) != 2:
        raise ReleaseControlError("qualified artifact manifest is not one wheel and one sdist")
    expected_media = {
        ".whl": "application/vnd.pypa.wheel+zip",
        ".tar.gz": "application/gzip",
    }
    names: list[str] = []
    suffixes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"media_type", "path", "sha256", "size"}:
            raise ReleaseControlError("qualified artifact manifest row shape is not closed")
        name = row["path"]
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ReleaseControlError("qualified artifact manifest path is unsafe")
        suffix = ".tar.gz" if name.endswith(".tar.gz") else Path(name).suffix
        if suffix not in expected_media or row["media_type"] != expected_media[suffix]:
            raise ReleaseControlError("qualified artifact manifest media type is invalid")
        _require_digest(row["sha256"], f"qualified artifact {name}")
        if isinstance(row["size"], bool) or not isinstance(row["size"], int) or row["size"] < 1:
            raise ReleaseControlError("qualified artifact manifest size is invalid")
        names.append(name)
        suffixes.add(suffix)
    if names != sorted(set(names)) or suffixes != set(expected_media):
        raise ReleaseControlError("qualified artifact manifest inventory is not canonical")
    if artifact["artifact_set_digest"] != sha256_json(rows):
        raise ReleaseControlError("qualified artifact set digest mismatch")
    return rows


def _validate_qualification_plan_payload(
    plan: Mapping[str, Any], *, candidate: Mapping[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
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
    for field in expected_fields - {
        "attempt_count",
        "cells",
        "expected_terminal_result",
        "milestone",
    }:
        _require_digest(plan[field], f"release qualification plan {field}")
    attempt_count = plan["attempt_count"]
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 1:
        raise ReleaseControlError("release qualification plan attempt count is invalid")
    unsigned_plan = dict(plan)
    claimed_plan_digest = unsigned_plan.pop("plan_digest")
    if claimed_plan_digest != sha256_json(unsigned_plan):
        raise ReleaseControlError("release qualification plan digest mismatch")
    if plan["expected_terminal_result"] != "PASS":
        raise ReleaseControlError("release qualification plan terminal result is invalid")
    if candidate is not None and (
        plan["candidate_digest"] != candidate["candidate_digest"]
        or plan["candidate_manifest_digest"] != candidate["artifact_manifest_digest"]
        or plan["predecessor_digest"] != candidate["predecessor_digest"]
        or plan["milestone"] != candidate["milestone"]
    ):
        raise ReleaseControlError("release qualification plan candidate binding mismatch")
    cells = plan["cells"]
    if not isinstance(cells, list) or not cells:
        raise ReleaseControlError("release qualification plan cells are malformed")
    expected_cell_fields = {
        "cell_id",
        "environment_id",
        "obligation_ids",
        "profile_id",
        "scenario_ids",
    }
    cell_index: dict[str, dict[str, Any]] = {}
    for cell in cells:
        if not isinstance(cell, dict) or set(cell) != expected_cell_fields:
            raise ReleaseControlError("release qualification plan cell shape is not closed")
        cell_id = _require_nonempty_string(cell["cell_id"], "qualification plan cell id")
        if cell_id in cell_index:
            raise ReleaseControlError("release qualification plan cell ids are not unique")
        _require_nonempty_string(cell["environment_id"], "qualification plan environment")
        _require_nonempty_string(cell["profile_id"], "qualification plan profile")
        _require_canonical_string_inventory(
            cell["obligation_ids"], "qualification plan obligations"
        )
        _require_canonical_string_inventory(cell["scenario_ids"], "qualification plan scenarios")
        cell_index[cell_id] = cell
    if list(cell_index) != sorted(cell_index):
        raise ReleaseControlError("release qualification plan cells are not canonical")
    return cell_index


def _validate_cell_result_payload(
    record: Mapping[str, Any],
    *,
    plan_cell: Mapping[str, Any],
    attempt_id: str,
    candidate_digest: str,
    plan_digest: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    cell = _passing_record(
        record,
        "release-cell-result",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "artifact_digest",
        "attempt_id",
        "candidate_digest",
        "cell_id",
        "completed_at",
        "counts",
        "environment_id",
        "junit_digest",
        "obligation_ids",
        "plan_digest",
        "profile_id",
        "result",
        "runner_identity",
        "scenario_ids",
        "started_at",
        "stderr_digest",
        "stdout_digest",
        "unexpected_outcomes",
    }
    if set(cell) != expected_fields:
        raise ReleaseControlError("release qualification cell result data shape is not closed")
    if (
        cell["attempt_id"] != attempt_id
        or cell["candidate_digest"] != candidate_digest
        or cell["cell_id"] != plan_cell["cell_id"]
        or cell["environment_id"] != plan_cell["environment_id"]
        or cell["obligation_ids"] != plan_cell["obligation_ids"]
        or cell["plan_digest"] != plan_digest
        or cell["profile_id"] != plan_cell["profile_id"]
        or cell["scenario_ids"] != plan_cell["scenario_ids"]
        or cell["result"] != "PASS"
        or cell["unexpected_outcomes"] != []
    ):
        raise ReleaseControlError("release qualification cell result binding mismatch")
    for field in (
        "artifact_digest",
        "junit_digest",
        "plan_digest",
        "stderr_digest",
        "stdout_digest",
    ):
        _require_digest(cell[field], f"release qualification cell {field}")
    _require_nonempty_string(cell["runner_identity"], "release qualification cell runner")
    _require_canonical_string_inventory(cell["obligation_ids"], "release cell obligations")
    _require_canonical_string_inventory(cell["scenario_ids"], "release cell scenarios")
    counts = cell["counts"]
    count_fields = {
        "deselected",
        "failed",
        "passed",
        "retried",
        "skipped",
        "xfailed",
        "xpassed",
    }
    if (
        not isinstance(counts, dict)
        or set(counts) != count_fields
        or any(type(counts[field]) is not int or counts[field] < 0 for field in count_fields)
        or counts["passed"] < 1
        or any(counts[field] != 0 for field in count_fields - {"passed"})
    ):
        raise ReleaseControlError("release qualification cell counts are not a clean PASS")
    started_at = _parse_utc_timestamp(cell["started_at"], "release cell start")
    completed_at = _parse_utc_timestamp(cell["completed_at"], "release cell completion")
    if completed_at < started_at:
        raise ReleaseControlError("release qualification cell completion precedes its start")
    return cell


def _validate_retention_payload(
    retention: Mapping[str, Any], *, expected_input_digest: str, expected_phase: str, label: str
) -> None:
    expected_fields = {
        "all_content_equal",
        "input_digest",
        "phase",
        "receipt_set_digest",
        "retained_at",
        "stores",
    }
    if set(retention) != expected_fields:
        raise ReleaseControlError(f"{label} data shape is not closed")
    if (
        retention["all_content_equal"] is not True
        or retention["input_digest"] != expected_input_digest
        or retention["phase"] != expected_phase
    ):
        raise ReleaseControlError(f"{label} does not bind the canonical input and phase")
    _require_digest(retention["input_digest"], f"{label} input")
    _require_digest(retention["receipt_set_digest"], f"{label} receipt set")
    _parse_utc_timestamp(retention["retained_at"], f"{label} retention time")
    stores = retention["stores"]
    if not isinstance(stores, list) or len(stores) != 2:
        raise ReleaseControlError(f"{label} requires exactly two store receipts")
    expected_store_fields = {
        "content_digest",
        "hold_receipt_digest",
        "independence_group",
        "namespace",
        "object_key",
        "put_receipt_digest",
        "read_back_digest",
        "store_id",
    }
    store_ids: list[str] = []
    independence_groups: list[str] = []
    for store in stores:
        if not isinstance(store, dict) or set(store) != expected_store_fields:
            raise ReleaseControlError(f"{label} store shape is not closed")
        for field in (
            "content_digest",
            "hold_receipt_digest",
            "put_receipt_digest",
            "read_back_digest",
        ):
            _require_digest(store[field], f"{label} {field}")
        if (
            store["content_digest"] != expected_input_digest
            or store["read_back_digest"] != expected_input_digest
        ):
            raise ReleaseControlError(f"{label} store read-back differs from the canonical input")
        store_ids.append(_require_nonempty_string(store["store_id"], f"{label} store id"))
        independence_groups.append(
            _require_nonempty_string(store["independence_group"], f"{label} independence group")
        )
        _require_nonempty_string(store["namespace"], f"{label} namespace")
        _require_nonempty_string(store["object_key"], f"{label} object key")
    if store_ids != ["payload-store-a", "payload-store-b"]:
        raise ReleaseControlError(f"{label} stores are missing or not canonical")
    if len(set(independence_groups)) != 2:
        raise ReleaseControlError(f"{label} stores are not independently administered")
    if retention["receipt_set_digest"] != sha256_json(stores):
        raise ReleaseControlError(f"{label} receipt-set digest mismatch")


def _validate_observed_store_readbacks(
    stores: Sequence[Mapping[str, Any]],
    *,
    expected_digest: str,
    readbacks: Mapping[str, Path] | None,
    label: str,
) -> None:
    expected_store_ids = {"payload-store-a", "payload-store-b"}
    if not isinstance(readbacks, Mapping) or set(readbacks) != expected_store_ids:
        raise ReleaseControlError(f"{label} requires two explicit observed store readbacks")
    if any(not isinstance(path, Path) for path in readbacks.values()):
        raise ReleaseControlError(f"{label} readback paths must be Path values")
    paths = [readbacks[store_id] for store_id in sorted(expected_store_ids)]
    if paths[0] == paths[1]:
        raise ReleaseControlError(f"{label} readback paths are not independent observations")
    try:
        if paths[0].resolve(strict=True) == paths[1].resolve(strict=True) or os.path.samefile(
            paths[0], paths[1]
        ):
            raise ReleaseControlError(f"{label} readbacks resolve to the same file")
    except (OSError, RuntimeError) as exc:
        raise ReleaseControlError(f"{label} readback path cannot be resolved: {exc}") from exc
    stores_by_id = {store["store_id"]: store for store in stores}
    for store_id, path in readbacks.items():
        observed_digest = _regular_file_digest(path)
        store = stores_by_id[store_id]
        if (
            observed_digest != expected_digest
            or store["content_digest"] != observed_digest
            or store["read_back_digest"] != observed_digest
        ):
            raise ReleaseControlError(f"{label} observed bytes differ for {store_id}")


def _validate_attempt_coordination(
    record: Mapping[str, Any],
    *,
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    attempt: Mapping[str, Any],
    expected_cell_ids: list[str],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> set[str]:
    coordination = _passing_record(
        record,
        "release-attempt-coordination",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "attempt_id",
        "candidate_digest",
        "cells",
        "coordination_result",
        "hard_runner_losses",
        "milestone",
        "provider",
        "qualification_plan_digest",
    }
    if set(coordination) != expected_fields:
        raise ReleaseControlError("release attempt coordination data shape is not closed")
    if (
        coordination["attempt_id"] != attempt["attempt_id"]
        or coordination["candidate_digest"] != attempt["candidate_digest"]
        or coordination["milestone"] != attempt["milestone"]
        or coordination["qualification_plan_digest"] != attempt["qualification_plan_digest"]
        or coordination["coordination_result"] != "PASS"
        or coordination["hard_runner_losses"] != []
        or coordination["provider"] != "github"
    ):
        raise ReleaseControlError("release attempt coordination binding mismatch")
    cells = coordination["cells"]
    if not isinstance(cells, list) or len(cells) != len(expected_cell_ids):
        raise ReleaseControlError("release attempt coordination cell matrix is incomplete")
    observed_cell_ids: list[str] = []
    job_ids: set[str] = set()
    provider_run_ids: set[str] = set()
    termination_digests: set[str] = set()
    expected_cell_fields = {
        "cell_id",
        "job_id",
        "provider_run_id",
        "provider_termination_digest",
        "status",
    }
    for cell in cells:
        if not isinstance(cell, dict) or set(cell) != expected_cell_fields:
            raise ReleaseControlError("release attempt coordination cell shape is not closed")
        cell_id = _require_nonempty_string(cell["cell_id"], "coordination cell id")
        job_id = _require_nonempty_string(cell["job_id"], "coordination job id")
        provider_run_id = _require_nonempty_string(
            cell["provider_run_id"], "coordination provider run id"
        )
        if job_id in job_ids or provider_run_id in provider_run_ids or cell["status"] != "terminal":
            raise ReleaseControlError("release attempt coordination is not uniquely terminal")
        observed_cell_ids.append(cell_id)
        job_ids.add(job_id)
        provider_run_ids.add(provider_run_id)
        termination_digest = _require_digest(
            cell["provider_termination_digest"], "release attempt provider termination"
        )
        if termination_digest in termination_digests:
            raise ReleaseControlError("release attempt provider terminations are not unique")
        termination_digests.add(termination_digest)
        termination = _resolved_evidence_record(
            indexed,
            termination_digest,
            "provider-run-termination",
            "release attempt provider termination",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        termination_data = _passing_record(
            termination,
            "provider-run-termination",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        if (
            set(termination_data) != {"job_id", "provider_run_id", "state", "tool"}
            or termination_data["state"] != "success"
            or termination_data["job_id"] != job_id
            or termination_data["provider_run_id"] != provider_run_id
            or not isinstance(termination_data["tool"], str)
            or re.fullmatch(
                r"[A-Za-z0-9._-]*(?:[Pp]rovider|[Gg]it[Hh]ub)[A-Za-z0-9._-]*",
                termination_data["tool"],
            )
            is None
        ):
            raise ReleaseControlError("release attempt provider termination is not successful")
    if observed_cell_ids != expected_cell_ids:
        raise ReleaseControlError("release attempt coordination cell inventory mismatch")
    return termination_digests


def _validate_attempt_evidence_manifest(
    record: Mapping[str, Any],
    *,
    attempt: Mapping[str, Any],
    required_digests: set[str],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    manifest = _passing_record(
        record,
        "release-evidence-manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "candidate_digest",
        "entries",
        "invocation_journal_digests",
        "manifest_digest",
        "phase",
        "scope_id",
        "scope_kind",
    }
    if set(manifest) != expected_fields:
        raise ReleaseControlError("release attempt evidence manifest data shape is not closed")
    if (
        manifest["candidate_digest"] != attempt["candidate_digest"]
        or manifest["phase"] != "attempt"
        or manifest["scope_id"] != attempt["attempt_id"]
        or manifest["scope_kind"] != "release-attempt"
    ):
        raise ReleaseControlError("release attempt evidence manifest binding mismatch")
    _require_digest(manifest["manifest_digest"], "release attempt evidence manifest")
    journals = manifest["invocation_journal_digests"]
    if (
        not isinstance(journals, list)
        or not journals
        or any(not isinstance(digest, str) for digest in journals)
        or journals != sorted(set(journals))
    ):
        raise ReleaseControlError("release attempt invocation journals are not canonical")
    for digest in journals:
        _require_digest(digest, "release attempt invocation journal")
    entries = manifest["entries"]
    if not isinstance(entries, list) or not entries:
        raise ReleaseControlError("release attempt evidence manifest has no entries")
    expected_entry_fields = {"media_type", "path", "role", "sha256", "size"}
    paths: list[str] = []
    observed_digests: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != expected_entry_fields:
            raise ReleaseControlError("release attempt evidence manifest entry is malformed")
        path = _require_nonempty_string(entry["path"], "release attempt evidence path")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReleaseControlError("release attempt evidence path is unsafe")
        _require_nonempty_string(entry["media_type"], "release attempt evidence media type")
        _require_nonempty_string(entry["role"], "release attempt evidence role")
        size = entry["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ReleaseControlError("release attempt evidence size is invalid")
        paths.append(path)
        observed_digests.append(_require_digest(entry["sha256"], "release attempt evidence entry"))
    if paths != sorted(set(paths)):
        raise ReleaseControlError("release attempt evidence paths are not canonical")
    if any(observed_digests.count(digest) != 1 for digest in required_digests):
        raise ReleaseControlError(
            "release attempt evidence manifest does not close required inputs"
        )


def _validate_attempt_index_payload(
    record: Mapping[str, Any],
    *,
    attempt: Mapping[str, Any],
    expected_manifest_digest: str,
    retention_digest: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    index = _passing_record(
        record,
        "release-attempt-index",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "backend_id",
        "committed_head",
        "disposition",
        "entry_manifest_digest",
        "entry_receipts_digest",
        "generation",
        "milestone",
        "operation_id",
        "previous_head",
        "read_back_digest",
        "scope_id",
        "scope_kind",
        "sequence",
        "stage",
        "token",
    }
    if set(index) != expected_fields:
        raise ReleaseControlError("release attempt index data shape is not closed")
    for field in (
        "committed_head",
        "entry_manifest_digest",
        "entry_receipts_digest",
        "read_back_digest",
    ):
        _require_digest(index[field], f"release attempt index {field}")
    if index["previous_head"] is not None:
        _require_digest(index["previous_head"], "release attempt index previous head")
    for field in ("generation", "sequence"):
        if isinstance(index[field], bool) or not isinstance(index[field], int) or index[field] < 1:
            raise ReleaseControlError(f"release attempt index {field} is invalid")
    if (
        index["backend_id"] != "attempt-index"
        or index["committed_head"] != index["read_back_digest"]
        or not isinstance(index["disposition"], str)
        or index["disposition"] not in {"committed", "idempotent"}
        or index["entry_manifest_digest"] != expected_manifest_digest
        or index["entry_receipts_digest"] != retention_digest
        or index["milestone"] != attempt["milestone"]
        or index["operation_id"] != attempt["attempt_id"]
        or index["scope_id"] != attempt["candidate_digest"]
        or index["scope_kind"] != "release_candidate"
        or index["sequence"] != record["sequence"]
        or index["stage"] != "qualification-attempt"
    ):
        raise ReleaseControlError("release attempt index semantic binding mismatch")
    _require_nonempty_string(index["token"], "release attempt index token")


def _validate_clean_warning_summary(
    record: Mapping[str, Any],
    *,
    candidate_digest: str,
    expected_subject_digest: str,
    label: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    warning = _passing_record(
        record,
        "release-warning-summary",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "candidate_digest",
        "deselection_count",
        "policy_digest",
        "result",
        "retry_count",
        "skip_count",
        "subject_digest",
        "summary_digest",
        "unexpected_warning_count",
        "warnings",
        "xfail_count",
        "xpass_count",
    }
    if set(warning) != expected_fields:
        raise ReleaseControlError(f"{label} data shape is not closed")
    for field in ("policy_digest", "subject_digest", "summary_digest"):
        _require_digest(warning[field], f"{label} {field}")
    count_fields = (
        "deselection_count",
        "retry_count",
        "skip_count",
        "unexpected_warning_count",
        "xfail_count",
        "xpass_count",
    )
    if (
        warning["candidate_digest"] != candidate_digest
        or warning["subject_digest"] != expected_subject_digest
        or warning["result"] != "PASS"
        or any(type(warning[field]) is not int or warning[field] != 0 for field in count_fields)
    ):
        raise ReleaseControlError(f"{label} is not clean")
    warnings = warning["warnings"]
    if warnings != []:
        raise ReleaseControlError(f"{label} warning inventory is not empty")


def validate_release_qualification_record(
    record: Mapping[str, Any],
    *,
    evidence_root: Path,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
    attempt_retention_readbacks: Mapping[str, Mapping[str, Path]] | None = None,
) -> None:
    data = _passing_record(
        record,
        "release-qualification",
        live=live,
        attestation_verifier=attestation_verifier,
    )
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
        cell_id = row["cell_id"]
        if not isinstance(cell_id, str) or not cell_id:
            raise ReleaseControlError("release qualification terminal cell id is invalid")
        terminal_ids.append(cell_id)
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
        attestation_verifier=attestation_verifier,
    )
    plan = _passing_record(
        plan_record,
        "release-qualification-plan",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    milestone = plan.get("milestone")
    if not isinstance(milestone, str) or milestone not in MILESTONES:
        raise ReleaseControlError("release qualification plan milestone is invalid")
    candidate_record = _candidate_record_for_digest(
        indexed,
        data["candidate_digest"],
        live=live,
        attestation_verifier=attestation_verifier,
    )
    candidate = _passing_record(
        candidate_record,
        "release-candidate-identity",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    _validate_candidate_identity_payload(
        candidate,
        expected_digest=data["candidate_digest"],
        expected_milestone=milestone,
    )
    plan_cells = _validate_qualification_plan_payload(plan, candidate=candidate)
    if list(plan_cells) != expected_cells:
        raise ReleaseControlError("release qualification plan cell inventory mismatch")

    attempts = [
        _resolved_evidence_record(
            indexed,
            digest,
            "release-attempt",
            "release qualification attempt",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for digest in data["attempt_digests"]
    ]
    if plan["attempt_count"] != len(attempts):
        raise ReleaseControlError("release qualification attempt count mismatch")
    observed_attempt_ids: list[str] = []
    observed_index_receipts: list[str] = []
    observed_retention_receipts: list[str] = []
    latest_cells: list[dict[str, Any]] | None = None
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
            or attempt["milestone"] != milestone
        ):
            raise ReleaseControlError("release qualification attempt binding mismatch")
        attempt_id = _require_nonempty_string(attempt["attempt_id"], "release attempt id")
        observed_attempt_ids.append(attempt_id)
        attempt_cells = attempt["cells"]
        if not isinstance(attempt_cells, list) or len(attempt_cells) != len(expected_cells):
            raise ReleaseControlError("release qualification attempt cell matrix is incomplete")
        observed_cell_ids: list[str] = []
        observed_cell_digests: set[str] = set()
        validated_attempt_cells: list[dict[str, Any]] = []
        for cell_row in attempt_cells:
            if not isinstance(cell_row, dict) or set(cell_row) != {
                "cell_id",
                "result",
                "result_digest",
            }:
                raise ReleaseControlError("release qualification attempt cell is malformed")
            cell_id = _require_nonempty_string(
                cell_row["cell_id"], "release qualification attempt cell id"
            )
            result_digest = _require_digest(
                cell_row["result_digest"], "release qualification attempt cell"
            )
            if cell_row["result"] != "PASS" or result_digest in observed_cell_digests:
                raise ReleaseControlError("release qualification attempt cell is not a unique PASS")
            observed_cell_ids.append(cell_id)
            observed_cell_digests.add(result_digest)
            plan_cell = plan_cells.get(cell_id)
            if plan_cell is None:
                raise ReleaseControlError("release qualification attempt names an unknown cell")
            cell_record = _resolved_evidence_record(
                indexed,
                result_digest,
                "release-cell-result",
                "release qualification cell result",
                live=live,
                attestation_verifier=attestation_verifier,
            )
            _validate_cell_result_payload(
                cell_record,
                plan_cell=plan_cell,
                attempt_id=attempt_id,
                candidate_digest=data["candidate_digest"],
                plan_digest=data["plan_digest"],
                live=live,
                attestation_verifier=attestation_verifier,
            )
            validated_attempt_cells.append(cell_row)
        if observed_cell_ids != expected_cells:
            raise ReleaseControlError("release qualification attempt cell inventory mismatch")

        coordination_digest = _require_digest(
            attempt["coordination_digest"], "release attempt coordination"
        )
        coordination_record = _resolved_evidence_record(
            indexed,
            coordination_digest,
            "release-attempt-coordination",
            "release attempt coordination",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        termination_digests = _validate_attempt_coordination(
            coordination_record,
            indexed=indexed,
            attempt=attempt,
            expected_cell_ids=expected_cells,
            live=live,
            attestation_verifier=attestation_verifier,
        )
        retention_digest = _require_digest(
            attempt["retention_receipts_digest"], "release attempt retention receipt"
        )
        retention_record = _resolved_evidence_record(
            indexed,
            retention_digest,
            "release-retention-receipts",
            "release qualification retention receipt",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        retention = _passing_record(
            retention_record,
            "release-retention-receipts",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        index_digest = _require_digest(
            attempt["index_receipt_digest"], "release attempt index receipt"
        )
        index_record = _resolved_evidence_record(
            indexed,
            index_digest,
            "release-attempt-index",
            "release qualification index receipt",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        index = _passing_record(
            index_record,
            "release-attempt-index",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        manifest_digest = _require_digest(
            index.get("entry_manifest_digest"), "release attempt evidence manifest"
        )
        manifest_record = _resolved_evidence_record(
            indexed,
            manifest_digest,
            "release-evidence-manifest",
            "release attempt evidence manifest",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        _validate_attempt_evidence_manifest(
            manifest_record,
            attempt=attempt,
            required_digests={
                data["plan_digest"],
                coordination_digest,
                *observed_cell_digests,
                *termination_digests,
            },
            live=live,
            attestation_verifier=attestation_verifier,
        )
        _validate_retention_payload(
            retention,
            expected_input_digest=manifest_digest,
            expected_phase="attempt",
            label="release qualification retention receipt",
        )
        if live or attempt_retention_readbacks is not None:
            readbacks = (
                attempt_retention_readbacks.get(retention_digest)
                if attempt_retention_readbacks is not None
                else None
            )
            _validate_observed_store_readbacks(
                retention["stores"],
                expected_digest=manifest_digest,
                readbacks=readbacks,
                label="release qualification retention receipt",
            )
        _validate_attempt_index_payload(
            index_record,
            attempt=attempt,
            expected_manifest_digest=manifest_digest,
            retention_digest=retention_digest,
            live=live,
            attestation_verifier=attestation_verifier,
        )
        attempt_warning = _resolved_evidence_record(
            indexed,
            attempt["warning_summary_digest"],
            "release-warning-summary",
            "release attempt warning summary",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        attempt_subject = dict(attempt)
        del attempt_subject["warning_summary_digest"]
        _validate_clean_warning_summary(
            attempt_warning,
            candidate_digest=data["candidate_digest"],
            expected_subject_digest=sha256_json(attempt_subject),
            label="release attempt warning summary",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        observed_index_receipts.append(index_digest)
        observed_retention_receipts.append(retention_digest)
        latest_cells = validated_attempt_cells

    if observed_attempt_ids != sorted(set(observed_attempt_ids)):
        raise ReleaseControlError("release qualification attempt ids are not canonical")
    if observed_index_receipts != data["attempt_index_receipt_digests"]:
        raise ReleaseControlError("release qualification index receipt bindings mismatch")
    if observed_retention_receipts != data["attempt_retention_receipt_digests"]:
        raise ReleaseControlError("release qualification retention receipt bindings mismatch")
    if attempt_retention_readbacks is not None and set(attempt_retention_readbacks) != set(
        observed_retention_receipts
    ):
        raise ReleaseControlError("release qualification readback receipt inventory mismatch")
    if latest_cells is None or latest_cells != terminals:
        raise ReleaseControlError("release qualification terminals are not the final attempt")
    warning_record = _resolved_evidence_record(
        indexed,
        data["warning_summary_digest"],
        "release-warning-summary",
        "release qualification warning summary",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualification_subject = dict(data)
    del qualification_subject["warning_summary_digest"]
    _validate_clean_warning_summary(
        warning_record,
        candidate_digest=data["candidate_digest"],
        expected_subject_digest=sha256_json(qualification_subject),
        label="release qualification warning summary",
        live=live,
        attestation_verifier=attestation_verifier,
    )


def _required_release_targets(milestone: str) -> list[str]:
    registry = read_json(RELEASE_TARGETS_PATH)
    if set(registry) != {"milestones", "owner", "schema_version"}:
        raise ReleaseControlError("release target registry shape is not closed")
    if (
        registry["owner"] != "MP2-007"
        or registry["schema_version"] != "metriplane.release-targets.v1"
    ):
        raise ReleaseControlError("release target registry identity is invalid")
    rows = registry["milestones"]
    if not isinstance(rows, list) or len(rows) != len(MILESTONES):
        raise ReleaseControlError("release target milestone inventory is incomplete")
    observed_milestones: list[str] = []
    selected: list[str] | None = None
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "predecessor",
            "required_targets",
            "version_line",
        }:
            raise ReleaseControlError("release target milestone row is malformed")
        milestone_id = row["id"]
        targets = row["required_targets"]
        if not isinstance(milestone_id, str):
            raise ReleaseControlError("release target milestone id is invalid")
        if (
            not isinstance(targets, list)
            or not targets
            or any(not isinstance(target, str) or not target for target in targets)
            or targets != sorted(set(targets))
        ):
            raise ReleaseControlError("release target requirement inventory is not canonical")
        observed_milestones.append(milestone_id)
        if milestone_id == milestone:
            selected = targets
    if tuple(observed_milestones) != MILESTONES or selected is None:
        raise ReleaseControlError("release target milestone bindings are invalid")
    return selected


def validate_publication_reconciliation_record(
    record: Mapping[str, Any],
    *,
    evidence_root: Path,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
    retention_readbacks: Mapping[str, Path] | None = None,
    attempt_retention_readbacks: Mapping[str, Mapping[str, Path]] | None = None,
) -> None:
    data = _passing_record(
        record,
        "release-publication-reconciliation",
        live=live,
        attestation_verifier=attestation_verifier,
    )
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
    if target_ids != _required_release_targets(data["milestone"]):
        raise ReleaseControlError(
            "publication reconciliation does not cover every required release target"
        )

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
            attestation_verifier=attestation_verifier,
        )
        for field, record_type in dependency_types.items()
    }
    validate_release_qualification_record(
        dependencies["qualification_digest"],
        evidence_root=evidence_root,
        live=live,
        attestation_verifier=attestation_verifier,
        attempt_retention_readbacks=attempt_retention_readbacks,
    )
    approval = _passing_record(
        dependencies["approval_digest"],
        "release-approval",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    approval_decision = _resolved_evidence_record(
        indexed,
        approval.get("approval_decision_digest"),
        "release-approval-decision",
        "publication reconciliation approval decision",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    dependencies["approval_decision_digest"] = approval_decision
    gate_instance = _resolved_evidence_record(
        indexed,
        approval.get("gate_instance_digest"),
        "release-gate-instance",
        "publication reconciliation approval gate instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    gate = _passing_record(
        gate_instance,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    role_assignments = _role_assignment_record_for_gate(indexed, gate)
    validate_release_approval_record(
        dependencies["approval_digest"],
        approval_decision=approval_decision,
        gate_instance=gate_instance,
        qualification=dependencies["qualification_digest"],
        role_assignments=role_assignments,
        no_prepublication_rubric=True,
        live=live,
        attestation_verifier=attestation_verifier,
    )
    candidate_record = _candidate_record_for_digest(
        indexed,
        data["candidate_digest"],
        live=live,
        attestation_verifier=attestation_verifier,
    )
    candidate = _passing_record(
        candidate_record,
        "release-candidate-identity",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    _validate_candidate_identity_payload(
        candidate,
        expected_digest=data["candidate_digest"],
        expected_milestone=data["milestone"],
    )
    artifact_manifest_record = _resolved_evidence_record(
        indexed,
        candidate["artifact_manifest_digest"],
        "release-artifact-manifest",
        "publication reconciliation qualified artifact manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    artifact_manifest = _passing_record(
        artifact_manifest_record,
        "release-artifact-manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualified_artifacts = _validate_artifact_manifest_payload(
        artifact_manifest, expected_milestone=data["milestone"]
    )
    if artifacts != qualified_artifacts:
        raise ReleaseControlError(
            "publication reconciliation artifacts differ from the qualified candidate"
        )
    if candidate["artifact_set_digest"] != artifact_manifest["artifact_set_digest"]:
        raise ReleaseControlError("publication reconciliation candidate artifact-set mismatch")
    if (
        candidate["build_invocation_id"] != artifact_manifest["build_invocation_id"]
        or candidate["source_freeze_digest"] != artifact_manifest["source_freeze_digest"]
    ):
        raise ReleaseControlError("publication reconciliation candidate build binding mismatch")
    evidence_manifest = _passing_record(
        dependencies["evidence_manifest_digest"],
        "release-evidence-manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    lock = _passing_record(
        dependencies["lock_receipt_digest"],
        "release-promotion-lock",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    observations = _passing_record(
        dependencies["observations_digest"],
        "release-publication-observations",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    promotion = _passing_record(
        dependencies["promotion_digest"],
        "release-promotion",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualification = _passing_record(
        dependencies["qualification_digest"],
        "release-qualification",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    retention = _passing_record(
        dependencies["staged_retention_receipts_digest"],
        "release-retention-receipts",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    manifest_fields = {
        "candidate_digest",
        "entries",
        "invocation_journal_digests",
        "manifest_digest",
        "phase",
        "scope_id",
        "scope_kind",
    }
    if set(evidence_manifest) != manifest_fields:
        raise ReleaseControlError(
            "publication reconciliation evidence manifest shape is not closed"
        )
    entries = evidence_manifest["entries"]
    journals = evidence_manifest["invocation_journal_digests"]
    if (
        not isinstance(entries, list)
        or not entries
        or not isinstance(journals, list)
        or not journals
        or any(not isinstance(digest, str) for digest in journals)
        or journals != sorted(set(journals))
    ):
        raise ReleaseControlError("publication reconciliation evidence manifest is incomplete")
    entry_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "media_type",
            "path",
            "role",
            "sha256",
            "size",
        }:
            raise ReleaseControlError(
                "publication reconciliation evidence manifest entry is malformed"
            )
        if (
            not isinstance(entry["media_type"], str)
            or not entry["media_type"]
            or not isinstance(entry["path"], str)
            or not entry["path"]
            or Path(entry["path"]).is_absolute()
            or ".." in Path(entry["path"]).parts
            or not isinstance(entry["role"], str)
            or not entry["role"]
            or isinstance(entry["size"], bool)
            or not isinstance(entry["size"], int)
            or entry["size"] < 0
        ):
            raise ReleaseControlError(
                "publication reconciliation evidence manifest entry is invalid"
            )
        _require_digest(entry["sha256"], "publication evidence manifest entry")
        entry_paths.append(entry["path"])
    if entry_paths != sorted(set(entry_paths)):
        raise ReleaseControlError("publication evidence manifest paths are not canonical")
    manifest_digest = _require_digest(
        evidence_manifest["manifest_digest"], "publication evidence manifest"
    )
    if manifest_digest != sha256_json({"entries": entries, "invocation_journal_digests": journals}):
        raise ReleaseControlError("publication evidence manifest digest mismatch")
    for digest in journals:
        _require_digest(digest, "publication evidence invocation journal")
    if (
        evidence_manifest["phase"] != "qualified-publication"
        or evidence_manifest["scope_kind"] != "release-candidate"
        or evidence_manifest["scope_id"] != candidate["package_version"]
    ):
        raise ReleaseControlError("publication evidence manifest candidate scope mismatch")
    lock_fields = {
        "acquired_index_head",
        "approval_digest",
        "attempt_index_checkpoint_digest",
        "backend_id",
        "candidate_digest",
        "controls_digest",
        "dead_owner_proof_digest",
        "epoch",
        "expected_index_head",
        "lease_expires_at",
        "lease_started_at",
        "lock_token",
        "mutation_started",
        "operation_id",
        "owner",
        "promotion_plan_digest",
        "recovery_authorization_digest",
        "state",
        "target_state_digest",
    }
    if set(lock) != lock_fields or lock["backend_id"] != "attempt-index":
        raise ReleaseControlError("publication reconciliation promotion lock shape is not closed")
    if isinstance(lock["epoch"], bool) or not isinstance(lock["epoch"], int) or lock["epoch"] < 1:
        raise ReleaseControlError("publication reconciliation promotion lock epoch is invalid")
    for field in (
        "acquired_index_head",
        "approval_digest",
        "attempt_index_checkpoint_digest",
        "controls_digest",
        "expected_index_head",
        "promotion_plan_digest",
        "target_state_digest",
    ):
        _require_digest(lock[field], f"publication reconciliation promotion lock {field}")
    lock_started_at = _parse_utc_timestamp(lock["lease_started_at"], "promotion lock lease start")
    lock_expires_at = _parse_utc_timestamp(lock["lease_expires_at"], "promotion lock lease expiry")
    if lock_expires_at <= lock_started_at:
        raise ReleaseControlError("publication reconciliation promotion lock lease is invalid")
    for field in ("lock_token", "operation_id", "owner"):
        _require_nonempty_string(lock[field], f"publication reconciliation promotion lock {field}")
    for field in ("dead_owner_proof_digest", "recovery_authorization_digest"):
        if lock[field] is not None:
            _require_digest(lock[field], f"publication reconciliation promotion lock {field}")
    promotion_fields = {
        "actions",
        "candidate_digest",
        "completed_at",
        "lock_receipt_digest",
        "mode",
        "mutation_started",
        "operation_id",
        "promotion_plan_digest",
        "publisher_id",
        "record_kind",
        "result",
        "started_at",
        "target_state_digest",
    }
    if set(promotion) != promotion_fields:
        raise ReleaseControlError("publication reconciliation promotion shape is not closed")
    if (
        promotion["mode"] != "execute"
        or promotion["record_kind"] != "promotion_execution"
        or not isinstance(promotion["actions"], list)
        or not promotion["actions"]
    ):
        raise ReleaseControlError("publication reconciliation promotion is malformed")
    promotion_started_at = _parse_utc_timestamp(promotion["started_at"], "promotion start")
    promotion_completed_at = _parse_utc_timestamp(promotion["completed_at"], "promotion completion")
    if (
        promotion_started_at < lock_started_at
        or promotion_completed_at < promotion_started_at
        or promotion_completed_at > lock_expires_at
    ):
        raise ReleaseControlError("publication reconciliation promotion timing is invalid")
    promotion_target_ids: list[str] = []
    for action in promotion["actions"]:
        if not isinstance(action, dict) or set(action) != {
            "action",
            "observed_digest",
            "result",
            "target_id",
        }:
            raise ReleaseControlError("publication reconciliation promotion action is malformed")
        if (
            not isinstance(action["action"], str)
            or not action["action"]
            or not isinstance(action["target_id"], str)
            or not action["target_id"]
            or action["result"] != "PASS"
        ):
            raise ReleaseControlError("publication reconciliation promotion action did not pass")
        _require_digest(action["observed_digest"], "publication promotion action")
        promotion_target_ids.append(action["target_id"])
    if promotion_target_ids != sorted(set(promotion_target_ids)):
        raise ReleaseControlError("publication reconciliation promotion actions are not canonical")
    observation_fields = {
        "all_targets_observed",
        "artifact_manifest_digest",
        "candidate_digest",
        "lock_receipt_digest",
        "observation_digest",
        "observed_at",
        "promotion_digest",
        "targets",
    }
    if set(observations) != observation_fields:
        raise ReleaseControlError("publication reconciliation observation shape is not closed")
    for field in (
        "artifact_manifest_digest",
        "lock_receipt_digest",
        "observation_digest",
        "promotion_digest",
    ):
        _require_digest(observations[field], f"publication reconciliation observation {field}")
    _parse_utc_timestamp(observations["observed_at"], "publication observation time")
    _validate_retention_payload(
        retention,
        expected_input_digest=data["evidence_manifest_digest"],
        expected_phase="qualified-publication",
        label="publication reconciliation retention",
    )
    if live or retention_readbacks is not None:
        _validate_observed_store_readbacks(
            retention["stores"],
            expected_digest=data["evidence_manifest_digest"],
            readbacks=retention_readbacks,
            label="publication reconciliation retention",
        )
    candidate_digest = data["candidate_digest"]
    candidate_bindings = {
        "approval": approval.get("candidate_digest"),
        "evidence manifest": evidence_manifest.get("candidate_digest"),
        "lock": lock.get("candidate_digest"),
        "observations": observations.get("candidate_digest"),
        "promotion": promotion.get("candidate_digest"),
        "qualification": qualification.get("candidate_digest"),
        "candidate identity": candidate.get("candidate_digest"),
    }
    for label, observed_candidate in candidate_bindings.items():
        if observed_candidate != candidate_digest:
            raise ReleaseControlError(f"publication reconciliation {label} candidate mismatch")
    if (
        lock.get("approval_digest") != data["approval_digest"]
        or approval.get("qualification_digest", data["qualification_digest"])
        != data["qualification_digest"]
        or promotion.get("lock_receipt_digest") != data["lock_receipt_digest"]
        or observations.get("lock_receipt_digest") != data["lock_receipt_digest"]
        or observations.get("promotion_digest") != data["promotion_digest"]
        or observations.get("artifact_manifest_digest") != candidate["artifact_manifest_digest"]
        or promotion.get("operation_id") != lock.get("operation_id")
        or promotion.get("promotion_plan_digest") != lock.get("promotion_plan_digest")
        or promotion.get("target_state_digest") != lock.get("target_state_digest")
        or promotion.get("publisher_id") != lock.get("owner")
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
    manifest_artifacts = [
        {
            "media_type": entry["media_type"],
            "path": entry["path"],
            "sha256": entry["sha256"],
            "size": entry["size"],
        }
        for entry in entries
        if entry["role"] == "release-artifact"
    ]
    if manifest_artifacts != artifacts:
        raise ReleaseControlError(
            "publication reconciliation evidence entries differ from qualified artifacts"
        )
    if retention["input_digest"] != data["evidence_manifest_digest"]:
        raise ReleaseControlError("publication reconciliation retention input binding mismatch")
    if promotion_target_ids != target_ids:
        raise ReleaseControlError("publication reconciliation promotion target set differs")
    observation_targets = observations.get("targets")
    if not isinstance(observation_targets, list) or not observation_targets:
        raise ReleaseControlError("publication reconciliation observations have no targets")
    observed_target_ids: list[str] = []
    for target in observation_targets:
        if not isinstance(target, dict) or set(target) != {
            "artifacts",
            "availability",
            "immutability",
            "provider_receipt_digest",
            "raw_result_digest",
            "target_id",
            "uri",
        }:
            raise ReleaseControlError("publication reconciliation observation target is malformed")
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ReleaseControlError("publication reconciliation observation target id is missing")
        if target.get("availability") != "present" or target.get("immutability") != "immutable":
            raise ReleaseControlError("publication reconciliation observed a non-final target")
        _require_digest(
            target["provider_receipt_digest"], "publication observation provider receipt"
        )
        _require_digest(target["raw_result_digest"], "publication observation raw result")
        if not isinstance(target["uri"], str) or not target["uri"]:
            raise ReleaseControlError("publication reconciliation observation URI is missing")
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
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    gate = _passing_record(
        record,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    candidate = _passing_record(
        candidate_identity_record,
        "release-candidate-identity",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    predecessor = _passing_record(
        predecessor_record,
        "release-predecessor",
        live=live,
        attestation_verifier=attestation_verifier,
    )
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
    record: Mapping[str, Any],
    *,
    gate_instance: Mapping[str, Any],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    plan = _passing_record(
        record,
        "release-qualification-plan",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    gate = _passing_record(
        gate_instance,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    _validate_qualification_plan_payload(plan)
    bindings = {
        "gate instance": (plan["gate_instance_digest"], sha256_json(gate_instance)),
        "candidate": (plan["candidate_digest"], gate.get("candidate_digest")),
        "predecessor": (plan["predecessor_digest"], gate.get("predecessor_digest")),
        "milestone": (plan["milestone"], gate.get("milestone")),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"release qualification plan {label} binding mismatch")


def _validate_release_approval_decision_record(
    record: Mapping[str, Any],
    *,
    approval: Mapping[str, Any],
    gate: Mapping[str, Any],
    qualification: Mapping[str, Any],
    roles: Mapping[str, str],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None,
) -> None:
    decision = _passing_record(
        record,
        "release-approval-decision",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "approval_kind",
        "author_id",
        "authority_policy_digest",
        "candidate_digest",
        "conflicts",
        "decision",
        "expires_at",
        "issued_at",
        "milestone",
        "qualification_digest",
        "reviewer_id",
        "rubric_result_digest",
        "signing_method",
    }
    if set(decision) != expected_fields:
        raise ReleaseControlError("release approval decision data shape is not closed")
    if (
        decision["approval_kind"] != "non_author_release_decision"
        or decision["decision"] != "APPROVED"
        or decision["conflicts"] != []
        or decision["signing_method"] != "provider-attestation-v1"
    ):
        raise ReleaseControlError("release approval decision is not a clean approval")
    _require_digest(decision["authority_policy_digest"], "approval decision authority policy")
    _require_digest(decision["candidate_digest"], "approval decision candidate")
    _require_digest(decision["qualification_digest"], "approval decision qualification")
    _require_nonempty_string(decision["author_id"], "approval decision author")
    _require_nonempty_string(decision["reviewer_id"], "approval decision reviewer")
    if decision["milestone"] not in MILESTONES:
        raise ReleaseControlError("release approval decision milestone is invalid")
    if decision["rubric_result_digest"] is not None:
        _require_digest(decision["rubric_result_digest"], "approval decision rubric")
    issued_at = _parse_utc_timestamp(decision["issued_at"], "approval decision issue time")
    expires_at = _parse_utc_timestamp(decision["expires_at"], "approval decision expiry")
    if expires_at <= issued_at:
        raise ReleaseControlError("release approval decision validity window is invalid")
    if live and not issued_at <= datetime.now(UTC) < expires_at:
        raise ReleaseControlError("release approval decision is not currently valid")
    bindings = {
        "author": (decision["author_id"], roles["author_id"]),
        "reviewer": (decision["reviewer_id"], roles["non_author_reviewer_id"]),
        "approval author": (decision["author_id"], approval["author_id"]),
        "approval reviewer": (decision["reviewer_id"], approval["reviewer_id"]),
        "candidate": (decision["candidate_digest"], approval["candidate_digest"]),
        "gate candidate": (decision["candidate_digest"], gate.get("candidate_digest")),
        "milestone": (decision["milestone"], gate.get("milestone")),
        "qualification": (decision["qualification_digest"], sha256_json(qualification)),
        "approval rubric": (decision["rubric_result_digest"], approval["rubric_result_digest"]),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"release approval decision {label} binding mismatch")
    if decision["reviewer_id"] == decision["author_id"]:
        raise ReleaseControlError("release approval decision is not independent")
    signers = _validated_record_signers(
        record,
        live=live,
        attestation_verifier=attestation_verifier,
    )
    if decision["reviewer_id"] not in signers:
        raise ReleaseControlError("release approval decision lacks reviewer authority")


def validate_release_approval_record(
    record: Mapping[str, Any],
    *,
    approval_decision: Mapping[str, Any],
    gate_instance: Mapping[str, Any],
    qualification: Mapping[str, Any],
    role_assignments: Mapping[str, Any],
    no_prepublication_rubric: bool,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    approval = _passing_record(
        record,
        "release-approval",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    gate = _passing_record(
        gate_instance,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualification_data = _passing_record(
        qualification,
        "release-qualification",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    basic = {"author_id", "candidate_digest", "conflicts", "decision", "reviewer_id"}
    extended = {
        "approval_decision_digest",
        "gate_instance_digest",
        "qualification_digest",
        "rubric_result_digest",
    }
    if set(approval) != basic | extended:
        raise ReleaseControlError("release approval data shape is not closed")
    if approval["decision"] != "APPROVED" or approval["conflicts"] != []:
        raise ReleaseControlError("release approval is not conflict-free and approved")
    milestone = gate.get("milestone")
    run_id = gate.get("run_id")
    if not isinstance(milestone, str) or milestone not in MILESTONES:
        raise ReleaseControlError("release approval gate milestone is invalid")
    run_id = _require_nonempty_string(run_id, "release approval gate run id")
    roles = validate_role_assignments(
        role_assignments,
        live=live,
        expected_milestone=milestone,
        expected_run_id=run_id,
        check_conflicts=True,
        check_freshness=live,
        attestation_verifier=attestation_verifier,
    )
    author = approval["author_id"]
    reviewer = approval["reviewer_id"]
    if author != roles["author_id"]:
        raise ReleaseControlError("release approval author does not match assigned roles")
    if reviewer == author or reviewer != roles["non_author_reviewer_id"]:
        raise ReleaseControlError("release approval is not from the assigned non-author reviewer")
    if approval["candidate_digest"] != gate.get("candidate_digest") or approval[
        "candidate_digest"
    ] != qualification_data.get("candidate_digest"):
        raise ReleaseControlError("release approval candidate binding mismatch")
    if approval["gate_instance_digest"] != sha256_json(gate_instance):
        raise ReleaseControlError("release approval gate-instance binding mismatch")
    if approval["qualification_digest"] != sha256_json(qualification):
        raise ReleaseControlError("release approval qualification binding mismatch")
    if no_prepublication_rubric and approval.get("rubric_result_digest") is not None:
        raise ReleaseControlError("prepublication approval unexpectedly names a rubric result")
    if not no_prepublication_rubric:
        _require_digest(approval["rubric_result_digest"], "approval rubric result")
    decision_digest = _require_digest(approval["approval_decision_digest"], "approval decision")
    if decision_digest != sha256_json(approval_decision):
        raise ReleaseControlError("release approval decision does not resolve to exact bytes")
    _validate_release_approval_decision_record(
        approval_decision,
        approval=approval,
        gate=gate,
        qualification=qualification,
        roles=roles,
        live=live,
        attestation_verifier=attestation_verifier,
    )
    signers = {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
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
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    candidate = _passing_record(
        record,
        "release-candidate-identity",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    predecessor = _passing_record(
        predecessor_record,
        "release-predecessor",
        live=live,
        attestation_verifier=attestation_verifier,
    )
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
    record: Mapping[str, Any],
    artifacts: Path,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    """Bind every publishable byte and filename to the frozen-source manifest."""

    validate_record(record, "release-artifact-manifest")
    if record["status"] != "PASS":
        raise ReleaseControlError("artifact manifest is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic artifact manifests cannot authorize live publication")
    _validated_record_signers(
        record,
        live=live,
        attestation_verifier=attestation_verifier,
    )
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
    readbacks: Mapping[str, Path] | None = None,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    """Validate two independent read-backs against the supplied canonical input."""

    validate_record(receipts, "release-retention-receipts")
    if receipts["status"] != "PASS":
        raise ReleaseControlError("retention receipt set is not passing")
    if live and receipts["synthetic"] is not False:
        raise ReleaseControlError("synthetic retention receipts cannot authorize a live release")
    _validated_record_signers(
        receipts,
        live=live,
        attestation_verifier=attestation_verifier,
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
        _validated_record_signers(
            record,
            live=live,
            attestation_verifier=attestation_verifier,
        )
        supplied_digests.append(_regular_file_digest(path))
    if manifest is not None:
        manifest_record = _release_input(
            manifest,
            "release-evidence-manifest",
            live=live,
            attestation_verifier=attestation_verifier,
        )
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
    if live or readbacks is not None:
        _validate_observed_store_readbacks(
            stores,
            expected_digest=expected_input_digest,
            readbacks=readbacks,
            label="release retention",
        )
    if (invocation_root is None) != (through_stage is None):
        raise ReleaseControlError("invocation-root and through-stage must be supplied together")
    if invocation_root is not None and (
        invocation_root.is_symlink() or not invocation_root.is_dir() or not through_stage
    ):
        raise ReleaseControlError("retention invocation journal is missing or unsafe")


def _validated_readiness_blockers(readiness_registry: Mapping[str, Any]) -> list[str]:
    raw_blockers = readiness_registry.get("blockers")
    if not isinstance(raw_blockers, list):
        raise ReleaseControlError("readiness registry blockers must be a list")
    codes: list[str] = []
    required_fields = {"code", "resolver"}
    count_fields = {"required_count", "resolved_count"}
    for blocker in raw_blockers:
        if not isinstance(blocker, dict):
            raise ReleaseControlError("readiness registry blocker must be an object")
        fields = set(blocker)
        if not required_fields.issubset(fields) or not fields.issubset(
            required_fields | count_fields
        ):
            raise ReleaseControlError("readiness registry blocker shape is not closed")
        if bool(fields & count_fields) and not count_fields.issubset(fields):
            raise ReleaseControlError("readiness registry blocker counts are incomplete")
        code = _require_nonempty_string(blocker["code"], "readiness blocker code")
        _require_nonempty_string(blocker["resolver"], "readiness blocker resolver")
        if count_fields.issubset(fields):
            required_count = blocker["required_count"]
            resolved_count = blocker["resolved_count"]
            if (
                isinstance(required_count, bool)
                or not isinstance(required_count, int)
                or required_count < 0
                or isinstance(resolved_count, bool)
                or not isinstance(resolved_count, int)
                or resolved_count < 0
                or resolved_count > required_count
            ):
                raise ReleaseControlError("readiness registry blocker counts are invalid")
        codes.append(code)
    if codes != sorted(set(codes)):
        raise ReleaseControlError("readiness registry blockers are not canonical")
    return codes


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

    if not isinstance(readiness_registry, Mapping):
        raise ReleaseControlError("readiness registry must be an object")

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

    delta_capability_ids: list[str] = []
    for disposition, before_required, after_required in (
        ("added", False, True),
        ("changed", True, True),
        ("removed", True, False),
    ):
        rows = delta_data[disposition]
        if not isinstance(rows, list):
            raise ReleaseControlError(f"readiness {disposition} capability delta is malformed")
        disposition_ids: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "after_digest",
                "before_digest",
                "capability_id",
            }:
                raise ReleaseControlError(
                    f"readiness {disposition} capability delta row is malformed"
                )
            capability_id = row["capability_id"]
            if not isinstance(capability_id, str) or not capability_id:
                raise ReleaseControlError("readiness capability delta id is missing")
            before = row["before_digest"]
            after = row["after_digest"]
            if before_required:
                _require_digest(before, f"readiness {disposition} before digest")
            elif before is not None:
                raise ReleaseControlError(
                    f"readiness {disposition} capability has an unexpected before digest"
                )
            if after_required:
                _require_digest(after, f"readiness {disposition} after digest")
            elif after is not None:
                raise ReleaseControlError(
                    f"readiness {disposition} capability has an unexpected after digest"
                )
            if disposition == "changed" and before == after:
                raise ReleaseControlError("readiness changed capability has identical digests")
            disposition_ids.append(capability_id)
        if disposition_ids != sorted(set(disposition_ids)):
            raise ReleaseControlError(
                f"readiness {disposition} capability inventory is not canonical"
            )
        delta_capability_ids.extend(disposition_ids)
    if len(delta_capability_ids) != len(set(delta_capability_ids)):
        raise ReleaseControlError("readiness capability delta repeats an id across dispositions")

    mappings = mapping["mappings"]
    if not isinstance(mappings, list) or not mappings:
        raise ReleaseControlError("readiness delta test mappings are missing or malformed")
    mapped_capability_ids: list[str] = []
    for row in mappings:
        if not isinstance(row, dict) or set(row) != {
            "capability_id",
            "environment_ids",
            "obligation_ids",
            "scenario_ids",
        }:
            raise ReleaseControlError("readiness delta test mapping row is malformed")
        capability_id = row["capability_id"]
        if not isinstance(capability_id, str) or not capability_id:
            raise ReleaseControlError("readiness delta test mapping capability is missing")
        for field in ("environment_ids", "obligation_ids", "scenario_ids"):
            values = row[field]
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value for value in values)
                or values != sorted(set(values))
            ):
                raise ReleaseControlError(f"readiness delta test mapping {field} is not canonical")
        mapped_capability_ids.append(capability_id)
    if mapped_capability_ids != sorted(set(mapped_capability_ids)):
        raise ReleaseControlError("readiness mapped capability inventory is not canonical")
    if mapped_capability_ids != sorted(delta_capability_ids):
        raise ReleaseControlError("readiness mapped capabilities do not equal the capability delta")
    if mapping["unmapped_capabilities"] != []:
        raise ReleaseControlError("readiness has unmapped changed capabilities")

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
    milestone_values = (
        gate_input_data.get("milestone"),
        gate.get("milestone"),
        candidate.get("milestone"),
        freeze.get("milestone"),
        impact.get("milestone"),
        artifact.get("milestone"),
        delta_data.get("milestone"),
        mapping.get("milestone"),
        predecessor_data.get("candidate_milestone"),
    )
    if (
        any(not isinstance(value, str) or value not in MILESTONES for value in milestone_values)
        or len(set(milestone_values)) != 1
    ):
        raise ReleaseControlError("readiness milestone bindings disagree")
    milestone = milestone_values[0]
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

    blockers = _validated_readiness_blockers(readiness_registry)
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
        optional="provider-attestation-keyring",
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
        "record",
        optional="provider-attestation-keyring store-readback attempt-store-readback",
        repeatable="store-readback attempt-store-readback",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_approval.py": _tool_contract(
        "approval-decision gate-instance qualification role-assignments "
        "no-prepublication-rubric record",
        optional="provider-attestation-keyring",
        boolean="no-prepublication-rubric",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_artifact_manifest.py": _tool_contract(
        "record artifacts read-hash",
        optional="provider-attestation-keyring",
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
        optional="provider-attestation-keyring",
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
        optional="provider-attestation-keyring",
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
        "record",
        optional="provider-attestation-keyring attempt-store-readback",
        repeatable="attempt-store-readback",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_qualification_plan.py": _tool_contract(
        "record gate-instance",
        optional="provider-attestation-keyring",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_retention.py": _tool_contract(
        "manifest receipts read-back",
        "input receipts read-back",
        "input manifest invocation-root through-stage receipts read-back",
        optional="provider-attestation-keyring store-readback",
        boolean="read-back",
        repeatable="input store-readback",
        output_flag=None,
        fixture_producer=False,
        record_flag=None,
    ),
    "validate_release_role_assignments.py": _tool_contract(
        "record milestone run-id check-conflicts check-freshness",
        optional="provider-attestation-keyring",
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


def _attestation_verifier_from_args(
    args: argparse.Namespace,
) -> ProviderAttestationVerifier | None:
    value = getattr(args, "provider_attestation_keyring", None)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReleaseControlError("provider attestation keyring path is missing")
    return ProviderAttestationVerifier.from_keyring(Path(value))


def _store_readbacks_from_args(values: object) -> Mapping[str, Path] | None:
    if values in (None, []):
        return None
    if not isinstance(values, list):
        raise ReleaseControlError("store readbacks must be repeatable bindings")
    parsed: dict[str, Path] = {}
    for value in values:
        if not isinstance(value, str) or value.count("=") != 1:
            raise ReleaseControlError("store readback must use STORE_ID=PATH")
        store_id, raw_path = value.split("=", 1)
        if store_id not in {"payload-store-a", "payload-store-b"} or not raw_path:
            raise ReleaseControlError("store readback binding is invalid")
        if store_id in parsed:
            raise ReleaseControlError("store readback binding is duplicated")
        parsed[store_id] = Path(raw_path)
    return parsed


def _attempt_store_readbacks_from_args(
    values: object,
) -> Mapping[str, Mapping[str, Path]] | None:
    if values in (None, []):
        return None
    if not isinstance(values, list):
        raise ReleaseControlError("attempt store readbacks must be repeatable bindings")
    parsed: dict[str, dict[str, Path]] = {}
    for value in values:
        if not isinstance(value, str) or value.count("=") != 1:
            raise ReleaseControlError(
                "attempt store readback must use RETENTION_DIGEST:STORE_ID=PATH"
            )
        identity, raw_path = value.split("=", 1)
        if identity.count(":") != 1 or not raw_path:
            raise ReleaseControlError("attempt store readback binding is invalid")
        retention_digest, store_id = identity.split(":", 1)
        _require_digest(retention_digest, "attempt retention readback")
        if store_id not in {"payload-store-a", "payload-store-b"}:
            raise ReleaseControlError("attempt store readback store id is invalid")
        stores = parsed.setdefault(retention_digest, {})
        if store_id in stores:
            raise ReleaseControlError("attempt store readback binding is duplicated")
        stores[store_id] = Path(raw_path)
    return parsed


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
        attestation_verifier = _attestation_verifier_from_args(args)
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
                attestation_verifier=attestation_verifier,
            )
            gate_instance = _release_input(
                readiness_paths[0],
                "release-gate-instance",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            candidate = _release_input(
                readiness_paths[1],
                "release-candidate-identity",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            predecessor = _release_input(
                readiness_paths[2],
                "release-predecessor",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            linear_snapshot = _release_input(
                readiness_paths[3],
                "linear-release-snapshot",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            source_freeze = _release_input(
                candidate_root / "source-freeze.json",
                "release-source-freeze",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            impact_manifest = _release_input(
                candidate_root / "impact-manifest.json",
                "release-impact-manifest",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            artifact_manifest = _release_input(
                readiness_paths[4],
                "release-artifact-manifest",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            delta = _release_input(
                readiness_paths[5],
                "release-capability-delta",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            delta_test_map = _release_input(
                readiness_paths[6],
                "release-delta-test-map",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
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
                attestation_verifier=attestation_verifier,
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
                readbacks=_store_readbacks_from_args(args.store_readback),
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_qualification.py":
            record_path = Path(args.record)
            result = read_json(record_path)
            validate_release_qualification_record(
                result,
                evidence_root=record_path.parent,
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
                attempt_retention_readbacks=_attempt_store_readbacks_from_args(
                    args.attempt_store_readback
                ),
            )
        elif name == "validate_publication_reconciliation.py":
            record_path = Path(args.record)
            result = read_json(record_path)
            validate_publication_reconciliation_record(
                result,
                evidence_root=record_path.parent,
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
                retention_readbacks=_store_readbacks_from_args(args.store_readback),
                attempt_retention_readbacks=_attempt_store_readbacks_from_args(
                    args.attempt_store_readback
                ),
            )
        elif name == "validate_release_gate_instance.py":
            result = read_json(Path(args.record))
            validate_release_gate_instance_record(
                result,
                candidate_identity_record=read_json(Path(args.candidate_identity)),
                predecessor_record=read_json(Path(args.predecessor)),
                task_state_policy=read_json(Path(args.task_state_policy)),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_qualification_plan.py":
            result = read_json(Path(args.record))
            validate_release_qualification_plan_record(
                result,
                gate_instance=read_json(Path(args.gate_instance)),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_approval.py":
            result = read_json(Path(args.record))
            validate_release_approval_record(
                result,
                approval_decision=read_json(Path(args.approval_decision)),
                gate_instance=read_json(Path(args.gate_instance)),
                qualification=read_json(Path(args.qualification)),
                role_assignments=read_json(Path(args.role_assignments)),
                no_prepublication_rubric=bool(args.no_prepublication_rubric),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_candidate_identity.py":
            result = read_json(Path(args.record))
            validate_release_candidate_identity_record(
                result,
                predecessor_record=read_json(Path(args.predecessor)),
                candidate_dir=Path(args.candidate_dir),
                no_evaluation_adoption=bool(args.no_evaluation_adoption),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
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
                validate_role_assignments(
                    result,
                    live=not fixture_mode,
                    expected_milestone=args.milestone,
                    expected_run_id=args.run_id,
                    check_conflicts=bool(args.check_conflicts),
                    check_freshness=bool(args.check_freshness),
                    attestation_verifier=attestation_verifier,
                )
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
    "signature_subject_digest",
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
