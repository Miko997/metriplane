# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail closed on denied licenses in exact frozen requirement exports."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, cast


class DependencyLicenseError(ValueError):
    """Exact dependency license evidence is unavailable or denied."""


PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^ ;\\]+)(?:\s*;.*)?\s*\\?$")
MAX_RESPONSE_BYTES = 2_000_000
SHA = re.compile(r"^[0-9a-f]{40}$")
EVENTS = {"pull_request", "push", "schedule"}
Fetch = Callable[[str, str], dict[str, Any]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DependencyLicenseError(message)


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_frozen_requirements(
    paths: Iterable[Path], *, allow_empty: bool = False
) -> list[tuple[str, str]]:
    packages: set[tuple[str, str]] = set()
    consumed = False
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise DependencyLicenseError(f"cannot read requirements export {path}: {exc}") from exc
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "--hash=")):
                continue
            match = PIN.fullmatch(stripped)
            if match is None:
                raise DependencyLicenseError(f"non-exact requirement in {path}: {stripped}")
            consumed = True
            name = _canonical_name(match.group(1))
            version = match.group(2)
            packages.add((name, version))
    _require(consumed or allow_empty, "requirements exports contain no exact packages")
    return sorted(packages)


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", *arguments], cwd=root, check=False, capture_output=True)
    if completed.returncode:
        raise DependencyLicenseError(
            f"git {' '.join(arguments)} failed: {completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def validate_source_identity(root: Path, *, event_name: str, base: str, head: str) -> None:
    _require(event_name in EVENTS, "unsupported provider event")
    _require(SHA.fullmatch(base) is not None, "invalid base SHA")
    _require(SHA.fullmatch(head) is not None, "invalid head SHA")
    actual_head = _git(root, "rev-parse", "HEAD")
    _require(actual_head.decode().strip() == head, "checked-out source differs from head SHA")
    if base == "0" * 40:
        _require(event_name == "push", "zero base is valid only for an initial push")
        return
    if event_name == "schedule":
        _require(base == head, "scheduled current-snapshot review must bind one SHA")
    else:
        _git(root, "merge-base", "--is-ancestor", base, head)


def _fetch_pypi(index_url: str, name: str, version: str) -> dict[str, Any]:
    url = f"{index_url.rstrip('/')}/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            _require(
                response.status == 200,
                f"metadata HTTP status for {name}=={version}: {response.status}",
            )
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise DependencyLicenseError(f"cannot fetch metadata for {name}=={version}: {exc}") from exc
    _require(
        len(payload) <= MAX_RESPONSE_BYTES, f"metadata response too large for {name}=={version}"
    )
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DependencyLicenseError(f"malformed metadata for {name}=={version}") from exc
    _require(isinstance(value, dict), f"metadata is not an object for {name}=={version}")
    return cast(dict[str, Any], value)


def _license_evidence(document: dict[str, Any], *, name: str, version: str) -> str:
    info = document.get("info")
    if not isinstance(info, dict):
        raise DependencyLicenseError(f"metadata lacks info for {name}=={version}")
    actual_name = info.get("name")
    actual_version = info.get("version")
    if not isinstance(actual_name, str) or _canonical_name(actual_name) != name:
        raise DependencyLicenseError(f"metadata name mismatch for {name}=={version}")
    _require(actual_version == version, f"metadata version mismatch for {name}=={version}")
    values: list[str] = []
    for key in ("license_expression", "license"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    classifiers = info.get("classifiers", [])
    _require(isinstance(classifiers, list), f"metadata classifiers malformed for {name}=={version}")
    values.extend(
        value for value in classifiers if isinstance(value, str) and value.startswith("License ::")
    )
    evidence = "\n".join(values)
    normalized = re.sub(r"[^A-Z0-9]+", " ", evidence.upper()).strip()
    _require(
        bool(normalized) and normalized not in {"UNKNOWN", "UNKNOWN LICENSE", "NONE", "N A"},
        f"missing or unknown license evidence for {name}=={version}",
    )
    return evidence


def _denied(evidence: str, denied: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]+", " ", evidence.upper()).strip()
    if denied == "GPL-3.0":
        return any(
            re.search(pattern, normalized) is not None
            for pattern in (
                r"(?<!AFFERO )(?<!LESSER )GNU GENERAL PUBLIC LICENSE (?:V|VERSION )?3(?:\D|$)",
                r"(?<!A)(?<!L)GPL ?V?3(?:\D|$)",
            )
        )
    if denied == "AGPL-3.0":
        return any(
            re.search(pattern, normalized) is not None
            for pattern in (
                r"GNU AFFERO GENERAL PUBLIC LICENSE (?:V|VERSION )?3(?:\D|$)",
                r"AGPL ?V?3(?:\D|$)",
            )
        )
    raise DependencyLicenseError(f"unsupported denied license policy: {denied}")


def validate_dependency_licenses(
    requirements: Iterable[Path],
    *,
    baseline_requirements: Iterable[Path],
    denied_licenses: Sequence[str],
    index_url: str,
    fetch: Fetch | None = None,
) -> dict[str, object]:
    _require(
        list(denied_licenses) == ["GPL-3.0", "AGPL-3.0"],
        "denied license policy must be exactly GPL-3.0 and AGPL-3.0",
    )
    _require(index_url == "https://pypi.org/pypi", "package metadata index drift")
    current_paths = list(requirements)
    baseline_paths = list(baseline_requirements)
    _require(
        len(current_paths) == len(baseline_paths) and bool(current_paths),
        "current and baseline project inventories differ",
    )
    projects = [set(parse_frozen_requirements([path])) for path in current_paths]
    baselines = [
        set(parse_frozen_requirements([path], allow_empty=True)) for path in baseline_paths
    ]
    packages = sorted(set().union(*projects))
    review_packages = sorted(
        set().union(*(current - baseline for current, baseline in zip(projects, baselines)))
    )
    fetch_metadata = fetch or (lambda name, version: _fetch_pypi(index_url, name, version))
    for name, version in review_packages:
        evidence = _license_evidence(fetch_metadata(name, version), name=name, version=version)
        for denied in denied_licenses:
            _require(not _denied(evidence, denied), f"denied license {denied}: {name}=={version}")
    return {
        "denied_licenses": list(denied_licenses),
        "package_count": len(packages),
        "reviewed_package_count": len(review_packages),
        "reviewed_packages": [f"{name}=={version}" for name, version in review_packages],
        "schema_version": "metriplane.dependency-license-review.v1",
        "verdict": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", action="append", type=Path, required=True)
    parser.add_argument("--baseline-requirements", action="append", type=Path, required=True)
    parser.add_argument("--deny-license", action="append", required=True)
    parser.add_argument("--index-url", default="https://pypi.org/pypi")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        validate_source_identity(
            args.repository_root.resolve(),
            event_name=args.event_name,
            base=args.base,
            head=args.head,
        )
        result = validate_dependency_licenses(
            args.requirements,
            baseline_requirements=args.baseline_requirements,
            denied_licenses=args.deny_license,
            index_url=args.index_url,
        )
    except DependencyLicenseError as exc:
        raise SystemExit(f"dependency license review failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
