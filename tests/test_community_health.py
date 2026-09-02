# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate community-health routes, forms, and release boundaries."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
FORMS_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
FORM_FILES = {
    "bug_report.yml",
    "documentation.yml",
    "integration_request.yml",
    "external_reproduction.yml",
}


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_required_community_health_files_exist() -> None:
    required = {
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "SUPPORT.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/config.yml",
        *(f".github/ISSUE_TEMPLATE/{name}" for name in FORM_FILES),
    }
    for relative_path in required:
        path = ROOT / relative_path
        assert path.is_file(), f"missing community-health file: {relative_path}"
        assert path.stat().st_size > 0, f"empty community-health file: {relative_path}"


def test_issue_forms_are_structured_and_do_not_invent_repository_state() -> None:
    actual_forms = {path.name for path in FORMS_DIR.glob("*.yml")} - {"config.yml"}
    assert actual_forms == FORM_FILES

    for name in sorted(FORM_FILES):
        form = yaml.safe_load((FORMS_DIR / name).read_text(encoding="utf-8"))
        assert isinstance(form, dict)
        assert form["name"]
        assert form["description"]
        assert form["title"]
        assert "labels" not in form, f"{name} must not assume labels exist"
        assert "assignees" not in form, f"{name} must not assume assignees"

        body = form["body"]
        assert isinstance(body, list) and body
        ids = [item["id"] for item in body if "id" in item]
        assert len(ids) == len(set(ids)), f"duplicate field ID in {name}"
        assert any(item.get("type") == "checkboxes" for item in body)
        for item in body:
            if item.get("type") == "dropdown":
                options = item.get("attributes", {}).get("options", [])
                assert options and all(isinstance(option, str) and option for option in options), (
                    f"dropdown options must be non-empty strings in {name}"
                )

        rendered = (FORMS_DIR / name).read_text(encoding="utf-8").lower()
        assert "private" in rendered
        assert "security" in rendered or "vulnerab" in rendered


def test_issue_routing_uses_project_owned_discussion_categories() -> None:
    config = yaml.safe_load((FORMS_DIR / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    links = config["contact_links"]
    assert [link["url"] for link in links] == [
        "https://github.com/Miko997/metriplane/discussions/categories/q-a",
        "https://github.com/Miko997/metriplane/discussions/categories/ideas",
        "https://github.com/Miko997/metriplane/security/advisories/new",
    ]
    support = _read("SUPPORT.md")
    assert links[0]["url"] in support
    assert links[1]["url"] in support


def test_contribution_guide_covers_development_privacy_and_frozen_evidence() -> None:
    guide = _read("CONTRIBUTING.md")
    for required in (
        "Python 3.12 or 3.13",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q",
        "tests/fixtures/",
        "synthetic fixture",
        "Privacy and contributed recordings",
        "Licensing and attribution",
        "v0.2.0",
        "8e35ed5bb20837f7dc46354777407b848d7ce17a",
        "v0.1.3",
    ):
        assert required in guide
    assert "evidence/paper_v2_0/" in guide
    assert "Do not edit, regenerate" in guide


def test_code_of_conduct_is_attributed_contributor_covenant_2_1() -> None:
    code = _read("CODE_OF_CONDUCT.md")
    for heading in (
        "## Our Pledge",
        "## Our Standards",
        "## Enforcement Responsibilities",
        "## Scope",
        "## Enforcement",
        "## Enforcement Guidelines",
        "## Attribution",
    ):
        assert heading in code
    assert "Contributor Covenant" in code
    assert "version 2.1" in code
    assert "https://www.contributor-covenant.org/version/2/1/code_of_conduct.html" in code


def test_support_asks_for_reproducible_non_sensitive_information() -> None:
    support = _read("SUPPORT.md")
    for required in (
        "metriplane --version",
        "operating system",
        "Python version",
        "exact command",
        "metriplane doctor",
        "metriplane demo",
        "smallest synthetic input",
        "No fresh v0.4.0 WSL2 or native-Windows validation is claimed",
        "Raw or generic ROS 2",
        "v0.2.0",
        "v0.1.3",
    ):
        assert required in support
    assert "upload credentials" in support


def test_pull_request_template_covers_required_review_dimensions() -> None:
    template = _read(".github/PULL_REQUEST_TEMPLATE.md")
    for heading in ("## Outcome", "## Changes", "## Validation", "## Boundaries"):
        assert heading in template
    for prompt in (
        "### Problem",
        "### Scope",
        "### User-visible behavior",
        "### Tests",
        "### Documentation",
        "### Compatibility",
        "### Privacy and security",
        "### Evidence and research impact",
        "### Checklist",
    ):
        assert prompt in template
    assert len(re.findall(r"^## ", template, re.MULTILINE)) == 4
    assert len(re.findall(r"^- \[ \] ", template, re.MULTILINE)) == 8
    assert "Frozen v0.2.0 evidence" in template
    assert "TIM v0.1.3" in template


def test_active_community_copy_uses_metriplane_product_casing() -> None:
    paths = [
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        ROOT / "CODE_OF_CONDUCT.md",
        ROOT / "SUPPORT.md",
        ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
        *sorted(FORMS_DIR.glob("*.yml")),
    ]
    for path in paths:
        assert "MetriPlane" not in path.read_text(encoding="utf-8"), path


def test_private_routes_are_verified_before_merge() -> None:
    security = _read("SECURITY.md")
    conduct = _read("CODE_OF_CONDUCT.md")
    issue_config = _read(".github/ISSUE_TEMPLATE/config.yml")
    combined = "\n".join((security, conduct, issue_config))

    pending_markers = (
        "SECURITY_PRIVATE_ROUTE_PENDING",
        "PRIVATE REPORTING ROUTE PENDING",
    )
    assert not any(marker in combined for marker in pending_markers), (
        "enable and verify GitHub private vulnerability reporting, then remove "
        "the security merge-blocker placeholders"
    )
    assert "https://github.com/Miko997/metriplane/security/advisories/new" in security
    assert "https://github.com/Miko997/metriplane/security/advisories/new" in issue_config
    assert (
        "https://docs.github.com/en/communities/maintaining-your-safety-on-github/"
        "reporting-abuse-or-spam" in conduct
    )
    assert "does not\nclaim to operate a separate private conduct inbox" in conduct
    assert not re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", combined, re.IGNORECASE), (
        "do not add an unverified email contact"
    )


def test_package_support_url_points_to_support_policy() -> None:
    pyproject = _read("pyproject.toml")
    assert 'Support = "https://github.com/Miko997/metriplane/blob/main/SUPPORT.md"' in pyproject
