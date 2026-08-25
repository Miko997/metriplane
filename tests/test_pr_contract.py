# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.check_pr_contract import ContractError, validate_body, validate_event

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"


def _body() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_checked_in_template_satisfies_four_heading_contract() -> None:
    result = validate_body(_body(), author="author")
    assert result["headings"] == ["Outcome", "Changes", "Validation", "Boundaries"]
    assert result["verdict"] == "PASS"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body.replace("## Changes", "## Extra\n\n## Changes"),
        lambda body: body.replace("## Changes", "## Validation", 1),
        lambda body: body.replace("### Compatibility", "### Removed"),
        lambda body: body.replace(
            "- [ ] The pull request is focused", "The pull request is focused", 1
        ),
    ],
)
def test_missing_extra_reordered_or_weakened_contract_fails(mutation: object) -> None:
    with pytest.raises(ContractError):
        validate_body(mutation(_body()), author="author")  # type: ignore[operator]


@pytest.mark.parametrize(
    "marker",
    [
        "\nassistant: here is the answer\n",
        "\n<system>raw prompt</system>\n",
        "\nBEGIN CHAT LOG\n",
        "\n## Agent transcript\n",
        "\nCo-authored-by: Codex <noreply@example.invalid>\n",
    ],
)
def test_raw_prompt_log_and_agent_attribution_dumps_fail(marker: str) -> None:
    with pytest.raises(ContractError, match="raw attribution"):
        validate_body(_body() + marker, author="author")


def test_compact_limit_requires_named_non_author_exception() -> None:
    body = _body() + ("x" * 12_000)
    with pytest.raises(ContractError, match="named exception"):
        validate_body(body, author="author")
    with pytest.raises(ContractError, match="non-author"):
        validate_body(
            body,
            author="author",
            exception_reviewer="author",
            exception_reason="Retained table is required",
        )
    result = validate_body(
        body,
        author="author",
        exception_reviewer="reviewer",
        exception_reason="Retained table is required",
    )
    assert result["exception_reviewer"] == "reviewer"
    event = {
        "pull_request": {
            "body": body,
            "head": {"sha": "a" * 40},
            "user": {"login": "author"},
        }
    }
    body_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    review = {
        "body": (
            f"MP2-004 compact-body exception sha256={body_digest}: Retained table is required"
        ),
        "commit_id": "a" * 40,
        "id": 1,
        "state": "APPROVED",
        "submitted_at": "2026-08-25T00:00:00Z",
        "user": {"login": "reviewer"},
    }
    assert validate_event(event, [review])["exception_reviewer"] == "reviewer"
    requested = {
        **review,
        "body": "Please revise",
        "id": 2,
        "state": "CHANGES_REQUESTED",
        "submitted_at": "2026-08-25T00:01:00Z",
    }
    with pytest.raises(ContractError, match="provider-approved"):
        validate_event(event, [review, requested])
    event["pull_request"]["body"] += "edited"
    with pytest.raises(ContractError, match="provider-approved"):
        validate_event(event, [review])
    event["pull_request"]["body"] = body
    review["commit_id"] = "b" * 40
    with pytest.raises(ContractError, match="provider-approved"):
        validate_event(event, [review])


def test_validator_uses_mechanical_markers_not_ai_style_detection() -> None:
    body = _body().replace(
        "What user or maintainer problem",
        "A concise automated analysis explains what user or maintainer problem",
    )
    assert validate_body(body, author="author")["verdict"] == "PASS"


def test_ci_activates_validator_only_when_base_contains_the_contract() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "${BASE_SHA}:tools/check_pr_contract.py" in workflow
    assert "MP2-004 transition PR uses the previous repository template" in workflow
    assert "pr-reviews.json" in workflow
