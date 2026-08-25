# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate the canonical release-blocker registry and enforce release blocking."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, TypedDict, cast

SCHEMA_VERSION = "metriplane.blockers.v1"
POLICY_VERSION = "MP2-006.v1"
REPORT_VERSION = "metriplane.blocker-check.v1"
SCHEMA_ID = "https://metriplane.com/schemas/metriplane.blockers.v1.schema.json"
SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
REGISTRY_PATH = "docs/status/blockers.json"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_COMMIT_FILES_LIMIT = 3000
GITHUB_PULL_COMMITS_LIMIT = 250
_GITHUB_ACTOR_RE = re.compile(r"github:([1-9][0-9]*)\Z")
_GITHUB_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
_GITHUB_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_GITHUB_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_GITHUB_REVIEW_STATES = {
    "APPROVED",
    "CHANGES_REQUESTED",
    "COMMENTED",
    "DISMISSED",
    "PENDING",
}
_GITHUB_REVIEWER_PERMISSIONS = {"admin", "maintain", "write"}
_IMMUTABLE_BLOCKER_FIELDS = {
    "id",
    "reported_by_actor_id",
    "opened_at",
    "initial_severity",
    "initial_security",
    "source",
}


class Evidence(TypedDict):
    path: str
    sha256: str
    kind: str
    producer_actor_id: str


class Approval(TypedDict):
    provider: str
    repository: str
    pull_request: int
    subject_sha256: str


class ApprovalContext(TypedDict):
    repo_root: Path
    expected_repository: str | None
    expected_pull_request: int | None
    expected_change_sha: str | None
    validated_sha: str | None
    require_merged_approval: bool
    github_token: str | None
    changed_action_keys: set[tuple[str, str]]
    history_errors: list[str]


class Downgrade(TypedDict):
    from_severity: str
    to_severity: str
    from_security: bool
    to_security: bool
    changed_by_actor_id: str
    changed_at: str
    reproduction_evidence: list[Evidence]
    control_evidence: list[Evidence]
    approval: Approval


class Closure(TypedDict):
    closed_by_actor_id: str
    closed_at: str
    resolution_evidence: list[Evidence]
    control_evidence: list[Evidence]
    approval: Approval


class Blocker(TypedDict):
    id: str
    title: str
    owner: str
    reported_by_actor_id: str
    opened_at: str
    initial_severity: str
    severity: str
    initial_security: bool
    security: bool
    status: str
    source: str
    acceptance_ids: list[str]
    downgrade: Downgrade | None
    closure: Closure | None


class Registry(TypedDict):
    schema_version: str
    policy_version: str
    blockers: list[Blocker]


class PolicyInputError(Exception):
    """A stable fail-closed input error."""


def _fail(message: str) -> NoReturn:
    raise PolicyInputError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _strict_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _fail(f"cannot read {path}: {exc}")
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(f"{path}: UTF-8 BOM is prohibited")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        _fail(f"{path}: invalid UTF-8 at byte {exc.start}")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=lambda token: _fail(f"{path}: non-finite number {token}"),
        )
    except json.JSONDecodeError as exc:
        _fail(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}")


