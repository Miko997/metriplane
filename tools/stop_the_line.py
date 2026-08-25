# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Durable, append-only main-health state and repair authorization controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.error
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


def github_approval_evidence(
    *,
    pull: dict[str, Any],
    review: dict[str, Any],
    reviews: list[dict[str, Any]],
    files: list[dict[str, Any]],
    repository: str,
    pull_request: str,
    issue: str,
) -> dict[str, Any]:
    """Normalize provider responses into exact repair-approval evidence."""
    latest: dict[str, dict[str, Any]] = {}
    for candidate in sorted(reviews, key=lambda item: (item.get("submitted_at") or "", item["id"])):
        login = candidate.get("user", {}).get("login")
        if login:
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
    marker = f"Main-health repair authorization: {issue}"
    if (review.get("body") or "").strip() != marker:
        raise HealthError("GitHub repair review does not bind the exact issue")
    changed_paths = sorted({item["filename"] for item in files})
    if not changed_paths or len(changed_paths) != len(files):
        raise HealthError("GitHub repair file inventory is empty or duplicated")
    return {
        "approval_id": str(review["id"]),
        "approval_provider": "github",
        "author": pull["user"]["login"],
        "author_id": str(pull["user"]["id"]),
        "captured_at": review["submitted_at"],
        "changed_paths": changed_paths,
        "commit_sha": pull["head"]["sha"],
        "issue": issue,
        "pull_request": pull_request,
        "repository": repository,
        "reviewer": review["user"]["login"],
        "reviewer_id": str(review["user"]["id"]),
        "schema_version": SCHEMA_VERSION,
        "state": review["state"],
    }


def _github_get(path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise HealthError(f"GitHub approval capture failed: {exc}") from exc


def capture_github_approval(
    *, repository: str, pull_request: str, review_id: str, issue: str, token: str
) -> dict[str, Any]:
    """Fetch exact provider state for one GitHub repair review."""
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise HealthError("invalid GitHub repository identity")
    if not pull_request.isdigit() or not review_id.isdigit():
        raise HealthError("GitHub pull request and review IDs must be numeric")
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
    return github_approval_evidence(
        pull=pull,
        review=review,
        reviews=reviews,
        files=files,
        repository=repository,
        pull_request=pull_request,
        issue=issue,
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
        "approval_digest",
        "approval_id",
        "approval_provider",
        "allowed_paths",
        "author",
        "author_id",
        "changed_paths_digest",
        "expires_at",
        "failing_obligations",
        "issue",
        "proposed_repair_sha",
        "pull_request",
        "repository",
        "required_cadences",
        "reviewer",
        "reviewer_id",
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
            "author",
            "author_id",
            "expires_at",
            "issue",
            "proposed_repair_sha",
            "pull_request",
            "repository",
            "reviewer",
            "reviewer_id",
        )
    ):
        raise HealthError("repair authorization identities must be non-empty strings")
    if (
        not re.fullmatch(r"[A-Z]+-[0-9]+", authorization["issue"])
        or not re.fullmatch(r"[^/\s]+/[^/\s]+", authorization["repository"])
        or not authorization["pull_request"].isdigit()
    ):
        raise HealthError("repair authorization provider identities are invalid")
    if authorization["approval_provider"] not in {"github", "linear"}:
        raise HealthError("repair approval provider is unsupported")
    if authorization["reviewer_id"] == authorization["author_id"]:
        raise HealthError("repair authorization must be approved by a non-author")
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
        "approval_id",
        "approval_provider",
        "author",
        "author_id",
        "captured_at",
        "changed_paths",
        "commit_sha",
        "issue",
        "pull_request",
        "repository",
        "reviewer",
        "reviewer_id",
        "schema_version",
        "state",
    }
    if (
        set(approval_evidence) != expected_evidence
        or approval_evidence["schema_version"] != SCHEMA_VERSION
        or approval_evidence["state"] != "APPROVED"
        or digest(approval_evidence) != authorization["approval_digest"]
    ):
        raise HealthError("provider approval evidence is invalid")
    _timestamp(approval_evidence["captured_at"])
    for field in (
        "approval_id",
        "approval_provider",
        "author",
        "author_id",
        "issue",
        "pull_request",
        "repository",
        "reviewer",
        "reviewer_id",
    ):
        if approval_evidence[field] != authorization[field]:
            raise HealthError(f"provider approval evidence disagrees on {field}")
    if (
        approval_evidence["commit_sha"] != repaired_main_sha
        or authorization["proposed_repair_sha"] != repaired_main_sha
    ):
        raise HealthError("repair evidence does not bind the repaired SHA")
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
        or not set(changed_paths) <= set(allowed_paths)
    ):
        raise HealthError("repair changed paths are invalid or unauthorized")
    if _timestamp(resolved_at) > _timestamp(authorization["expires_at"]):
        raise HealthError("repair authorization has expired")
    if sorted(authorization["failing_obligations"]) != sorted(incident["failing_obligations"]):
        raise HealthError("authorization does not bind the exact failing obligations")
    declared_cadences = authorization["required_cadences"]
    if (
        not isinstance(declared_cadences, list)
        or len(declared_cadences) != len(set(declared_cadences))
        or not set(declared_cadences) <= {"nightly", "weekly"}
    ):
        raise HealthError("repair cadence requirements are invalid")
    return declared_cadences


