# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations

import copy
import datetime as dt

import pytest

from tools.linear_work_order_provider import LinearObservationError, observe_project_graph

PROJECT = "cf53f98f-0965-4360-a66e-530457e40354"
NOW = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.timezone.utc)
CATALOG = {"tasks": [{"linear_issue": "MET-1"}, {"linear_issue": "MET-2"}]}


def _issue(identifier: str) -> dict:
    relation = {
        "id": "relation-1",
        "type": "blocks",
        "issue": {"identifier": "MET-1"},
        "relatedIssue": {"identifier": "MET-2"},
    }
    connection = {"nodes": [relation], "pageInfo": {"hasNextPage": False}}
    return {
        "id": "uuid-" + identifier,
        "identifier": identifier,
        "updatedAt": "2026-09-18T11:00:00.000Z",
        "project": {"id": PROJECT},
        "state": {"type": "backlog"},
        "assignee": {"id": "owner-id"},
        "relations": connection
        if identifier == "MET-1"
        else {"nodes": [], "pageInfo": {"hasNextPage": False}},
        "inverseRelations": connection
        if identifier == "MET-2"
        else {"nodes": [], "pageInfo": {"hasNextPage": False}},
    }


def _observe(issues: dict[str, dict], *, second_time: dt.datetime = NOW) -> dict:
    return observe_project_graph(
        CATALOG,
        project_id=PROJECT,
        issue_reader=lambda identifier: (
            copy.deepcopy(issues[identifier]),
            NOW if identifier == "MET-1" else second_time,
        ),
    )


def test_complete_reciprocal_provider_observation() -> None:
    result = _observe({"MET-1": _issue("MET-1"), "MET-2": _issue("MET-2")})
    assert result["edges"] == [{"blocker": "MET-1", "blocked": "MET-2"}]
    assert result["captured_at"] == "2026-09-18T12:00:00Z"
    assert len(result["cursor"]) == 64


def test_outside_downstream_issue_does_not_require_unqueried_inverse() -> None:
    issues = {"MET-1": _issue("MET-1"), "MET-2": _issue("MET-2")}
    outside = {
        "id": "relation-outside",
        "type": "blocks",
        "issue": {"identifier": "MET-1"},
        "relatedIssue": {"identifier": "MET-3"},
    }
    issues["MET-1"]["relations"]["nodes"].append(outside)
    result = _observe(issues)
    assert result["edges"] == [{"blocker": "MET-1", "blocked": "MET-2"}]
    issues["MET-1"]["relations"]["nodes"].pop()
    assert result["cursor"] != _observe(issues)["cursor"]


def test_outside_blocker_of_catalog_issue_remains_not_ready() -> None:
    issues = {"MET-1": _issue("MET-1"), "MET-2": _issue("MET-2")}
    issues["MET-2"]["inverseRelations"]["nodes"].append(
        {
            "id": "relation-outside",
            "type": "blocks",
            "issue": {"identifier": "MET-3"},
            "relatedIssue": {"identifier": "MET-2"},
        }
    )
    with pytest.raises(LinearObservationError, match="reciprocally complete"):
        _observe(issues)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows["MET-2"].update(
            {"inverseRelations": {"nodes": [], "pageInfo": {"hasNextPage": False}}}
        ),
        lambda rows: rows["MET-1"].update(
            {"relations": {"nodes": [], "pageInfo": {"hasNextPage": True}}}
        ),
        lambda rows: rows["MET-1"].update({"project": {"id": "wrong"}}),
        lambda rows: rows["MET-1"].update({"identifier": "MET-3"}),
        lambda rows: rows["MET-1"].pop("state"),
    ],
)
def test_partial_or_substituted_provider_answer_rejected(mutate: object) -> None:
    issues = {"MET-1": _issue("MET-1"), "MET-2": _issue("MET-2")}
    mutate(issues)
    with pytest.raises(LinearObservationError):
        _observe(issues)


def test_provider_clock_window_rejected() -> None:
    issues = {"MET-1": _issue("MET-1"), "MET-2": _issue("MET-2")}
    with pytest.raises(LinearObservationError, match="freshness"):
        _observe(issues, second_time=NOW + dt.timedelta(minutes=6))
