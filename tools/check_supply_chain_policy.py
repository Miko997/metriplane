# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail-closed validation for the MP2-029 supply-chain control contract."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any

import yaml


class SupplyChainPolicyError(ValueError):
    """The repository does not satisfy its declared supply-chain policy."""


SHA_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
SOURCE_RUN = (
    'source_sha="$(git rev-parse HEAD)"\n'
    'test "$source_sha" = "$GITHUB_SHA"\n'
    'echo "sha=$source_sha" >> "$GITHUB_OUTPUT"\n'
)
REQUIRED_CONTROLS = {
    "dependency-review",
    "osv",
    "pip-audit",
    "image-scan",
    "secret-scan",
    "sbom",
}
SUPPLY_CHAIN_DEPENDENCIES = (
    "policy",
    "dependency-review",
    "osv",
    "pip-audit",
    "image-scan",
    "secret-scan",
    "sbom",
)
WRITE_PERMISSION_ALLOWLIST = {
    ("cluster-fuzz-lite.yml", "fuzz", "security-events"),
    ("codeql.yml", "analyze-python", "security-events"),
    ("codeql.yml", "analyze-javascript", "security-events"),
    ("publish-pypi.yml", "publish-testpypi", "id-token"),
    ("publish-pypi.yml", "publish-pypi", "id-token"),
    ("scorecard-analysis.yml", "analysis", "security-events"),
    ("scorecard-analysis.yml", "analysis", "id-token"),
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SupplyChainPolicyError(message)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path}: expected object")
    return value


def _permissions(
    value: Any, *, workflow: str, job: str | None, writes: set[tuple[str, str, str]]
) -> None:
    _require(isinstance(value, dict), f"permissions must be an explicit mapping: {workflow}")
    for permission, access in value.items():
        _require(isinstance(permission, str), f"invalid permission: {workflow}")
        _require(access in {"read", "write", "none"}, f"invalid permission access: {workflow}")
        if access == "write":
            _require(job is not None, f"workflow-level write permission: {workflow}:{permission}")
            writes.add((workflow, job, permission))


def _workflow_step(job: dict[str, Any], action: str, label: str) -> dict[str, Any]:
    matches = [step for step in job.get("steps", []) if step.get("uses") == action]
    _require(len(matches) == 1, f"{label}: action step is missing or duplicated")
    return matches[0]


