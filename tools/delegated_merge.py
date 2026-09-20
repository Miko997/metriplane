# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Pure, human-review-distinct admission for one signed v0.5 merge request."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, canonical_json, sha256_json
from tools.program_delegation import validate_program_grant
from tools.task_delegation import DelegationError, parse_utc
from tools.validate_task_work_order import validate as validate_work_order


class DelegatedMergeError(ValueError):
    """A proposed machine merge request is outside its signed authority."""


DELEGATE_REQUEST_SUBJECT_FIELDS = frozenset(
    {
        "request_id",
        "grant_id",
        "repository",
        "project_id",
        "executor_id",
        "task_id",
        "linear_issue",
        "work_order_id",
        "work_order_digest",
        "pull_request",
        "base_sha",
        "head_sha",
        "head_tree",
        "changed_paths_digest",
        "collaboration_digest",
        "ruleset_digests",
        "state_commit",
        "health_generation",
        "issued_at",
        "expires_at",
        "nonce",
    }
)


def merge_request_id(subject: Mapping[str, Any]) -> str:
    return sha256_json({key: value for key, value in subject.items() if key != "request_id"})


def durable_request_digest(request: Mapping[str, Any]) -> str:
    """Match the broker spool's canonical JSON-plus-newline identity."""

    return hashlib.sha256(canonical_json(request) + b"\n").hexdigest()


