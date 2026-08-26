# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Durable, append-only main-health state and repair authorization controls."""

from __future__ import annotations

import argparse
import base64
import email.utils
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
GLOBAL_SCOPES = {"main", "nightly", "weekly"}
CADENCE_BY_SCOPE = {
    "candidate": "candidate",
    "main": "protected-main",
    "nightly": "nightly",
    "weekly": "weekly",
}
PASS = "success"
CANONICAL_REPAIR_CADENCES = ["nightly", "weekly"]
AUTHORIZED_REVIEWER_PERMISSIONS = {"admin", "maintain", "write"}
OWNER_ADMISSION_MAX_AGE_SECONDS = 300
MAIN_HEALTH_CONTEXT = "Main health admission / required"
GITHUB_ACTIONS_INTEGRATION_ID = 15368
MAIN_HEALTH_PUBLISHER_INTEGRATION_ID = 4722589
CORE_REQUIRED_CONTEXTS = {
    "Documentation / required",
    "Metriplane / required",
    "Security / required",
}
OWNER_BYPASS_ACTOR = {
    "actor_id": 5,
    "actor_type": "RepositoryRole",
    "bypass_mode": "pull_request",
}
CORE_PULL_REQUEST_PARAMETERS = {
    "allowed_merge_methods": ["merge", "squash", "rebase"],
    "dismiss_stale_reviews_on_push": False,
    "require_code_owner_review": False,
    "require_extra_approval_for_unattributed_changes": True,
    "require_last_push_approval": False,
    "required_approving_review_count": 0,
    "required_review_thread_resolution": False,
    "required_reviewers": [],
}
ACTIVATION_POLICY = {
    "candidate_mutates_global_state": False,
    "global_cadences": ["protected-main", "nightly", "weekly"],
    "prehistory_disposition": "not_measured",
    "repair_requires_non_author": True,
    "schema_version": SCHEMA_VERSION,
    "state_branch": "metriplane-main-health-state",
    "writer_workflow": ".github/workflows/main-health.yml",
}
STATE_FIELDS = {
    "activation_digest",
    "first_bad_sha",
    "generation",
    "history_head",
    "incident_digest",
    "last_good_sha",
    "resolution_digest",
    "schema_version",
    "status",
    "updated_at",
}


