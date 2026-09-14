#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Summarize the manually recorded first-time-user comprehension gate."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "metriplane.human_comprehension_results.v1"
ROOT_FIELDS = {
    "_copyright",
    "_license",
    "schema_version",
    "candidate_commit",
    "candidate_version",
    "materials",
    "testers",
}
BOOLEAN_FIELDS = (
    "demo_command_found",
    "product_understood",
    "report_found",
    "intervention_required",
)
MISCONCEPTION_FIELDS = (
    "controls_machinery_misconception",
    "deterministic_replay_equals_physical_accuracy_misconception",
)
TEXT_FIELDS = ("first_failed_command", "first_confusing_term")
TESTER_FIELDS = {
    "tester_id",
    *BOOLEAN_FIELDS,
    *MISCONCEPTION_FIELDS,
    *TEXT_FIELDS,
    "time_to_report_seconds",
}
TESTER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
CANDIDATE_COMMIT = re.compile(r"[0-9a-f]{40}")
CANDIDATE_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){2}(?:[A-Za-z0-9.+-]{1,32})?")
PRODUCT_PAGES = {"readme", "pypi-style-page"}
INSTALLATION_INSTRUCTIONS = {"candidate-wheel", "source-checkout", "published-package"}
LOCAL_PATH = re.compile(r"(?:^|[\s=])(?:/(?!/)\S+|~[\\/]\S*|[A-Za-z]:[\\/]\S+)")
USER_IDENTITY = re.compile(r"(?i)(?:^|\s)[^\s@]+@[^\s@]+")
PRIVATE_URL = re.compile(
    r"(?i)https?://(?:localhost|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})"
)
UNREDACTED_SECRET = re.compile(
    r"(?i)(?:^|\s)(?:(?:[A-Za-z_]*(?:TOKEN|PASSWORD|PASSWD|SECRET|API_KEY))="
    r"|--(?:token|password|passwd|secret|api[-_]?key)(?:=|\s+))(?!<REDACTED>)\S+"
)


def _percentage(count: int, total: int) -> str:
    return f"{100 * count / total:.1f}%" if total else "N/A"


def _validate_optional_text(
    value: Any,
    *,
    field: str,
    index: int,
    maximum: int,
) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"testers[{index}].{field} must be a string or null")
    if not value or value != value.strip() or len(value) > maximum:
        raise ValueError(
            f"testers[{index}].{field} must contain 1-{maximum} trimmed characters or be null"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"testers[{index}].{field} must be a single printable line")


def _validate_candidate_metadata(payload: dict[str, Any], tester_count: int) -> None:
    commit = payload.get("candidate_commit")
    version = payload.get("candidate_version")
    materials = payload.get("materials")
    values = (commit, version, materials)

    if any(value is None for value in values):
        if tester_count:
            raise ValueError(
                "candidate_commit, candidate_version, and materials are required when testers exist"
            )
        if not all(value is None for value in values):
            raise ValueError("candidate metadata must be entirely null or entirely populated")
        return

    if not isinstance(commit, str) or CANDIDATE_COMMIT.fullmatch(commit) is None:
        raise ValueError("candidate_commit must be a full 40-character lowercase Git SHA")
    if (
        not isinstance(version, str)
        or len(version) > 64
        or CANDIDATE_VERSION.fullmatch(version) is None
    ):
        raise ValueError(
            "candidate_version must be a release-like version of at most 64 characters"
        )
    if not isinstance(materials, dict) or set(materials) != {
        "product_page",
        "installation_instructions",
    }:
        raise ValueError("materials must contain only product_page and installation_instructions")
    product_page = materials["product_page"]
    installation_instructions = materials["installation_instructions"]
    if not isinstance(product_page, str) or product_page not in PRODUCT_PAGES:
        raise ValueError(f"materials.product_page must be one of {sorted(PRODUCT_PAGES)}")
    if (
        not isinstance(installation_instructions, str)
        or installation_instructions not in INSTALLATION_INSTRUCTIONS
    ):
        raise ValueError(
            "materials.installation_instructions must be one of "
            f"{sorted(INSTALLATION_INSTRUCTIONS)}"
        )


def _validate_tester(raw: Any, index: int, seen_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"testers[{index}] must be an object")

    missing = TESTER_FIELDS - raw.keys()
    extra = raw.keys() - TESTER_FIELDS
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected {', '.join(sorted(extra))}")
        raise ValueError(f"testers[{index}] has " + "; ".join(details))

    tester_id = raw["tester_id"]
    if not isinstance(tester_id, str) or TESTER_ID.fullmatch(tester_id) is None:
        raise ValueError(
            f"testers[{index}].tester_id must be a 1-32 character anonymous ID using "
            "letters, numbers, underscores, or hyphens"
        )
    if tester_id in seen_ids:
        raise ValueError(f"duplicate tester_id: {tester_id}")
    seen_ids.add(tester_id)

    for field in BOOLEAN_FIELDS:
        if type(raw[field]) is not bool:
            raise ValueError(f"testers[{index}].{field} must be true or false")
    for field in MISCONCEPTION_FIELDS:
        if raw[field] is not None and type(raw[field]) is not bool:
            raise ValueError(f"testers[{index}].{field} must be true, false, or null")
    _validate_optional_text(
        raw["first_failed_command"],
        field="first_failed_command",
        index=index,
        maximum=500,
    )
    _validate_optional_text(
        raw["first_confusing_term"],
        field="first_confusing_term",
        index=index,
        maximum=200,
    )

    command = raw["first_failed_command"]
    if command is not None:
        privacy_patterns = (
            (LOCAL_PATH, "a local absolute or user path; replace it with <PATH>"),
            (USER_IDENTITY, "a user identity; replace it with <USER>"),
            (PRIVATE_URL, "a private/local URL; replace it with <PRIVATE_URL>"),
            (UNREDACTED_SECRET, "an apparent secret; replace its value with <REDACTED>"),
        )
        for pattern, explanation in privacy_patterns:
            if pattern.search(command):
                raise ValueError(f"testers[{index}].first_failed_command contains {explanation}")

    elapsed = raw["time_to_report_seconds"]
    if elapsed is not None and (
        type(elapsed) not in (int, float) or not math.isfinite(float(elapsed)) or elapsed < 0
    ):
        raise ValueError(f"testers[{index}].time_to_report_seconds must be non-negative or null")
    if raw["report_found"] and elapsed is None:
        raise ValueError(
            f"testers[{index}].time_to_report_seconds is required when report_found is true"
        )
    if not raw["report_found"] and elapsed is not None:
        raise ValueError(
            f"testers[{index}].time_to_report_seconds must be null when report_found is false"
        )
    return raw