def validate_delegate_package_at_base(
    package: Mapping[str, Any],
    *,
    exact_base_root: Path,
    temporary_root: Path,
    provider_now: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild the work order from canonical package bytes and exact Git base."""
    fields = {
        "schema_version",
        "request",
        "work_order",
        "delegation",
        "linear_snapshot",
        "dependencies",
        "commands",
        "resolution",
    }
    if (
        set(package) != fields
        or package.get("schema_version") != "metriplane.delegate-merge-package.v1"
    ):
        raise DelegatedMergeError("delegate merge package shape is not closed")
    for name in fields - {"schema_version"}:
        if not isinstance(package.get(name), Mapping):
            raise DelegatedMergeError("delegate merge package has a malformed record")
    work_order = package["work_order"]
    delegation = package["delegation"]
    if work_order.get("delegation") != delegation:
        raise DelegatedMergeError("delegate merge work-order delegation differs from its input")
    with tempfile.TemporaryDirectory(dir=temporary_root, prefix="delegate-validation-") as name:
        temporary = Path(name)
        inputs: dict[str, Path] = {}
        for label in (
            "work_order",
            "delegation",
            "linear_snapshot",
            "dependencies",
            "commands",
            "resolution",
        ):
            path = temporary / f"{label}.json"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_json(package[label]))
            inputs[label] = path
        result = validate_work_order(
            inputs["work_order"],
            schema_path=exact_base_root / "schemas/metriplane.task-work-order.v2.schema.json",
            assignment_schema_path=None,
            catalog_path=exact_base_root / "docs/status/task-work-orders.json",
            catalog_schema_path=exact_base_root
            / "schemas/metriplane.mp2-work-order-set.v1.schema.json",
            keyring_path=None,
            repository_root=exact_base_root,
            delegation_path=inputs["delegation"],
            delegation_schema_path=exact_base_root
            / "schemas/metriplane.task-delegation.v2.schema.json",
            authority_keyring_path=exact_base_root / "docs/status/task-delegation-authority.json",
            authority_keyring_schema_path=exact_base_root
            / "schemas/metriplane.task-delegation-authority.v1.schema.json",
            linear_snapshot_path=inputs["linear_snapshot"],
            linear_snapshot_schema_path=exact_base_root
            / "schemas/metriplane.linear-work-order-snapshot.v1.schema.json",
            dependency_evidence_path=inputs["dependencies"],
            command_registry_path=inputs["commands"],
            resolution_path=inputs["resolution"],
            repository="Miko997/metriplane",
            project_id="cf53f98f-0965-4360-a66e-530457e40354",
            grantor_id="96778fbb-c8ff-42b3-9217-7cac45dcd097",
            executor_id="01a096e0-4e21-7a11-9f0f-fb303387c5c0",
            validated_at=provider_now,
            fixture_mode=False,
        )
    if result.get("verdict") != "READY":
        raise DelegatedMergeError("delegated work order is not READY at the provider boundary")
    return dict(work_order), result


def select_delegate_admission(
    request: Mapping[str, Any],
    *,
    grant: Mapping[str, Any],
    authority: Mapping[str, Any],
    catalog: Mapping[str, Any],
    work_order: Mapping[str, Any],
    validated_work_order: Mapping[str, Any],
    pull: Mapping[str, Any],
    head_tree: str,
    changed_paths: list[str],
    owner_context: Mapping[str, Any],
    state: Mapping[str, Any],
    provider_now: str,
    owner_id: int,
) -> dict[str, Any]:
    """Accept only after the caller independently rebuilt the exact work order."""
    if set(request) != {"schema_version", "subject", "subject_digest", "signature"}:
        raise DelegatedMergeError("delegate merge request shape is not closed")
    if request.get("schema_version") != "metriplane.delegate-merge-request.v1":
        raise DelegatedMergeError("delegate merge request version is unsupported")
    subject = request.get("subject")
    signature = request.get("signature")
    if not isinstance(subject, Mapping) or not isinstance(signature, Mapping):
        raise DelegatedMergeError("delegate merge request subject or signature is malformed")
    if set(subject) != DELEGATE_REQUEST_SUBJECT_FIELDS or set(signature) != {
        "provider",
        "actor_id",
        "key_id",
        "signature",
    }:
        raise DelegatedMergeError("delegate merge request claims are not closed")
    digest = sha256_json(subject)
    if request.get("subject_digest") != digest or subject.get("request_id") != merge_request_id(
        subject
    ):
        raise DelegatedMergeError("delegate merge request digest or stable identity differs")
    try:
        program = validate_program_grant(
            grant,
            authority,
            catalog,
            repository="Miko997/metriplane",
            project_id="cf53f98f-0965-4360-a66e-530457e40354",
            grantor_id="96778fbb-c8ff-42b3-9217-7cac45dcd097",
            executor_id="01a096e0-4e21-7a11-9f0f-fb303387c5c0",
            evaluated_at=provider_now,
            live=True,
        )
    except DelegationError as exc:
        raise DelegatedMergeError("owner program grant is not currently trusted") from exc
    if subject["grant_id"] != program["grant_id"] or subject["task_id"] not in program["task_ids"]:
        raise DelegatedMergeError("delegate request is outside the owner program task set")
    base = pull.get("base")
    head = pull.get("head")
    author = pull.get("user")
    if not all(isinstance(value, Mapping) for value in (base, head, author)):
        raise DelegatedMergeError("delegate request pull identity is malformed")
    assert isinstance(base, Mapping)
    assert isinstance(head, Mapping)
    assert isinstance(author, Mapping)
    head_repository = head.get("repo")
    if (
        pull.get("state") != "open"
        or pull.get("draft") is not False
        or base.get("ref") != "main"
        or not isinstance(head_repository, Mapping)
        or head_repository.get("full_name") != "Miko997/metriplane"
        or author.get("id") != owner_id
        or author.get("login") != "Miko997"
    ):
        raise DelegatedMergeError("delegate request is not an exact owner-repository PR")
    expected = {
        "grant_id": program["grant_id"],
        "repository": "Miko997/metriplane",
        "project_id": "cf53f98f-0965-4360-a66e-530457e40354",
        "executor_id": "01a096e0-4e21-7a11-9f0f-fb303387c5c0",
        "task_id": work_order.get("task_id"),
        "linear_issue": work_order.get("linear_issue"),
        "work_order_id": work_order.get("materialization_id"),
        "work_order_digest": sha256_json(work_order),
        "pull_request": pull.get("number"),
        "base_sha": base.get("sha"),
        "head_sha": head.get("sha"),
        "head_tree": head_tree,
        "changed_paths_digest": owner_context.get("changed_paths_digest"),
        "collaboration_digest": owner_context.get("collaboration_digest"),
        "ruleset_digests": owner_context.get("ruleset_digests"),
        "state_commit": state.get("state_commit"),
        "health_generation": state.get("generation"),
    }
    if any(subject.get(key) != value for key, value in expected.items()):
        raise DelegatedMergeError("delegate request does not bind exact provider/work-order state")
    resolution = work_order.get("resolution")
    if not isinstance(resolution, Mapping):
        raise DelegatedMergeError("delegate request has no resolved task path ownership")
    permitted: set[str] = set()
    for group_name in ("anchors", "outputs"):
        groups = resolution.get(group_name)
        if not isinstance(groups, list):
            raise DelegatedMergeError("delegate request has no finite task path ownership")
        for group in groups:
            if not isinstance(group, Mapping) or not isinstance(group.get("destinations"), list):
                raise DelegatedMergeError("delegate request path ownership is malformed")
            for destination in group["destinations"]:
                if not isinstance(destination, Mapping):
                    raise DelegatedMergeError("delegate request path ownership is malformed")
                if destination.get("owner") == subject["task_id"]:
                    path = destination.get("path")
                    if not isinstance(path, str) or not path:
                        raise DelegatedMergeError("delegate request owned path is invalid")
                    permitted.add(path)
    if (
        not changed_paths
        or len(changed_paths) != len(set(changed_paths))
        or any(not isinstance(path, str) or path not in permitted for path in changed_paths)
        or hashlib.sha256(canonical_json(sorted(changed_paths)) + b"\n").hexdigest()
        != subject["changed_paths_digest"]
    ):
        raise DelegatedMergeError("delegate PR changes a path outside exact task ownership")
    work_order_delegation = work_order.get("delegation")
    if (
        state.get("status") != "green"
        or state.get("last_good_sha") != subject["base_sha"]
        or validated_work_order.get("verdict") != "READY"
        or validated_work_order.get("task_id") != subject["task_id"]
        or validated_work_order.get("base_sha") != subject["base_sha"]
        or work_order.get("verdict") != "READY"
        or work_order.get("base_sha") != subject["base_sha"]
        or work_order.get("repository") != "Miko997/metriplane"
        or work_order.get("project_id") != subject["project_id"]
        or work_order.get("executor_id") != subject["executor_id"]
        or not isinstance(work_order_delegation, Mapping)
        or work_order_delegation.get("program_grant") != grant
    ):
        raise DelegatedMergeError("delegate request has no exact current READY work order")
    if (
        not isinstance(subject.get("nonce"), str)
        or re.fullmatch(r"[0-9a-f]{64}", subject["nonce"]) is None
        or not isinstance(subject.get("pull_request"), int)
        or isinstance(subject["pull_request"], bool)
        or subject["pull_request"] <= 0
    ):
        raise DelegatedMergeError("delegate request replay or PR identity is malformed")
    now = parse_utc(provider_now, "delegate request provider time")
    issued = parse_utc(subject.get("issued_at"), "delegate request issued-at")
    expires = parse_utc(subject.get("expires_at"), "delegate request expiry")
    if issued > now + dt.timedelta(seconds=60) or expires <= now:
        raise DelegatedMergeError("delegate merge request is not currently valid")
    if issued >= expires or expires - issued > dt.timedelta(minutes=10):
        raise DelegatedMergeError("delegate merge request lease is not short-lived")
    if expires > parse_utc(program["expires_at"], "owner program grant expiry"):
        raise DelegatedMergeError("delegate request outlives the owner program grant")
    if {key: signature.get(key) for key in ("provider", "actor_id", "key_id")} != {
        "provider": "codex_goal",
        "actor_id": subject["executor_id"],
        "key_id": program["delegate_key_id"],
    }:
        raise DelegatedMergeError("delegate merge signature identity is invalid")
    verifier = ProviderAttestationVerifier(
        keys={
            ("codex_goal", subject["executor_id"]): bytes.fromhex(
                program["delegate_public_key_hex"]
            )
        }
    )
    if not verifier.verify(signature, subject_digest=digest):
        raise DelegatedMergeError("delegate merge signature is not trusted")
    return {
        "authorization_mode": "v0.5-owner-program-delegate",
        "base_sha": subject["base_sha"],
        "changed_paths_digest": subject["changed_paths_digest"],
        "collaboration_digest": subject["collaboration_digest"],
        "head_sha": subject["head_sha"],
        "health_generation": subject["health_generation"],
        "kind": "delegate-normal",
        "nonce": subject["nonce"],
        "program_grant_id": program["grant_id"],
        "pull_request": subject["pull_request"],
        "request": dict(subject),
        "request_digest": durable_request_digest(subject),
        "ruleset_digests": subject["ruleset_digests"],
        "schema_version": 1,
        "state_commit": subject["state_commit"],
        "task_id": subject["task_id"],
        "work_order_id": subject["work_order_id"],
    }