@lru_cache(maxsize=1)
def _load_baseline_validator(
    repo_root: Path,
) -> tuple[Callable[[Any, dict[str, Any]], None], type[Exception]]:
    module_path = repo_root / "tools" / "baseline_snapshot.py"
    spec = importlib.util.spec_from_file_location("metriplane_blocker_schema_engine", module_path)
    if spec is None or spec.loader is None:
        _fail(f"cannot load schema engine: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    validator = getattr(module, "_internal_validate", None)
    error_type = getattr(module, "SnapshotError", None)
    if not callable(validator):
        _fail("baseline schema engine does not expose _internal_validate")
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("baseline schema engine does not expose SnapshotError")
    return (
        cast(Callable[[Any, dict[str, Any]], None], validator),
        error_type,
    )


def _validate_schema_contract(schema: dict[str, Any]) -> None:
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        _fail("schema draft identity is not exact")
    if schema.get("$id") != SCHEMA_ID:
        _fail("schema $id is not exact")
    if schema.get("additionalProperties") is not False:
        _fail("registry schema must reject unknown root fields")
    properties = schema.get("properties")
    definitions = schema.get("$defs")
    if not isinstance(properties, dict) or not isinstance(definitions, dict):
        _fail("schema properties and $defs must be objects")
    if set(schema.get("required", [])) != {"schema_version", "policy_version", "blockers"}:
        _fail("registry schema required field set is not exact")
    if properties.get("schema_version") != {"const": SCHEMA_VERSION}:
        _fail("schema_version const is not exact")
    if properties.get("policy_version") != {"const": POLICY_VERSION}:
        _fail("policy_version const is not exact")
    required_definitions = {
        "actor_id",
        "approval",
        "blocker",
        "closure",
        "downgrade",
        "evidence",
        "severity",
        "sha256",
        "timestamp",
    }
    if set(definitions) != required_definitions:
        _fail("schema $defs set is not exact")
    object_fields = {
        "approval": {
            "provider",
            "repository",
            "pull_request",
            "subject_sha256",
        },
        "blocker": {
            "id",
            "title",
            "owner",
            "reported_by_actor_id",
            "opened_at",
            "initial_severity",
            "severity",
            "initial_security",
            "security",
            "status",
            "source",
            "acceptance_ids",
            "downgrade",
            "closure",
        },
        "closure": {
            "closed_by_actor_id",
            "closed_at",
            "resolution_evidence",
            "control_evidence",
            "approval",
        },
        "downgrade": {
            "from_severity",
            "to_severity",
            "from_security",
            "to_security",
            "changed_by_actor_id",
            "changed_at",
            "reproduction_evidence",
            "control_evidence",
            "approval",
        },
        "evidence": {"path", "sha256", "kind", "producer_actor_id"},
    }
    for name, expected_fields in object_fields.items():
        definition = definitions[name]
        if not isinstance(definition, dict) or definition.get("additionalProperties") is not False:
            _fail(f"schema definition {name!r} must reject unknown fields")
        defined_properties = definition.get("properties")
        if not isinstance(defined_properties, dict):
            _fail(f"schema definition {name!r} properties must be an object")
        if set(defined_properties) != expected_fields or set(definition.get("required", [])) != (
            expected_fields
        ):
            _fail(f"schema definition {name!r} field set is not exact")


def _schema_validate(instance: Any, schema: dict[str, Any]) -> None:
    validator, schema_error = _load_baseline_validator(Path(__file__).resolve().parents[1])
    try:
        validator(instance, schema)
    except schema_error as exc:
        code = getattr(exc, "code", "SCHEMA_VALIDATION_FAILED")
        message = getattr(exc, "message", str(exc))
        _fail(f"{code}: {message}")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _action_digests(value: Any) -> dict[tuple[str, str], str]:
    if not isinstance(value, dict) or not isinstance(value.get("blockers"), list):
        _fail("base blocker registry has a malformed root")
    result: dict[tuple[str, str], str] = {}
    for blocker in value["blockers"]:
        if not isinstance(blocker, dict) or not isinstance(blocker.get("id"), str):
            _fail("base blocker registry contains a malformed blocker")
        for action in ("downgrade", "closure"):
            record = blocker.get(action)
            if record is not None:
                if not isinstance(record, dict):
                    _fail(f"base blocker registry contains a malformed {action}")
                result[(blocker["id"], action)] = _sha256(record)
    return result


def _require_local_commit(repo_root: Path, sha: str, label: str) -> None:
    root = repo_root.resolve(strict=True)
    commit = subprocess.run(
        ["/usr/bin/git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if commit.returncode != 0:
        _fail(f"{label} is not an available local commit")


def _strict_json_bytes(raw: bytes, label: str) -> Any:
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(f"{label} contains a prohibited UTF-8 BOM")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, item in pairs:
            if key in parsed:
                _fail(f"{label} contains duplicate JSON key {key!r}")
            parsed[key] = item
        return parsed

    try:
        return json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda token: _fail(f"{label} contains non-finite number {token}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not strict UTF-8 JSON: {exc}")


def _base_registry(repo_root: Path, base_sha: str) -> Registry | None:
    root = repo_root.resolve(strict=True)
    _require_local_commit(root, base_sha, "GitHub base SHA")
    exists = subprocess.run(
        ["/usr/bin/git", "cat-file", "-e", f"{base_sha}:{REGISTRY_PATH}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if exists.returncode != 0:
        return None
    captured = subprocess.run(
        ["/usr/bin/git", "show", f"{base_sha}:{REGISTRY_PATH}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if captured.returncode != 0:
        _fail("cannot read the blocker registry at the GitHub base SHA")
    value = _strict_json_bytes(captured.stdout, "base blocker registry")
    if not isinstance(value, dict) or not isinstance(value.get("blockers"), list):
        _fail("base blocker registry has a malformed root")
    _action_digests(value)
    return cast(Registry, value)


def _history_errors(registry: Registry, base: Registry | None) -> list[str]:
    if base is None:
        return []
    errors: list[str] = []
    current_by_id = {blocker["id"]: blocker for blocker in registry["blockers"]}
    base_by_id = {blocker["id"]: blocker for blocker in base["blockers"]}
    if len(base_by_id) != len(base["blockers"]):
        return ["base blocker registry contains duplicate blocker IDs"]
    for blocker_id, retained in base_by_id.items():
        current = current_by_id.get(blocker_id)
        if current is None:
            errors.append(
                f"{blocker_id}: retained blocker was removed; registry history is append-only"
            )
            continue
        current_fields = cast(dict[str, Any], current)
        retained_fields = cast(dict[str, Any], retained)
        for field in sorted(_IMMUTABLE_BLOCKER_FIELDS):
            if current_fields[field] != retained_fields[field]:
                errors.append(f"{blocker_id}: immutable field {field} was rewritten")
        for action in ("downgrade", "closure"):
            retained_action = retained_fields[action]
            if retained_action is not None and current_fields[action] != retained_action:
                errors.append(
                    f"{blocker_id}: retained {action} record was removed or rewritten; "
                    "action history is append-only"
                )
    return errors


def _changed_action_keys(
    registry: Registry, base: Registry | None, has_pull_context: bool
) -> set[tuple[str, str]]:
    current = _action_digests(registry)
    if not has_pull_context:
        return set()
    if base is None:
        return set(current)
    retained = _action_digests(base)
    return {key for key, digest in current.items() if retained.get(key) != digest}


def _clean_evidence_path(relative: str) -> str:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or relative != pure.as_posix()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        _fail(f"evidence path is not a clean repository-relative path: {relative!r}")
    return pure.as_posix()


def _evidence_blob(repo_root: Path, validated_sha: str, relative: str) -> bytes:
    clean = _clean_evidence_path(relative)
    root = repo_root.resolve(strict=True)
    tree = subprocess.run(
        ["/usr/bin/git", "ls-tree", "-z", validated_sha, "--", clean],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if tree.returncode != 0:
        _fail(f"cannot inspect evidence at validated commit: {relative!r}")
    records = [record for record in tree.stdout.split(b"\0") if record]
    if len(records) != 1:
        _fail(f"evidence is not tracked at the validated commit: {relative!r}")
    try:
        metadata, encoded_path = records[0].split(b"\t", 1)
        mode, object_type, _object_id = metadata.split(b" ", 2)
        tracked_path = encoded_path.decode("utf-8", "strict")
    except (UnicodeDecodeError, ValueError):
        _fail(f"evidence tree entry is malformed at the validated commit: {relative!r}")
    if tracked_path != clean or object_type != b"blob" or mode not in {b"100644", b"100755"}:
        _fail(f"evidence is not a tracked regular file at the validated commit: {relative!r}")
    captured = subprocess.run(
        ["/usr/bin/git", "show", f"{validated_sha}:{clean}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if captured.returncode != 0:
        _fail(f"cannot read evidence blob at the validated commit: {relative!r}")
    return captured.stdout


def _check_evidence(
    blocker_id: str,
    records: list[Evidence],
    expected_kind: str,
    repo_root: Path,
    validated_sha: str | None,
    errors: list[str],
) -> None:
    identities = [_canonical_bytes(record) for record in records]
    if len(identities) != len(set(identities)):
        errors.append(f"{blocker_id}: duplicate {expected_kind} evidence record")
    for record in records:
        if record["kind"] != expected_kind:
            errors.append(
                f"{blocker_id}: expected {expected_kind} evidence, found {record['kind']}"
            )
        if validated_sha is None:
            errors.append(f"{blocker_id}: --validated-sha is required for governed evidence")
            continue
        try:
            blob = _evidence_blob(repo_root, validated_sha, record["path"])
        except PolicyInputError as exc:
            errors.append(f"{blocker_id}: {exc}")
            continue
        digest = hashlib.sha256(blob).hexdigest()
        if digest != record["sha256"]:
            errors.append(
                f"{blocker_id}: evidence SHA-256 mismatch at validated commit: {record['path']}"
            )


def _github_get(path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (OSError, ValueError, TimeoutError) as exc:
        raise PolicyInputError(f"GitHub approval verification failed: {exc}") from exc


def _github_pages(path: str, token: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, 101):
        separator = "&" if "?" in path else "?"
        value = _github_get(f"{path}{separator}per_page=100&page={page}", token)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            _fail(f"GitHub approval verification returned a malformed array for {path}")
        batch = cast(list[dict[str, Any]], value)
        if len(batch) > 100:
            _fail(f"GitHub approval verification exceeded the requested page size for {path}")
        records.extend(batch)
        if len(batch) < 100:
            return records
    _fail(f"GitHub approval verification exceeded the page limit for {path}")


def _provider_actor_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    actor_id = value.get("id")
    if isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id <= 0:
        return None
    if value.get("type") != "User":
        return None
    return f"github:{actor_id}"


def _provider_actor_identity(value: Any) -> tuple[str, str] | None:
    actor_id = _provider_actor_id(value)
    if actor_id is None or not isinstance(value, dict):
        return None
    login = value.get("login")
    if not isinstance(login, str) or _GITHUB_LOGIN_RE.fullmatch(login) is None:
        return None
    return actor_id, login


def _github_reviewer_authorized(*, repository: str, reviewer: str, login: str, token: str) -> bool:
    value = _github_get(f"repos/{repository}/collaborators/{login}/permission", token)
    if not isinstance(value, dict):
        _fail("GitHub reviewer permission response is malformed")
    permission = value.get("permission")
    provider_user = _provider_actor_identity(value.get("user"))
    if provider_user is None or provider_user != (reviewer, login):
        _fail("GitHub reviewer permission identity is malformed or mismatched")
    return permission in _GITHUB_REVIEWER_PERMISSIONS


def _approval_marker(
    *,
    repository: str,
    pull_request: int,
    change_sha: str,
    blocker_id: str,
    action: str,
    subject_sha256: str,
) -> str:
    return "\n".join(
        (
            "METRIPLANE_BLOCKER_APPROVAL_V1",
            f"repository={repository}",
            f"pull_request={pull_request}",
            f"change_sha={change_sha}",
            f"blocker_id={blocker_id}",
            f"action={action}",
            f"subject_sha256={subject_sha256}",
        )
    )


def _github_registry_change_actors(
    *, repository: str, pull_request: int, expected_commit_count: int, token: str
) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    files = _github_pages(f"repos/{repository}/pulls/{pull_request}/files", token)
    filenames = [item.get("filename") for item in files]
    if any(not isinstance(filename, str) for filename in filenames):
        return set(), ["provider pull request file inventory is malformed"]
    if REGISTRY_PATH not in filenames:
        return set(), [f"provider pull request does not change {REGISTRY_PATH}"]
    if len(filenames) != len(set(cast(list[str], filenames))):
        errors.append("provider pull request file inventory contains duplicates")

    actors: set[str] = set()
    registry_commit_found = False
    if expected_commit_count > GITHUB_PULL_COMMITS_LIMIT:
        return set(), [
            "provider pull request commit count exceeds the verifiable REST inventory limit"
        ]
    commits = _github_pages(f"repos/{repository}/pulls/{pull_request}/commits", token)
    if not commits:
        return set(), ["provider pull request commit inventory is empty"]
    if len(commits) != expected_commit_count:
        return set(), ["provider pull request commit inventory count is incomplete"]
    commit_shas = [commit.get("sha") for commit in commits]
    if any(not isinstance(sha, str) or _GIT_SHA_RE.fullmatch(sha) is None for sha in commit_shas):
        return set(), ["provider pull request contains a malformed commit SHA"]
    if len(commit_shas) != len(set(cast(list[str], commit_shas))):
        return set(), ["provider pull request commit inventory contains duplicates"]
    for commit in commits:
        sha = commit.get("sha")
        if not isinstance(sha, str) or _GIT_SHA_RE.fullmatch(sha) is None:
            errors.append("provider pull request contains a malformed commit SHA")
            continue
        changed: list[Any] = []
        detail: dict[str, Any] | None = None
        for page in range(1, 101):
            value = _github_get(f"repos/{repository}/commits/{sha}?per_page=100&page={page}", token)
            if not isinstance(value, dict) or not isinstance(value.get("files"), list):
                errors.append(f"provider commit {sha} has no verifiable file inventory")
                detail = None
                break
            if value.get("sha") != sha:
                errors.append(f"provider commit {sha} detail identity is unbound")
                detail = None
                break
            if detail is None:
                detail = value
            else:
                for role in ("author", "committer"):
                    if _provider_actor_id(value.get(role)) != _provider_actor_id(detail.get(role)):
                        errors.append(f"provider commit {sha} identity changed between file pages")
                        detail = None
                        break
                if detail is None:
                    break
            page_files = cast(list[Any], value["files"])
            changed.extend(
                item.get("filename") if isinstance(item, dict) else None for item in page_files
            )
            if len(changed) >= GITHUB_COMMIT_FILES_LIMIT and len(page_files) == 100:
                errors.append(
                    f"provider commit {sha} file inventory reached the unverifiable REST limit"
                )
                detail = None
                break
            if len(page_files) < 100:
                break
        else:
            errors.append(f"provider commit {sha} file inventory exceeded the page limit")
            detail = None
        if detail is None:
            continue
        if any(not isinstance(filename, str) for filename in changed):
            errors.append(f"provider commit {sha} file inventory is malformed")
            continue
        if len(changed) != len(set(cast(list[str], changed))):
            errors.append(f"provider commit {sha} file inventory contains duplicates")
            continue
        if REGISTRY_PATH not in changed:
            continue
        registry_commit_found = True
        for role in ("author", "committer"):
            actor = _provider_actor_id(detail.get(role))
            if actor is None:
                errors.append(
                    f"provider commit {sha} registry-change {role} has no linked human identity"
                )
            else:
                actors.add(actor)
    if not registry_commit_found:
        errors.append("no provider commit verifiably owns the blocker registry change")
    return actors, errors


def _git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["/usr/bin/git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo_root.resolve(strict=True),
        capture_output=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        _fail("cannot verify approval merge ancestry in the local checkout")
    return result.returncode == 0


def _verify_github_approval(
    *,
    blocker: Blocker,
    approval: Approval,
    action_actor_id: str,
    action: str,
    action_at: str,
    context: ApprovalContext,
) -> list[str]:
    prefix = blocker["id"]
    repository = approval["repository"]
    pull_request = approval["pull_request"]
    errors: list[str] = []
    if _GITHUB_REPOSITORY_RE.fullmatch(repository) is None:
        return [f"{prefix}: GitHub approval repository identity is invalid"]
    expected_repository = context["expected_repository"]
    if expected_repository is not None and repository != expected_repository:
        errors.append(f"{prefix}: approval is bound to the wrong repository")
    expected_pull_request = context["expected_pull_request"]
    action_changed = (blocker["id"], action) in context["changed_action_keys"]
    if (
        action_changed
        and expected_pull_request is not None
        and pull_request != expected_pull_request
    ):
        errors.append(f"{prefix}: approval is not bound to the current pull request")
    for label, actor_id in (
        ("reporter", blocker["reported_by_actor_id"]),
        ("action actor", action_actor_id),
    ):
        if _GITHUB_ACTOR_RE.fullmatch(actor_id) is None:
            errors.append(
                f"{prefix}: {label} lacks a comparable provider-authenticated GitHub actor ID"
            )
    token = context["github_token"]
    if token is None or not token.strip():
        errors.append(f"{prefix}: GitHub provider token is required for live approval verification")
    if errors:
        return errors
    assert token is not None

    try:
        pull = _github_get(f"repos/{repository}/pulls/{pull_request}", token)
        if not isinstance(pull, dict):
            _fail("GitHub approval verification returned a malformed pull request")
        base = pull.get("base")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        base_repository = base_repo.get("full_name") if isinstance(base_repo, dict) else None
        if (
            not isinstance(base_repository, str)
            or base_repository.casefold() != repository.casefold()
        ):
            errors.append(f"{prefix}: provider pull request belongs to the wrong repository")
        if pull.get("number") != pull_request:
            errors.append(f"{prefix}: provider pull request identity is unbound")
        expected_commit_count = pull.get("commits")
        if (
            isinstance(expected_commit_count, bool)
            or not isinstance(expected_commit_count, int)
            or expected_commit_count <= 0
        ):
            errors.append(f"{prefix}: provider pull request commit count is malformed")
            expected_commit_count = 0
        head = pull.get("head")
        head_sha = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(head_sha, str) or _GIT_SHA_RE.fullmatch(head_sha) is None:
            errors.append(f"{prefix}: provider pull request head SHA is malformed")
            return errors
        expected_change_sha = context["expected_change_sha"]
        if action_changed and expected_change_sha is not None and head_sha != expected_change_sha:
            errors.append(
                f"{prefix}: provider pull request head is stale or not the validation SHA"
            )
        validated_sha = context["validated_sha"]
        if context["require_merged_approval"]:
            merge_sha = pull.get("merge_commit_sha")
            merged_at = pull.get("merged_at")
            if (
                pull.get("merged") is not True
                or pull.get("state") != "closed"
                or not isinstance(merge_sha, str)
                or _GIT_SHA_RE.fullmatch(merge_sha) is None
                or not isinstance(merged_at, str)
                or _GITHUB_TIMESTAMP_RE.fullmatch(merged_at) is None
            ):
                errors.append(f"{prefix}: approval pull request is not verifiably merged")
            elif validated_sha is None:
                errors.append(f"{prefix}: merged approval requires an exact validated release SHA")
            else:
                try:
                    _parse_timestamp(merged_at)
                    _require_local_commit(
                        context["repo_root"], merge_sha, "provider approval merge SHA"
                    )
                    if not _git_is_ancestor(context["repo_root"], merge_sha, validated_sha):
                        errors.append(
                            f"{prefix}: approval merge is not an ancestor of the validated "
                            "release SHA"
                        )
                except (PolicyInputError, ValueError) as exc:
                    errors.append(f"{prefix}: merged approval ancestry is invalid: {exc}")
        pull_author = _provider_actor_id(pull.get("user"))
        if pull_author is None:
            errors.append(f"{prefix}: pull-request author has no linked human provider identity")
        registry_actors, actor_errors = _github_registry_change_actors(
            repository=repository,
            pull_request=pull_request,
            expected_commit_count=expected_commit_count,
            token=token,
        )
        errors.extend(f"{prefix}: {error}" for error in actor_errors)
        if errors:
            return errors

        reviews = _github_pages(f"repos/{repository}/pulls/{pull_request}/reviews", token)
    except PolicyInputError as exc:
        return [f"{prefix}: {exc}"]

    submitted_reviews: list[tuple[str, int, str, str, dict[str, Any]]] = []
    malformed_reviews = False
    review_ids: set[int] = set()
    for review in reviews:
        review_id = review.get("id")
        if isinstance(review_id, bool) or not isinstance(review_id, int) or review_id <= 0:
            malformed_reviews = True
            continue
        if review_id in review_ids:
            malformed_reviews = True
            continue
        review_ids.add(review_id)
        reviewer_identity = _provider_actor_identity(review.get("user"))
        if reviewer_identity is None:
            malformed_reviews = True
            continue
        reviewer, reviewer_login = reviewer_identity
        state = review.get("state")
        if state not in _GITHUB_REVIEW_STATES:
            malformed_reviews = True
            continue
        submitted_at = review.get("submitted_at")
        if state == "PENDING":
            if submitted_at is not None:
                malformed_reviews = True
            continue
        if (
            not isinstance(submitted_at, str)
            or _GITHUB_TIMESTAMP_RE.fullmatch(submitted_at) is None
        ):
            malformed_reviews = True
            continue
        try:
            _parse_timestamp(submitted_at)
        except ValueError:
            malformed_reviews = True
            continue
        submitted_reviews.append((submitted_at, review_id, reviewer, reviewer_login, review))

    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    for _submitted_at, _review_id, reviewer, reviewer_login, review in sorted(
        submitted_reviews, key=lambda item: (item[0], item[1])
    ):
        if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[reviewer] = (reviewer_login, review)
    if malformed_reviews:
        errors.append(f"{prefix}: provider reviews contain malformed state, time, or identity data")
    if any(review.get("state") == "CHANGES_REQUESTED" for _login, review in latest.values()):
        errors.append(f"{prefix}: provider pull request has current requested changes")
    if errors:
        return errors

    marker = _approval_marker(
        repository=repository,
        pull_request=pull_request,
        change_sha=head_sha,
        blocker_id=blocker["id"],
        action=action,
        subject_sha256=approval["subject_sha256"],
    )
    approved = [
        (reviewer, login, review)
        for reviewer, (login, review) in latest.items()
        if review.get("state") == "APPROVED"
    ]
    current = [item for item in approved if item[2].get("commit_id") == head_sha]
    bound = [
        item
        for item in current
        for review in (item[2],)
        if isinstance(review.get("body"), str) and review["body"].strip() == marker
    ]
    timely: list[tuple[str, str, dict[str, Any]]] = []
    for item in bound:
        review = item[2]
        submitted_at = review.get("submitted_at")
        if not isinstance(submitted_at, str):
            continue
        try:
            if _parse_timestamp(submitted_at) >= _parse_timestamp(action_at):
                timely.append(item)
        except ValueError:
            continue
    if not approved:
        return [f"{prefix}: no current provider-authenticated APPROVED review exists"]
    if not current:
        return [f"{prefix}: provider approval does not bind the current head SHA"]
    if not bound:
        return [f"{prefix}: provider approval does not bind the exact action subject"]
    if not timely:
        return [f"{prefix}: provider approval is malformed or predates the action"]

    conflict_actors = {blocker["reported_by_actor_id"], action_actor_id, *registry_actors}
    assert pull_author is not None
    conflict_actors.add(pull_author)
    independent = [item for item in timely if item[0] not in conflict_actors]
    if not independent:
        return [
            (
                f"{prefix}: provider approval reviewer is not independent of the pull-request "
                "author, registry-change authors/committers, reporter, and action actor"
            )
        ]
    authorized: list[tuple[str, str, dict[str, Any]]] = []
    try:
        for reviewer, login, review in independent:
            if _github_reviewer_authorized(
                repository=repository,
                reviewer=reviewer,
                login=login,
                token=token,
            ):
                authorized.append((reviewer, login, review))
    except PolicyInputError as exc:
        return [f"{prefix}: {exc}"]
    if not authorized:
        return [f"{prefix}: provider reviewer lacks eligible repository write permission"]
    return []


def _approval_errors(
    blocker: Blocker,
    approval: Approval,
    actor_id: str,
    subject: dict[str, Any],
    action_at: str,
    context: ApprovalContext,
) -> list[str]:
    prefix = blocker["id"]
    if approval["subject_sha256"] != _sha256(subject):
        return [f"{prefix}: approval subject SHA-256 does not bind the exact record"]
    if approval["provider"] != "github":
        return [
            (
                f"{prefix}: provider {approval['provider']!r} has no configured live verifier; "
                "production validation fails closed"
            )
        ]
    return _verify_github_approval(
        blocker=blocker,
        approval=approval,
        action_actor_id=actor_id,
        action=cast(str, subject["action"]),
        action_at=action_at,
        context=context,
    )


def _downgrade_subject(blocker: Blocker, downgrade: Downgrade) -> dict[str, Any]:
    return {
        "blocker_id": blocker["id"],
        "action": "downgrade",
        "reported_by_actor_id": blocker["reported_by_actor_id"],
        "from_severity": downgrade["from_severity"],
        "to_severity": downgrade["to_severity"],
        "from_security": downgrade["from_security"],
        "to_security": downgrade["to_security"],
        "changed_by_actor_id": downgrade["changed_by_actor_id"],
        "changed_at": downgrade["changed_at"],
        "reproduction_evidence": downgrade["reproduction_evidence"],
        "control_evidence": downgrade["control_evidence"],
    }


def _closure_subject(blocker: Blocker, closure: Closure) -> dict[str, Any]:
    return {
        "blocker_id": blocker["id"],
        "action": "closure",
        "reported_by_actor_id": blocker["reported_by_actor_id"],
        "closed_by_actor_id": closure["closed_by_actor_id"],
        "closed_at": closure["closed_at"],
        "resolution_evidence": closure["resolution_evidence"],
        "control_evidence": closure["control_evidence"],
    }


def _check_downgrade(
    blocker: Blocker,
    repo_root: Path,
    errors: list[str],
    approval_context: ApprovalContext,
) -> None:
    initial_error_count = len(errors)
    initial_rank = SEVERITY_RANK[blocker["initial_severity"]]
    current_rank = SEVERITY_RANK[blocker["severity"]]
    needed = current_rank > initial_rank or (
        blocker["initial_security"] and not blocker["security"]
    )
    downgrade = blocker["downgrade"]
    if downgrade is None:
        if needed:
            errors.append(f"{blocker['id']}: downgrade requires a governed downgrade record")
        return
    if not needed:
        errors.append(
            f"{blocker['id']}: downgrade record exists without a classification downgrade"
        )
    expected = (
        blocker["initial_severity"],
        blocker["severity"],
        blocker["initial_security"],
        blocker["security"],
    )
    actual = (
        downgrade["from_severity"],
        downgrade["to_severity"],
        downgrade["from_security"],
        downgrade["to_security"],
    )
    if actual != expected:
        errors.append(
            f"{blocker['id']}: downgrade transition does not match blocker classifications"
        )
    if _parse_timestamp(downgrade["changed_at"]) < _parse_timestamp(blocker["opened_at"]):
        errors.append(f"{blocker['id']}: downgrade predates blocker creation")
    _check_evidence(
        blocker["id"],
        downgrade["reproduction_evidence"],
        "reproduction",
        repo_root,
        approval_context["validated_sha"],
        errors,
    )
    _check_evidence(
        blocker["id"],
        downgrade["control_evidence"],
        "control",
        repo_root,
        approval_context["validated_sha"],
        errors,
    )
    if len(errors) == initial_error_count:
        errors.extend(
            _approval_errors(
                blocker,
                downgrade["approval"],
                downgrade["changed_by_actor_id"],
                _downgrade_subject(blocker, downgrade),
                downgrade["changed_at"],
                approval_context,
            )
        )


def _check_closure(
    blocker: Blocker,
    repo_root: Path,
    errors: list[str],
    approval_context: ApprovalContext,
) -> None:
    initial_error_count = len(errors)
    closure = blocker["closure"]
    if blocker["status"] == "closed" and closure is None:
        errors.append(f"{blocker['id']}: closed status requires a governed closure record")
        return
    if blocker["status"] != "closed" and closure is not None:
        errors.append(f"{blocker['id']}: closure record requires closed status")
        return
    if closure is None:
        return
    if _parse_timestamp(closure["closed_at"]) < _parse_timestamp(blocker["opened_at"]):
        errors.append(f"{blocker['id']}: closure predates blocker creation")
    downgrade = blocker["downgrade"]
    if downgrade is not None and _parse_timestamp(closure["closed_at"]) < _parse_timestamp(
        downgrade["changed_at"]
    ):
        errors.append(f"{blocker['id']}: closure predates downgrade")
    _check_evidence(
        blocker["id"],
        closure["resolution_evidence"],
        "resolution",
        repo_root,
        approval_context["validated_sha"],
        errors,
    )
    _check_evidence(
        blocker["id"],
        closure["control_evidence"],
        "control",
        repo_root,
        approval_context["validated_sha"],
        errors,
    )
    if len(errors) == initial_error_count:
        errors.extend(
            _approval_errors(
                blocker,
                closure["approval"],
                closure["closed_by_actor_id"],
                _closure_subject(blocker, closure),
                closure["closed_at"],
                approval_context,
            )
        )


def validate_registry(
    registry: Registry,
    repo_root: Path,
    approval_context: ApprovalContext,
) -> tuple[list[str], list[str]]:
    """Return sorted semantic errors and release-blocking IDs."""
    errors = list(approval_context["history_errors"])
    blockers = registry["blockers"]
    ids = [blocker["id"] for blocker in blockers]
    if len(ids) != len(set(ids)):
        errors.append("registry contains duplicate blocker IDs")
    if ids != sorted(ids):
        errors.append("registry blocker IDs must be sorted lexicographically")
    for blocker in blockers:
        if blocker["acceptance_ids"] != sorted(blocker["acceptance_ids"]):
            errors.append(f"{blocker['id']}: acceptance_ids must be sorted")
        _check_downgrade(blocker, repo_root, errors, approval_context)
        _check_closure(blocker, repo_root, errors, approval_context)
    blocking_ids = sorted(
        blocker["id"]
        for blocker in blockers
        if blocker["status"] != "closed"
        and (blocker["severity"] in {"P0", "P1"} or blocker["security"])
    )
    return sorted(errors), blocking_ids


def _report(
    registry_path: Path,
    *,
    errors: list[str],
    blocking_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": REPORT_VERSION,
        "registry": registry_path.as_posix(),
        "valid": not errors,
        "release_blocked": bool(blocking_ids) if not errors else True,
        "blocking_ids": blocking_ids,
        "error_count": len(errors),
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("docs/status/blockers.json"))
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/metriplane.blockers.v1.schema.json")
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--github-repository")
    parser.add_argument("--github-pull-request", type=int)
    parser.add_argument("--github-change-sha")
    parser.add_argument("--github-base-sha")
    parser.add_argument("--validated-sha")
    parser.add_argument("--require-merged-approval", action="store_true")
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    registry_path = cast(Path, args.registry)
    schema_path = cast(Path, args.schema)
    repo_root = cast(Path, args.repo_root)
    try:
        expected_repository = cast(str | None, args.github_repository)
        expected_pull_request = cast(int | None, args.github_pull_request)
        expected_change_sha = cast(str | None, args.github_change_sha)
        expected_base_sha = cast(str | None, args.github_base_sha)
        validated_sha = cast(str | None, args.validated_sha)
        require_merged_approval = cast(bool, args.require_merged_approval)
        if (
            expected_repository is not None
            and _GITHUB_REPOSITORY_RE.fullmatch(expected_repository) is None
        ):
            _fail("--github-repository must be an exact owner/repository identity")
        if expected_pull_request is not None and expected_pull_request <= 0:
            _fail("--github-pull-request must be positive")
        if expected_change_sha is not None and _GIT_SHA_RE.fullmatch(expected_change_sha) is None:
            _fail("--github-change-sha must be a lowercase 40-character Git SHA")
        if expected_base_sha is not None and _GIT_SHA_RE.fullmatch(expected_base_sha) is None:
            _fail("--github-base-sha must be a lowercase 40-character Git SHA")
        if validated_sha is not None and _GIT_SHA_RE.fullmatch(validated_sha) is None:
            _fail("--validated-sha must be a lowercase 40-character Git SHA")
        if (expected_pull_request is None) != (expected_change_sha is None):
            _fail("--github-pull-request and --github-change-sha must be provided together")
        if expected_pull_request is not None and expected_repository is None:
            _fail("pull-request validation requires --github-repository")
        if expected_change_sha is not None and validated_sha != expected_change_sha:
            _fail("pull-request validation SHA must equal --github-change-sha")
        if require_merged_approval and validated_sha is None:
            _fail("--require-merged-approval requires --validated-sha")
        if validated_sha is not None:
            _require_local_commit(repo_root, validated_sha, "validated SHA")
        token_env = cast(str, args.github_token_env)
        if not token_env or re.fullmatch(r"[A-Z][A-Z0-9_]*", token_env) is None:
            _fail("--github-token-env must be an uppercase environment variable name")
        approval_context: ApprovalContext = {
            "repo_root": repo_root,
            "expected_repository": expected_repository,
            "expected_pull_request": expected_pull_request,
            "expected_change_sha": expected_change_sha,
            "validated_sha": validated_sha,
            "require_merged_approval": require_merged_approval,
            "github_token": os.environ.get(token_env),
            "changed_action_keys": set(),
            "history_errors": [],
        }
        raw_schema = _strict_json(schema_path)
        if not isinstance(raw_schema, dict):
            _fail("schema root must be an object")
        schema = cast(dict[str, Any], raw_schema)
        _validate_schema_contract(schema)
        raw_registry = _strict_json(registry_path)
        _schema_validate(raw_registry, schema)
        registry = cast(Registry, raw_registry)
        base_registry = (
            _base_registry(repo_root, expected_base_sha) if expected_base_sha is not None else None
        )
        if base_registry is not None:
            _schema_validate(base_registry, schema)
        approval_context["history_errors"] = _history_errors(registry, base_registry)
        approval_context["changed_action_keys"] = _changed_action_keys(
            registry,
            base_registry,
            expected_pull_request is not None,
        )
        errors, blocking_ids = validate_registry(registry, repo_root, approval_context)
    except (PolicyInputError, OSError) as exc:
        errors = [str(exc)]
        blocking_ids = []
    report = _report(registry_path, errors=errors, blocking_ids=blocking_ids)
    if args.json:
        print(_canonical_bytes(report).decode("utf-8"))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    elif blocking_ids:
        print("Release blocked by: " + ", ".join(blocking_ids))
    else:
        print("Release blocker policy passed.")
    if errors:
        return 2
    if blocking_ids:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
