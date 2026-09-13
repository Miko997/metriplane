# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Closed, fail-closed validation for task delegation authority."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, sha256_json


class DelegationError(ValueError):
    """A delegation input is malformed, substituted, or untrusted."""


class DelegationNotReady(DelegationError):
    """A valid delegation or authority record is not currently active."""


def parse_utc(value: object, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise DelegationError(f"{label} is not canonical UTC time")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise DelegationError(f"{label} is not canonical UTC time") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise DelegationError(f"{label} is not canonical UTC time")
    return parsed


def delegation_id(subject: Mapping[str, Any]) -> str:
    identity = {key: value for key, value in subject.items() if key != "delegation_id"}
    return sha256_json(identity)


def key_id(public_key_hex: str) -> str:
    try:
        public_key = bytes.fromhex(public_key_hex)
    except ValueError as exc:
        raise DelegationError("delegation authority public key is not hexadecimal") from exc
    if len(public_key) != 32:
        raise DelegationError("delegation authority public key is not Ed25519")
    return hashlib.sha256(public_key).hexdigest()


def tracker_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    task = snapshot.get("task")
    if not isinstance(task, Mapping):
        raise DelegationError("Linear work-order snapshot task is invalid")
    task_claims = {key: value for key, value in task.items() if key != "delegation_id"}
    claims = {key: value for key, value in snapshot.items() if key != "task"}
    claims["task"] = task_claims
    return sha256_json(claims)


def _authority_key(
    authority: Mapping[str, Any],
    *,
    provider: str,
    actor_id: str,
    signing_key_id: str,
) -> Mapping[str, Any]:
    rows = authority.get("keys")
    if not isinstance(rows, list):
        raise DelegationError("delegation authority key set is invalid")
    identities: list[tuple[str, str, str]] = []
    matches: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DelegationError("delegation authority key row is invalid")
        identity = (row.get("provider"), row.get("actor_id"), row.get("key_id"))
        if not all(isinstance(value, str) for value in identity):
            raise DelegationError("delegation authority key identity is invalid")
        identities.append(identity)  # type: ignore[arg-type]
        if identity == (provider, actor_id, signing_key_id):
            matches.append(row)
    if identities != sorted(identities) or len(set(identities)) != len(identities):
        raise DelegationError("delegation authority keys are not unique canonical rows")
    if len(matches) != 1:
        raise DelegationError("delegation signing key is unknown or ambiguous")
    row = matches[0]
    public_key_hex = row.get("public_key_hex")
    if not isinstance(public_key_hex, str) or key_id(public_key_hex) != signing_key_id:
        raise DelegationError("delegation signing key identity does not match its public key")
    return row


def validate_delegation(
    delegation: Mapping[str, Any],
    authority: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    task_id: str,
    linear_issue: str,
    repository: str,
    project_id: str,
    base_sha: str,
    base_tree: str,
    grantor_id: str,
    executor_id: str,
    evaluated_at: str,
    live: bool,
) -> dict[str, bool]:
    if delegation.get("schema_version") != "metriplane.task-delegation.v1":
        raise DelegationError("task delegation schema version is unsupported")
    if authority.get("schema_version") != "metriplane.task-delegation-authority.v1":
        raise DelegationError("task delegation authority schema version is unsupported")
    if snapshot.get("schema_version") != "metriplane.linear-work-order-snapshot.v1":
        raise DelegationError("Linear work-order snapshot schema version is unsupported")

    synthetic = delegation.get("synthetic")
    snapshot_synthetic = snapshot.get("synthetic")
    if not isinstance(synthetic, bool) or snapshot_synthetic is not synthetic:
        raise DelegationError("delegation and Linear snapshot authority modes differ")
    if live and (synthetic or snapshot_synthetic):
        raise DelegationError("synthetic delegation evidence cannot supply live authority")

    subject = delegation.get("subject")
    if not isinstance(subject, Mapping):
        raise DelegationError("task delegation subject is invalid")
    claimed_subject_digest = delegation.get("subject_digest")
    actual_subject_digest = sha256_json(subject)
    if claimed_subject_digest != actual_subject_digest:
        raise DelegationError("task delegation subject digest mismatch")
    if subject.get("delegation_id") != delegation_id(subject):
        raise DelegationError("task delegation stable identity mismatch")
    if subject.get("tracker_snapshot_digest") != tracker_snapshot_digest(snapshot):
        raise DelegationError("task delegation does not bind the exact Linear snapshot claims")
    grantor = subject.get("grantor")
    delegate = subject.get("delegate")
    scope = subject.get("scope")
    tracker = subject.get("tracker")
    if not all(isinstance(row, Mapping) for row in (grantor, delegate, scope, tracker)):
        raise DelegationError("task delegation roles or scope are invalid")
    assert isinstance(grantor, Mapping)
    assert isinstance(delegate, Mapping)
    assert isinstance(scope, Mapping)
    assert isinstance(tracker, Mapping)

    grantor_provider = grantor.get("provider")
    grantor_actor = grantor.get("actor_id")
    if not isinstance(grantor_provider, str) or not isinstance(grantor_actor, str):
        raise DelegationError("task delegation grantor identity is invalid")
    if grantor_actor != grantor_id:
        raise DelegationError("task delegation does not name the authorized grantor")
    if grantor.get("role") != "repository_owner":
        raise DelegationError("task delegation grantor is not a repository owner")
    if delegate.get("kind") != "codex_goal" or delegate.get("executor_id") != executor_id:
        raise DelegationError("task delegation does not name the actual executor")
    if grantor_actor == executor_id:
        raise DelegationError("task delegate cannot grant its own authority")

    expected_scope = {
        "authority": scope.get("authority"),
        "base_sha": base_sha,
        "base_tree": base_tree,
        "linear_issue": linear_issue,
        "project_id": project_id,
        "repository": repository,
        "task_id": task_id,
    }
    if (
        scope != expected_scope
        or not isinstance(scope.get("authority"), str)
        or not scope["authority"]
    ):
        raise DelegationError("task delegation scope does not match the requested work order")
    if tracker.get("provider") != "linear":
        raise DelegationError("task delegation tracker provider is unsupported")

    signature = delegation.get("signature")
    if not isinstance(signature, Mapping):
        raise DelegationError("task delegation signature is invalid")
    signing_key_id = subject.get("signing_key_id")
    expected_signer = {
        "actor_id": grantor_actor,
        "key_id": signing_key_id,
        "provider": grantor_provider,
    }
    if {key: signature.get(key) for key in expected_signer} != expected_signer:
        raise DelegationError("task delegation signer is not the grantor")
    if not isinstance(signing_key_id, str):
        raise DelegationError("task delegation signing key identity is invalid")

    authority_key = _authority_key(
        authority,
        provider=grantor_provider,
        actor_id=grantor_actor,
        signing_key_id=signing_key_id,
    )
    if (
        authority_key.get("role") != "repository_owner"
        or authority_key.get("repository") != repository
        or authority_key.get("project_id") != project_id
    ):
        raise DelegationError("delegation key is not authorized for this repository and project")
    if authority_key.get("status") != "active":
        raise DelegationNotReady("delegation signing key is revoked")
    if live and authority_key.get("trust_class") != "production":
        raise DelegationError("fixture key cannot supply live delegation authority")

    revoked = authority.get("revoked_delegation_ids")
    if (
        not isinstance(revoked, list)
        or not all(isinstance(value, str) for value in revoked)
        or revoked != sorted(set(revoked))
    ):
        raise DelegationError("revoked delegation identities are not canonical")
    if subject["delegation_id"] in revoked:
        raise DelegationNotReady("task delegation is revoked")

    evaluated = parse_utc(evaluated_at, "delegation evaluation time")
    issued = parse_utc(subject.get("issued_at"), "delegation issued-at")
    expires = parse_utc(subject.get("expires_at"), "delegation expiry")
    key_from = parse_utc(authority_key.get("not_before"), "delegation key not-before")
    key_until = parse_utc(authority_key.get("not_after"), "delegation key not-after")
    if issued >= expires or key_from >= key_until:
        raise DelegationError("delegation or key validity interval is empty")
    if issued > evaluated:
        raise DelegationError("task delegation is issued in the future")
    if evaluated >= expires:
        raise DelegationNotReady("task delegation is expired")
    if issued < key_from or expires > key_until:
        raise DelegationError("task delegation exceeds signing-key validity")
    if evaluated < key_from or evaluated >= key_until:
        raise DelegationNotReady("delegation signing key is outside its validity window")

    public_key_hex = authority_key.get("public_key_hex")
    assert isinstance(public_key_hex, str)
    verifier = ProviderAttestationVerifier(
        keys={(grantor_provider, grantor_actor): bytes.fromhex(public_key_hex)}
    )
    if not verifier.verify(signature, subject_digest=actual_subject_digest):
        raise DelegationError("task delegation signature is not trusted")

    if snapshot.get("repository") != repository or snapshot.get("project_id") != project_id:
        raise DelegationError("Linear snapshot scope does not match the delegation")
    if snapshot.get("event_cursor") != tracker.get("event_cursor"):
        raise DelegationNotReady("Linear event cursor differs from the signed delegation")
    captured = parse_utc(snapshot.get("captured_at"), "Linear snapshot capture time")
    max_age = subject.get("max_snapshot_age_seconds")
    if not isinstance(max_age, int) or isinstance(max_age, bool):
        raise DelegationError("delegation snapshot age limit is invalid")
    if captured < issued or captured > evaluated:
        raise DelegationError("Linear snapshot time is outside the evaluated delegation interval")
    if (evaluated - captured).total_seconds() > max_age:
        raise DelegationNotReady("Linear work-order snapshot is stale")

    task = snapshot.get("task")
    expected_task = {
        "assignee_actor_id": grantor_actor,
        "base_sha": base_sha,
        "delegate_executor_id": executor_id,
        "delegation_event_id": tracker.get("event_id"),
        "delegation_id": subject.get("delegation_id"),
        "delegation_status": "active",
        "issue_state": task.get("issue_state") if isinstance(task, Mapping) else None,
        "linear_issue": linear_issue,
        "task_id": task_id,
    }
    if not isinstance(task, Mapping) or task != expected_task:
        raise DelegationNotReady("Linear task assignment does not match the signed delegation")
    if task.get("issue_state") not in {"backlog", "unstarted", "started"}:
        raise DelegationNotReady("Linear task is not executable")

    return {
        "authority_scope_exact": True,
        "delegation_active": True,
        "delegate_exact": True,
        "grantor_authorized": True,
        "linear_assignment_exact": True,
        "signature_trusted": True,
        "time_window_valid": True,
    }