def load_results(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("results document must be an object")
    unexpected = set(payload) - ROOT_FIELDS
    missing = {
        "schema_version",
        "candidate_commit",
        "candidate_version",
        "materials",
        "testers",
    } - payload.keys()
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if unexpected:
            details.append(f"unexpected {', '.join(sorted(unexpected))}")
        raise ValueError("results document has " + "; ".join(details))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    raw_testers = payload.get("testers")
    if not isinstance(raw_testers, list):
        raise ValueError("testers must be an array")

    seen_ids: set[str] = set()
    testers = [_validate_tester(raw, index, seen_ids) for index, raw in enumerate(raw_testers)]
    _validate_candidate_metadata(payload, len(testers))
    return {
        "candidate_commit": payload["candidate_commit"],
        "candidate_version": payload["candidate_version"],
        "materials": payload["materials"],
        "testers": testers,
    }


def summarize(results: dict[str, Any]) -> tuple[list[str], int]:
    testers = results["testers"]
    total = len(testers)
    if total == 0:
        materials = results["materials"]
        materials_text = (
            "N/A"
            if materials is None
            else f"{materials['product_page']} + {materials['installation_instructions']}"
        )
        lines = [
            "HUMAN COMPREHENSION GATE: MANUAL GATE PENDING",
            f"Candidate commit: {results['candidate_commit'] or 'N/A'}",
            f"Candidate version: {results['candidate_version'] or 'N/A'}",
            f"Materials: {materials_text}",
            "Tester count: 0",
            "Demo-command find rate: N/A",
            "Report-found rate: N/A",
            "Independent completion rate: N/A",
            "Comprehension rate: N/A",
            "Median time to report: N/A",
            "Gates: PENDING (no human observations recorded)",
        ]
        return lines, 2

    command_found = sum(tester["demo_command_found"] for tester in testers)
    reports_found = sum(tester["report_found"] for tester in testers)
    understood = sum(tester["product_understood"] for tester in testers)
    independent = sum(
        tester["report_found"] and not tester["intervention_required"] for tester in testers
    )
    times = [
        float(tester["time_to_report_seconds"])
        for tester in testers
        if tester["time_to_report_seconds"] is not None
    ]
    median_seconds = statistics.median(times) if times else None

    gates = {
        "Every tester found the demo command": command_found == total,
        "Comprehension rate is at least 80%": understood / total >= 0.8,
        "Independent completion rate is at least 80%": independent / total >= 0.8,
        "Median time to report is under 300 seconds": (
            median_seconds is not None and median_seconds < 300
        ),
        "Nobody believed Metriplane controls machinery": all(
            tester["controls_machinery_misconception"] is False for tester in testers
        ),
        "Nobody treated deterministic replay equality as physical accuracy": all(
            tester["deterministic_replay_equals_physical_accuracy_misconception"] is False
            for tester in testers
        ),
    }
    passed = all(gates.values())
    materials = results["materials"]
    lines = [
        f"HUMAN COMPREHENSION GATE: {'PASS' if passed else 'FAIL'}",
        f"Candidate commit: {results['candidate_commit']}",
        f"Candidate version: {results['candidate_version']}",
        (f"Materials: {materials['product_page']} + {materials['installation_instructions']}"),
        f"Tester count: {total}",
        f"Demo-command find rate: {_percentage(command_found, total)}",
        f"Report-found rate: {_percentage(reports_found, total)}",
        f"Independent completion rate: {_percentage(independent, total)}",
        f"Comprehension rate: {_percentage(understood, total)}",
        (
            f"Median time to report: {median_seconds:.1f} seconds"
            if median_seconds is not None
            else "Median time to report: N/A"
        ),
        "Gates:",
    ]
    lines.extend(f"- {'PASS' if result else 'FAIL'}  {name}" for name, result in gates.items())
    return lines, 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize manually recorded first-time-user observations."
    )
    parser.add_argument("results", type=Path, help="Path to the comprehension results JSON")
    args = parser.parse_args(argv)

    try:
        results = load_results(args.results)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"human comprehension results: ERROR: {exc}", file=sys.stderr)
        return 2

    lines, exit_code = summarize(results)
    print("\n".join(lines))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
