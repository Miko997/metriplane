# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
GUIDE = DOCS / "user-guide"
MKDOCS = ROOT / "mkdocs.yml"

EXPECTED_NAV = (
    "README.md",
    "user-guide/quickstart.md",
    "user-guide/what-metriplane-does.md",
    "user-guide/missing-tool-example.md",
    "user-guide/inputs-and-outputs.md",
    "user-guide/cli.md",
    "user-guide/process-rules.md",
    "user-guide/use-your-own-run.md",
    "user-guide/external-fixtures.md",
    "user-guide/integrations.md",
    "specs/external-source-contract-v1.md",
    "specs/external-source-contract-v1-audit.md",
    "user-guide/maniskill-pickcube-proof.md",
    "user-guide/external-source-family-matrix-v1/README.md",
    "user-guide/external-source-family-matrix-v1/MATRIX.md",
    "user-guide/external-source-family-matrix-v1/SOURCE-CROSSWALK.md",
    "user-guide/external-source-family-matrix-v1/PROVENANCE-CROSSWALK.md",
    "user-guide/external-source-family-matrix-v1/STATE-MODEL-CROSSWALK.md",
    "user-guide/external-source-family-matrix-v1/SEMANTICS.md",
    "user-guide/external-source-family-matrix-v1/UNSUPPORTED-PATHS.md",
    "user-guide/external-source-family-matrix-v1/REOPENING.md",
    "user-guide/external-source-family-matrix-v1/EVALUATOR.md",
    "user-guide/external-source-family-matrix-v1/PARTNER-SUMMARY.md",
    "user-guide/external-source-family-matrix-v1/VALIDATION.md",
    "user-guide/external-source-family-matrix-v1/READINESS.md",
    "user-guide/troubleshooting.md",
    "user-guide/contributing.md",
    "user-guide/research-artifacts.md",
    "user-guide/citing.md",
)


def _front_door_text() -> str:
    return "\n".join((DOCS / path).read_text(encoding="utf-8") for path in EXPECTED_NAV)


def _nav_paths(nav: list[object]) -> list[str]:
    paths: list[str] = []
    for item in nav:
        assert isinstance(item, dict) and len(item) == 1
        value = next(iter(item.values()))
        if isinstance(value, str):
            paths.append(value)
        else:
            assert isinstance(value, list)
            paths.extend(_nav_paths(value))
    return paths


def test_mkdocs_uses_stock_theme_and_explicit_front_door_nav() -> None:
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
    assert config["strict"] is True
    assert config["theme"] == {"name": "mkdocs"}
    assert config["docs_dir"] == "docs"
    assert "site_url" not in config  # No documentation deployment exists yet.
    assert tuple(_nav_paths(config["nav"])) == EXPECTED_NAV
    assert all((DOCS / path).is_file() for path in EXPECTED_NAV)