class HealthError(ValueError):
    """A main-health transition is invalid or cannot be verified."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HealthError(f"cannot read retained JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HealthError(f"{path} must contain a JSON object")
    return value


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(value)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_immutable(path: Path, value: dict[str, Any]) -> str:
    expected = digest(value)
    if path.exists():
        if _read(path) != value:
            raise HealthError(f"immutable record collision: {path}")
    else:
        _atomic_write(path, value)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise HealthError(f"read-back digest mismatch for {path}")
    return expected


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HealthError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise HealthError("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_sha(value: str) -> None:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise HealthError(f"invalid commit SHA: {value!r}")


def _validate_summary(summary: dict[str, Any]) -> None:
    required = {
        "cadence",
        "conclusion",
        "obligations",
        "recorded_at",
        "run_id",
        "schema_version",
        "sha",
    }
    if set(summary) != required:
        raise HealthError("result summary shape is invalid")
    if summary["schema_version"] != SCHEMA_VERSION:
        raise HealthError("unsupported result summary schema")
    _validate_sha(summary["sha"])
    _timestamp(summary["recorded_at"])
    if summary["cadence"] not in set(CADENCE_BY_SCOPE.values()):
        raise HealthError("result cadence is unsupported")
    if not isinstance(summary["run_id"], str) or not summary["run_id"]:
        raise HealthError("result run_id must be a non-empty string")
    if summary["conclusion"] not in {PASS, "failure"}:
        raise HealthError("result conclusion must be success or failure")
    obligations = summary["obligations"]
    if not isinstance(obligations, list) or not obligations:
        raise HealthError("at least one obligation is required")
    if any(not isinstance(item, dict) or set(item) != {"id", "result"} for item in obligations):
        raise HealthError("obligation shape is invalid")
    ids = [item.get("id") for item in obligations if isinstance(item, dict)]
    if len(ids) != len(obligations) or len(ids) != len(set(ids)):
        raise HealthError("obligation IDs must be present and unique")
    if not all(isinstance(identifier, str) and identifier for identifier in ids):
        raise HealthError("obligation IDs must be non-empty strings")
    results = {item.get("result") for item in obligations}
    if not results <= {PASS, "failure"}:
        raise HealthError("obligation results must be success or failure")
    expected = PASS if results == {PASS} else "failure"
    if summary["conclusion"] != expected:
        raise HealthError("summary conclusion disagrees with obligation results")


def _load_state(root: Path) -> dict[str, Any] | None:
    path = root / "state.json"
    if not path.exists():
        return None
    state = _read(path)
    if set(state) != STATE_FIELDS or state["schema_version"] != SCHEMA_VERSION:
        raise HealthError("state shape or schema is invalid")
    return state


def _require_generation(state: dict[str, Any] | None, expected: int) -> None:
    actual = -1 if state is None else state["generation"]
    if actual != expected:
        raise HealthError(f"CAS conflict: expected generation {expected}, found {actual}")


def activate(
    root: Path,
    *,
    policy: dict[str, Any],
    first_sha: str,
    recorded_at: str,
) -> dict[str, Any]:
    """Create the one-time activation record and truthful not-measured boundary."""
    if _load_state(root) is not None or (root / "activation.json").exists():
        raise HealthError("main health is already activated")
    _validate_sha(first_sha)
    _timestamp(recorded_at)
    if policy != ACTIVATION_POLICY:
        raise HealthError("activation policy does not match the canonical contract")
    policy_digest = digest(policy)
    _write_immutable(root / "activation-policy.json", policy)
    activation = {
        "activated_at": recorded_at,
        "first_measured_sha": first_sha,
        "policy_digest": policy_digest,
        "prehistory_disposition": "not_measured",
        "schema_version": SCHEMA_VERSION,
    }
    activation_digest = _write_immutable(root / "activation.json", activation)
    state = {
        "activation_digest": activation_digest,
        "first_bad_sha": None,
        "generation": 0,
        "history_head": None,
        "incident_digest": None,
        "last_good_sha": None,
        "resolution_digest": None,
        "schema_version": SCHEMA_VERSION,
        "status": "not_measured",
        "updated_at": recorded_at,
    }
    _atomic_write(root / "state.json", state)
    return state


def _retain_result(root: Path, summary: dict[str, Any]) -> str:
    _validate_summary(summary)
    result_digest = digest(summary)
    _write_immutable(root / "results" / f"{result_digest}.json", summary)
    retention = {
        "backend": "main-health-state-branch",
        "read_back_sha256": result_digest,
        "result_digest": result_digest,
        "schema_version": SCHEMA_VERSION,
    }
    retention_digest = _write_immutable(root / "retention" / f"{result_digest}.json", retention)
    if _read(root / "retention" / f"{result_digest}.json")["result_digest"] != result_digest:
        raise HealthError("retention read-back did not bind the result")
    return retention_digest


def _append_history(
    root: Path,
    *,
    prior: dict[str, Any],
    summary: dict[str, Any],
    result_digest: str,
    retention_digest: str,
    status: str,
) -> tuple[dict[str, Any], str]:
    generation = prior["generation"] + 1
    entry = {
        "cadence": summary["cadence"],
        "generation": generation,
        "previous_digest": prior["history_head"],
        "recorded_at": summary["recorded_at"],
        "result_digest": result_digest,
        "resolution_digest": None,
        "retention_digest": retention_digest,
        "schema_version": SCHEMA_VERSION,
        "sha": summary["sha"],
        "status": status,
    }
    entry_digest = digest(entry)
    _write_immutable(root / "history" / f"{generation:08d}-{entry_digest}.json", entry)
    return entry, entry_digest


def ingest(
    root: Path,
    *,
    scope: str,
    summary: dict[str, Any],
    activation_policy: dict[str, Any] | None = None,
    expected_generation: int | None = None,
) -> dict[str, Any]:
    """Ingest a result; candidates are validated but never mutate global state."""
    _validate_summary(summary)
    expected_cadence = CADENCE_BY_SCOPE.get(scope)
    if summary["cadence"] != expected_cadence:
        raise HealthError(
            f"scope {scope!r} requires cadence {expected_cadence!r}, found {summary['cadence']!r}"
        )
    if scope == "candidate":
        return {
            "accepted": summary["conclusion"] == PASS,
            "mutated": False,
            "schema_version": SCHEMA_VERSION,
            "sha": summary["sha"],
        }
    if scope not in GLOBAL_SCOPES:
        raise HealthError(f"unsupported global scope: {scope!r}")
    state = _load_state(root)
    if expected_generation is not None:
        _require_generation(state, expected_generation)
    if state is None:
        if activation_policy is None:
            raise HealthError("first global result requires the activation policy")
        state = activate(
            root,
            policy=activation_policy,
            first_sha=summary["sha"],
            recorded_at=summary["recorded_at"],
        )
    elif _timestamp(summary["recorded_at"]) < _timestamp(state["updated_at"]):
        raise HealthError("result timestamp predates the current state")
    result_digest = digest(summary)
    retention_digest = _retain_result(root, summary)
    failed = summary["conclusion"] != PASS
    status = "red" if failed or state["status"] == "red" else "green"
    incident_digest = state["incident_digest"]
    first_bad_sha = state["first_bad_sha"]
    last_good_sha = state["last_good_sha"]
    if failed:
        failing = sorted(item["id"] for item in summary["obligations"] if item["result"] != PASS)
        if state["status"] != "red":
            incident = {
                "failing_obligations": failing,
                "first_bad_sha": summary["sha"],
                "opened_at": summary["recorded_at"],
                "result_digest": result_digest,
                "schema_version": SCHEMA_VERSION,
                "status": "open",
            }
            incident_digest = digest(incident)
            _write_immutable(root / "incidents" / f"{incident_digest}.json", incident)
            first_bad_sha = summary["sha"]
    elif status == "green":
        last_good_sha = summary["sha"]

    _, history_digest = _append_history(
        root,
        prior=state,
        summary=summary,
        result_digest=result_digest,
        retention_digest=retention_digest,
        status=status,
    )
    updated = {
        **state,
        "first_bad_sha": first_bad_sha,
        "generation": state["generation"] + 1,
        "history_head": history_digest,
        "incident_digest": incident_digest,
        "last_good_sha": last_good_sha,
        "status": status,
        "updated_at": summary["recorded_at"],
    }
    _atomic_write(root / "state.json", updated)
    if _read(root / "state.json") != updated:
        raise HealthError("state read-back mismatch")
    return updated


def _retained_passing_results(root: Path) -> set[tuple[str, str, str]]:
    """Return only passing results reached through validated retained history."""
    retained: set[tuple[str, str, str]] = set()
    for path in sorted((root / "history").glob("*.json")):
        entry = _read(path)
        result = _read(root / "results" / f"{entry['result_digest']}.json")
        if result["conclusion"] == PASS:
            retained.add((result["sha"], result["cadence"], entry["result_digest"]))
    return retained


def _github_changed_paths(pull: dict[str, Any], files: list[dict[str, Any]]) -> list[str]:
    changed_files = pull.get("changed_files")
    if (
        not isinstance(changed_files, int)
        or changed_files <= 0
        or changed_files > 3_000
        or len(files) != changed_files
    ):
        raise HealthError("GitHub repair file inventory is incomplete or exceeds 3,000 files")
    paths: list[str] = []
    for item in files:
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename:
            raise HealthError("GitHub repair file inventory contains an invalid filename")
        paths.append(filename)
        if item.get("status") == "renamed":
            previous = item.get("previous_filename")
            if not isinstance(previous, str) or not previous:
                raise HealthError("GitHub repair rename is missing its previous filename")
            paths.append(previous)
    if len(paths) != len(set(paths)):
        raise HealthError("GitHub repair changed-path inventory contains duplicates")
    return sorted(paths)


def github_approval_evidence(
    *,
    pull: dict[str, Any],
    review: dict[str, Any],
    reviews: list[dict[str, Any]],
    files: list[dict[str, Any]],
    head_commit: dict[str, Any],
    merge_commit: dict[str, Any],
    reviewer_permissions: dict[str, str],
    captured_at: str,
    repository: str,
    pull_request: str,
    issue: str,
    incident_digest: str,
) -> dict[str, Any]:
    """Normalize provider responses into exact repair-approval evidence."""
    latest: dict[str, dict[str, Any]] = {}
    for candidate in sorted(reviews, key=lambda item: (item.get("submitted_at") or "", item["id"])):
        login = candidate.get("user", {}).get("login")
        permission = reviewer_permissions.get(str(login).casefold(), "")
        if login and permission in AUTHORIZED_REVIEWER_PERMISSIONS:
            state = candidate.get("state")
            if state == "DISMISSED":
                latest.pop(login.casefold(), None)
            elif state in {"APPROVED", "CHANGES_REQUESTED"}:
                latest[login.casefold()] = candidate
    reviewer_login = review.get("user", {}).get("login", "")
    if latest.get(reviewer_login.casefold(), {}).get("id") != review.get("id"):
        raise HealthError("GitHub repair review has been superseded")
    if any(item.get("state") == "CHANGES_REQUESTED" for item in latest.values()):
        raise HealthError("GitHub repair pull request has current requested changes")
    if review.get("state") != "APPROVED":
        raise HealthError("GitHub repair review is not approved")
    if review.get("commit_id") != pull["head"]["sha"]:
        raise HealthError("GitHub repair review does not bind the current head")
    marker = f"Main-health repair authorization: {issue}\nIncident: {incident_digest}"
    if (review.get("body") or "").strip() != marker:
        raise HealthError("GitHub repair review does not bind the exact issue and incident")
    reviewer_permission = reviewer_permissions.get(reviewer_login.casefold(), "")
    if reviewer_permission not in AUTHORIZED_REVIEWER_PERMISSIONS:
        raise HealthError("GitHub repair reviewer does not have repository write authority")
    changed_paths = _github_changed_paths(pull, files)
    if _timestamp(captured_at) < _timestamp(review["submitted_at"]):
        raise HealthError("GitHub repair capture predates the approval decision")
    merge_proof = _github_merge_proof(
        pull=pull,
        head_commit=head_commit,
        merge_commit=merge_commit,
    )
    return {
        "admission": None,
        "admission_digest": None,
        "authorization_mode": "independent-review",
        "approval_id": str(review["id"]),
        "approval_provider": "github",
        "author": pull["user"]["login"],
        "author_id": str(pull["user"]["id"]),
        "base_sha": pull["base"]["sha"],
        "captured_at": captured_at,
        "changed_paths": changed_paths,
        "collaborators": None,
        "decision_at": review["submitted_at"],
        "incident_digest": incident_digest,
        "issue": issue,
        "manifest": None,
        "manifest_digest": None,
        "pending_invitations": None,
        "pull_request": pull_request,
        "repository": repository,
        "reviewer": review["user"]["login"],
        "reviewer_id": str(review["user"]["id"]),
        "reviewer_permission": reviewer_permission,
        "merge_gate": None,
        "merge_gate_digest": None,
        "schema_version": SCHEMA_VERSION,
        "state": review["state"],
        **merge_proof,
    }


def _github_merge_proof(
    *,
    pull: dict[str, Any],
    head_commit: dict[str, Any],
    merge_commit: dict[str, Any],
) -> dict[str, Any]:
    if not pull.get("merged") or not pull.get("merged_at") or not pull.get("merge_commit_sha"):
        raise HealthError("GitHub repair pull request is not merged")
    base_sha = pull.get("base", {}).get("sha")
    head_sha = pull.get("head", {}).get("sha")
    merge_sha = pull["merge_commit_sha"]
    if head_commit.get("sha") != head_sha or merge_commit.get("sha") != merge_sha:
        raise HealthError("GitHub repair commit responses do not bind the pull request")
    try:
        reviewed_tree_sha = head_commit["tree"]["sha"]
        merge_tree_sha = merge_commit["tree"]["sha"]
        merge_parent_shas = [parent["sha"] for parent in merge_commit["parents"]]
    except (KeyError, TypeError) as exc:
        raise HealthError("GitHub repair merge proof is malformed") from exc
    if (
        not isinstance(head_sha, str)
        or not isinstance(base_sha, str)
        or not isinstance(merge_sha, str)
        or merge_parent_shas != [base_sha, head_sha]
        or reviewed_tree_sha != merge_tree_sha
    ):
        raise HealthError("GitHub repair merge does not preserve the exact base and reviewed head")
    _validate_sha(base_sha)
    _validate_sha(head_sha)
    _validate_sha(merge_sha)
    _validate_sha(reviewed_tree_sha)
    _validate_sha(merge_tree_sha)
    for parent_sha in merge_parent_shas:
        _validate_sha(parent_sha)
    return {
        "head_sha": head_sha,
        "merge_commit_sha": merge_sha,
        "merge_parent_shas": merge_parent_shas,
        "merge_tree_sha": merge_tree_sha,
        "reviewed_tree_sha": reviewed_tree_sha,
    }


def _github_collaboration_inventory(
    collaborators: list[dict[str, Any]],
    invitations: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    normalized_collaborators: list[dict[str, str]] = []
    for item in collaborators:
        login = item.get("login")
        provider_permissions = item.get("permissions") or {}
        if provider_permissions.get("admin") is True:
            collaborator_permission: Any = "admin"
        elif provider_permissions.get("maintain") is True:
            collaborator_permission = "maintain"
        elif provider_permissions.get("push") is True:
            collaborator_permission = "write"
        else:
            collaborator_permission = item.get("role_name")
        if collaborator_permission == "push":
            collaborator_permission = "write"
        if not isinstance(login, str) or not login or not isinstance(collaborator_permission, str):
            raise HealthError("GitHub collaborator inventory is malformed")
        normalized_collaborators.append(
            {
                "id": str(item.get("id", "")),
                "login": login,
                "permission": collaborator_permission,
            }
        )
    normalized_collaborators.sort(key=lambda item: item["login"].casefold())
    if any(not item["id"] for item in normalized_collaborators) or len(
        {item["login"].casefold() for item in normalized_collaborators}
    ) != len(normalized_collaborators):
        raise HealthError("GitHub collaborator inventory is incomplete or duplicated")

    normalized_invitations: list[dict[str, str]] = []
    for item in invitations:
        invitee = item.get("invitee") or {}
        identity = invitee.get("login") or item.get("email")
        invitation_permission = item.get("permissions")
        if invitation_permission == "push":
            invitation_permission = "write"
        if (
            not isinstance(identity, str)
            or not identity
            or not isinstance(invitation_permission, str)
        ):
            raise HealthError("GitHub collaborator invitation inventory is malformed")
        normalized_invitations.append(
            {
                "id": str(item.get("id", "")),
                "invitee": identity,
                "permission": invitation_permission,
            }
        )
    normalized_invitations.sort(key=lambda item: (item["invitee"].casefold(), item["id"]))
    if any(not item["id"] for item in normalized_invitations) or len(
        {item["id"] for item in normalized_invitations}
    ) != len(normalized_invitations):
        raise HealthError("GitHub collaborator invitation inventory is incomplete or duplicated")
    return normalized_collaborators, normalized_invitations


def github_owner_emergency_evidence(
    *,
    pull: dict[str, Any],
    files: list[dict[str, Any]],
    head_commit: dict[str, Any],
    merge_commit: dict[str, Any],
    manifest: dict[str, Any],
    admission: dict[str, Any],
    merge_gate: dict[str, Any],
    collaborators: list[dict[str, Any]],
    invitations: list[dict[str, Any]],
    captured_at: str,
    owner_permission: str,
    repository: str,
    pull_request: str,
    issue: str,
    incident_digest: str,
) -> dict[str, Any]:
    """Normalize a truthful single-maintainer owner-emergency decision."""
    _validate_owner_manifest(manifest)
    repository_owner = repository.split("/", 1)[0]
    author = pull.get("user", {}).get("login", "")
    if author.casefold() != repository_owner.casefold() or owner_permission != "admin":
        raise HealthError("owner emergency requires the repository owner with admin permission")
    collaborator_inventory, invitation_inventory = _github_collaboration_inventory(
        collaborators, invitations
    )
    if any(
        item["login"].casefold() != repository_owner.casefold()
        and item["permission"] in AUTHORIZED_REVIEWER_PERMISSIONS
        for item in collaborator_inventory
    ) or any(
        item["permission"] in AUTHORIZED_REVIEWER_PERMISSIONS for item in invitation_inventory
    ):
        raise HealthError("owner emergency requires no eligible independent collaborator")
    if manifest["collaboration_digest"] != digest(
        {
            "collaborators": collaborator_inventory,
            "pending_invitations": invitation_inventory,
        }
    ):
        raise HealthError("owner emergency collaborator inventory changed since admission")
    marker = f"Main-health owner emergency: {issue}\nIncident: {incident_digest}"
    if (pull.get("body") or "").count(marker) != 1:
        raise HealthError("owner-emergency pull request does not bind the exact issue and incident")
    changed_paths = _github_changed_paths(pull, files)
    if (
        manifest["allowed_paths"] != changed_paths
        or manifest["base_sha"] != pull.get("base", {}).get("sha")
        or manifest["incident_digest"] != incident_digest
        or manifest["issue"] != issue
        or str(manifest["pull_request"]) != pull_request
        or manifest["repository"] != repository
    ):
        raise HealthError("owner-emergency manifest disagrees with provider state")
    admission_payload = _validate_comment_attestation(admission, "owner admission")
    expected_admission_fields = {
        "authorization_mode",
        "base_sha",
        "changed_paths",
        "checked_at",
        "collaboration_digest",
        "collaborators",
        "head_sha",
        "incident_digest",
        "issue",
        "manifest_digest",
        "main_health_ruleset",
        "main_health_ruleset_digest",
        "main_health_ruleset_id",
        "pending_invitations",
        "protection_ruleset",
        "protection_ruleset_digest",
        "protection_ruleset_id",
        "pull_request",
        "repository",
        "schema_version",
        "status",
    }
    if (
        set(admission_payload) != expected_admission_fields
        or admission_payload["schema_version"] != SCHEMA_VERSION
        or admission_payload["status"] != "repair-candidate"
        or admission_payload["authorization_mode"] != "single-maintainer-owner-emergency"
        or admission_payload["base_sha"] != pull["base"]["sha"]
        or admission_payload["changed_paths"] != changed_paths
        or admission_payload["collaboration_digest"] != manifest["collaboration_digest"]
        or admission_payload["collaborators"] != collaborator_inventory
        or admission_payload["head_sha"] != pull["head"]["sha"]
        or admission_payload["incident_digest"] != incident_digest
        or admission_payload["issue"] != issue
        or admission_payload["manifest_digest"] != digest(manifest)
        or admission_payload["pending_invitations"] != invitation_inventory
        or admission_payload["pull_request"] != pull_request
        or admission_payload["repository"] != repository
        or admission["comment_author"].casefold() != repository_owner.casefold()
    ):
        raise HealthError("owner emergency admission does not bind provider state")
    protection_ruleset = admission_payload.get("protection_ruleset")
    main_health_ruleset = admission_payload.get("main_health_ruleset")
    if not isinstance(protection_ruleset, dict) or not isinstance(main_health_ruleset, dict):
        raise HealthError("owner emergency admission rulesets are malformed")
    _validate_owner_bypass_rulesets(protection_ruleset, main_health_ruleset)
    expected_gate_fields = {
        "admission_comment_id",
        "admission_digest",
        "bypass_actor",
        "head_sha",
        "main_health_ruleset_digest",
        "main_health_ruleset_id",
        "merge_commit_sha",
        "merged_at",
        "merged_by",
        "merged_by_id",
        "protection_ruleset_digest",
        "protection_ruleset_id",
        "pull_request",
        "repository",
        "schema_version",
    }
    admission_digest = digest(admission)
    merged_by = pull.get("merged_by") or {}
    if (
        set(merge_gate) != expected_gate_fields
        or merge_gate["schema_version"] != SCHEMA_VERSION
        or merge_gate["admission_comment_id"] != admission["comment_id"]
        or merge_gate["admission_digest"] != admission_digest
        or merge_gate["bypass_actor"] != OWNER_BYPASS_ACTOR
        or merge_gate["head_sha"] != pull["head"]["sha"]
        or merge_gate["main_health_ruleset_digest"] != digest(main_health_ruleset)
        or merge_gate["main_health_ruleset_id"] != admission_payload["main_health_ruleset_id"]
        or merge_gate["merge_commit_sha"] != pull["merge_commit_sha"]
        or merge_gate["merged_at"] != pull["merged_at"]
        or merge_gate["merged_by"].casefold() != repository_owner.casefold()
        or merge_gate["merged_by"] != merged_by.get("login")
        or merge_gate["merged_by_id"] != str(merged_by.get("id", ""))
        or merge_gate["protection_ruleset_digest"] != digest(protection_ruleset)
        or merge_gate["protection_ruleset_id"] != admission_payload["protection_ruleset_id"]
        or merge_gate["pull_request"] != pull_request
        or merge_gate["repository"] != repository
        or admission_payload["main_health_ruleset_digest"] != digest(main_health_ruleset)
        or admission_payload["protection_ruleset_digest"] != digest(protection_ruleset)
    ):
        raise HealthError("owner emergency merge-gate evidence is invalid")
    admission_at = _timestamp(admission_payload["checked_at"])
    admitted_at = _timestamp(admission["comment_created_at"])
    merged_at = _timestamp(pull["merged_at"])
    captured = _timestamp(captured_at)
    if (
        admission_at > admitted_at
        or admitted_at > merged_at
        or (merged_at - admitted_at).total_seconds() > OWNER_ADMISSION_MAX_AGE_SECONDS
        or merged_at > captured
    ):
        raise HealthError("owner emergency admission and capture do not bracket the merge")
    if merged_at > _timestamp(manifest["expires_at"]):
        raise HealthError("owner emergency merge occurred after manifest expiry")
    merge_proof = _github_merge_proof(
        pull=pull,
        head_commit=head_commit,
        merge_commit=merge_commit,
    )
    return {
        "admission": admission,
        "admission_digest": digest(admission),
        "authorization_mode": "single-maintainer-owner-emergency",
        "approval_id": f"owner-emergency:{pull_request}:{merge_proof['merge_commit_sha']}",
        "approval_provider": "github",
        "author": author,
        "author_id": str(pull["user"]["id"]),
        "base_sha": pull["base"]["sha"],
        "captured_at": captured_at,
        "changed_paths": changed_paths,
        "collaborators": collaborator_inventory,
        "decision_at": pull["merged_at"],
        "incident_digest": incident_digest,
        "issue": issue,
        "manifest": manifest,
        "manifest_digest": digest(manifest),
        "pending_invitations": invitation_inventory,
        "pull_request": pull_request,
        "repository": repository,
        "reviewer": author,
        "reviewer_id": str(pull["user"]["id"]),
        "reviewer_permission": owner_permission,
        "merge_gate": merge_gate,
        "merge_gate_digest": digest(merge_gate),
        "schema_version": SCHEMA_VERSION,
        "state": "OWNER_EMERGENCY",
        **merge_proof,
    }


def _github_request(
    path: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None if payload is None else canonical_bytes(payload)
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise HealthError(f"GitHub approval capture failed: {exc}") from exc


def _github_get(path: str, token: str) -> Any:
    return _github_request(path, token)


def _github_provider_now(token: str) -> datetime:
    request = urllib.request.Request(
        "https://api.github.com/rate_limit",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            json.load(response)
            provider_date = response.headers.get("Date")
        parsed = email.utils.parsedate_to_datetime(provider_date)
    except (
        TypeError,
        ValueError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise HealthError(f"GitHub provider time capture failed: {exc}") from exc
    if parsed.tzinfo is None:
        raise HealthError("GitHub provider time response has no timezone")
    return parsed.astimezone(UTC)


def _github_provider_timestamp(token: str) -> str:
    return _github_provider_now(token).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def github_provider_clock(token: str) -> dict[str, Any]:
    provider_now = _github_provider_now(token).replace(microsecond=0)
    return {
        "epoch": int(provider_now.timestamp()),
        "timestamp": provider_now.isoformat().replace("+00:00", "Z"),
    }


def _validate_github_check_run(
    check_run: dict[str, Any],
    *,
    app_id: int,
    app_slug: str,
    conclusion: str | None,
    details_url: str | None,
    external_id: str | None,
    head_sha: str,
    name: str,
    completed_at: str | None = None,
    output_summary: str | None = None,
    output_title: str | None = None,
) -> None:
    app = check_run.get("app")
    if not (
        type(check_run.get("id")) is int
        and check_run["id"] > 0
        and check_run.get("head_sha") == head_sha
        and check_run.get("name") == name
        and check_run.get("status") == "completed"
        and isinstance(app, dict)
        and app.get("id") == app_id
        and app.get("slug") == app_slug
    ):
        raise HealthError("GitHub check run identity is not provider-bound")
    if conclusion is not None and check_run.get("conclusion") != conclusion:
        raise HealthError("GitHub check run conclusion is not provider-bound")
    if details_url is not None and check_run.get("details_url") != details_url:
        raise HealthError("GitHub check run details URL is not provider-bound")
    if external_id is not None and check_run.get("external_id") != external_id:
        raise HealthError("GitHub check run external ID is not provider-bound")
    if completed_at is not None:
        actual_completed_at = check_run.get("completed_at")
        if not isinstance(actual_completed_at, str) or (
            _timestamp(actual_completed_at) != _timestamp(completed_at)
        ):
            raise HealthError("GitHub check run completion time is not provider-bound")
    output = check_run.get("output")
    if output_title is not None and (
        not isinstance(output, dict) or output.get("title") != output_title
    ):
        raise HealthError("GitHub check run output title is not provider-bound")
    if output_summary is not None and (
        not isinstance(output, dict) or output.get("summary") != output_summary
    ):
        raise HealthError("GitHub check run output summary is not provider-bound")


def _github_check_runs(
    *, repository: str, head_sha: str, name: str, app_id: int, token: str
) -> list[dict[str, Any]]:
    _validate_sha(head_sha)
    query = urllib.parse.urlencode({"check_name": name, "filter": "all"})
    runs: list[dict[str, Any]] = []
    page = 1
    while True:
        response = _github_get(
            f"repos/{repository}/commits/{head_sha}/check-runs?{query}&per_page=100&page={page}",
            token,
        )
        if not isinstance(response, dict):
            raise HealthError("GitHub check-run inventory is malformed")
        batch = response.get("check_runs")
        if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
            raise HealthError("GitHub check-run inventory is malformed")
        for item in batch:
            app = item.get("app")
            if not isinstance(app, dict):
                raise HealthError("GitHub check-run inventory is malformed")
            if item.get("name") == name and app.get("id") == app_id:
                runs.append(item)
        if len(batch) < 100:
            return runs
        page += 1


def _github_check_payload(
    *,
    completed_at: str,
    conclusion: str,
    details_url: str,
    external_id: str,
    name: str,
    output_summary: str,
    output_title: str,
) -> dict[str, Any]:
    if conclusion not in {"failure", "success"}:
        raise HealthError("GitHub check conclusion must be failure or success")
    if not all((name, external_id, details_url, output_title, output_summary)):
        raise HealthError("GitHub check fields must be non-empty")
    _timestamp(completed_at)
    return {
        "completed_at": completed_at,
        "conclusion": conclusion,
        "details_url": details_url,
        "external_id": external_id,
        "name": name,
        "output": {"summary": output_summary, "title": output_title},
        "status": "completed",
    }


def set_github_check_run(
    *,
    app_id: int,
    app_slug: str,
    conclusion: str,
    details_url: str,
    external_id: str,
    head_sha: str,
    name: str,
    output_summary: str,
    output_title: str,
    repository: str,
    token: str,
) -> dict[str, Any]:
    """Create one App-owned check per head/name and mutate that exact check thereafter."""
    if app_id <= 0 or not app_slug:
        raise HealthError("GitHub App identity is invalid")
    completed_at = _github_provider_timestamp(token)
    runs = _github_check_runs(
        repository=repository,
        head_sha=head_sha,
        name=name,
        app_id=app_id,
        token=token,
    )
    ordered_runs: list[tuple[int, dict[str, Any]]] = []
    seen_ids: set[int] = set()
    for check_run in runs:
        _validate_github_check_run(
            check_run,
            app_id=app_id,
            app_slug=app_slug,
            conclusion=None,
            details_url=None,
            external_id=None,
            head_sha=head_sha,
            name=name,
        )
        check_run_id = check_run["id"]
        if check_run_id in seen_ids:
            raise HealthError("GitHub check-run inventory contains a duplicate ID")
        seen_ids.add(check_run_id)
        ordered_runs.append((check_run_id, check_run))
    ordered_runs.sort(key=lambda item: item[0])
    runs = [check_run for _, check_run in ordered_runs]
    canonical = runs[-1] if runs else None
    for duplicate in runs[:-1]:
        assert canonical is not None
        duplicate_id = duplicate.get("id")
        if type(duplicate_id) is not int or duplicate_id <= 0:
            raise HealthError("GitHub duplicate check run has an invalid ID")
        superseded_name = f"{name} [superseded {duplicate_id}]"
        superseded_external_id = f"superseded:{duplicate_id}"
        superseded_title = "Superseded check run"
        superseded_summary = f"Replaced by canonical check run {canonical['id']}."
        payload = _github_check_payload(
            completed_at=completed_at,
            conclusion="failure",
            details_url=details_url,
            external_id=superseded_external_id,
            name=superseded_name,
            output_summary=superseded_summary,
            output_title=superseded_title,
        )
        response = _github_request(
            f"repos/{repository}/check-runs/{duplicate_id}",
            token,
            method="PATCH",
            payload=payload,
        )
        if not isinstance(response, dict):
            raise HealthError("GitHub duplicate check quarantine response is malformed")
        _validate_github_check_run(
            response,
            app_id=app_id,
            app_slug=app_slug,
            conclusion="failure",
            details_url=details_url,
            external_id=superseded_external_id,
            head_sha=head_sha,
            name=superseded_name,
            completed_at=completed_at,
            output_summary=superseded_summary,
            output_title=superseded_title,
        )

    payload = _github_check_payload(
        completed_at=completed_at,
        conclusion=conclusion,
        details_url=details_url,
        external_id=external_id,
        name=name,
        output_summary=output_summary,
        output_title=output_title,
    )
    if canonical is None:
        payload = {"head_sha": head_sha, **payload}
        response = _github_request(
            f"repos/{repository}/check-runs",
            token,
            method="POST",
            payload=payload,
        )
    else:
        check_run_id = canonical.get("id")
        if type(check_run_id) is not int or check_run_id <= 0:
            raise HealthError("GitHub canonical check run has an invalid ID")
        response = _github_request(
            f"repos/{repository}/check-runs/{check_run_id}",
            token,
            method="PATCH",
            payload=payload,
        )
    if not isinstance(response, dict):
        raise HealthError("GitHub check publication response is malformed")
    _validate_github_check_run(
        response,
        app_id=app_id,
        app_slug=app_slug,
        conclusion=conclusion,
        details_url=details_url,
        external_id=external_id,
        head_sha=head_sha,
        name=name,
        completed_at=completed_at,
        output_summary=output_summary,
        output_title=output_title,
    )
    return response


def get_github_check_run(
    *,
    app_id: int,
    app_slug: str,
    head_sha: str,
    name: str,
    repository: str,
    token: str,
) -> dict[str, Any]:
    runs = _github_check_runs(
        repository=repository,
        head_sha=head_sha,
        name=name,
        app_id=app_id,
        token=token,
    )
    if len(runs) != 1:
        raise HealthError("GitHub App must own exactly one canonical check run")
    check_run = runs[0]
    _validate_github_check_run(
        check_run,
        app_id=app_id,
        app_slug=app_slug,
        conclusion=None,
        details_url=None,
        external_id=None,
        head_sha=head_sha,
        name=name,
    )
    return check_run


def expire_github_check_run(
    *,
    app_id: int,
    app_slug: str,
    check_run_id: int,
    details_url: str,
    external_id: str,
    head_sha: str,
    name: str,
    output_summary: str,
    output_title: str,
    repository: str,
    token: str,
) -> dict[str, Any]:
    """Fail an exact lease identity; a newer external ID is an explicit no-op."""
    current = _github_get(f"repos/{repository}/check-runs/{check_run_id}", token)
    if not isinstance(current, dict):
        raise HealthError("GitHub check expiry lookup is malformed")
    _validate_github_check_run(
        current,
        app_id=app_id,
        app_slug=app_slug,
        conclusion=None,
        details_url=None,
        external_id=None,
        head_sha=head_sha,
        name=name,
    )
    if current.get("external_id") != external_id:
        return {
            "check_run_id": check_run_id,
            "external_id": current.get("external_id"),
            "state": "stale",
        }
    if current.get("conclusion") == "failure":
        return {
            "check_run_id": check_run_id,
            "external_id": external_id,
            "state": "already-failed",
        }
    completed_at = _github_provider_timestamp(token)
    payload = _github_check_payload(
        completed_at=completed_at,
        conclusion="failure",
        details_url=details_url,
        external_id=external_id,
        name=name,
        output_summary=output_summary,
        output_title=output_title,
    )
    del payload["external_id"]
    response = _github_request(
        f"repos/{repository}/check-runs/{check_run_id}",
        token,
        method="PATCH",
        payload=payload,
    )
    if not isinstance(response, dict):
        raise HealthError("GitHub check expiry response is malformed")
    _validate_github_check_run(
        response,
        app_id=app_id,
        app_slug=app_slug,
        conclusion="failure",
        details_url=details_url,
        external_id=external_id,
        head_sha=head_sha,
        name=name,
        completed_at=completed_at,
        output_summary=output_summary,
        output_title=output_title,
    )
    return {"check_run": response, "state": "expired"}


def _github_graphql(query: str, variables: dict[str, Any], token: str) -> dict[str, Any]:
    response = _github_request(
        "graphql",
        token,
        method="POST",
        payload={"query": query, "variables": variables},
    )
    if not isinstance(response, dict) or response.get("errors"):
        raise HealthError("GitHub GraphQL merge request failed")
    data = response.get("data")
    if not isinstance(data, dict):
        raise HealthError("GitHub GraphQL merge response is malformed")
    return data


def _github_list(path: str, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        batch = _github_get(f"{path}{separator}per_page=100&page={page}", token)
        if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
            raise HealthError("GitHub paginated response is malformed")
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def _github_stable_collaboration_snapshot(
    repository: str, token: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    invitations_before = _github_list(f"repos/{repository}/invitations", token)
    collaborators_before = _github_list(f"repos/{repository}/collaborators?affiliation=all", token)
    invitations_after = _github_list(f"repos/{repository}/invitations", token)
    collaborators_after = _github_list(f"repos/{repository}/collaborators?affiliation=all", token)
    before = _github_collaboration_inventory(collaborators_before, invitations_before)
    after = _github_collaboration_inventory(collaborators_after, invitations_after)
    if before != after:
        raise HealthError("GitHub collaboration inventory changed during capture")
    return collaborators_after, invitations_after


def _ruleset_configuration(ruleset: dict[str, Any]) -> dict[str, Any]:
    required = {"bypass_actors", "conditions", "enforcement", "name", "rules", "target"}
    if not required <= set(ruleset) or not isinstance(ruleset.get("rules"), list):
        raise HealthError("GitHub main ruleset response is malformed")
    return {field: ruleset[field] for field in sorted(required)}


def _ruleset_status_checks(configuration: dict[str, Any]) -> list[dict[str, Any]]:
    status_rules = [
        rule
        for rule in configuration.get("rules", [])
        if rule.get("type") == "required_status_checks"
    ]
    if len(status_rules) != 1:
        raise HealthError("GitHub ruleset must contain exactly one required-status rule")
    parameters = status_rules[0].get("parameters")
    if not isinstance(parameters, dict):
        raise HealthError("GitHub required-status rule parameters are malformed")
    checks = parameters.get("required_status_checks")
    if not isinstance(checks, list) or not all(isinstance(check, dict) for check in checks):
        raise HealthError("GitHub required-status checks are malformed")
    if (
        parameters.get("strict_required_status_checks_policy") is not True
        or parameters.get("do_not_enforce_on_create") is not False
    ):
        raise HealthError("GitHub required-status strictness is malformed")
    return checks


def _validate_owner_bypass_rulesets(
    protection: dict[str, Any], main_health: dict[str, Any]
) -> None:
    expected_conditions = {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}}
    if (
        protection.get("name") != "Protect main"
        or protection.get("target") != "branch"
        or protection.get("enforcement") != "active"
        or protection.get("bypass_actors") != []
        or protection.get("conditions") != expected_conditions
    ):
        raise HealthError("GitHub core protection ruleset is not the governed configuration")
    protection_rules = protection.get("rules")
    if not isinstance(protection_rules, list):
        raise HealthError("GitHub core protection rules are malformed")
    rules_by_type = {rule.get("type"): rule for rule in protection_rules if isinstance(rule, dict)}
    if (
        len(protection_rules) != 4
        or len(rules_by_type) != 4
        or rules_by_type.get("deletion") != {"type": "deletion"}
        or rules_by_type.get("non_fast_forward") != {"type": "non_fast_forward"}
        or rules_by_type.get("pull_request")
        != {"parameters": CORE_PULL_REQUEST_PARAMETERS, "type": "pull_request"}
        or "required_status_checks" not in rules_by_type
    ):
        raise HealthError("GitHub core branch and pull-request protections are not governed")
    protection_checks = _ruleset_status_checks(protection)
    if (
        len(protection_checks) != len(CORE_REQUIRED_CONTEXTS)
        or {check.get("context") for check in protection_checks} != CORE_REQUIRED_CONTEXTS
        or any(
            check.get("integration_id") != GITHUB_ACTIONS_INTEGRATION_ID
            for check in protection_checks
        )
    ):
        raise HealthError("GitHub core required checks are not the governed configuration")
    if (
        main_health.get("name") != "Protect main health admission"
        or main_health.get("target") != "branch"
        or main_health.get("enforcement") != "active"
        or main_health.get("bypass_actors") != [OWNER_BYPASS_ACTOR]
        or main_health.get("conditions") != expected_conditions
        or len(main_health.get("rules", [])) != 1
        or _ruleset_status_checks(main_health)
        != [
            {
                "context": MAIN_HEALTH_CONTEXT,
                "integration_id": MAIN_HEALTH_PUBLISHER_INTEGRATION_ID,
            }
        ]
    ):
        raise HealthError("GitHub main-health bypass ruleset is not the governed configuration")


def _github_manifest(repository: str, head_sha: str, token: str) -> dict[str, Any]:
    response = _github_get(
        f"repos/{repository}/contents/docs/status/main-health-owner-emergency.json?ref={head_sha}",
        token,
    )
    try:
        manifest = json.loads(base64.b64decode(response["content"], validate=False))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HealthError("GitHub owner-emergency manifest response is malformed") from exc
    if not isinstance(manifest, dict):
        raise HealthError("GitHub owner-emergency manifest is not a JSON object")
    return manifest


def _provider_artifact_body(kind: str, artifact: dict[str, Any]) -> str:
    return (
        f"Metriplane main-health {kind}\n"
        f"Digest: {digest(artifact)}\n\n"
        f"{canonical_bytes(artifact).decode().rstrip()}"
    )


def _github_comment_attestation(
    *,
    artifact: dict[str, Any],
    comment: dict[str, Any],
    kind: str,
    repository: str,
    pull_request: str,
) -> dict[str, Any]:
    expected_body = _provider_artifact_body(kind, artifact)
    issue_suffix = f"/repos/{repository}/issues/{pull_request}"
    created_at = comment.get("created_at")
    updated_at = comment.get("updated_at")
    author = comment.get("user", {}).get("login")
    author_id = comment.get("user", {}).get("id")
    if (
        comment.get("body") != expected_body
        or not str(comment.get("issue_url", "")).endswith(issue_suffix)
        or not isinstance(created_at, str)
        or not isinstance(updated_at, str)
        or created_at != updated_at
        or not isinstance(author, str)
        or not author
        or author_id is None
        or not str(comment.get("id", "")).isdigit()
    ):
        raise HealthError(f"GitHub {kind} comment is malformed, edited, or misplaced")
    _timestamp(created_at)
    return {
        "artifact": artifact,
        "artifact_digest": digest(artifact),
        "comment_author": author,
        "comment_author_id": str(author_id),
        "comment_created_at": created_at,
        "comment_id": str(comment["id"]),
        "comment_updated_at": updated_at,
        "provider": "github",
        "schema_version": SCHEMA_VERSION,
    }


def _post_github_artifact(
    *,
    artifact: dict[str, Any],
    kind: str,
    repository: str,
    pull_request: str,
    token: str,
) -> dict[str, Any]:
    comment = _github_request(
        f"repos/{repository}/issues/{pull_request}/comments",
        token,
        method="POST",
        payload={"body": _provider_artifact_body(kind, artifact)},
    )
    if not isinstance(comment, dict):
        raise HealthError(f"GitHub {kind} comment response is malformed")
    return _github_comment_attestation(
        artifact=artifact,
        comment=comment,
        kind=kind,
        repository=repository,
        pull_request=pull_request,
    )


def _refetch_github_artifact(
    *,
    retained: dict[str, Any],
    kind: str,
    repository: str,
    pull_request: str,
    token: str,
) -> dict[str, Any]:
    comment_id = retained.get("comment_id")
    if not isinstance(comment_id, str) or not comment_id.isdigit():
        raise HealthError(f"retained GitHub {kind} comment ID is invalid")
    comment = _github_get(f"repos/{repository}/issues/comments/{comment_id}", token)
    artifact = retained.get("artifact")
    if not isinstance(comment, dict) or not isinstance(artifact, dict):
        raise HealthError(f"retained GitHub {kind} attestation is malformed")
    current = _github_comment_attestation(
        artifact=artifact,
        comment=comment,
        kind=kind,
        repository=repository,
        pull_request=pull_request,
    )
    if current != retained:
        raise HealthError(f"retained GitHub {kind} attestation is stale")
    return current


def _validate_comment_attestation(attestation: dict[str, Any], kind: str) -> dict[str, Any]:
    artifact = attestation.get("artifact")
    if (
        set(attestation)
        != {
            "artifact",
            "artifact_digest",
            "comment_author",
            "comment_author_id",
            "comment_created_at",
            "comment_id",
            "comment_updated_at",
            "provider",
            "schema_version",
        }
        or attestation.get("schema_version") != SCHEMA_VERSION
        or attestation.get("provider") != "github"
        or not isinstance(artifact, dict)
        or attestation.get("artifact_digest") != digest(artifact)
        or not isinstance(attestation.get("comment_author"), str)
        or not attestation["comment_author"]
        or not isinstance(attestation.get("comment_author_id"), str)
        or not attestation["comment_author_id"]
        or not isinstance(attestation.get("comment_id"), str)
        or not attestation["comment_id"].isdigit()
        or attestation.get("comment_created_at") != attestation.get("comment_updated_at")
        or not isinstance(attestation.get("comment_created_at"), str)
    ):
        raise HealthError(f"owner-emergency {kind} attestation is invalid")
    _timestamp(attestation["comment_created_at"])
    return artifact


def capture_github_approval(
    *,
    repository: str,
    pull_request: str,
    review_id: str,
    issue: str,
    incident_digest: str,
    token: str,
) -> dict[str, Any]:
    """Fetch exact provider state for one GitHub repair review."""
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise HealthError("invalid GitHub repository identity")
    if not pull_request.isdigit() or not review_id.isdigit():
        raise HealthError("GitHub pull request and review IDs must be numeric")
    if not re.fullmatch(r"[0-9a-f]{64}", incident_digest):
        raise HealthError("invalid main-health incident digest")
    pull = _github_get(f"repos/{repository}/pulls/{pull_request}", token)
    reviews: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _github_get(
            f"repos/{repository}/pulls/{pull_request}/reviews?per_page=100&page={page}",
            token,
        )
        if not isinstance(batch, list):
            raise HealthError("GitHub repair review response is not an array")
        reviews.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    review = next((item for item in reviews if str(item.get("id")) == review_id), None)
    files: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _github_get(
            f"repos/{repository}/pulls/{pull_request}/files?per_page=100&page={page}",
            token,
        )
        if not isinstance(batch, list):
            raise HealthError("GitHub repair file response is not an array")
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    if not isinstance(pull, dict) or not isinstance(review, dict):
        raise HealthError("GitHub repair approval responses are malformed")
    head_sha = pull.get("head", {}).get("sha", "")
    merge_sha = pull.get("merge_commit_sha", "")
    head_commit = _github_get(f"repos/{repository}/git/commits/{head_sha}", token)
    merge_commit = _github_get(f"repos/{repository}/git/commits/{merge_sha}", token)
    reviewer_permissions: dict[str, str] = {}
    reviewer_logins = sorted(
        {
            item.get("user", {}).get("login", "")
            for item in reviews
            if item.get("user", {}).get("login")
        },
        key=str.casefold,
    )
    for login in reviewer_logins:
        permission = _github_get(
            f"repos/{repository}/collaborators/{login}/permission",
            token,
        )
        if not isinstance(permission, dict):
            raise HealthError("GitHub repair reviewer permission response is malformed")
        reviewer_permissions[login.casefold()] = str(permission.get("permission", ""))
    if not all(isinstance(item, dict) for item in (head_commit, merge_commit)):
        raise HealthError("GitHub repair merge or permission responses are malformed")
    return github_approval_evidence(
        pull=pull,
        review=review,
        reviews=reviews,
        files=files,
        head_commit=head_commit,
        merge_commit=merge_commit,
        reviewer_permissions=reviewer_permissions,
        captured_at=_github_provider_timestamp(token),
        repository=repository,
        pull_request=pull_request,
        issue=issue,
        incident_digest=incident_digest,
    )


def capture_github_owner_admission(
    *,
    root: Path,
    repository: str,
    pull_request: str,
    issue: str,
    incident_digest: str,
    expected_head_sha: str,
    protection_ruleset_id: str,
    main_health_ruleset_id: str,
    token: str,
) -> dict[str, Any]:
    """Fetch live owner-emergency state and anchor it before merge on GitHub."""
    if (
        not re.fullmatch(r"[^/\s]+/[^/\s]+", repository)
        or not pull_request.isdigit()
        or not re.fullmatch(r"[0-9a-f]{64}", incident_digest)
        or not protection_ruleset_id.isdigit()
        or not main_health_ruleset_id.isdigit()
    ):
        raise HealthError("invalid owner-admission provider identity")
    _validate_sha(expected_head_sha)
    validate_git_history(root)
    pull = _github_get(f"repos/{repository}/pulls/{pull_request}", token)
    if not isinstance(pull, dict) or pull.get("merged"):
        raise HealthError("owner admission requires an unmerged GitHub pull request")
    head_sha = pull.get("head", {}).get("sha", "")
    if head_sha != expected_head_sha:
        raise HealthError("owner admission does not bind the current pull request head")
    files = _github_list(f"repos/{repository}/pulls/{pull_request}/files", token)
    collaborators, invitations = _github_stable_collaboration_snapshot(repository, token)
    manifest = _github_manifest(repository, head_sha, token)
    author = pull.get("user", {}).get("login", "")
    permission = _github_get(f"repos/{repository}/collaborators/{author}/permission", token)
    protection_response = _github_get(f"repos/{repository}/rulesets/{protection_ruleset_id}", token)
    main_health_response = _github_get(
        f"repos/{repository}/rulesets/{main_health_ruleset_id}", token
    )
    if not all(
        isinstance(item, dict) for item in (permission, protection_response, main_health_response)
    ):
        raise HealthError("GitHub owner admission permission or ruleset response is malformed")
    repository_owner = repository.split("/", 1)[0]
    if author.casefold() != repository_owner.casefold() or permission.get("permission") != "admin":
        raise HealthError("owner admission requires the repository owner with admin permission")
    admission = validate_owner_emergency_candidate(
        root,
        manifest=manifest,
        pull=pull,
        files=files,
        collaborators=collaborators,
        invitations=invitations,
        expected_head_sha=expected_head_sha,
        checked_at=_github_provider_timestamp(token),
    )
    protection_ruleset = _ruleset_configuration(protection_response)
    main_health_ruleset = _ruleset_configuration(main_health_response)
    _validate_owner_bypass_rulesets(protection_ruleset, main_health_ruleset)
    admission.update(
        {
            "main_health_ruleset": main_health_ruleset,
            "main_health_ruleset_digest": digest(main_health_ruleset),
            "main_health_ruleset_id": main_health_ruleset_id,
            "protection_ruleset": protection_ruleset,
            "protection_ruleset_digest": digest(protection_ruleset),
            "protection_ruleset_id": protection_ruleset_id,
        }
    )
    attestation = _post_github_artifact(
        artifact=admission,
        kind="owner admission",
        repository=repository,
        pull_request=pull_request,
        token=token,
    )
    if (
        attestation["comment_author"].casefold() != repository_owner.casefold()
        or _timestamp(attestation["comment_created_at"]) < _timestamp(admission["checked_at"])
        or _timestamp(attestation["comment_created_at"]) > _timestamp(manifest["expires_at"])
    ):
        raise HealthError("GitHub owner admission comment does not attest the owner decision")
    return attestation


def merge_github_owner_emergency(
    *,
    root: Path,
    repository: str,
    pull_request: str,
    issue: str,
    incident_digest: str,
    admission_attestation: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    """Use the governed PR-only owner bypass for one exact admitted head."""
    validate_git_history(root)
    repository_owner = repository.split("/", 1)[0]
    last_attestation: dict[str, Any] | None = None
    last_pull: dict[str, Any] | None = None
    last_manifest: dict[str, Any] | None = None
    for _ in range(2):
        attestation = _refetch_github_artifact(
            retained=admission_attestation,
            kind="owner admission",
            repository=repository,
            pull_request=pull_request,
            token=token,
        )
        admission = attestation["artifact"]
        if (
            admission.get("repository") != repository
            or admission.get("pull_request") != pull_request
            or admission.get("issue") != issue
            or admission.get("incident_digest") != incident_digest
        ):
            raise HealthError("owner admission does not bind the requested merge")
        admitted_at = _timestamp(attestation["comment_created_at"])
        checked_at = _github_provider_now(token)
        if (
            attestation["comment_author"].casefold() != repository_owner.casefold()
            or _timestamp(admission["checked_at"]) > admitted_at
            or admitted_at > checked_at
        ):
            raise HealthError("owner admission provider lease is invalid")
        pull = _github_get(f"repos/{repository}/pulls/{pull_request}", token)
        if not isinstance(pull, dict):
            raise HealthError("GitHub owner-emergency pull response is malformed")
        head_sha = pull.get("head", {}).get("sha", "")
        manifest = _github_manifest(repository, head_sha, token)
        collaborators, invitations = _github_stable_collaboration_snapshot(repository, token)
        files = _github_list(f"repos/{repository}/pulls/{pull_request}/files", token)
        permission = _github_get(
            f"repos/{repository}/collaborators/{repository_owner}/permission", token
        )
        protection_response = _github_get(
            f"repos/{repository}/rulesets/{admission.get('protection_ruleset_id', '')}", token
        )
        main_health_response = _github_get(
            f"repos/{repository}/rulesets/{admission.get('main_health_ruleset_id', '')}", token
        )
        if not all(
            isinstance(item, dict)
            for item in (permission, protection_response, main_health_response)
        ):
            raise HealthError("GitHub owner merge permission or ruleset response is malformed")
        if permission.get("permission") != "admin":
            raise HealthError("governed owner merge requires current admin permission")
        protection = _ruleset_configuration(protection_response)
        main_health = _ruleset_configuration(main_health_response)
        _validate_owner_bypass_rulesets(protection, main_health)
        if (
            protection != admission.get("protection_ruleset")
            or digest(protection) != admission.get("protection_ruleset_digest")
            or main_health != admission.get("main_health_ruleset")
            or digest(main_health) != admission.get("main_health_ruleset_digest")
        ):
            raise HealthError("owner admission ruleset policy changed before merge")
        candidate_checked_at = (
            pull.get("merged_at")
            if pull.get("merged")
            else checked_at.isoformat().replace("+00:00", "Z")
        )
        if not isinstance(candidate_checked_at, str):
            raise HealthError("GitHub owner merge timestamp is malformed")
        live_admission = validate_owner_emergency_candidate(
            root,
            manifest=manifest,
            pull=pull,
            files=files,
            collaborators=collaborators,
            invitations=invitations,
            expected_head_sha=admission["head_sha"],
            checked_at=candidate_checked_at,
        )
        for field, value in live_admission.items():
            if field != "checked_at" and admission.get(field) != value:
                raise HealthError(f"owner admission is stale at {field}")
        if not pull.get("merged") and (
            checked_at > _timestamp(manifest["expires_at"])
            or (checked_at - admitted_at).total_seconds() > OWNER_ADMISSION_MAX_AGE_SECONDS
        ):
            raise HealthError("owner admission expired at the merge boundary")
        last_attestation, last_pull, last_manifest = attestation, pull, manifest

    if last_attestation is None or last_pull is None or last_manifest is None:
        raise HealthError("owner merge preflight did not produce stable provider state")
    admission = last_attestation["artifact"]
    if not last_pull.get("merged"):
        provider_now = _github_provider_now(token)
        admitted_at = _timestamp(last_attestation["comment_created_at"])
        if (
            provider_now > _timestamp(last_manifest["expires_at"])
            or (provider_now - admitted_at).total_seconds() > OWNER_ADMISSION_MAX_AGE_SECONDS
        ):
            raise HealthError("owner admission expired immediately before merge")
        node_id = last_pull.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise HealthError("GitHub pull request node identity is missing")
        merge_data = _github_graphql(
            """
            mutation($input:MergePullRequestInput!){
              mergePullRequest(input:$input){pullRequest{id merged mergedAt}}
            }
            """,
            {
                "input": {
                    "expectedHeadOid": admission["head_sha"],
                    "mergeMethod": "MERGE",
                    "pullRequestId": node_id,
                }
            },
            token,
        )
        merge_result = merge_data.get("mergePullRequest", {}).get("pullRequest", {})
        if (
            not isinstance(merge_result, dict)
            or merge_result.get("id") != node_id
            or merge_result.get("merged") is not True
            or not isinstance(merge_result.get("mergedAt"), str)
        ):
            raise HealthError("GitHub GraphQL merge response does not bind the admitted pull")
    merged_pull = _github_get(f"repos/{repository}/pulls/{pull_request}", token)
    if not isinstance(merged_pull, dict) or not merged_pull.get("merged"):
        raise HealthError("GitHub owner-emergency pull request is not merged")
    merged_by = merged_pull.get("merged_by") or {}
    merged_at = _timestamp(str(merged_pull.get("merged_at", "")))
    admitted_at = _timestamp(last_attestation["comment_created_at"])
    merge_sha = merged_pull.get("merge_commit_sha")
    if (
        merged_pull.get("head", {}).get("sha") != admission["head_sha"]
        or not isinstance(merge_sha, str)
        or not isinstance(merged_by.get("login"), str)
        or merged_by.get("id") is None
        or merged_by.get("login", "").casefold() != repository_owner.casefold()
        or merged_at < admitted_at
        or (merged_at - admitted_at).total_seconds() > OWNER_ADMISSION_MAX_AGE_SECONDS
        or merged_at > _timestamp(last_manifest["expires_at"])
    ):
        raise HealthError("GitHub owner bypass did not merge the exact admitted head")
    _validate_sha(merge_sha)
    head_commit = _github_get(f"repos/{repository}/git/commits/{admission['head_sha']}", token)
    merge_commit = _github_get(f"repos/{repository}/git/commits/{merge_sha}", token)
    if not isinstance(head_commit, dict) or not isinstance(merge_commit, dict):
        raise HealthError("GitHub owner merge commit proof responses are malformed")
    _github_merge_proof(
        pull=merged_pull,
        head_commit=head_commit,
        merge_commit=merge_commit,
    )
    return {
        "admission_comment_id": last_attestation["comment_id"],
        "admission_digest": digest(last_attestation),
        "bypass_actor": OWNER_BYPASS_ACTOR,
        "head_sha": admission["head_sha"],
        "main_health_ruleset_digest": admission["main_health_ruleset_digest"],
        "main_health_ruleset_id": admission["main_health_ruleset_id"],
        "merge_commit_sha": merged_pull["merge_commit_sha"],
        "merged_at": merged_pull["merged_at"],
        "merged_by": merged_by["login"],
        "merged_by_id": str(merged_by["id"]),
        "protection_ruleset_digest": admission["protection_ruleset_digest"],
        "protection_ruleset_id": admission["protection_ruleset_id"],
        "pull_request": pull_request,
        "repository": repository,
        "schema_version": SCHEMA_VERSION,
    }


def capture_github_owner_emergency(
    *,
    repository: str,
    pull_request: str,
    issue: str,
    incident_digest: str,
    admission: dict[str, Any],
    merge_gate: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    """Fetch exact provider state for a merged owner-emergency repair."""
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise HealthError("invalid GitHub repository identity")
    if not pull_request.isdigit() or not re.fullmatch(r"[0-9a-f]{64}", incident_digest):
        raise HealthError("invalid owner-emergency pull request or incident identity")
    pull = _github_get(f"repos/{repository}/pulls/{pull_request}", token)
    if not isinstance(pull, dict):
        raise HealthError("GitHub owner-emergency pull response is malformed")
    files: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _github_get(
            f"repos/{repository}/pulls/{pull_request}/files?per_page=100&page={page}",
            token,
        )
        if not isinstance(batch, list):
            raise HealthError("GitHub repair file response is not an array")
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    head_sha = pull.get("head", {}).get("sha", "")
    merge_sha = pull.get("merge_commit_sha", "")
    author = pull.get("user", {}).get("login", "")
    manifest = _github_manifest(repository, head_sha, token)
    collaborators, invitations = _github_stable_collaboration_snapshot(repository, token)
    admission = _refetch_github_artifact(
        retained=admission,
        kind="owner admission",
        repository=repository,
        pull_request=pull_request,
        token=token,
    )
    admission_payload = admission["artifact"]
    protection_response = _github_get(
        f"repos/{repository}/rulesets/{admission_payload.get('protection_ruleset_id', '')}", token
    )
    main_health_response = _github_get(
        f"repos/{repository}/rulesets/{admission_payload.get('main_health_ruleset_id', '')}", token
    )
    head_commit = _github_get(f"repos/{repository}/git/commits/{head_sha}", token)
    merge_commit = _github_get(f"repos/{repository}/git/commits/{merge_sha}", token)
    permission = _github_get(f"repos/{repository}/collaborators/{author}/permission", token)
    if not all(
        isinstance(item, dict)
        for item in (
            head_commit,
            merge_commit,
            permission,
            protection_response,
            main_health_response,
        )
    ):
        raise HealthError("GitHub owner-emergency merge or permission responses are malformed")
    protection = _ruleset_configuration(protection_response)
    main_health = _ruleset_configuration(main_health_response)
    _validate_owner_bypass_rulesets(protection, main_health)
    merged_by = pull.get("merged_by") or {}
    current_gate = {
        "admission_comment_id": admission["comment_id"],
        "admission_digest": digest(admission),
        "bypass_actor": OWNER_BYPASS_ACTOR,
        "head_sha": head_sha,
        "main_health_ruleset_digest": digest(main_health),
        "main_health_ruleset_id": admission_payload["main_health_ruleset_id"],
        "merge_commit_sha": merge_sha,
        "merged_at": pull.get("merged_at"),
        "merged_by": merged_by.get("login"),
        "merged_by_id": str(merged_by.get("id", "")),
        "protection_ruleset_digest": digest(protection),
        "protection_ruleset_id": admission_payload["protection_ruleset_id"],
        "pull_request": pull_request,
        "repository": repository,
        "schema_version": SCHEMA_VERSION,
    }
    if merge_gate != current_gate:
        raise HealthError("retained owner merge gate is stale")
    return github_owner_emergency_evidence(
        pull=pull,
        files=files,
        head_commit=head_commit,
        merge_commit=merge_commit,
        manifest=manifest,
        admission=admission,
        merge_gate=current_gate,
        collaborators=collaborators,
        invitations=invitations,
        captured_at=_github_provider_timestamp(token),
        owner_permission=permission.get("permission", ""),
        repository=repository,
        pull_request=pull_request,
        issue=issue,
        incident_digest=incident_digest,
    )


def _validate_repair_binding(
    *,
    authorization: dict[str, Any],
    approval_evidence: dict[str, Any],
    incident: dict[str, Any],
    repaired_main_sha: str,
    resolved_at: str,
) -> list[str]:
    if (
        set(incident)
        != {
            "failing_obligations",
            "first_bad_sha",
            "opened_at",
            "result_digest",
            "schema_version",
            "status",
        }
        or incident.get("schema_version") != SCHEMA_VERSION
        or incident.get("status") != "open"
    ):
        raise HealthError("repair incident shape or schema is invalid")
    required_auth = {
        "authorization_mode",
        "approval_digest",
        "approval_id",
        "approval_provider",
        "allowed_paths",
        "author",
        "author_id",
        "changed_paths_digest",
        "expires_at",
        "failing_obligations",
        "incident_digest",
        "issue",
        "manifest_digest",
        "policy_amendment_digest",
        "proposed_repair_sha",
        "pull_request",
        "repository",
        "required_cadences",
        "reviewer",
        "reviewer_id",
        "reviewer_permission",
        "schema_version",
    }
    if set(authorization) != required_auth or authorization["schema_version"] != SCHEMA_VERSION:
        raise HealthError("repair authorization shape or schema is invalid")
    if not all(
        isinstance(authorization[field], str) and authorization[field]
        for field in (
            "approval_digest",
            "approval_id",
            "approval_provider",
            "authorization_mode",
            "author",
            "author_id",
            "expires_at",
            "issue",
            "proposed_repair_sha",
            "pull_request",
            "repository",
            "reviewer",
            "reviewer_id",
            "reviewer_permission",
        )
    ):
        raise HealthError("repair authorization identities must be non-empty strings")
    if (
        not re.fullmatch(r"[A-Z]+-[0-9]+", authorization["issue"])
        or not re.fullmatch(r"[^/\s]+/[^/\s]+", authorization["repository"])
        or not authorization["pull_request"].isdigit()
    ):
        raise HealthError("repair authorization provider identities are invalid")
    mode = authorization["authorization_mode"]
    if authorization["approval_provider"] != "github":
        raise HealthError("repair approval provider is unsupported")
    if mode == "independent-review":
        if (
            authorization["reviewer_id"] == authorization["author_id"]
            or authorization["manifest_digest"] is not None
            or authorization["policy_amendment_digest"] is not None
        ):
            raise HealthError("repair authorization must be approved by a non-author")
    elif mode == "single-maintainer-owner-emergency":
        repository_owner = authorization["repository"].split("/", 1)[0]
        if (
            authorization["reviewer_id"] != authorization["author_id"]
            or authorization["reviewer"].casefold() != repository_owner.casefold()
            or authorization["author"].casefold() != repository_owner.casefold()
            or authorization["reviewer_permission"] != "admin"
        ):
            raise HealthError("owner emergency must be an explicit repository-owner decision")
    else:
        raise HealthError("repair authorization mode is unsupported")
    allowed_paths = authorization["allowed_paths"]
    failing_obligations = authorization["failing_obligations"]
    if (
        not isinstance(allowed_paths, list)
        or not allowed_paths
        or len(allowed_paths) != len(set(allowed_paths))
        or not all(isinstance(path, str) and path for path in allowed_paths)
        or not isinstance(failing_obligations, list)
        or not failing_obligations
        or len(failing_obligations) != len(set(failing_obligations))
        or not all(isinstance(item, str) and item for item in failing_obligations)
    ):
        raise HealthError("repair authorization path or obligation inventory is invalid")
    expected_evidence = {
        "admission",
        "admission_digest",
        "authorization_mode",
        "approval_id",
        "approval_provider",
        "author",
        "author_id",
        "base_sha",
        "captured_at",
        "changed_paths",
        "collaborators",
        "decision_at",
        "head_sha",
        "incident_digest",
        "issue",
        "manifest",
        "manifest_digest",
        "merge_commit_sha",
        "merge_parent_shas",
        "merge_tree_sha",
        "pending_invitations",
        "pull_request",
        "repository",
        "reviewed_tree_sha",
        "reviewer",
        "reviewer_id",
        "reviewer_permission",
        "merge_gate",
        "merge_gate_digest",
        "schema_version",
        "state",
    }
    if (
        set(approval_evidence) != expected_evidence
        or approval_evidence["schema_version"] != SCHEMA_VERSION
        or digest(approval_evidence) != authorization["approval_digest"]
    ):
        raise HealthError("provider approval evidence is invalid")
    expected_state = "APPROVED" if mode == "independent-review" else "OWNER_EMERGENCY"
    if approval_evidence["state"] != expected_state:
        raise HealthError("provider decision does not match the authorization mode")
    decision_at = _timestamp(approval_evidence["decision_at"])
    captured_at = _timestamp(approval_evidence["captured_at"])
    if decision_at > captured_at:
        raise HealthError("provider decision occurs after its evidence capture")
    for field in (
        "approval_id",
        "approval_provider",
        "authorization_mode",
        "author",
        "author_id",
        "incident_digest",
        "issue",
        "pull_request",
        "repository",
        "reviewer",
        "reviewer_id",
        "reviewer_permission",
    ):
        if approval_evidence[field] != authorization[field]:
            raise HealthError(f"provider approval evidence disagrees on {field}")
    if authorization["incident_digest"] != digest(incident):
        raise HealthError("repair authorization does not bind the open incident")
    manifest = approval_evidence["manifest"]
    if mode == "independent-review":
        if (
            manifest is not None
            or approval_evidence["admission"] is not None
            or approval_evidence["admission_digest"] is not None
            or approval_evidence["manifest_digest"] is not None
            or approval_evidence["collaborators"] is not None
            or approval_evidence["pending_invitations"] is not None
            or approval_evidence["merge_gate"] is not None
            or approval_evidence["merge_gate_digest"] is not None
        ):
            raise HealthError("independent repair evidence cannot carry an emergency manifest")
    else:
        if not isinstance(manifest, dict):
            raise HealthError("owner-emergency provider evidence is missing its manifest")
        admission_attestation = approval_evidence["admission"]
        merge_gate = approval_evidence["merge_gate"]
        if (
            not isinstance(admission_attestation, dict)
            or not isinstance(merge_gate, dict)
            or approval_evidence["admission_digest"] != digest(admission_attestation)
            or approval_evidence["merge_gate_digest"] != digest(merge_gate)
        ):
            raise HealthError("owner-emergency evidence is missing provider attestations")
        admission = _validate_comment_attestation(admission_attestation, "owner admission")
        if (
            set(admission)
            != {
                "authorization_mode",
                "base_sha",
                "changed_paths",
                "checked_at",
                "collaboration_digest",
                "collaborators",
                "head_sha",
                "incident_digest",
                "issue",
                "manifest_digest",
                "main_health_ruleset",
                "main_health_ruleset_digest",
                "main_health_ruleset_id",
                "pending_invitations",
                "protection_ruleset",
                "protection_ruleset_digest",
                "protection_ruleset_id",
                "pull_request",
                "repository",
                "schema_version",
                "status",
            }
            or admission.get("schema_version") != SCHEMA_VERSION
            or admission.get("status") != "repair-candidate"
            or admission.get("authorization_mode") != "single-maintainer-owner-emergency"
        ):
            raise HealthError("owner-emergency evidence is missing its pre-merge admission")
        _validate_owner_manifest(manifest)
        manifest_digest = digest(manifest)
        amendment_digest = digest(manifest["policy_amendment"])
        if (
            approval_evidence["manifest_digest"] != manifest_digest
            or authorization["manifest_digest"] != manifest_digest
            or authorization["policy_amendment_digest"] != amendment_digest
            or authorization["allowed_paths"] != manifest["allowed_paths"]
            or authorization["expires_at"] != manifest["expires_at"]
            or authorization["failing_obligations"] != manifest["failing_obligations"]
            or authorization["incident_digest"] != manifest["incident_digest"]
            or authorization["issue"] != manifest["issue"]
            or authorization["pull_request"] != str(manifest["pull_request"])
            or authorization["repository"] != manifest["repository"]
            or authorization["required_cadences"] != manifest["required_cadences"]
            or approval_evidence["base_sha"] != manifest["base_sha"]
        ):
            raise HealthError("owner-emergency authorization disagrees with admitted manifest")
        collaborators = approval_evidence["collaborators"]
        invitations = approval_evidence["pending_invitations"]
        repository_owner = authorization["repository"].split("/", 1)[0]
        if (
            not isinstance(collaborators, list)
            or not collaborators
            or collaborators
            != sorted(collaborators, key=lambda item: str(item.get("login", "")).casefold())
            or not all(
                isinstance(item, dict)
                and set(item) == {"id", "login", "permission"}
                and all(isinstance(item[field], str) and item[field] for field in item)
                for item in collaborators
            )
            or not any(
                item["login"].casefold() == repository_owner.casefold()
                and item["permission"] == "admin"
                for item in collaborators
            )
            or any(
                item["login"].casefold() != repository_owner.casefold()
                and item["permission"] in AUTHORIZED_REVIEWER_PERMISSIONS
                for item in collaborators
            )
            or not isinstance(invitations, list)
            or invitations
            != sorted(
                invitations,
                key=lambda item: (str(item.get("invitee", "")).casefold(), str(item.get("id", ""))),
            )
            or not all(
                isinstance(item, dict)
                and set(item) == {"id", "invitee", "permission"}
                and all(isinstance(item[field], str) and item[field] for field in item)
                for item in invitations
            )
            or any(item["permission"] in AUTHORIZED_REVIEWER_PERMISSIONS for item in invitations)
            or digest(
                {
                    "collaborators": collaborators,
                    "pending_invitations": invitations,
                }
            )
            != manifest["collaboration_digest"]
        ):
            raise HealthError("owner-emergency evidence does not prove single-maintainer status")
        admission_checked_at = admission.get("checked_at")
        if not isinstance(admission_checked_at, str):
            raise HealthError("owner-emergency admission timestamp is invalid")
        expected_gate_fields = {
            "admission_comment_id",
            "admission_digest",
            "bypass_actor",
            "head_sha",
            "main_health_ruleset_digest",
            "main_health_ruleset_id",
            "merge_commit_sha",
            "merged_at",
            "merged_by",
            "merged_by_id",
            "protection_ruleset_digest",
            "protection_ruleset_id",
            "pull_request",
            "repository",
            "schema_version",
        }
        protection_ruleset = admission.get("protection_ruleset")
        main_health_ruleset = admission.get("main_health_ruleset")
        if not isinstance(protection_ruleset, dict) or not isinstance(main_health_ruleset, dict):
            raise HealthError("owner-emergency admitted rulesets are malformed")
        _validate_owner_bypass_rulesets(protection_ruleset, main_health_ruleset)
        admission_digest = digest(admission_attestation)
        admitted_at = _timestamp(admission_attestation["comment_created_at"])
        if (
            admission.get("collaborators") != collaborators
            or admission.get("pending_invitations") != invitations
            or admission.get("collaboration_digest") != manifest["collaboration_digest"]
            or admission.get("manifest_digest") != manifest_digest
            or admission.get("head_sha") != approval_evidence["head_sha"]
            or admission.get("base_sha") != approval_evidence["base_sha"]
            or admission.get("changed_paths") != approval_evidence["changed_paths"]
            or admission.get("incident_digest") != authorization["incident_digest"]
            or admission.get("issue") != authorization["issue"]
            or admission.get("pull_request") != authorization["pull_request"]
            or admission.get("repository") != authorization["repository"]
            or admission_attestation["comment_author"].casefold() != repository_owner.casefold()
            or _timestamp(admission_checked_at) > admitted_at
            or admitted_at > decision_at
            or (decision_at - admitted_at).total_seconds() > OWNER_ADMISSION_MAX_AGE_SECONDS
            or decision_at > _timestamp(manifest["expires_at"])
            or decision_at > captured_at
            or set(merge_gate) != expected_gate_fields
            or merge_gate.get("schema_version") != SCHEMA_VERSION
            or merge_gate.get("admission_comment_id") != admission_attestation["comment_id"]
            or merge_gate.get("admission_digest") != admission_digest
            or merge_gate.get("bypass_actor") != OWNER_BYPASS_ACTOR
            or merge_gate.get("head_sha") != approval_evidence["head_sha"]
            or merge_gate.get("main_health_ruleset_digest") != digest(main_health_ruleset)
            or merge_gate.get("main_health_ruleset_id") != admission.get("main_health_ruleset_id")
            or merge_gate.get("merge_commit_sha") != approval_evidence["merge_commit_sha"]
            or merge_gate.get("merged_at") != approval_evidence["decision_at"]
            or merge_gate.get("merged_by", "").casefold() != repository_owner.casefold()
            or merge_gate.get("merged_by") != approval_evidence["reviewer"]
            or merge_gate.get("merged_by_id") != approval_evidence["reviewer_id"]
            or merge_gate.get("protection_ruleset_digest") != digest(protection_ruleset)
            or merge_gate.get("protection_ruleset_id") != admission.get("protection_ruleset_id")
            or merge_gate.get("pull_request") != authorization["pull_request"]
            or merge_gate.get("repository") != authorization["repository"]
            or admission.get("main_health_ruleset_digest") != digest(main_health_ruleset)
            or admission.get("protection_ruleset_digest") != digest(protection_ruleset)
        ):
            raise HealthError("owner-emergency admission does not bracket the exact merge")
    if (
        approval_evidence["head_sha"] != authorization["proposed_repair_sha"]
        or approval_evidence["merge_commit_sha"] != repaired_main_sha
        or approval_evidence["reviewed_tree_sha"] != approval_evidence["merge_tree_sha"]
    ):
        raise HealthError("repair evidence does not bind the reviewed head to repaired main")
    for sha_field in (
        "base_sha",
        "head_sha",
        "merge_commit_sha",
        "reviewed_tree_sha",
        "merge_tree_sha",
    ):
        _validate_sha(approval_evidence[sha_field])
    parents = approval_evidence["merge_parent_shas"]
    if not isinstance(parents, list) or parents != [
        approval_evidence["base_sha"],
        approval_evidence["head_sha"],
    ]:
        raise HealthError("repair merge parent inventory is invalid")
    for parent_sha in parents:
        _validate_sha(parent_sha)
    changed_paths = approval_evidence["changed_paths"]
    if (
        not isinstance(changed_paths, list)
        or not changed_paths
        or len(changed_paths) != len(set(changed_paths))
        or not all(
            isinstance(path, str)
            and path
            and not path.startswith("/")
            and ".." not in Path(path).parts
            for path in changed_paths
        )
        or digest(sorted(changed_paths)) != authorization["changed_paths_digest"]
        or changed_paths != allowed_paths
    ):
        raise HealthError("repair changed paths are invalid or unauthorized")
    resolution_time = _timestamp(resolved_at)
    if resolution_time < captured_at or resolution_time > _timestamp(authorization["expires_at"]):
        raise HealthError("repair authorization has expired")
    if sorted(authorization["failing_obligations"]) != sorted(incident["failing_obligations"]):
        raise HealthError("authorization does not bind the exact failing obligations")
    declared_cadences = authorization["required_cadences"]
    if declared_cadences != CANONICAL_REPAIR_CADENCES:
        raise HealthError("repair cadence requirements do not match canonical policy")
    if authorization["reviewer_permission"] not in AUTHORIZED_REVIEWER_PERMISSIONS:
        raise HealthError("repair reviewer lacks repository write authority")
    return list(CANONICAL_REPAIR_CADENCES)


def resolve(
    root: Path,
    *,
    authorization: dict[str, Any],
    approval_evidence: dict[str, Any],
    repaired_main: dict[str, Any],
    resolved_at: str,
    expected_generation: int,
) -> dict[str, Any]:
    """Clear red through an exact retained provider-authorized repair."""
    state = _load_state(root)
    _require_generation(state, expected_generation)
    if state is None or state["status"] != "red" or not state["incident_digest"]:
        raise HealthError("repair resolution requires an open red incident")
    validate_history(root)
    _timestamp(resolved_at)
    _validate_summary(repaired_main)
    if repaired_main["cadence"] != "protected-main" or repaired_main["conclusion"] != PASS:
        raise HealthError("repaired main must be a passing protected-main result")
    incident = _read(root / "incidents" / f"{state['incident_digest']}.json")
    declared_cadences = _validate_repair_binding(
        authorization=authorization,
        approval_evidence=approval_evidence,
        incident=incident,
        repaired_main_sha=repaired_main["sha"],
        resolved_at=resolved_at,
    )

    retained = _retained_passing_results(root)
    exact_repaired_main = (
        repaired_main["sha"],
        "protected-main",
        digest(repaired_main),
    )
    if exact_repaired_main not in retained:
        raise HealthError("exact repaired-main result is not retained in validated history")
    retained_cadences = {cadence for sha, cadence, _ in retained if sha == repaired_main["sha"]}
    required_cadences = set(declared_cadences) | {"protected-main"}
    if not required_cadences <= retained_cadences:
        raise HealthError("required retained main/deep repair results are incomplete")

    _write_immutable(
        root / "approval-evidence" / f"{digest(approval_evidence)}.json",
        approval_evidence,
    )
    authorization_digest = _write_immutable(
        root / "repair-authorizations" / f"{digest(authorization)}.json",
        authorization,
    )
    policy_amendment_digest = authorization["policy_amendment_digest"]
    if policy_amendment_digest is not None:
        manifest = approval_evidence["manifest"]
        if not isinstance(manifest, dict):
            raise HealthError("owner-emergency resolution is missing its policy amendment")
        retained_amendment_digest = _write_immutable(
            root / "policy-amendments" / f"{policy_amendment_digest}.json",
            manifest["policy_amendment"],
        )
        if retained_amendment_digest != policy_amendment_digest:
            raise HealthError("owner-emergency policy amendment digest mismatch")
    resolution = {
        "authorization_mode": authorization["authorization_mode"],
        "authorization_digest": authorization_digest,
        "incident_digest": state["incident_digest"],
        "policy_amendment_digest": policy_amendment_digest,
        "repaired_main_sha": repaired_main["sha"],
        "resolved_at": resolved_at,
        "schema_version": SCHEMA_VERSION,
    }
    resolution_digest = digest(resolution)
    _write_immutable(root / "resolutions" / f"{resolution_digest}.json", resolution)
    updated = {
        **state,
        "first_bad_sha": None,
        "generation": state["generation"] + 1,
        "incident_digest": None,
        "last_good_sha": repaired_main["sha"],
        "resolution_digest": resolution_digest,
        "status": "green",
        "updated_at": resolved_at,
    }
    history = {
        "cadence": "repair-resolution",
        "generation": updated["generation"],
        "previous_digest": state["history_head"],
        "recorded_at": resolved_at,
        "result_digest": digest(repaired_main),
        "resolution_digest": resolution_digest,
        "retention_digest": digest(_read(root / "retention" / f"{digest(repaired_main)}.json")),
        "schema_version": SCHEMA_VERSION,
        "sha": repaired_main["sha"],
        "status": "green",
    }
    history_digest = digest(history)
    _write_immutable(
        root / "history" / f"{updated['generation']:08d}-{history_digest}.json",
        history,
    )
    updated["history_head"] = history_digest
    _atomic_write(root / "state.json", updated)
    validated = validate_history(root)
    if validated["status"] != "green" or validated["generation"] != updated["generation"]:
        raise HealthError("resolved state failed post-write validation")
    return updated


def validate_history(root: Path) -> dict[str, Any]:
    state = _load_state(root)
    if state is None:
        raise HealthError("main health has not been activated")
    activation = _read(root / "activation.json")
    if set(activation) != {
        "activated_at",
        "first_measured_sha",
        "policy_digest",
        "prehistory_disposition",
        "schema_version",
    }:
        raise HealthError("activation shape is invalid")
    if digest(activation) != state["activation_digest"]:
        raise HealthError("activation digest mismatch")
    activation_policy = _read(root / "activation-policy.json")
    if activation_policy != ACTIVATION_POLICY:
        raise HealthError("activation policy does not match the canonical contract")
    if digest(activation_policy) != activation["policy_digest"]:
        raise HealthError("activation policy digest mismatch")
    previous = None
    previous_status = "not_measured"
    previous_timestamp = _timestamp(activation["activated_at"])
    result_digests: set[str] = set()
    repair_resolution_digests: list[str] = []
    repair_history: dict[str, dict[str, Any]] = {}
    passing_results: set[tuple[str, str, str]] = set()
    repair_retained: dict[str, set[tuple[str, str, str]]] = {}
    derived_incidents: dict[str, dict[str, Any]] = {}
    current_incident_digest: str | None = None
    entries = sorted((root / "history").glob("*.json"))
    for generation, path in enumerate(entries, start=1):
        entry = _read(path)
        if set(entry) != {
            "cadence",
            "generation",
            "previous_digest",
            "recorded_at",
            "result_digest",
            "resolution_digest",
            "retention_digest",
            "schema_version",
            "sha",
            "status",
        }:
            raise HealthError("history entry shape is invalid")
        if entry["generation"] != generation or entry["previous_digest"] != previous:
            raise HealthError("history generation or predecessor mismatch")
        entry_digest = digest(entry)
        if not path.name.endswith(f"-{entry_digest}.json"):
            raise HealthError("history filename digest mismatch")
        result_path = root / "results" / f"{entry['result_digest']}.json"
        if (
            not result_path.is_file()
            or hashlib.sha256(result_path.read_bytes()).hexdigest() != entry["result_digest"]
        ):
            raise HealthError("history result is missing or corrupted")
        result = _read(result_path)
        result_digests.add(entry["result_digest"])
        _validate_summary(result)
        if result["sha"] != entry["sha"]:
            raise HealthError("history SHA disagrees with its result")
        if entry["cadence"] == "repair-resolution":
            expected_status = "green"
            if not isinstance(entry["resolution_digest"], str):
                raise HealthError("repair history is missing its resolution digest")
            repair_resolution_digests.append(entry["resolution_digest"])
            repair_history[entry["resolution_digest"]] = entry
            repair_retained[entry["resolution_digest"]] = set(passing_results)
            if result["cadence"] != "protected-main" or result["conclusion"] != PASS:
                raise HealthError("repair history does not bind a green main result")
            resolution = _read(root / "resolutions" / f"{entry['resolution_digest']}.json")
            if (
                current_incident_digest is None
                or resolution.get("incident_digest") != current_incident_digest
            ):
                raise HealthError("repair history does not close the derived open incident")
            current_incident_digest = None
        else:
            if entry["resolution_digest"] is not None:
                raise HealthError("normal history cannot point to a repair resolution")
            if result["conclusion"] == PASS:
                passing_results.add((result["sha"], result["cadence"], entry["result_digest"]))
            if (
                result["cadence"] != entry["cadence"]
                or result["recorded_at"] != entry["recorded_at"]
            ):
                raise HealthError("history cadence disagrees with its result")
            expected_status = (
                "red" if result["conclusion"] != PASS or previous_status == "red" else "green"
            )
            if result["conclusion"] != PASS and previous_status != "red":
                incident = {
                    "failing_obligations": sorted(
                        item["id"] for item in result["obligations"] if item["result"] != PASS
                    ),
                    "first_bad_sha": result["sha"],
                    "opened_at": result["recorded_at"],
                    "result_digest": entry["result_digest"],
                    "schema_version": SCHEMA_VERSION,
                    "status": "open",
                }
                current_incident_digest = digest(incident)
                retained_incident = _read(root / "incidents" / f"{current_incident_digest}.json")
                if retained_incident != incident:
                    raise HealthError("retained incident does not match its opening history entry")
                derived_incidents[current_incident_digest] = incident
        if entry["status"] != expected_status:
            raise HealthError("history status disagrees with its result chain")
        recorded_at = _timestamp(entry["recorded_at"])
        if recorded_at < previous_timestamp:
            raise HealthError("history timestamps are not monotonic")
        retention_path = root / "retention" / f"{entry['result_digest']}.json"
        if not retention_path.is_file():
            raise HealthError("history retention receipt is missing")
        retention = _read(retention_path)
        if (
            set(retention) != {"backend", "read_back_sha256", "result_digest", "schema_version"}
            or retention["backend"] != "main-health-state-branch"
            or digest(retention) != entry["retention_digest"]
            or retention["result_digest"] != entry["result_digest"]
            or retention["read_back_sha256"] != entry["result_digest"]
        ):
            raise HealthError("history retention receipt is invalid")
        previous = entry_digest
        previous_status = entry["status"]
        previous_timestamp = recorded_at
    if len(entries) != state["generation"] or previous != state["history_head"]:
        raise HealthError("state does not point to the complete history")
    if state["incident_digest"] != current_incident_digest:
        raise HealthError("state incident pointer disagrees with derived history")
    for directory in ("results", "retention"):
        actual = {path.stem for path in (root / directory).glob("*.json")}
        if actual != result_digests:
            raise HealthError(f"{directory} contains missing or orphaned evidence")
    if state["generation"] == 0:
        if state["status"] != "not_measured" or state["history_head"] is not None:
            raise HealthError("unmeasured state contradicts activation history")
    else:
        first = _read(entries[0])
        if activation["first_measured_sha"] != first["sha"]:
            raise HealthError("activation does not bind the first measured result")
        final = _read(entries[-1])
        if state["status"] != final["status"] or state["updated_at"] != final["recorded_at"]:
            raise HealthError("state status or timestamp contradicts history")
        if state["status"] == "red":
            if not state["incident_digest"] or not state["first_bad_sha"]:
                raise HealthError("red state is missing its incident identity")
            incident = derived_incidents[state["incident_digest"]]
            if (
                set(incident)
                != {
                    "failing_obligations",
                    "first_bad_sha",
                    "opened_at",
                    "result_digest",
                    "schema_version",
                    "status",
                }
                or incident["first_bad_sha"] != state["first_bad_sha"]
                or incident["status"] != "open"
                or not (root / "results" / f"{incident['result_digest']}.json").is_file()
            ):
                raise HealthError("red state incident is invalid")
        elif (
            state["incident_digest"] is not None
            or state["first_bad_sha"] is not None
            or state["last_good_sha"] != final["sha"]
        ):
            raise HealthError("green state contradicts its final history entry")
    if len(repair_resolution_digests) != len(set(repair_resolution_digests)):
        raise HealthError("repair history contains a duplicate resolution")
    resolution_digests = set(repair_resolution_digests)
    latest_resolution = repair_resolution_digests[-1] if repair_resolution_digests else None
    if state["resolution_digest"] != latest_resolution:
        raise HealthError("state does not point to the latest repair resolution")
    authorization_digests: set[str] = set()
    evidence_digests: set[str] = set()
    policy_amendment_digests: set[str] = set()
    incident_digests = set(derived_incidents)
    for resolution_digest in repair_resolution_digests:
        path = root / "resolutions" / f"{resolution_digest}.json"
        resolution = _read(path)
        if (
            set(resolution)
            != {
                "authorization_mode",
                "authorization_digest",
                "incident_digest",
                "policy_amendment_digest",
                "repaired_main_sha",
                "resolved_at",
                "schema_version",
            }
            or resolution["schema_version"] != SCHEMA_VERSION
            or digest(resolution) != resolution_digest
        ):
            raise HealthError("resolution filename digest mismatch")
        incident_digest = resolution["incident_digest"]
        incident = _read(root / "incidents" / f"{incident_digest}.json")
        if digest(incident) != incident_digest:
            raise HealthError("resolved incident digest mismatch")
        authorization_digest = resolution["authorization_digest"]
        authorization = _read(root / "repair-authorizations" / f"{authorization_digest}.json")
        if digest(authorization) != authorization_digest:
            raise HealthError("repair authorization digest mismatch")
        authorization_digests.add(authorization_digest)
        evidence_digest = authorization["approval_digest"]
        evidence = _read(root / "approval-evidence" / f"{evidence_digest}.json")
        if digest(evidence) != evidence_digest:
            raise HealthError("repair approval evidence digest mismatch")
        evidence_digests.add(evidence_digest)
        amendment_digest = resolution["policy_amendment_digest"]
        if amendment_digest is not None:
            if not isinstance(amendment_digest, str):
                raise HealthError("resolution policy amendment digest is invalid")
            amendment = _read(root / "policy-amendments" / f"{amendment_digest}.json")
            if (
                digest(amendment) != amendment_digest
                or authorization["policy_amendment_digest"] != amendment_digest
                or not isinstance(evidence["manifest"], dict)
                or evidence["manifest"]["policy_amendment"] != amendment
            ):
                raise HealthError("resolution policy amendment is invalid")
            policy_amendment_digests.add(amendment_digest)
        elif authorization["policy_amendment_digest"] is not None:
            raise HealthError("resolution omits its policy amendment")
        if (
            resolution["authorization_mode"] != authorization["authorization_mode"]
            or evidence["authorization_mode"] != resolution["authorization_mode"]
            or evidence["head_sha"] != authorization["proposed_repair_sha"]
            or evidence["merge_commit_sha"] != resolution["repaired_main_sha"]
            or resolution["repaired_main_sha"] != repair_history[resolution_digest]["sha"]
            or resolution["resolved_at"] != repair_history[resolution_digest]["recorded_at"]
        ):
            raise HealthError("resolution evidence disagrees on the reviewed or repaired SHA")
        declared_cadences = _validate_repair_binding(
            authorization=authorization,
            approval_evidence=evidence,
            incident=incident,
            repaired_main_sha=resolution["repaired_main_sha"],
            resolved_at=resolution["resolved_at"],
        )
        retained = repair_retained[resolution_digest]
        repair_entry = repair_history[resolution_digest]
        exact_main = (
            resolution["repaired_main_sha"],
            "protected-main",
            repair_entry["result_digest"],
        )
        cadences = {
            cadence for sha, cadence, _ in retained if sha == resolution["repaired_main_sha"]
        }
        if (
            exact_main not in retained
            or not (set(declared_cadences) | {"protected-main"}) <= cadences
        ):
            raise HealthError("resolution lacks its exact retained main/deep evidence")
    stored = {
        "approval-evidence": evidence_digests,
        "incidents": incident_digests,
        "policy-amendments": policy_amendment_digests,
        "repair-authorizations": authorization_digests,
        "resolutions": resolution_digests,
    }
    for directory, expected in stored.items():
        actual = {path.stem for path in (root / directory).glob("*.json")}
        if actual != expected:
            raise HealthError(f"{directory} contains missing or orphaned evidence")
    governed_directories = {
        "approval-evidence",
        "history",
        "incidents",
        "policy-amendments",
        "repair-authorizations",
        "resolutions",
        "results",
        "retention",
    }
    governed_root_files = {"activation-policy.json", "activation.json", "state.json"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if len(relative.parts) == 1 and relative.name in governed_root_files:
            continue
        if (
            len(relative.parts) == 2
            and relative.parts[0] in governed_directories
            and relative.suffix == ".json"
        ):
            continue
        raise HealthError(f"retained state contains an ungoverned file: {relative.as_posix()}")
    return {
        "activation_digest": state["activation_digest"],
        "generation": state["generation"],
        "history_head": state["history_head"],
        "schema_version": SCHEMA_VERSION,
        "status": state["status"],
    }


def _git_output(root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise HealthError(f"cannot execute Git for retained state: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise HealthError(f"cannot inspect retained state Git history: {detail}")
    return completed.stdout


def _expected_git_additions(root: Path) -> list[set[str]]:
    additions_by_generation: list[set[str]] = []
    seen = {"activation-policy.json", "activation.json", "state.json"}
    previous_status = "not_measured"
    for generation, history_path in enumerate(sorted((root / "history").glob("*.json")), start=1):
        entry = _read(history_path)
        result = _read(root / "results" / f"{entry['result_digest']}.json")
        additions = {
            history_path.relative_to(root).as_posix(),
            f"results/{entry['result_digest']}.json",
            f"retention/{entry['result_digest']}.json",
        }
        if result["conclusion"] != PASS and previous_status != "red":
            incident = {
                "failing_obligations": sorted(
                    item["id"] for item in result["obligations"] if item["result"] != PASS
                ),
                "first_bad_sha": result["sha"],
                "opened_at": result["recorded_at"],
                "result_digest": entry["result_digest"],
                "schema_version": SCHEMA_VERSION,
                "status": "open",
            }
            additions.add(f"incidents/{digest(incident)}.json")
        resolution_digest = entry["resolution_digest"]
        if resolution_digest is not None:
            resolution = _read(root / "resolutions" / f"{resolution_digest}.json")
            authorization_digest = resolution["authorization_digest"]
            authorization = _read(root / "repair-authorizations" / f"{authorization_digest}.json")
            additions.update(
                {
                    f"approval-evidence/{authorization['approval_digest']}.json",
                    f"repair-authorizations/{authorization_digest}.json",
                    f"resolutions/{resolution_digest}.json",
                }
            )
            if resolution["policy_amendment_digest"] is not None:
                additions.add(f"policy-amendments/{resolution['policy_amendment_digest']}.json")
        new_additions = additions - seen
        if generation == 1:
            new_additions.update(seen)
        additions_by_generation.append(new_additions)
        seen.update(additions)
        previous_status = entry["status"]
    return additions_by_generation


def _expected_git_states(root: Path) -> list[dict[str, Any]]:
    activation = _read(root / "activation.json")
    state: dict[str, Any] = {
        "activation_digest": digest(activation),
        "first_bad_sha": None,
        "generation": 0,
        "history_head": None,
        "incident_digest": None,
        "last_good_sha": None,
        "resolution_digest": None,
        "schema_version": SCHEMA_VERSION,
        "status": "not_measured",
        "updated_at": activation["activated_at"],
    }
    states: list[dict[str, Any]] = []
    for history_path in sorted((root / "history").glob("*.json")):
        entry = _read(history_path)
        result = _read(root / "results" / f"{entry['result_digest']}.json")
        first_bad_sha = state["first_bad_sha"]
        incident_digest = state["incident_digest"]
        last_good_sha = state["last_good_sha"]
        resolution_digest = state["resolution_digest"]
        if entry["cadence"] == "repair-resolution":
            first_bad_sha = None
            incident_digest = None
            last_good_sha = entry["sha"]
            resolution_digest = entry["resolution_digest"]
        elif result["conclusion"] != PASS and state["status"] != "red":
            incident = {
                "failing_obligations": sorted(
                    item["id"] for item in result["obligations"] if item["result"] != PASS
                ),
                "first_bad_sha": result["sha"],
                "opened_at": result["recorded_at"],
                "result_digest": entry["result_digest"],
                "schema_version": SCHEMA_VERSION,
                "status": "open",
            }
            first_bad_sha = result["sha"]
            incident_digest = digest(incident)
        elif entry["status"] == "green":
            last_good_sha = entry["sha"]
        state = {
            **state,
            "first_bad_sha": first_bad_sha,
            "generation": entry["generation"],
            "history_head": digest(entry),
            "incident_digest": incident_digest,
            "last_good_sha": last_good_sha,
            "resolution_digest": resolution_digest,
            "status": entry["status"],
            "updated_at": entry["recorded_at"],
        }
        states.append(state)
    return states


def validate_git_history(root: Path) -> dict[str, Any]:
    """Prove every state-branch commit is one append-only validated transition."""
    if _git_output(root, "status", "--porcelain", "--untracked-files=all"):
        raise HealthError("retained state Git checkout is not clean")
    head = _git_output(root, "rev-parse", "HEAD").decode().strip()
    _validate_sha(head)
    commits = _git_output(root, "rev-list", "--reverse", "--first-parent", head).decode().split()
    if not commits:
        raise HealthError("retained state Git history is empty")
    current_state = validate_history(root)
    expected_additions = _expected_git_additions(root)
    expected_states = _expected_git_states(root)
    if len(expected_additions) != len(commits):
        raise HealthError("retained state Git history does not match its generations")
    for ordinal, commit in enumerate(commits, start=1):
        _validate_sha(commit)
        ancestry = _git_output(root, "rev-list", "--parents", "-n", "1", commit).decode().split()
        expected_length = 1 if ordinal == 1 else 2
        if len(ancestry) != expected_length or ancestry[0] != commit:
            raise HealthError("retained state Git history is not a single-parent chain")
        try:
            state = json.loads(_git_output(root, "show", f"{commit}:state.json"))
        except json.JSONDecodeError as exc:
            raise HealthError("retained state Git commit has malformed state") from exc
        if not isinstance(state, dict) or state != expected_states[ordinal - 1]:
            raise HealthError("retained state Git commit has an invalid generation pointer")
        if ordinal == 1:
            actual = set(
                _git_output(root, "ls-tree", "-r", "--name-only", "-z", commit).decode().split("\0")
            )
            actual.discard("")
            if actual != expected_additions[0]:
                raise HealthError("retained state Git root does not match generation one")
            continue
        changes = (
            _git_output(
                root,
                "diff-tree",
                "--no-commit-id",
                "--name-status",
                "--no-renames",
                "-r",
                "-z",
                ancestry[1],
                commit,
            )
            .decode()
            .split("\0")
        )
        if changes and changes[-1] == "":
            changes.pop()
        if len(changes) % 2 != 0:
            raise HealthError("retained state Git transition is malformed")
        pairs = list(zip(changes[0::2], changes[1::2], strict=True))
        if pairs.count(("M", "state.json")) != 1:
            raise HealthError("retained state Git transition does not update its pointer once")
        actual_additions: set[str] = set()
        for status, path in pairs:
            if path == "state.json":
                if status != "M":
                    raise HealthError("retained state Git transition replaces its pointer")
            else:
                if status != "A":
                    raise HealthError("retained state Git history rewrites immutable evidence")
                actual_additions.add(path)
        if actual_additions != expected_additions[ordinal - 1]:
            raise HealthError("retained state Git commit has invalid generation evidence")
    if current_state["generation"] != len(commits):
        raise HealthError("retained state checkout does not match its Git HEAD")
    return {**current_state, "state_commit": head}


def validate_candidate(
    root: Path,
    *,
    base_sha: str,
    checked_at: str,
    max_age_seconds: int,
) -> dict[str, Any]:
    """Require fresh green health for the exact pull-request base SHA."""
    _validate_sha(base_sha)
    if max_age_seconds <= 0:
        raise HealthError("candidate evidence max age must be positive")
    state = _load_state(root)
    validate_history(root)
    if state is None or state["status"] != "green":
        raise HealthError("candidate base does not have green main health")
    if state["last_good_sha"] != base_sha:
        raise HealthError("candidate base SHA is not the last measured green main")
    age = (_timestamp(checked_at) - _timestamp(state["updated_at"])).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise HealthError("candidate main-health evidence is stale")
    return {
        "base_sha": base_sha,
        "checked_at": checked_at,
        "generation": state["generation"],
        "schema_version": SCHEMA_VERSION,
        "status": "green",
    }


def _validate_owner_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "authorization_mode",
        "allowed_paths",
        "base_sha",
        "collaboration_digest",
        "expires_at",
        "failing_obligations",
        "incident_digest",
        "issue",
        "policy_amendment",
        "pull_request",
        "repository",
        "required_cadences",
        "schema_version",
    }
    if set(manifest) != required or manifest.get("schema_version") != SCHEMA_VERSION:
        raise HealthError("owner-emergency candidate manifest shape or schema is invalid")
    if manifest["authorization_mode"] != "single-maintainer-owner-emergency":
        raise HealthError("owner-emergency candidate mode is invalid")
    if manifest["required_cadences"] != CANONICAL_REPAIR_CADENCES:
        raise HealthError("owner-emergency candidate cadences do not match canonical policy")
    _validate_sha(manifest["base_sha"])
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["collaboration_digest"]):
        raise HealthError("owner-emergency collaboration digest is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["incident_digest"]):
        raise HealthError("owner-emergency candidate incident digest is invalid")
    if (
        not re.fullmatch(r"[A-Z]+-[0-9]+", manifest["issue"])
        or not re.fullmatch(r"[^/\s]+/[^/\s]+", manifest["repository"])
        or not str(manifest["pull_request"]).isdigit()
    ):
        raise HealthError("owner-emergency candidate provider identity is invalid")
    amendment = manifest["policy_amendment"]
    if amendment != {
        "amended_rule": "repair_requires_non_author",
        "authorization_mode": "single-maintainer-owner-emergency",
        "incident_digest": manifest["incident_digest"],
        "reason": "single-maintainer-no-independent-collaborator",
        "schema_version": SCHEMA_VERSION,
        "scope": "incident-only",
    }:
        raise HealthError("owner-emergency policy amendment is invalid")
    allowed_paths = manifest["allowed_paths"]
    if (
        not isinstance(allowed_paths, list)
        or not allowed_paths
        or allowed_paths != sorted(set(allowed_paths))
        or not all(
            isinstance(path, str)
            and path
            and not path.startswith("/")
            and ".." not in Path(path).parts
            for path in allowed_paths
        )
    ):
        raise HealthError("owner-emergency allowed paths are invalid")


def validate_owner_emergency_candidate(
    root: Path,
    *,
    manifest: dict[str, Any],
    pull: dict[str, Any],
    files: list[dict[str, Any]],
    collaborators: list[dict[str, Any]],
    invitations: list[dict[str, Any]],
    expected_head_sha: str,
    checked_at: str,
) -> dict[str, Any]:
    """Admit one exact owner-authored repair candidate while main is red."""
    _validate_owner_manifest(manifest)
    _validate_sha(expected_head_sha)
    allowed_paths = manifest["allowed_paths"]
    changed_paths = _github_changed_paths(pull, files)
    if changed_paths != allowed_paths:
        raise HealthError("owner-emergency candidate does not bind the exact changed paths")
    collaborator_inventory, invitation_inventory = _github_collaboration_inventory(
        collaborators, invitations
    )
    repository_owner = manifest["repository"].split("/", 1)[0]
    if any(
        item["login"].casefold() != repository_owner.casefold()
        and item["permission"] in AUTHORIZED_REVIEWER_PERMISSIONS
        for item in collaborator_inventory
    ) or any(
        item["permission"] in AUTHORIZED_REVIEWER_PERMISSIONS for item in invitation_inventory
    ):
        raise HealthError("owner-emergency admission found an eligible independent collaborator")
    collaboration_digest = digest(
        {
            "collaborators": collaborator_inventory,
            "pending_invitations": invitation_inventory,
        }
    )
    if collaboration_digest != manifest["collaboration_digest"]:
        raise HealthError("owner-emergency admission collaboration digest is stale")
    state = _load_state(root)
    validate_history(root)
    if state is None or state["status"] != "red" or not state["incident_digest"]:
        raise HealthError("owner-emergency admission requires an open red incident")
    incident = _read(root / "incidents" / f"{state['incident_digest']}.json")
    if manifest["incident_digest"] != state["incident_digest"] or sorted(
        manifest["failing_obligations"]
    ) != sorted(incident["failing_obligations"]):
        raise HealthError("owner-emergency candidate does not bind the open incident")
    entries = sorted((root / "history").glob("*.json"))
    if not entries or _read(entries[-1])["sha"] != manifest["base_sha"]:
        raise HealthError("owner-emergency candidate base is not the latest measured main")
    try:
        pull_number = str(pull["number"])
        pull_repository = pull["base"]["repo"]["full_name"]
        pull_base_sha = pull["base"]["sha"]
        pull_head_sha = pull["head"]["sha"]
        pull_author = pull["user"]["login"]
    except (KeyError, TypeError) as exc:
        raise HealthError("owner-emergency provider pull response is malformed") from exc
    _validate_sha(pull_head_sha)
    marker = (
        f"Main-health owner emergency: {manifest['issue']}\nIncident: {manifest['incident_digest']}"
    )
    if (
        pull_number != str(manifest["pull_request"])
        or pull_repository != manifest["repository"]
        or pull_base_sha != manifest["base_sha"]
        or pull_head_sha != expected_head_sha
        or pull_author.casefold() != repository_owner.casefold()
        or (pull.get("body") or "").count(marker) != 1
    ):
        raise HealthError("owner-emergency provider identity or marker is invalid")
    checked = _timestamp(checked_at)
    if checked > _timestamp(manifest["expires_at"]):
        raise HealthError("owner-emergency candidate manifest has expired")
    return {
        "authorization_mode": manifest["authorization_mode"],
        "base_sha": manifest["base_sha"],
        "checked_at": checked_at,
        "changed_paths": changed_paths,
        "collaboration_digest": collaboration_digest,
        "collaborators": collaborator_inventory,
        "head_sha": pull_head_sha,
        "incident_digest": manifest["incident_digest"],
        "issue": manifest["issue"],
        "manifest_digest": digest(manifest),
        "pending_invitations": invitation_inventory,
        "pull_request": pull_number,
        "repository": manifest["repository"],
        "schema_version": SCHEMA_VERSION,
        "status": "repair-candidate",
    }


def _json_argument(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return parsed


def _json_file_argument(value: str) -> dict[str, Any]:
    try:
        return _read(Path(value))
    except HealthError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _validate_current_provider_capture(retained: dict[str, Any], current: dict[str, Any]) -> None:
    if set(retained) != set(current):
        raise HealthError("retained and current provider evidence shapes differ")
    for field, value in retained.items():
        if field != "captured_at" and value != current[field]:
            raise HealthError(f"retained provider evidence is stale at {field}")
    if _timestamp(current["captured_at"]) < _timestamp(retained["captured_at"]):
        raise HealthError("current provider capture predates retained evidence")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--root", type=Path, required=True)
    ingest_parser.add_argument("--scope", required=True)
    ingest_parser.add_argument("--summary-json", type=_json_argument, required=True)
    ingest_parser.add_argument("--activation-policy-json", type=_json_argument)
    ingest_parser.add_argument("--expected-generation", type=int)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--root", type=Path, required=True)
    resolve_parser.add_argument("--authorization-json", type=_json_argument, required=True)
    resolve_parser.add_argument("--approval-evidence-json", type=_json_file_argument, required=True)
    resolve_parser.add_argument("--repaired-main-json", type=_json_argument, required=True)
    resolve_parser.add_argument("--expected-generation", type=int, required=True)
    resolve_parser.add_argument("--owner-admission-json", type=_json_file_argument)
    resolve_parser.add_argument("--owner-merge-gate-json", type=_json_file_argument)

    approval_parser = subparsers.add_parser("capture-approval")
    approval_parser.add_argument("--repository", required=True)
    approval_parser.add_argument("--pull-request", required=True)
    approval_parser.add_argument("--review-id", required=True)
    approval_parser.add_argument("--issue", required=True)
    approval_parser.add_argument("--incident-digest", required=True)

    admission_parser = subparsers.add_parser("capture-owner-admission")
    admission_parser.add_argument("--root", type=Path, required=True)
    admission_parser.add_argument("--repository", required=True)
    admission_parser.add_argument("--pull-request", required=True)
    admission_parser.add_argument("--issue", required=True)
    admission_parser.add_argument("--incident-digest", required=True)
    admission_parser.add_argument("--expected-head-sha", required=True)
    admission_parser.add_argument("--protection-ruleset-id", required=True)
    admission_parser.add_argument("--main-health-ruleset-id", required=True)

    merge_parser = subparsers.add_parser("merge-owner-emergency")
    merge_parser.add_argument("--root", type=Path, required=True)
    merge_parser.add_argument("--repository", required=True)
    merge_parser.add_argument("--pull-request", required=True)
    merge_parser.add_argument("--issue", required=True)
    merge_parser.add_argument("--incident-digest", required=True)
    merge_parser.add_argument("--admission-json", type=_json_file_argument, required=True)

    owner_parser = subparsers.add_parser("capture-owner-emergency")
    owner_parser.add_argument("--repository", required=True)
    owner_parser.add_argument("--pull-request", required=True)
    owner_parser.add_argument("--issue", required=True)
    owner_parser.add_argument("--incident-digest", required=True)
    owner_parser.add_argument("--admission-json", type=_json_file_argument, required=True)
    owner_parser.add_argument("--merge-gate-json", type=_json_file_argument, required=True)

    check_set_parser = subparsers.add_parser("github-check-set")
    check_set_parser.add_argument("--repository", required=True)
    check_set_parser.add_argument("--head-sha", required=True)
    check_set_parser.add_argument("--name", required=True)
    check_set_parser.add_argument("--external-id", required=True)
    check_set_parser.add_argument("--conclusion", choices=("failure", "success"), required=True)
    check_set_parser.add_argument("--details-url", required=True)
    check_set_parser.add_argument("--output-title", required=True)
    check_set_parser.add_argument("--output-summary", required=True)
    check_set_parser.add_argument("--app-id", type=int, required=True)
    check_set_parser.add_argument("--app-slug", required=True)

    check_get_parser = subparsers.add_parser("github-check-get")
    check_get_parser.add_argument("--repository", required=True)
    check_get_parser.add_argument("--head-sha", required=True)
    check_get_parser.add_argument("--name", required=True)
    check_get_parser.add_argument("--app-id", type=int, required=True)
    check_get_parser.add_argument("--app-slug", required=True)

    check_expire_parser = subparsers.add_parser("github-check-expire")
    check_expire_parser.add_argument("--repository", required=True)
    check_expire_parser.add_argument("--head-sha", required=True)
    check_expire_parser.add_argument("--check-run-id", type=int, required=True)
    check_expire_parser.add_argument("--name", required=True)
    check_expire_parser.add_argument("--external-id", required=True)
    check_expire_parser.add_argument("--details-url", required=True)
    check_expire_parser.add_argument("--output-title", required=True)
    check_expire_parser.add_argument("--output-summary", required=True)
    check_expire_parser.add_argument("--app-id", type=int, required=True)
    check_expire_parser.add_argument("--app-slug", required=True)

    subparsers.add_parser("github-provider-clock")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--root", type=Path, required=True)

    validate_git_parser = subparsers.add_parser("validate-git")
    validate_git_parser.add_argument("--root", type=Path, required=True)

    candidate_parser = subparsers.add_parser("candidate")
    candidate_parser.add_argument("--root", type=Path, required=True)
    candidate_parser.add_argument("--base-sha", required=True)
    candidate_parser.add_argument("--checked-at", required=True)
    candidate_parser.add_argument("--max-age-seconds", type=int, required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--root", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result: dict[str, Any]
    try:
        if args.command == "ingest":
            result = ingest(
                args.root,
                scope=args.scope,
                summary=args.summary_json,
                activation_policy=args.activation_policy_json,
                expected_generation=args.expected_generation,
            )
        elif args.command == "resolve":
            validate_git_history(args.root)
            authorization = args.authorization_json
            approval_evidence = args.approval_evidence_json
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise HealthError("GITHUB_TOKEN is required for provider authentication")
            if authorization.get("authorization_mode") == "independent-review":
                current_evidence = capture_github_approval(
                    repository=authorization["repository"],
                    pull_request=authorization["pull_request"],
                    review_id=authorization["approval_id"],
                    issue=authorization["issue"],
                    incident_digest=authorization["incident_digest"],
                    token=token,
                )
            elif authorization.get("authorization_mode") == "single-maintainer-owner-emergency":
                if args.owner_admission_json is None or args.owner_merge_gate_json is None:
                    raise HealthError("owner emergency resolution requires provider attestations")
                current_evidence = capture_github_owner_emergency(
                    repository=authorization["repository"],
                    pull_request=authorization["pull_request"],
                    issue=authorization["issue"],
                    incident_digest=authorization["incident_digest"],
                    admission=args.owner_admission_json,
                    merge_gate=args.owner_merge_gate_json,
                    token=token,
                )
            else:
                raise HealthError("operational resolver authorization mode is unsupported")
            _validate_current_provider_capture(approval_evidence, current_evidence)
            result = resolve(
                args.root,
                authorization=authorization,
                approval_evidence=approval_evidence,
                repaired_main=args.repaired_main_json,
                resolved_at=_github_provider_timestamp(token),
                expected_generation=args.expected_generation,
            )
        elif args.command == "capture-approval":
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise HealthError("GITHUB_TOKEN is required for provider authentication")
            result = capture_github_approval(
                repository=args.repository,
                pull_request=args.pull_request,
                review_id=args.review_id,
                issue=args.issue,
                incident_digest=args.incident_digest,
                token=token,
            )
        elif args.command == "capture-owner-emergency":
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise HealthError("GITHUB_TOKEN is required for provider authentication")
            result = capture_github_owner_emergency(
                repository=args.repository,
                pull_request=args.pull_request,
                issue=args.issue,
                incident_digest=args.incident_digest,
                admission=args.admission_json,
                merge_gate=args.merge_gate_json,
                token=token,
            )
        elif args.command == "capture-owner-admission":
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise HealthError("GITHUB_TOKEN is required for provider authentication")
            result = capture_github_owner_admission(
                root=args.root,
                repository=args.repository,
                pull_request=args.pull_request,
                issue=args.issue,
                incident_digest=args.incident_digest,
                expected_head_sha=args.expected_head_sha,
                protection_ruleset_id=args.protection_ruleset_id,
                main_health_ruleset_id=args.main_health_ruleset_id,
                token=token,
            )
        elif args.command == "merge-owner-emergency":
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise HealthError("GITHUB_TOKEN is required for provider authentication")
            result = merge_github_owner_emergency(
                root=args.root,
                repository=args.repository,
                pull_request=args.pull_request,
                issue=args.issue,
                incident_digest=args.incident_digest,
                admission_attestation=args.admission_json,
                token=token,
            )
        elif args.command in {
            "github-check-set",
            "github-check-get",
            "github-check-expire",
            "github-provider-clock",
        }:
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not token:
                raise HealthError(
                    "GH_TOKEN or GITHUB_TOKEN is required for provider authentication"
                )
            if args.command == "github-provider-clock":
                result = github_provider_clock(token)
            elif args.command == "github-check-set":
                result = set_github_check_run(
                    repository=args.repository,
                    head_sha=args.head_sha,
                    name=args.name,
                    external_id=args.external_id,
                    conclusion=args.conclusion,
                    details_url=args.details_url,
                    output_title=args.output_title,
                    output_summary=args.output_summary,
                    app_id=args.app_id,
                    app_slug=args.app_slug,
                    token=token,
                )
            elif args.command == "github-check-get":
                result = get_github_check_run(
                    repository=args.repository,
                    head_sha=args.head_sha,
                    name=args.name,
                    app_id=args.app_id,
                    app_slug=args.app_slug,
                    token=token,
                )
            else:
                result = expire_github_check_run(
                    repository=args.repository,
                    head_sha=args.head_sha,
                    check_run_id=args.check_run_id,
                    name=args.name,
                    external_id=args.external_id,
                    details_url=args.details_url,
                    output_title=args.output_title,
                    output_summary=args.output_summary,
                    app_id=args.app_id,
                    app_slug=args.app_slug,
                    token=token,
                )
        elif args.command == "validate":
            result = validate_history(args.root)
        elif args.command == "validate-git":
            result = validate_git_history(args.root)
        elif args.command == "candidate":
            validate_git_history(args.root)
            result = validate_candidate(
                args.root,
                base_sha=args.base_sha,
                checked_at=args.checked_at,
                max_age_seconds=args.max_age_seconds,
            )
        else:
            state = _load_state(args.root)
            result = state or {"schema_version": SCHEMA_VERSION, "status": "not_measured"}
    except (HealthError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"main health validation failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
