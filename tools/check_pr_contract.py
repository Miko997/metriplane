# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Deterministically validate the compact four-heading pull-request contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

H2 = ["Outcome", "Changes", "Validation", "Boundaries"]
H3 = [
    "Problem",
    "User-visible behavior",
    "Scope",
    "Compatibility",
    "Evidence and research impact",
    "Tests",
    "Documentation",
    "Privacy and security",
    "Checklist",
]
CHECKLIST_MARKERS = [
    "focused and its diff has been reviewed",
    "relevant failure path",
    "complete suite pass locally",
    "documentation remain truthful",
    "compatible licensing",
    "No credentials, private recordings",
    "Frozen v0.2.0 evidence",
    "TIM v0.1.3 measurements",
]
RAW_DUMP_PATTERNS = [
    re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    for pattern in (
        r"^\s*(?:system|assistant|user|tool)\s*:\s*",
        r"<\/?(?:system|assistant|user|tool)(?:\s|>)",
        r"BEGIN (?:RAW )?(?:PROMPT|TRANSCRIPT|CHAT LOG)",
        r"^##\s+(?:Agent|Prompt|Transcript|Raw log)\b",
        r"Co-authored-by:\s*(?:ChatGPT|Codex|Claude)",
    )
]


class ContractError(ValueError):
    """The pull-request body does not satisfy the mechanical contract."""


def validate_event(
    event: dict[str, Any],
    reviews: list[dict[str, Any]],
    *,
    max_bytes: int = 12_000,
) -> dict[str, object]:
    """Validate a provider event and an exact-head, non-author review exception."""
    pull_request = event["pull_request"]
    body = pull_request.get("body") or ""
    author = pull_request["user"]["login"]
    if len(body.encode("utf-8")) <= max_bytes:
        return validate_body(body, author=author, max_bytes=max_bytes)
    head_sha = pull_request["head"]["sha"]
    body_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    prefix = f"MP2-004 compact-body exception sha256={body_digest}:"
    latest: dict[str, dict[str, Any]] = {}
    for review in sorted(reviews, key=lambda item: (item.get("submitted_at") or "", item["id"])):
        login = review.get("user", {}).get("login")
        if login:
            latest[login.casefold()] = review
    approved = [
        review
        for review in latest.values()
        if review.get("state") == "APPROVED"
        and review.get("commit_id") == head_sha
        and review.get("user", {}).get("login", "").casefold() != author.casefold()
        and (review.get("body") or "").startswith(prefix)
        and (review.get("body") or "")[len(prefix) :].strip()
    ]
    if any(review.get("state") == "CHANGES_REQUESTED" for review in latest.values()):
        approved = []
    if not approved:
        raise ContractError(
            "body exceeds compact limit without an exact-head provider-approved exception"
        )
    review = max(approved, key=lambda item: (item.get("submitted_at") or "", item["id"]))
    return validate_body(
        body,
        author=author,
        exception_reviewer=review["user"]["login"],
        exception_reason=review["body"][len(prefix) :].strip(),
        max_bytes=max_bytes,
    )


def validate_body(
    body: str,
    *,
    author: str,
    exception_reviewer: str | None = None,
    exception_reason: str | None = None,
    max_bytes: int = 12_000,
) -> dict[str, object]:
    for pattern in RAW_DUMP_PATTERNS:
        if pattern.search(body):
            raise ContractError(f"raw attribution/log dump marker rejected: {pattern.pattern}")
    headings = re.findall(r"^## ([^#\n].*)$", body, re.MULTILINE)
    if headings != H2:
        raise ContractError(f"H2 headings must be exactly {H2!r}; found {headings!r}")
    h3 = re.findall(r"^### ([^#\n].*)$", body, re.MULTILINE)
    if h3 != H3:
        raise ContractError("required review prompts are missing, extra, or out of order")
    checklist = re.findall(r"^- \[[ xX]\] (.+)$", body, re.MULTILINE)
    if len(checklist) != 8:
        raise ContractError("the checklist must contain exactly eight obligations")
    for marker in CHECKLIST_MARKERS:
        if not any(marker in item for item in checklist):
            raise ContractError(f"missing checklist obligation containing {marker!r}")
    size = len(body.encode("utf-8"))
    if size > max_bytes:
        if not exception_reviewer or not exception_reason:
            raise ContractError("body exceeds compact limit without a named exception")
        if exception_reviewer.casefold() == author.casefold():
            raise ContractError("compact-body exception reviewer must be a non-author")
    return {
        "bytes": size,
        "exception_reviewer": exception_reviewer,
        "headings": headings,
        "schema_version": 1,
        "verdict": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--body-file", type=Path)
    source.add_argument("--event", type=Path)
    parser.add_argument("--author")
    parser.add_argument("--exception-reviewer")
    parser.add_argument("--exception-reason")
    parser.add_argument("--reviews-file", type=Path)
    parser.add_argument("--max-bytes", type=int, default=12_000)
    args = parser.parse_args()
    if args.event:
        event = json.loads(args.event.read_text(encoding="utf-8"))
        reviews = (
            json.loads(args.reviews_file.read_text(encoding="utf-8")) if args.reviews_file else []
        )
        if not isinstance(reviews, list):
            raise SystemExit("provider reviews must be a JSON array")
        body = ""
        author = ""
    else:
        assert args.body_file is not None
        body = args.body_file.read_text(encoding="utf-8")
        author = args.author or ""
    if not args.event and not author:
        raise SystemExit("pull-request author is required")
    try:
        if args.event:
            result = validate_event(event, reviews, max_bytes=args.max_bytes)
        else:
            result = validate_body(
                body,
                author=author,
                exception_reviewer=args.exception_reviewer,
                exception_reason=args.exception_reason,
                max_bytes=args.max_bytes,
            )
    except (ContractError, KeyError, TypeError) as exc:
        raise SystemExit(f"pull-request contract validation failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
