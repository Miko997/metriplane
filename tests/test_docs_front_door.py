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
    "user-guide/integrations.md",
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


def test_preview_install_and_research_boundaries_are_truthful() -> None:
    quickstart = (GUIDE / "quickstart.md").read_text(encoding="utf-8")
    research = (GUIDE / "research-artifacts.md").read_text(encoding="utf-8")

    assert "v0.3.0 is not published yet" in quickstart
    assert "PyPI still serves v0.2.1" in quickstart
    assert "manual pre-release path" in quickstart
    assert 'python -m pip install "metriplane==0.3.0"' in quickstart
    assert "not" in quickstart.split("planned release path", 1)[1].lower()
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