def test_documentation_workflow_pins_actions_and_runs_strict_build() -> None:
    workflow = (ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    assert (
        "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in workflow
    )
    assert (
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    )
    assert "python -m mkdocs build --strict" in workflow


def test_curated_internal_markdown_links_resolve() -> None:
    link_pattern = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
    failures: list[str] = []

    for relative in EXPECTED_NAV:
        source = DOCS / relative
        for raw_target in link_pattern.findall(source.read_text(encoding="utf-8")):
            target = raw_target.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.exists():
                failures.append(f"{source.relative_to(ROOT)} -> {target}")

    assert failures == []


def test_front_door_explains_supported_input_and_product_limits() -> None:
    text = _front_door_text()
    required = (
        "FrameStateModel",
        "already-estimated",
        "zone labels",
        "positions alone",
        "exactly one work order",
        "zero incidents",
        "does not control machinery",
        "does not prove physical",
        "raw video",
        "rosbag",
        "MCAP",
    )
    assert all(fragment.lower() in text.lower() for fragment in required)


def test_after_demo_tutorial_uses_real_command_sequence() -> None:
    tutorial = (GUIDE / "use-your-own-run.md").read_text(encoding="utf-8")
    commands = (
        "metriplane demo --export-inputs my-cell",
        "metriplane atlas validate-pack my-cell/domain-pack",
        "metriplane atlas run",
        "--session-jsonl my-cell/session.jsonl",
        "--pack my-cell/domain-pack",
        "--out my-cell-run",
        "metriplane atlas report --run-dir my-cell-run",
        "metriplane atlas bundle verify",
        "metriplane atlas test",
    )
    offsets = [tutorial.index(command) for command in commands]
    assert offsets == sorted(offsets)


def test_external_fixture_guide_uses_the_canonical_safe_workflow() -> None:
    guide = (GUIDE / "external-fixtures.md").read_text(encoding="utf-8")

    required = (
        "newer than the\n> published Metriplane v0.3.0 packages",
        "development wheel built from commit",
        "a901ea8d3be62355997c08e3030512e4129ee03c",
        "The v0.3.0 packages on PyPI and conda-forge do not contain these commands",
        "metriplane external validate path/to/fixture",
        "metriplane external validate path/to/fixture --json",
        "metriplane external run path/to/fixture --out external-run",
        "--run-id inspection-replay-1",
        "external_source_provenance.json",
        "does not download it",
        "does not execute the adapter",
        "expected-outcome.json",
        "never supplied to Atlas",
        "original source framework",
        "does not prove",
        "production-ready",
    )
    assert all(fragment in guide for fragment in required)
    assert guide.index("**Availability:**") < guide.index("An External Fixture Bundle")


def test_v030_package_install_and_research_boundaries_are_truthful() -> None:
    front_door = (DOCS / "README.md").read_text(encoding="utf-8")
    quickstart = (GUIDE / "quickstart.md").read_text(encoding="utf-8")
    troubleshooting = (GUIDE / "troubleshooting.md").read_text(encoding="utf-8")
    research = (GUIDE / "research-artifacts.md").read_text(encoding="utf-8")
    exact_quickstart = """```bash
python -m pip install \"metriplane==0.3.0\"
metriplane demo --open
```"""

    assert exact_quickstart in front_door
    assert exact_quickstart in quickstart
    assert 'python -m pip install "metriplane==0.3.0"' in troubleshooting
    for text in (front_door, quickstart, troubleshooting):
        assert "current-`main`" not in text
        assert "source preview" not in text.lower()
        assert "not published" not in text.lower()
        assert "PyPI still serves v0.2.1" not in text
    assert "10.5281/zenodo.20736619" in research
    assert "10.2139/ssrn.7166858" in research
    assert "v0.1.3" in research
    assert "Do **not** attach\nthat DOI to v0.3.0" in research


def test_current_front_door_uses_product_casing() -> None:
    text = "\n".join(
        (DOCS / path).read_text(encoding="utf-8")
        for path in EXPECTED_NAV
        if path != "user-guide/citing.md"
    )
    assert "MetriPlane" not in text
    assert "agent/bundled-demo" not in text

    citation = (GUIDE / "citing.md").read_text(encoding="utf-8")
    assert "# Citing Metriplane" in citation
    assert "MetriPlane v0.2.0" in citation  # Exact frozen artifact title.


def test_pack_file_requirements_match_loader_compatibility() -> None:
    inputs = (GUIDE / "inputs-and-outputs.md").read_text(encoding="utf-8")
    assert "three required files" in inputs
    assert "`contracts.yaml` is optional" in inputs
    assert "`work_orders.csv` is optional for compatibility" in inputs


def test_root_readme_documentation_links_are_absolute_for_pypi() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Documentation", 1)[1].split("## License", 1)[0]
    assert "](docs/" not in section
    assert "](CONTRIBUTING.md)" not in section
    assert section.count("https://github.com/Miko997/metriplane/") >= 6
