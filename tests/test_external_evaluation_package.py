# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs" / "external-evaluation"

REQUIRED_FILES = {
    "README.md",
    "ONE_PAGE_OFFER.md",
    "metriplane_recorded_state_evaluation.pdf",
    "metriplane_recorded_state_evaluation.pdf.license",
    "DATA_INTAKE.md",
    "ACCEPTANCE_CRITERIA.md",
    "SOW_TEMPLATE.md",
    "TARGET_QUALIFICATION.md",
    "target_qualification.csv",
    "target_qualification.csv.license",
    "FAQ.md",
    "FACTUAL_ACKNOWLEDGEMENT.md",
    "PERMISSION_OPTIONS.md",
}

LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_package_contains_the_complete_forwardable_set() -> None:
    assert PACKAGE.is_dir()
    assert REQUIRED_FILES <= {path.name for path in PACKAGE.iterdir()}


def test_local_markdown_links_resolve() -> None:
    for markdown_path in sorted(PACKAGE.glob("*.md")):
        text = markdown_path.read_text(encoding="utf-8")
        for target in LOCAL_LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = (markdown_path.parent / target.split("#", 1)[0]).resolve()
            assert target_path.exists(), f"Broken link in {markdown_path}: {target}"


def test_offer_keeps_the_bounded_outcome_model() -> None:
    offer = (PACKAGE / "ONE_PAGE_OFFER.md").read_text(encoding="utf-8")
    assert "2 to 4 weeks" in offer
    assert "recorded files only" in offer.lower()
    assert "SUPPORTED" in offer
    assert "PARTIALLY SUPPORTED" in offer
    assert "NOT SUPPORTED" in offer
    assert "A positive incident is not required" in offer
    assert "No production connection is required" in offer


def test_acceptance_criteria_preserve_unknown_state_and_negative_results() -> None:
    criteria = (PACKAGE / "ACCEPTANCE_CRITERIA.md").read_text(encoding="utf-8")
    assert "Unknown state would have to be treated as absence" in criteria
    assert "`NOT SUPPORTED` is a valid result" in criteria
    assert "Source facts, adapter-derived facts, operator rules, and Metriplane results" in criteria
    assert "A no-incident result does not fabricate incident artifacts" in criteria


def test_sow_is_outcome_neutral_and_requires_separate_publication_permission() -> None:
    sow = (PACKAGE / "SOW_TEMPLATE.md").read_text(encoding="utf-8")
    assert "not conditional on a positive technical result" in sow
    assert "appropriate counsel" in sow
    assert "No organization name, logo, quotation" in sow
    assert "It does not state" in sow
    assert "organization endorses Metriplane" in sow


def test_target_sheet_schema_matches_the_scoring_model() -> None:
    with (PACKAGE / "target_qualification.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert len(rows) == 1
    assert rows[0] == [
        "organization",
        "public_website",
        "source_type",
        "proposed_process_question",
        "trace_fit_0_3",
        "rights_path_0_3",
        "field_semantics_0_3",
        "reviewer_availability_0_3",
        "process_question_0_3",
        "delivery_friction_0_3",
        "independence_0_3",
        "timeline_0_3",
        "total_0_24",
        "hard_stop",
        "status",
        "smallest_next_action",
        "public_notes",
    ]


def test_pdf_is_a_real_single_page_offer_with_expected_metadata() -> None:
    pdf = PACKAGE / "metriplane_recorded_state_evaluation.pdf"
    data = pdf.read_bytes()
    assert len(data) > 5_000
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert b"/Count 1" in data
    assert b"/Title (Metriplane Recorded-State Evaluation)" in data


def test_docs_index_links_to_the_package() -> None:
    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "[External evaluation package](external-evaluation/README.md)" in docs_index
