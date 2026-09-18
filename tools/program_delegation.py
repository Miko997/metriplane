# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Verify a bounded owner-signed v0.5 implementation program grant.

This verifier does not issue task delegations or authorize a merge. In
particular, possessing a program grant is not a substitute for fresh provider
state, an exact-base task work order, or an independently verified request.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, sha256_json

try:
    from tools.task_delegation import (
        DelegationError,
        DelegationNotReady,
        _authority_key,
        key_id,
        parse_utc,
    )
except ImportError:
    from task_delegation import (
        DelegationError,
        DelegationNotReady,
        _authority_key,
        key_id,
        parse_utc,
    )


def program_grant_id(subject: Mapping[str, Any]) -> str:
    return sha256_json({key: value for key, value in subject.items() if key != "grant_id"})


def _implementation_tasks(catalog: Mapping[str, Any]) -> list[str]:
    rows = catalog.get("tasks")
    if not isinstance(rows, list):
        raise DelegationError("program grant task catalog is invalid")
    tasks: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DelegationError("program grant task catalog row is invalid")
        if row.get("first_required_release") == "v0.5" and row.get("role") == "implementation":
            task_id = row.get("task_id")
            if not isinstance(task_id, str):
                raise DelegationError("program grant task identity is invalid")
            tasks.append(task_id)
    if not tasks or len(tasks) != len(set(tasks)):
        raise DelegationError("program grant implementation task set is invalid")
    return sorted(tasks)


