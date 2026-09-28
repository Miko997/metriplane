# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

from setuptools import find_namespace_packages

import metriplane
from metriplane._version import DEVELOPMENT_VERSION, RELEASE_VERSION


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGES = {
    "integrations",
    "integrations.isaac",
    "integrations.isaac.scene_templates",
    "integrations.omniverse",
    "metriplane",
    "metriplane.assistant",
    "metriplane.atlas",
    "metriplane.backends",
    "metriplane.calibration",
    "metriplane.camera",
    "metriplane.camera_trust",
    "metriplane.compute",
    "metriplane.config",
    "metriplane.contracts",
    "metriplane.counterfactuals",
    "metriplane.demo",
    "metriplane.demo.assets",
    "metriplane.demo.assets.assembly_cell",
    "metriplane.exporters",
    "metriplane.external_sources",
    "metriplane.fleet",
    "metriplane.forecasting",
    "metriplane.fusion",
    "metriplane.mapping",
    "metriplane.observability",
    "metriplane.pipeline",
    "metriplane.preview",
    "metriplane.provenance",
    "metriplane.recording",
    "metriplane.replay",
    "metriplane.runner",
    "metriplane.sentinel",
    "metriplane.streaming",
    "metriplane.system",
    "metriplane.testing",
    "metriplane.time",
    "metriplane.trace",
}


def _metadata() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_development_and_release_identities_are_distinct_and_pep440_normalized() -> None:
    assert DEVELOPMENT_VERSION == "0.5.0.dev0"
    assert RELEASE_VERSION == "0.5.0"
    assert DEVELOPMENT_VERSION != RELEASE_VERSION
    assert metriplane.__version__ in {DEVELOPMENT_VERSION, RELEASE_VERSION}


def test_build_backend_and_dynamic_version_source_are_exact() -> None:
    metadata = _metadata()

    assert metadata["build-system"] == {
        "requires": ["setuptools==82.0.1"],
        "build-backend": "setuptools.build_meta",
    }
    assert metadata["project"]["dynamic"] == ["version"]  # type: ignore[index]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"] == {  # type: ignore[index]
        "attr": "metriplane.__version__"
    }


def test_package_discovery_is_an_exact_allowlist() -> None:
    metadata = _metadata()
    policy = metadata["tool"]["setuptools"]["packages"]["find"]  # type: ignore[index]
    declared = policy["include"]
    discovered = find_namespace_packages(
        where=str(ROOT),
        include=declared,
        exclude=policy["exclude"],
    )

    assert "metriplane*" not in declared
    assert "integrations*" not in declared
    assert all("*" not in name[:-1] for name in declared)
    assert len(declared) == len(set(declared))
    assert set(discovered) == EXPECTED_PACKAGES
    assert not any(name.startswith("integrations.ros2") for name in discovered)


def test_wheel_metadata_and_payload_match_the_declared_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(".git", ".venv", "*.egg-info", "build", "dist"),
    )
    subprocess.run(["git", "init", "-q", source], check=True)
    subprocess.run(["git", "-C", source, "add", "--all"], check=True)
    subprocess.run(
        ["git", "-C", source, "commit", "-qm", "package identity fixture"],
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Metriplane Tests",
            "GIT_AUTHOR_EMAIL": "tests@metriplane.invalid",
            "GIT_COMMITTER_NAME": "Metriplane Tests",
            "GIT_COMMITTER_EMAIL": "tests@metriplane.invalid",
        },
    )
    dist = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--outdir",
            str(dist),
            str(source),
        ],
        check=True,
        cwd=source,
        capture_output=True,
        text=True,
    )
    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1
    normalized_version = metriplane.__version__.replace("-", "_")
    assert wheels[0].name == f"metriplane-{normalized_version}-py3-none-any.whl"

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        installed_metadata = archive.read(metadata_name).decode("utf-8")
        assert f"Version: {metriplane.__version__}\n" in installed_metadata
        assert "metriplane/_version.py" in names
        assert "metriplane/py.typed" in names
        assert "metriplane/build-info.json" in names
        assert not any(name.startswith("integrations/ros2/") for name in names)

    assert importlib.metadata.version("setuptools") == "82.0.1"