def _checkout_step(
    job: dict[str, Any], *, label: str, expected_inputs: dict[str, Any]
) -> dict[str, Any]:
    matches = [
        step
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    _require(len(matches) == 1, f"{label}: checkout is missing or duplicated")
    checkout = matches[0]
    _require(checkout.get("with") == expected_inputs, f"{label}: checkout input drift")
    return checkout


def _validate_source_job(
    job: dict[str, Any], *, label: str, checkout_inputs: dict[str, Any], source_name: str
) -> None:
    _require(
        job.get("outputs", {}).get("source_sha") == "${{ steps.source.outputs.sha }}",
        f"{label}: exact source output is missing",
    )
    _checkout_step(job, label=label, expected_inputs=checkout_inputs)
    matches = [step for step in job.get("steps", []) if step.get("id") == "source"]
    _require(len(matches) == 1, f"{label}: source step is missing or duplicated")
    _require(
        matches[0] == {"name": source_name, "id": "source", "run": SOURCE_RUN},
        f"{label}: source step drift",
    )


def _named_run_argv(job: dict[str, Any], name: str, label: str) -> list[str]:
    matches = [step for step in job.get("steps", []) if step.get("name") == name]
    _require(len(matches) == 1, f"{label}: command step is missing or duplicated")
    run = matches[0].get("run")
    _require(isinstance(run, str), f"{label}: command is not a string")
    return shlex.split(run)


def _validate_aggregate(
    job: dict[str, Any], *, dependencies: tuple[str, ...], terminal: str, label: str
) -> None:
    _require(job.get("if") == "always()", f"{label}: condition is not canonical")
    _require(job.get("needs") == list(dependencies), f"{label}: dependency drift")
    env = job.get("env")
    _require(isinstance(env, dict) and set(env) == {"RESULTS_JSON"}, f"{label}: environment drift")
    try:
        results = json.loads(env["RESULTS_JSON"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise SupplyChainPolicyError(f"{label}: results are not canonical JSON") from exc
    _require(
        isinstance(results, dict) and tuple(results) == dependencies, f"{label}: result keys drift"
    )
    for dependency in dependencies:
        _require(
            results[dependency]
            == {
                "result": f"${{{{ needs.{dependency}.result }}}}",
                "sha": f"${{{{ needs.{dependency}.outputs.source_sha }}}}",
            },
            f"{label}: result binding drift: {dependency}",
        )
    matches = [
        step
        for step in job.get("steps", [])
        if step.get("name")
        in {"Validate exact supply-chain aggregate", "Validate exact aggregate result"}
    ]
    _require(len(matches) == 1, f"{label}: validator step is missing or duplicated")
    expected_argv = [
        "python",
        "tools/check_required_terminal.py",
        "aggregate",
        "--terminal",
        terminal,
        "--expected-sha",
        "$GITHUB_SHA",
    ]
    for dependency in dependencies:
        expected_argv.extend(("--expected-dependency", dependency))
    expected_argv.extend(("--results-json", "$RESULTS_JSON"))
    run = matches[0].get("run")
    _require(
        isinstance(run, str) and shlex.split(run) == expected_argv,
        f"{label}: validator argv drift",
    )


def _validate_supply_chain_workflow(workflow: dict[str, Any], policy: dict[str, Any]) -> None:
    jobs = workflow["jobs"]
    controls = {
        "policy",
        "dependency-review",
        "osv",
        "pip-audit",
        "image-scan",
        "secret-scan",
        "sbom",
    }
    _require(set(jobs) == controls | {"aggregate"}, "supply-chain job inventory drift")
    actions = policy["actions"]
    action_jobs = {
        "dependency-review": "dependency-review",
        "osv": "osv",
        "pip-audit": "pip-audit",
        "image-scan": "image-scan",
        "secret-scan": "secret-scan",
        "sbom": "sbom",
    }
    for name, job in jobs.items():
        _require(job.get("continue-on-error") is not True, f"{name}: continue-on-error")
        expected_if = "always()" if name == "aggregate" else None
        _require(job.get("if") == expected_if, f"{name}: job condition is not canonical")
        _validate_source_job(
            job,
            label=name,
            checkout_inputs={
                "persist-credentials": False,
                **({"fetch-depth": 0} if name == "secret-scan" else {}),
            },
            source_name="Record exact source",
        )
        for step in job.get("steps", []):
            _require(step.get("continue-on-error") is not True, f"{name}: step allows failure")
    for control, job_name in action_jobs.items():
        step = _workflow_step(jobs[job_name], actions[control], control)
        if control != "dependency-review":
            _require("if" not in step, f"{control}: scanner is conditional")

    dependency_step = _workflow_step(
        jobs["dependency-review"], actions["dependency-review"], "dependency-review"
    )
    _require(
        dependency_step.get("if") == "github.event_name == 'pull_request'",
        "dependency-review condition drift",
    )
    _require(
        dependency_step.get("with")
        == {
            "fail-on-severity": "moderate",
            "license-check": True,
            "deny-licenses": "GPL-3.0, AGPL-3.0",
        },
        "dependency review inputs",
    )

    osv_inputs = _workflow_step(jobs["osv"], actions["osv"], "osv").get("with", {})
    _require(osv_inputs == {"scan-args": "--recursive\n./"}, "OSV scan target")
    _require(
        _named_run_argv(
            jobs["pip-audit"], "Export the exact locked dependency graph", "pip-audit export"
        )
        == [
            "uv",
            "export",
            "--directory",
            "${{ matrix.project }}",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--no-emit-local",
            "--format",
            "requirements-txt",
            "--output-file",
            "$RUNNER_TEMP/requirements.txt",
        ],
        "pip-audit export command drift",
    )
    pip_inputs = _workflow_step(jobs["pip-audit"], actions["pip-audit"], "pip-audit").get(
        "with", {}
    )
    _require(
        pip_inputs
        == {
            "inputs": "${{ runner.temp }}/requirements.txt",
            "no-deps": True,
            "require-hashes": True,
            "vulnerability-service": "OSV",
        },
        "pip-audit fail-closed inputs",
    )
    expected_projects = [project["directory"] for project in policy["python_projects"]]
    _require(
        jobs["pip-audit"]["strategy"]["matrix"]["project"] == expected_projects,
        "pip-audit project matrix drift",
    )

    image_matrix = jobs["image-scan"]["strategy"]["matrix"]["include"]
    _require(
        [entry["dockerfile"] for entry in image_matrix] == policy["images"]["scanned"],
        "runtime image matrix drift",
    )
    _require(
        image_matrix
        == [
            {"dockerfile": "docker/Dockerfile", "image": "portable"},
            {"dockerfile": "docker/jetson.Dockerfile", "image": "jetson-replay"},
        ],
        "runtime image identity drift",
    )
    _require(
        _named_run_argv(
            jobs["image-scan"], "Build exact-source runtime image", "runtime image build"
        )
        == [
            "docker",
            "build",
            "--tag",
            "metriplane-supply-chain-${{ matrix.image }}:$GITHUB_SHA",
            "--file",
            "${{ matrix.dockerfile }}",
            ".",
        ],
        "runtime image build command drift",
    )
    trivy = _workflow_step(jobs["image-scan"], actions["image-scan"], "image-scan").get("with", {})
    _require(
        trivy
        == {
            "image-ref": "metriplane-supply-chain-${{ matrix.image }}:${{ github.sha }}",
            "version": policy["tool_versions"]["trivy"],
            "format": "table",
            "exit-code": "1",
            "ignore-unfixed": True,
            "vuln-type": "os,library",
            "severity": "CRITICAL,HIGH",
        },
        "Trivy fail-closed inputs",
    )
    secret = _workflow_step(jobs["secret-scan"], actions["secret-scan"], "secret-scan").get(
        "with", {}
    )
    _require(
        secret
        == {
            "path": "./",
            "extra_args": "--results=verified,unknown",
            "version": policy["tool_versions"]["trufflehog"],
        },
        "secret scanner inputs",
    )
    sbom = _workflow_step(jobs["sbom"], actions["sbom"], "sbom").get("with", {})
    _require(
        sbom
        == {
            "path": ".",
            "format": "spdx-json",
            "output-file": "metriplane-${{ github.sha }}.spdx.json",
            "artifact-name": "metriplane-${{ github.sha }}-sbom",
            "syft-version": policy["tool_versions"]["syft"],
            "upload-artifact": True,
            "upload-artifact-retention": 30,
            "upload-release-assets": False,
        },
        "SBOM retention inputs",
    )

    _validate_aggregate(
        jobs["aggregate"],
        dependencies=SUPPLY_CHAIN_DEPENDENCIES,
        terminal="Supply-chain aggregate",
        label="supply-chain aggregate",
    )


def validate_policy(root: Path) -> dict[str, Any]:
    policy = _load_json(root / "supply-chain-policy.json")
    _require(policy.get("schema_version") == "metriplane.supply-chain-policy.v1", "schema")
    _require(policy.get("owner") == "MP2-029", "owner")
    _require(set(policy.get("required_controls", [])) == REQUIRED_CONTROLS, "controls")

    actions = policy.get("actions")
    _require(isinstance(actions, dict) and set(actions) == REQUIRED_CONTROLS, "actions")
    for name, action in actions.items():
        _require(isinstance(action, str) and SHA_ACTION.fullmatch(action) is not None, name)

    versions = policy.get("tool_versions")
    _require(
        isinstance(versions, dict) and set(versions) == {"syft", "trivy", "trufflehog"}, "versions"
    )
    _require(all(isinstance(value, str) and value for value in versions.values()), "versions")

    projects = policy.get("python_projects")
    _require(isinstance(projects, list) and projects, "python projects")
    declared_locks: set[str] = set()
    for project in projects:
        _require(isinstance(project, dict) and set(project) == {"directory", "lock"}, "project")
        directory = root / project["directory"]
        lock = root / project["lock"]
        _require((directory / "pyproject.toml").is_file(), f"missing pyproject: {directory}")
        _require(lock.is_file() and lock.name == "uv.lock", f"missing lock: {lock}")
        declared_locks.add(lock.relative_to(root).as_posix())
    additional_locks = policy.get("additional_locks")
    _require(
        isinstance(additional_locks, list)
        and additional_locks
        and len(set(additional_locks)) == len(additional_locks),
        "additional locks",
    )
    _require(all((root / path).is_file() for path in additional_locks), "missing additional lock")
    all_locks = {path.relative_to(root).as_posix() for path in root.rglob("uv.lock")}
    _require(declared_locks | set(additional_locks) == all_locks, "lock inventory drift")

    images = policy.get("images")
    _require(isinstance(images, dict) and set(images) == {"scanned", "excluded"}, "images")
    scanned_images = images["scanned"]
    excluded_images = images["excluded"]
    _require(
        isinstance(scanned_images, list)
        and isinstance(excluded_images, list)
        and all(
            isinstance(item, dict) and set(item) == {"path", "reason"} for item in excluded_images
        ),
        "image inventory",
    )
    excluded_paths = [item["path"] for item in excluded_images]
    _require(all(item["reason"] for item in excluded_images), "image exclusion reason")
    all_images = {
        path.relative_to(root).as_posix() for path in root.rglob("*Dockerfile") if path.is_file()
    }
    _require(set(scanned_images) | set(excluded_paths) == all_images, "image inventory drift")

    license_files = policy.get("license_files")
    _require(
        isinstance(license_files, list) and len(set(license_files)) == len(license_files),
        "licenses",
    )
    _require(all((root / path).is_file() for path in license_files), "missing license file")

    writes: set[tuple[str, str, str]] = set()
    workflow_directory = root / ".github/workflows"
    workflow_paths = sorted(workflow_directory.iterdir())
    _require(
        all(path.is_file() and path.suffix in {".yml", ".yaml"} for path in workflow_paths),
        "unexpected workflow document form",
    )
    for path in workflow_paths:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        _require(isinstance(workflow, dict), f"invalid workflow: {path}")
        _permissions(workflow.get("permissions"), workflow=path.name, job=None, writes=writes)
        jobs = workflow.get("jobs")
        _require(isinstance(jobs, dict), f"missing jobs: {path.name}")
        for job_name, job in jobs.items():
            _require(isinstance(job, dict), f"invalid job: {path.name}:{job_name}")
            if "permissions" in job:
                _permissions(job["permissions"], workflow=path.name, job=job_name, writes=writes)
            job_uses = job.get("uses")
            if isinstance(job_uses, str) and not job_uses.startswith("./"):
                _require(
                    SHA_ACTION.fullmatch(job_uses) is not None,
                    f"unpinned job action: {path.name}:{job_uses}",
                )
            for step in job.get("steps", []):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if isinstance(uses, str) and not uses.startswith("./"):
                    _require(
                        SHA_ACTION.fullmatch(uses) is not None,
                        f"unpinned action: {path.name}:{uses}",
                    )
                if isinstance(uses, str) and uses.startswith("actions/checkout@"):
                    _require(
                        step.get("with", {}).get("persist-credentials") is False,
                        f"checkout credentials persist: {path.name}:{job_name}",
                    )
    _require(writes == WRITE_PERMISSION_ALLOWLIST, "write permission allowlist drift")

    supply_chain = yaml.safe_load(
        (root / ".github/workflows/supply-chain-security.yml").read_text(encoding="utf-8")
    )
    _validate_supply_chain_workflow(supply_chain, policy)
    codeql = yaml.safe_load((root / ".github/workflows/codeql.yml").read_text(encoding="utf-8"))
    for name in ("analyze-python", "analyze-javascript"):
        _validate_source_job(
            codeql["jobs"][name],
            label=f"codeql {name}",
            checkout_inputs={"persist-credentials": False},
            source_name="Record checked-out source",
        )
    security = codeql["jobs"]["security-required"]
    _checkout_step(
        security,
        label="security aggregate",
        expected_inputs={"persist-credentials": False},
    )
    _validate_aggregate(
        security,
        dependencies=("analyze-python", "analyze-javascript", "supply-chain"),
        terminal="Security / required",
        label="security aggregate",
    )
    _require(
        codeql["jobs"]["supply-chain"]["uses"] == "./.github/workflows/supply-chain-security.yml",
        "supply-chain call",
    )
    dependabot = yaml.safe_load((root / ".github/dependabot.yml").read_text(encoding="utf-8"))
    pip_directories: set[str] = set()
    docker_directories: set[str] = set()
    for update in dependabot["updates"]:
        directories = update.get("directories", [update.get("directory")])
        if update["package-ecosystem"] == "pip":
            pip_directories.update(directories)
        elif update["package-ecosystem"] == "docker":
            docker_directories.update(directories)
    expected_pip_directories = {
        "/" if project["directory"] == "." else f"/{project['directory']}" for project in projects
    }
    _require(pip_directories == expected_pip_directories, "Dependabot Python coverage drift")
    _require(docker_directories == {"/", "/docker"}, "Dependabot Docker coverage drift")
    return policy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    policy = validate_policy(args.repository_root.resolve())
    print(
        json.dumps(
            {
                "owner": policy["owner"],
                "result": "success",
                "schema_version": policy["schema_version"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