def validate_program_grant(
    grant: Mapping[str, Any],
    authority: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    repository: str,
    project_id: str,
    grantor_id: str,
    executor_id: str,
    evaluated_at: str,
    live: bool,
) -> dict[str, Any]:
    """Check the owner root and the *whole* signed authority boundary.

    Callers must schema-validate both inputs and bind the authority/keyring and
    catalog bytes to the exact protected base before accepting a live grant.
    The result is only a validated grant description, never READY on its own.
    """
    if set(grant) != {"schema_version", "synthetic", "subject", "subject_digest", "signature"}:
        raise DelegationError("program grant record shape is not closed")
    if grant.get("schema_version") != "metriplane.program-delegation.v1":
        raise DelegationError("program grant schema version is unsupported")
    if authority.get("schema_version") != "metriplane.task-delegation-authority.v1":
        raise DelegationError("program grant authority schema version is unsupported")
    synthetic = grant.get("synthetic")
    if not isinstance(synthetic, bool) or (live and synthetic):
        raise DelegationError("synthetic program grant cannot supply live authority")
    subject = grant.get("subject")
    if not isinstance(subject, Mapping):
        raise DelegationError("program grant subject is invalid")
    if set(subject) != {
        "grant_id",
        "grantor",
        "delegate",
        "attestor",
        "scope",
        "issued_at",
        "expires_at",
        "signing_key_id",
    }:
        raise DelegationError("program grant subject shape is not closed")
    subject_digest = sha256_json(subject)
    if grant.get("subject_digest") != subject_digest:
        raise DelegationError("program grant subject digest mismatch")
    grant_id = subject.get("grant_id")
    if grant_id != program_grant_id(subject):
        raise DelegationError("program grant stable identity mismatch")
    grantor = subject.get("grantor")
    delegate = subject.get("delegate")
    attestor = subject.get("attestor")
    scope = subject.get("scope")
    if not all(isinstance(value, Mapping) for value in (grantor, delegate, attestor, scope)):
        raise DelegationError("program grant roles or scope are invalid")
    assert isinstance(grantor, Mapping)
    assert isinstance(delegate, Mapping)
    assert isinstance(attestor, Mapping)
    assert isinstance(scope, Mapping)
    if (
        set(grantor) != {"provider", "actor_id", "role"}
        or set(delegate) != {"kind", "executor_id", "key_id", "public_key_hex"}
        or set(attestor) != {"kind", "service", "key_id", "public_key_hex"}
    ):
        raise DelegationError("program grant role shape is not closed")
    provider = grantor.get("provider")
    if provider not in {"linear", "github"} or grantor.get("actor_id") != grantor_id:
        raise DelegationError("program grant does not name the authorized owner")
    if grantor.get("role") != "repository_owner" or grantor_id == executor_id:
        raise DelegationError("program grantor role is invalid")
    if delegate.get("kind") != "codex_goal" or delegate.get("executor_id") != executor_id:
        raise DelegationError("program grant does not name the actual executor")
    delegate_public = delegate.get("public_key_hex")
    if (
        not isinstance(delegate_public, str)
        or delegate_public != delegate_public.lower()
        or delegate.get("key_id") != key_id(delegate_public)
    ):
        raise DelegationError("program grant delegate key identity is invalid")
    attestor_public = attestor.get("public_key_hex")
    if (
        attestor.get("kind") != "isolated_provider_attestor"
        or attestor.get("service") != "metriplane-health"
        or not isinstance(attestor_public, str)
        or attestor_public != attestor_public.lower()
        or attestor.get("key_id") != key_id(attestor_public)
        or attestor_public == delegate_public
    ):
        raise DelegationError("program grant provider attestor is not isolated from the delegate")

    tasks = _implementation_tasks(catalog)
    expected_scope = {
        "repository": repository,
        "project_id": project_id,
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
    }
    if scope != expected_scope:
        raise DelegationError("program grant exceeds or differs from v0.5 implementation scope")

    signing_key_id = subject.get("signing_key_id")
    signature = grant.get("signature")
    if not isinstance(signing_key_id, str) or not isinstance(signature, Mapping):
        raise DelegationError("program grant signer is invalid")
    if set(signature) != {"provider", "actor_id", "key_id", "signature"}:
        raise DelegationError("program grant signature shape is not closed")
    expected_signer = {
        "provider": provider,
        "actor_id": grantor_id,
        "key_id": signing_key_id,
    }
    if {key: signature.get(key) for key in expected_signer} != expected_signer:
        raise DelegationError("program grant signature does not name the owner")
    owner_key = _authority_key(
        authority,
        provider=provider,
        actor_id=grantor_id,
        signing_key_id=signing_key_id,
    )
    if (
        owner_key.get("role") != "repository_owner"
        or owner_key.get("repository") != repository
        or owner_key.get("project_id") != project_id
    ):
        raise DelegationError("program grant key is outside the repository/project")
    if owner_key.get("status") != "active":
        raise DelegationNotReady("program grant owner key is revoked")
    if live and owner_key.get("trust_class") != "production":
        raise DelegationError("fixture owner key cannot authorize a live program grant")
    revoked = authority.get("revoked_delegation_ids")
    if (
        not isinstance(revoked, list)
        or not all(isinstance(value, str) for value in revoked)
        or revoked != sorted(set(revoked))
    ):
        raise DelegationError("program grant revocation set is invalid")
    if grant_id in revoked:
        raise DelegationNotReady("program grant is revoked")

    now = parse_utc(evaluated_at, "program grant evaluation time")
    issued = parse_utc(subject.get("issued_at"), "program grant issued-at")
    expires = parse_utc(subject.get("expires_at"), "program grant expiry")
    key_from = parse_utc(owner_key.get("not_before"), "program grant owner key not-before")
    key_until = parse_utc(owner_key.get("not_after"), "program grant owner key not-after")
    if issued >= expires or issued < key_from or expires > key_until:
        raise DelegationError("program grant interval is outside the owner key interval")
    if issued > now:
        raise DelegationError("program grant is issued in the future")
    if now >= expires or now < key_from or now >= key_until:
        raise DelegationNotReady("program grant is not currently active")

    public = owner_key.get("public_key_hex")
    if not isinstance(public, str):
        raise DelegationError("program grant owner public key is invalid")
    verifier = ProviderAttestationVerifier(keys={(provider, grantor_id): bytes.fromhex(public)})
    if not verifier.verify(signature, subject_digest=subject_digest):
        raise DelegationError("program grant owner signature is not trusted")
    return {
        "grant_id": grant_id,
        "delegate_key_id": delegate["key_id"],
        "delegate_public_key_hex": delegate_public,
        "attestor_key_id": attestor["key_id"],
        "attestor_public_key_hex": attestor_public,
        "expires_at": subject["expires_at"],
        "task_ids": tasks,
    }
