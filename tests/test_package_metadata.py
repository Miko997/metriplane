# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_describes_the_installed_user_outcome() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert project["description"] == (
        "Turn recorded workcell state into incident reports, verified evidence, "
        "and repeatable robotics regression checks."
    )
    assert project["requires-python"] == ">=3.12,<3.14"
    assert set(
        (
            "robotics",
            "robotics testing",
            "incident analysis",
            "replay",
            "regression testing",
            "reproducibility",
            "workcells",
            "simulation",
            "digital twins",
            "industrial automation",
        )
    ).issubset(project["keywords"])
    for classifier in (
        "Intended Audience :: Developers",
        "Intended Audience :: Manufacturing",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Testing",
    ):
        assert classifier in project["classifiers"]


def test_project_urls_are_current_and_keep_research_versions_distinct() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    urls = metadata["project"]["urls"]

    assert urls == {
        "Homepage": "https://www.metriplane.com/",
        "Documentation": "https://github.com/Miko997/metriplane/blob/main/docs/README.md",
        "Repository": "https://github.com/Miko997/metriplane",
        "Issues": "https://github.com/Miko997/metriplane/issues",
        "Changelog": "https://github.com/Miko997/metriplane/blob/main/CHANGELOG.md",
        "Support": "https://github.com/Miko997/metriplane/blob/main/SUPPORT.md",
        "Roadmap": "https://github.com/Miko997/metriplane/blob/main/ROADMAP.md",
        "Research Artifact v0.2.0": "https://doi.org/10.5281/zenodo.20736619",
        "Research Preprint": "https://doi.org/10.2139/ssrn.7166858",
    }
    assert "v0.2.0" in next(label for label in urls if label.startswith("Research Artifact"))


def test_distribution_version_remains_dynamic_until_release_candidate() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["dynamic"] == ["version"]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "metriplane.__version__"
    }
