# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.check_dependency_licenses import (
    DependencyLicenseError,
    parse_frozen_requirements,
    validate_dependency_licenses,
    validate_source_identity,
)


def _requirements(tmp_path: Path, text: str = "demo==1.2.3\n", name: str = "current") -> Path:
    path = tmp_path / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _metadata(license_value: str | None, *, version: str = "1.2.3") -> dict[str, Any]:
    return {
        "info": {
            "classifiers": [],
            "license": license_value,
            "license_expression": None,
            "name": "demo",
            "version": version,
        }
    }


def _validate(
    tmp_path: Path,
    *,
    license_value: str | None,
    current: str = "demo==1.2.3\n",
    baseline: str = "",
) -> dict[str, object]:
    return validate_dependency_licenses(
        [_requirements(tmp_path, current)],
        baseline_requirements=[_requirements(tmp_path, baseline, "baseline")],
        denied_licenses=["GPL-3.0", "AGPL-3.0"],
        index_url="https://pypi.org/pypi",
        fetch=lambda _name, _version: _metadata(license_value),
    )


def test_exact_frozen_requirements_are_deduplicated(tmp_path: Path) -> None:
    first = _requirements(tmp_path)
    second = _requirements(tmp_path, "Demo==1.2.3\n", "second")
    assert parse_frozen_requirements([first, second]) == [("demo", "1.2.3")]


def test_distinct_frozen_versions_are_each_reviewed(tmp_path: Path) -> None:
    first = _requirements(tmp_path)
    second = _requirements(tmp_path, "demo==2.0.0\n", "second")
    assert parse_frozen_requirements([first, second]) == [
        ("demo", "1.2.3"),
        ("demo", "2.0.0"),
    ]


@pytest.mark.parametrize("line", ("demo>=1", "demo", "demo @ https://example.invalid/demo.whl"))
def test_non_exact_requirement_fails_closed(tmp_path: Path, line: str) -> None:
    with pytest.raises(DependencyLicenseError, match="non-exact requirement"):
        parse_frozen_requirements([_requirements(tmp_path, f"{line}\n")])


@pytest.mark.parametrize(
    ("license_value", "denied"),
    (
        ("GPL-3.0-only", "GPL-3.0"),
        ("GNU General Public License v3", "GPL-3.0"),
        ("AGPL-3.0-or-later", "AGPL-3.0"),
        ("GNU Affero General Public License Version 3", "AGPL-3.0"),
    ),
)
def test_denied_license_fails_closed(tmp_path: Path, license_value: str, denied: str) -> None:
    with pytest.raises(DependencyLicenseError, match=f"denied license {denied}"):
        _validate(tmp_path, license_value=license_value)


@pytest.mark.parametrize("license_value", (None, "", "UNKNOWN", "Unknown License", "N/A"))
def test_missing_or_unknown_license_evidence_fails_closed(
    tmp_path: Path, license_value: str | None
) -> None:
    with pytest.raises(DependencyLicenseError, match="missing or unknown license evidence"):
        _validate(tmp_path, license_value=license_value)


def test_lgpl_and_mit_are_not_misclassified_as_denied(tmp_path: Path) -> None:
    assert _validate(tmp_path, license_value="MIT OR LGPL-3.0-only")["verdict"] == "PASS"


def test_unchanged_project_runtime_package_is_not_reclassified(tmp_path: Path) -> None:
    result = _validate(
        tmp_path,
        license_value="GPL-3.0-only",
        baseline="demo==1.2.3\n",
    )
    assert result["reviewed_package_count"] == 0
    assert result["reviewed_packages"] == []


def test_cross_project_introduction_cannot_hide_behind_other_baseline(tmp_path: Path) -> None:
    current_a = _requirements(tmp_path, "demo==1.2.3\n", "current-a")
    current_b = _requirements(tmp_path, "other==2.0.0\n", "current-b")
    baseline_a = _requirements(tmp_path, "", "baseline-a")
    baseline_b = _requirements(tmp_path, "demo==1.2.3\nother==2.0.0\n", "baseline-b")

    def metadata(name: str, version: str) -> dict[str, Any]:
        if name == "demo":
            return _metadata("GPL-3.0-only", version=version)
        return {
            "info": {
                "classifiers": [],
                "license": "MIT",
                "license_expression": None,
                "name": name,
                "version": version,
            }
        }

    with pytest.raises(DependencyLicenseError, match="denied license GPL-3.0"):
        validate_dependency_licenses(
            [current_a, current_b],
            baseline_requirements=[baseline_a, baseline_b],
            denied_licenses=["GPL-3.0", "AGPL-3.0"],
            index_url="https://pypi.org/pypi",
            fetch=metadata,
        )


def test_source_identity_is_exact_and_schedule_bound(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True
    )
    _requirements(tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    validate_source_identity(tmp_path, event_name="schedule", base=head, head=head)
    with pytest.raises(DependencyLicenseError, match="checked-out source differs"):
        validate_source_identity(tmp_path, event_name="schedule", base=head, head="f" * 40)


def test_metadata_must_bind_exact_name_and_version(tmp_path: Path) -> None:
    with pytest.raises(DependencyLicenseError, match="metadata version mismatch"):
        validate_dependency_licenses(
            [_requirements(tmp_path)],
            baseline_requirements=[_requirements(tmp_path, "", "baseline")],
            denied_licenses=["GPL-3.0", "AGPL-3.0"],
            index_url="https://pypi.org/pypi",
            fetch=lambda _name, _version: _metadata("MIT", version="9.9.9"),
        )


def test_policy_index_and_project_inventory_drift_fail_closed(tmp_path: Path) -> None:
    requirements = [_requirements(tmp_path)]
    baseline = [_requirements(tmp_path, "", "baseline")]
    with pytest.raises(DependencyLicenseError, match="denied license policy"):
        validate_dependency_licenses(
            requirements,
            baseline_requirements=baseline,
            denied_licenses=["GPL-3.0"],
            index_url="https://pypi.org/pypi",
        )
    with pytest.raises(DependencyLicenseError, match="metadata index drift"):
        validate_dependency_licenses(
            requirements,
            baseline_requirements=baseline,
            denied_licenses=["GPL-3.0", "AGPL-3.0"],
            index_url="https://mirror.invalid/pypi",
        )
    with pytest.raises(DependencyLicenseError, match="project inventories differ"):
        validate_dependency_licenses(
            requirements,
            baseline_requirements=[],
            denied_licenses=["GPL-3.0", "AGPL-3.0"],
            index_url="https://pypi.org/pypi",
        )
