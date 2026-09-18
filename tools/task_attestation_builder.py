# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Derive exact-base task observation claims without signing them.

The isolated service must supply a graph read from Linear itself, verify exact
protected main and the committed keyring/catalog, then sign the resulting
subject. Codex may only countersign the already attested subject.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from tools.program_delegation import validate_program_grant
from tools.task_delegation import (
    DelegationError,
    DelegationNotReady,
    delegation_id,
    parse_utc,
    tracker_snapshot_digest,
)


def prepare_task_observation(
    *,
    catalog: Mapping[str, Any],
    authority: Mapping[str, Any],
    grant: Mapping[str, Any],
    graph: Mapping[str, Any],
    task_id: str,
    repository: str,
    project_id: str,
    grantor_id: str,
    executor_id: str,
    base_sha: str,
    base_tree: str,
    live: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = catalog.get("tasks")
    if not isinstance(rows, list):
        raise DelegationError("task observation catalog is invalid")
    selected = [row for row in rows if isinstance(row, Mapping) and row.get("task_id") == task_id]
    if len(selected) != 1 or selected[0].get("role") != "implementation":
        raise DelegationError("task observation is not one exact implementation task")
    task = selected[0]
    issue = task.get("linear_issue")
    captured_raw = graph.get("captured_at")
    captured = parse_utc(captured_raw, "task observation provider capture time")
    program = validate_program_grant(
        grant,
        authority,
        catalog,
        repository=repository,
        project_id=project_id,
        grantor_id=grantor_id,
        executor_id=executor_id,
        evaluated_at=captured_raw,
        live=live,
    )
    if task_id not in program["task_ids"]:
        raise DelegationError("task observation is outside the owner program grant")
    issues = graph.get("issues")
    if not isinstance(issues, Mapping) or not isinstance(issue, str):
        raise DelegationError("task observation provider issue inventory is invalid")
    observed = issues.get(issue)
    if not isinstance(observed, Mapping) or observed.get("identifier") != issue:
        raise DelegationError("task observation issue is absent from the provider graph")
    assignee = observed.get("assignee")
    state = observed.get("state")
    if not isinstance(assignee, Mapping) or assignee.get("id") != grantor_id:
        raise DelegationNotReady("Linear task is not assigned to the owner grantor")
    if not isinstance(state, Mapping) or state.get("type") not in {
        "backlog",
        "unstarted",
        "started",
    }:
        raise DelegationNotReady("Linear task state is not executable")
    cursor = graph.get("cursor")
    event_id = observed.get("updatedAt")
    edges = graph.get("edges")
    if (
        not isinstance(cursor, str)
        or len(cursor) != 64
        or not isinstance(event_id, str)
        or not event_id
        or not isinstance(edges, list)
    ):
        raise DelegationError("task observation provider identity is incomplete")
    expiry = min(
        captured + dt.timedelta(minutes=10),
        parse_utc(program["expires_at"], "owner program grant expiry"),
    )
    if expiry <= captured:
        raise DelegationNotReady("owner program grant has no task lease remaining")
    issued_at = captured.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = {
        "schema_version": "metriplane.linear-work-order-snapshot.v1",
        "provider_status": "available",
        "repository": repository,
        "project_id": project_id,
        "event_cursor": cursor,
        "captured_at": issued_at,
        "synthetic": not live,
        "task": {
            "task_id": task_id,
            "linear_issue": issue,
            "issue_state": state["type"],
            "assignee_actor_id": grantor_id,
            "delegation_id": "0" * 64,
            "delegate_executor_id": executor_id,
            "delegation_event_id": event_id,
            "base_sha": base_sha,
            "delegation_status": "active",
        },
        "edges": edges,
    }
    subject = {
        "program_grant_id": program["grant_id"],
        "grantor": grant["subject"]["grantor"],
        "delegate": {"kind": "codex_goal", "executor_id": executor_id},
        "scope": {
            "authority": "implementation",
            "repository": repository,
            "project_id": project_id,
            "task_id": task_id,
            "linear_issue": issue,
            "base_sha": base_sha,
            "base_tree": base_tree,
        },
        "tracker": {"provider": "linear", "event_id": event_id, "event_cursor": cursor},
        "issued_at": issued_at,
        "expires_at": expires_at,
        "tracker_snapshot_digest": tracker_snapshot_digest(snapshot),
        "delegate_key_id": program["delegate_key_id"],
        "attestor_key_id": program["attestor_key_id"],
    }
    subject["delegation_id"] = delegation_id(subject)
    snapshot["task"]["delegation_id"] = subject["delegation_id"]
    # Signing a partial relation graph would turn a provider outage into
    # apparent READY. The attestor checks the same frozen catalog boundary as
    # the work-order materializer before it signs.
    from tools.materialize_task_work_order import _validate_relations

    _validate_relations(catalog, snapshot)
    return subject, snapshot