def resolve(
    root: Path,
    *,
    authorization: dict[str, Any],
    approval_evidence: dict[str, Any],
    repaired_main: dict[str, Any],
    resolved_at: str,
    expected_generation: int,
) -> dict[str, Any]:
    """Clear red only through an exact non-author-approved repair."""
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
    _validate_repair_binding(
        authorization=authorization,
        approval_evidence=approval_evidence,
        incident=incident,
        repaired_main_sha=repaired_main["sha"],
        resolved_at=resolved_at,
    )

    required_auth = {
        "approval_digest",
        "approval_id",
        "approval_provider",
        "allowed_paths",
        "author",
        "author_id",
        "changed_paths_digest",
        "expires_at",
        "failing_obligations",
        "issue",
        "proposed_repair_sha",
        "pull_request",
        "repository",
        "required_cadences",
        "reviewer",
        "reviewer_id",
        "schema_version",
    }
    if set(authorization) != required_auth:
        raise HealthError("repair authorization shape is invalid")
    if authorization["schema_version"] != SCHEMA_VERSION:
        raise HealthError("unsupported repair authorization schema")
    if authorization["approval_provider"] not in {"github", "linear"}:
        raise HealthError("repair approval provider is unsupported")
    if len(authorization["approval_digest"]) != 64 or any(
        character not in "0123456789abcdef" for character in authorization["approval_digest"]
    ):
        raise HealthError("repair approval digest is invalid")
    if authorization["reviewer_id"] == authorization["author_id"]:
        raise HealthError("repair authorization must be approved by a non-author")
    expected_evidence = {
        "approval_id",
        "approval_provider",
        "author",
        "author_id",
        "captured_at",
        "changed_paths",
        "commit_sha",
        "issue",
        "pull_request",
        "repository",
        "reviewer",
        "reviewer_id",
        "schema_version",
        "state",
    }
    if set(approval_evidence) != expected_evidence:
        raise HealthError("provider approval evidence shape is invalid")
    if approval_evidence["schema_version"] != SCHEMA_VERSION:
        raise HealthError("unsupported provider approval evidence schema")
    _timestamp(approval_evidence["captured_at"])
    if approval_evidence["state"] != "APPROVED":
        raise HealthError("provider review is not approved")
    if digest(approval_evidence) != authorization["approval_digest"]:
        raise HealthError("provider approval evidence digest mismatch")
    for field in (
        "approval_id",
        "approval_provider",
        "author",
        "author_id",
        "issue",
        "pull_request",
        "repository",
        "reviewer",
        "reviewer_id",
    ):
        if approval_evidence[field] != authorization[field]:
            raise HealthError(f"provider approval evidence disagrees on {field}")
    if approval_evidence["commit_sha"] != repaired_main["sha"]:
        raise HealthError("provider approval does not bind the repaired SHA")
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
    ):
        raise HealthError("provider changed paths are invalid")
    if digest(sorted(changed_paths)) != authorization["changed_paths_digest"]:
        raise HealthError("authorization does not bind the exact changed paths")
    if _timestamp(resolved_at) > _timestamp(authorization["expires_at"]):
        raise HealthError("repair authorization has expired")
    if authorization["proposed_repair_sha"] != repaired_main["sha"]:
        raise HealthError("repair SHA does not match authorization")
    if sorted(authorization["failing_obligations"]) != sorted(incident["failing_obligations"]):
        raise HealthError("authorization does not bind the exact failing obligations")
    if not set(changed_paths) <= set(authorization["allowed_paths"]):
        raise HealthError("repair changes exceed the authorized paths")
    declared_cadences = authorization["required_cadences"]
    if (
        not isinstance(declared_cadences, list)
        or len(declared_cadences) != len(set(declared_cadences))
        or not set(declared_cadences) <= {"nightly", "weekly"}
    ):
        raise HealthError("repair cadence requirements are invalid")
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
    resolution = {
        "authorization_digest": authorization_digest,
        "incident_digest": state["incident_digest"],
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
            incident = _read(root / "incidents" / f"{state['incident_digest']}.json")
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
                or digest(incident) != state["incident_digest"]
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
    incident_digests = {state["incident_digest"]} if state["incident_digest"] else set()
    for resolution_digest in repair_resolution_digests:
        path = root / "resolutions" / f"{resolution_digest}.json"
        resolution = _read(path)
        if digest(resolution) != resolution_digest:
            raise HealthError("resolution filename digest mismatch")
        incident_digest = resolution["incident_digest"]
        incident = _read(root / "incidents" / f"{incident_digest}.json")
        if digest(incident) != incident_digest:
            raise HealthError("resolved incident digest mismatch")
        incident_digests.add(incident_digest)
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
        if (
            resolution["repaired_main_sha"] != authorization["proposed_repair_sha"]
            or evidence["commit_sha"] != resolution["repaired_main_sha"]
            or resolution["repaired_main_sha"] != repair_history[resolution_digest]["sha"]
            or resolution["resolved_at"] != repair_history[resolution_digest]["recorded_at"]
        ):
            raise HealthError("resolution evidence disagrees on the repaired SHA")
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
        "repair-authorizations": authorization_digests,
        "resolutions": resolution_digests,
    }
    for directory, expected in stored.items():
        actual = {path.stem for path in (root / directory).glob("*.json")}
        if actual != expected:
            raise HealthError(f"{directory} contains missing or orphaned evidence")
    return {
        "activation_digest": state["activation_digest"],
        "generation": state["generation"],
        "history_head": state["history_head"],
        "schema_version": SCHEMA_VERSION,
        "status": state["status"],
    }


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


