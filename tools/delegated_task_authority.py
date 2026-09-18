# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Verify a task instance under a bounded owner program grant.

Only the isolated provider attestor may certify fresh Linear observations.
The executor's separate signature expresses its request, not human review or
provider evidence. This module never signs and cannot fetch provider state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, sha256_json

try:
    from tools.program_delegation import validate_program_grant
    from tools.task_delegation import (
        DelegationError,
        DelegationNotReady,
        delegation_id,
        parse_utc,
        tracker_snapshot_digest,
    )
except ImportError:
    from program_delegation import validate_program_grant
    from task_delegation import (
        DelegationError,
        DelegationNotReady,
        delegation_id,
        parse_utc,
        tracker_snapshot_digest,
    )


def validate_delegated_task(
    delegation: Mapping[str, Any],
    authority: Mapping[str, Any],
    catalog: Mapping[str, Any],
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
    if set(delegation) != {
        "schema_version",
        "synthetic",
        "program_grant",
        "subject",
        "subject_digest",
        "delegate_signature",
        "attestor_signature",
    }:
        raise DelegationError("delegated task record shape is not closed")
    if delegation.get("schema_version") != "metriplane.task-delegation.v2":
        raise DelegationError("delegated task schema version is unsupported")
    if snapshot.get("schema_version") != "metriplane.linear-work-order-snapshot.v1":
        raise DelegationError("delegated task snapshot schema version is unsupported")
    synthetic = delegation.get("synthetic")
    if not isinstance(synthetic, bool) or snapshot.get("synthetic") is not synthetic:
        raise DelegationError("delegated task and snapshot modes differ")
    if live and synthetic:
        raise DelegationError("synthetic task instance cannot supply live authority")

    grant = delegation.get("program_grant")
    if not isinstance(grant, Mapping):
        raise DelegationError("delegated task has no owner program grant")
    program = validate_program_grant(
        grant,
        authority,
        catalog,
        repository=repository,
        project_id=project_id,
        grantor_id=grantor_id,
        executor_id=executor_id,
        evaluated_at=evaluated_at,
        live=live,
    )
    if task_id not in program["task_ids"]:
        raise DelegationError("task is outside the owner-approved implementation program")

    subject = delegation.get("subject")
    if not isinstance(subject, Mapping):
        raise DelegationError("delegated task subject is invalid")
    if set(subject) != {
        "delegation_id",
        "program_grant_id",
        "grantor",
        "delegate",
        "scope",
        "tracker",
        "issued_at",
        "expires_at",
        "tracker_snapshot_digest",
        "delegate_key_id",
        "attestor_key_id",
    }:
        raise DelegationError("delegated task subject shape is not closed")
    subject_digest = sha256_json(subject)
    if delegation.get("subject_digest") != subject_digest:
        raise DelegationError("delegated task subject digest mismatch")
    if subject.get("delegation_id") != delegation_id(subject):
        raise DelegationError("delegated task stable identity mismatch")
    if subject.get("program_grant_id") != program["grant_id"]:
        raise DelegationError("delegated task does not bind the owner program grant")
    if subject.get("tracker_snapshot_digest") != tracker_snapshot_digest(snapshot):
        raise DelegationError("delegated task does not bind the exact provider snapshot")
    grantor = subject.get("grantor")
    delegate = subject.get("delegate")
    scope = subject.get("scope")
    tracker = subject.get("tracker")
    if not all(isinstance(value, Mapping) for value in (grantor, delegate, scope, tracker)):
        raise DelegationError("delegated task roles or scope are invalid")
    assert isinstance(grantor, Mapping)
    assert isinstance(delegate, Mapping)
    assert isinstance(scope, Mapping)
    assert isinstance(tracker, Mapping)
    if set(grantor) != {"provider", "actor_id", "role"} or set(delegate) != {"kind", "executor_id"}:
        raise DelegationError("delegated task role shape is not closed")
    if grantor != grant["subject"]["grantor"]:
        raise DelegationError("delegated task grantor differs from the owner grant")
    if delegate != {"kind": "codex_goal", "executor_id": executor_id}:
        raise DelegationError("delegated task executor differs from the owner grant")
    expected_scope = {
        "authority": "implementation",
        "base_sha": base_sha,
        "base_tree": base_tree,
        "linear_issue": linear_issue,
        "project_id": project_id,
        "repository": repository,
        "task_id": task_id,
    }
    if scope != expected_scope:
        raise DelegationError("delegated task scope or exact base is invalid")
    if tracker.get("provider") != "linear" or set(tracker) != {
        "provider",
        "event_id",
        "event_cursor",
    }:
        raise DelegationError("delegated task tracker identity is invalid")
    if (
        subject.get("delegate_key_id") != program["delegate_key_id"]
        or subject.get("attestor_key_id") != program["attestor_key_id"]
    ):
        raise DelegationError("delegated task key binding differs from the owner grant")

    issued = parse_utc(subject.get("issued_at"), "delegated task issued-at")
    expires = parse_utc(subject.get("expires_at"), "delegated task expiry")
    now = parse_utc(evaluated_at, "delegated task evaluation time")
    grant_issued = parse_utc(grant["subject"]["issued_at"], "owner program grant issued-at")
    grant_expires = parse_utc(program["expires_at"], "owner program grant expiry")
    if issued >= expires or issued < grant_issued or issued > now or expires > grant_expires:
        raise DelegationError("delegated task time interval is invalid")
    if (expires - issued).total_seconds() > 600:
        raise DelegationError("delegated task lease exceeds ten minutes")
    if now >= expires:
        raise DelegationNotReady("delegated task lease is expired")
    captured = parse_utc(snapshot.get("captured_at"), "provider snapshot capture time")
    if captured > now or captured < issued or (now - captured).total_seconds() > 300:
        raise DelegationNotReady("provider snapshot is not fresh within the task lease")
    if snapshot.get("repository") != repository or snapshot.get("project_id") != project_id:
        raise DelegationError("provider snapshot repository/project differs from the task")
    if snapshot.get("event_cursor") != tracker.get("event_cursor"):
        raise DelegationNotReady("provider event cursor differs from the task lease")
    task = snapshot.get("task")
    expected_task = {
        "assignee_actor_id": grantor_id,
        "base_sha": base_sha,
        "delegate_executor_id": executor_id,
        "delegation_event_id": tracker.get("event_id"),
        "delegation_id": subject.get("delegation_id"),
        "delegation_status": "active",
        "issue_state": task.get("issue_state") if isinstance(task, Mapping) else None,
        "linear_issue": linear_issue,
        "task_id": task_id,
    }
    if task != expected_task or task["issue_state"] not in {"backlog", "unstarted", "started"}:
        raise DelegationNotReady("provider task assignment or execution state is not READY")

    identities = (
        (
            "delegate_signature",
            "codex_goal",
            executor_id,
            "delegate",
            program["delegate_key_id"],
            program["delegate_public_key_hex"],
        ),
        (
            "attestor_signature",
            "metriplane-health",
            "metriplane-health",
            "attestor",
            program["attestor_key_id"],
            program["attestor_public_key_hex"],
        ),
    )
    for field, provider, actor, label, signer_key_id, public_hex in identities:
        signature = delegation.get(field)
        if (
            not isinstance(signature, Mapping)
            or set(signature) != {"provider", "actor_id", "key_id", "signature"}
            or {key: signature.get(key) for key in ("provider", "actor_id", "key_id")}
            != {"provider": provider, "actor_id": actor, "key_id": signer_key_id}
        ):
            raise DelegationError(f"delegated task {label} signature identity is invalid")
        verifier = ProviderAttestationVerifier(keys={(provider, actor): bytes.fromhex(public_hex)})
        if not verifier.verify(signature, subject_digest=subject_digest):
            raise DelegationError(f"delegated task {label} signature is not trusted")

    return {
        "authority_scope_exact": True,
        "delegation_active": True,
        "delegate_exact": True,
        "grantor_authorized": True,
        "linear_assignment_exact": True,
        "signature_trusted": True,
        "time_window_valid": True,
    }
