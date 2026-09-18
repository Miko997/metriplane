# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Read a complete Linear task graph for an isolated work-order attestor.

The fixed GraphQL document is read-only. This module never signs a record and
never accepts caller-authored issue or relation data as a provider response.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from metriplane.release_control import canonical_json, sha256_json

LINEAR_ENDPOINT = "https://api.linear.app/graphql"
MAX_RESPONSE_BYTES = 1_000_000
ISSUE_QUERY = """query WorkOrderIssue($id: String!) {
  issue(id: $id) {
    id identifier updatedAt
    project { id }
    assignee { id }
    state { type }
    relations(first: 50) {
      nodes { id type issue { identifier } relatedIssue { identifier } }
      pageInfo { hasNextPage }
    }
    inverseRelations(first: 50) {
      nodes { id type issue { identifier } relatedIssue { identifier } }
      pageInfo { hasNextPage }
    }
  }
}"""


class LinearObservationError(ValueError):
    """A provider answer is malformed, partial, or outside task scope."""


class LinearProviderUnavailable(ConnectionError):
    """A provider request has no authoritative response."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, request: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _provider_time(value: str | None) -> dt.datetime:
    if value is None:
        raise LinearObservationError("Linear response has no provider Date header")
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError) as exc:
        raise LinearObservationError("Linear provider Date header is invalid") from exc
    if parsed.tzinfo is None:
        raise LinearObservationError("Linear provider Date header has no timezone")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0)


class LinearGraphqlReader:
    """Use only inside a credential-isolated process; never print the token."""

    def __init__(self, token: str) -> None:
        if not token or any(character.isspace() for character in token):
            raise LinearObservationError("Linear read-only credential is invalid")
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect())

    def issue(self, identifier: str) -> tuple[dict[str, Any], dt.datetime]:
        body = canonical_json({"query": ISSUE_QUERY, "variables": {"id": identifier}})
        request = urllib.request.Request(
            LINEAR_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=15) as response:
                if response.status != 200 or response.url != LINEAR_ENDPOINT:
                    raise LinearProviderUnavailable("Linear returned a non-authoritative response")
                provider_now = _provider_time(response.headers.get("Date"))
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LinearProviderUnavailable("Linear provider read is unavailable") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise LinearObservationError("Linear response exceeds the bounded size")
        try:
            value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LinearObservationError("Linear returned malformed JSON") from exc
        if not isinstance(value, dict) or value.get("errors") or set(value) != {"data"}:
            raise LinearObservationError("Linear returned GraphQL errors or partial data")
        data = value["data"]
        if (
            not isinstance(data, dict)
            or set(data) != {"issue"}
            or not isinstance(data["issue"], dict)
        ):
            raise LinearObservationError("Linear issue response is absent or malformed")
        return data["issue"], provider_now


def _relation_set(issue: Mapping[str, Any]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    forward: set[tuple[str, str]] = set()
    inverse: set[tuple[str, str]] = set()
    for field, target in (("relations", forward), ("inverseRelations", inverse)):
        connection = issue.get(field)
        if not isinstance(connection, Mapping) or set(connection) != {"nodes", "pageInfo"}:
            raise LinearObservationError("Linear relation connection is incomplete")
        page = connection["pageInfo"]
        nodes = connection["nodes"]
        if not isinstance(page, Mapping) or page.get("hasNextPage") is not False:
            raise LinearObservationError("Linear relation pagination is incomplete")
        if not isinstance(nodes, list) or len(nodes) > 50:
            raise LinearObservationError("Linear relation inventory is malformed")
        relation_ids: set[str] = set()
        for relation in nodes:
            if not isinstance(relation, Mapping):
                raise LinearObservationError("Linear relation row is malformed")
            relation_id = relation.get("id")
            if not isinstance(relation_id, str) or not relation_id or relation_id in relation_ids:
                raise LinearObservationError("Linear relation identity is missing or duplicated")
            relation_ids.add(relation_id)
            if relation.get("type") != "blocks":
                continue
            source = relation.get("issue")
            destination = relation.get("relatedIssue")
            if not isinstance(source, Mapping) or not isinstance(destination, Mapping):
                raise LinearObservationError("Linear blocking relation endpoint is malformed")
            blocker = source.get("identifier")
            blocked = destination.get("identifier")
            if not isinstance(blocker, str) or not isinstance(blocked, str):
                raise LinearObservationError("Linear blocking relation endpoint is missing")
            pair = (blocker, blocked)
            if pair in target:
                raise LinearObservationError("Linear blocking relation is duplicated")
            target.add(pair)
    return forward, inverse


def observe_project_graph(
    catalog: Mapping[str, Any],
    *,
    project_id: str,
    issue_reader: Callable[[str], tuple[dict[str, Any], dt.datetime]],
) -> dict[str, Any]:
    """Read every catalog issue; reject any partial or non-reciprocal graph."""
    rows = catalog.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise LinearObservationError("work-order catalog task set is invalid")
    identifiers = [row.get("linear_issue") for row in rows if isinstance(row, Mapping)]
    if (
        len(identifiers) != len(rows)
        or not all(isinstance(value, str) and value for value in identifiers)
        or len(identifiers) != len(set(identifiers))
    ):
        raise LinearObservationError("work-order catalog issue inventory is not exact")
    observed: dict[str, dict[str, Any]] = {}
    forward: set[tuple[str, str]] = set()
    inverse: set[tuple[str, str]] = set()
    times: list[dt.datetime] = []
    for identifier in sorted(identifiers):
        issue, provider_now = issue_reader(identifier)
        if issue.get("identifier") != identifier or not isinstance(issue.get("id"), str):
            raise LinearObservationError("Linear issue identity differs from the catalog")
        project = issue.get("project")
        if not isinstance(project, Mapping) or project.get("id") != project_id:
            raise LinearObservationError("Linear issue is outside the required project")
        state = issue.get("state")
        if not isinstance(state, Mapping) or not isinstance(state.get("type"), str):
            raise LinearObservationError("Linear issue state is missing")
        assignee = issue.get("assignee")
        if assignee is not None and (
            not isinstance(assignee, Mapping) or not isinstance(assignee.get("id"), str)
        ):
            raise LinearObservationError("Linear issue assignee is malformed")
        updated = issue.get("updatedAt")
        if not isinstance(updated, str) or not updated:
            raise LinearObservationError("Linear issue update identity is missing")
        seen_forward, seen_inverse = _relation_set(issue)
        forward.update(seen_forward)
        inverse.update(seen_inverse)
        observed[identifier] = issue
        times.append(provider_now)
    if not times or max(times) - min(times) > dt.timedelta(minutes=5):
        raise LinearObservationError("Linear graph read exceeded the freshness interval")
    # A catalog issue may block a release-coordination issue outside this
    # frozen catalog. Its inverse cannot be observed by this bounded query.
    # An outside blocker of a catalog issue is still an extra, unverified
    # dependency and must fail the reciprocal check.
    catalog_issues = set(identifiers)
    catalog_forward = {edge for edge in forward if edge[1] in catalog_issues}
    if catalog_forward != inverse:
        raise LinearObservationError("Linear blocking graph is not reciprocally complete")
    return {
        "issues": observed,
        "edges": [
            {"blocker": blocker, "blocked": blocked} for blocker, blocked in sorted(catalog_forward)
        ],
        "cursor": sha256_json({"issues": observed, "edges": sorted(catalog_forward)}),
        "captured_at": max(times).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