def _json_argument(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return parsed


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
    resolve_parser.add_argument("--repaired-main-json", type=_json_argument, required=True)
    resolve_parser.add_argument("--resolved-at", required=True)
    resolve_parser.add_argument("--expected-generation", type=int, required=True)

    approval_parser = subparsers.add_parser("capture-approval")
    approval_parser.add_argument("--repository", required=True)
    approval_parser.add_argument("--pull-request", required=True)
    approval_parser.add_argument("--review-id", required=True)
    approval_parser.add_argument("--issue", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--root", type=Path, required=True)

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
            authorization = args.authorization_json
            if authorization.get("approval_provider") != "github":
                raise HealthError("the operational resolver requires a GitHub approval")
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise HealthError("GITHUB_TOKEN is required for provider authentication")
            approval_evidence = capture_github_approval(
                repository=authorization["repository"],
                pull_request=authorization["pull_request"],
                review_id=authorization["approval_id"],
                issue=authorization["issue"],
                token=token,
            )
            result = resolve(
                args.root,
                authorization=authorization,
                approval_evidence=approval_evidence,
                repaired_main=args.repaired_main_json,
                resolved_at=args.resolved_at,
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
                token=token,
            )
        elif args.command == "validate":
            result = validate_history(args.root)
        elif args.command == "candidate":
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
