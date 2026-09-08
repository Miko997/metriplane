# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.check_required_terminal import (
    TerminalValidationError,
    validate_policy,
    validate_terminal,
)
from tools.observe_main_health import REQUIRED_WORKFLOWS

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "status" / "required-terminals.json"
WORKFLOWS = ROOT / ".github" / "workflows"
SHA = "a" * 40


def _results() -> dict[str, dict[str, str]]:
    return {
        "linux": {"result": "success", "sha": SHA},
        "macos": {"result": "success", "sha": SHA},
    }


def _copy_workflow_producers(policy: dict[str, Any], workflow_root: Path) -> None:
    for terminal in policy["terminals"]:
        producers = [terminal.get("producer")]
        transition = terminal.get("transition")
        if isinstance(transition, dict):
            producers.append(transition.get("producer"))
        for producer in producers:
            if isinstance(producer, str) and producer.startswith(".github/workflows/"):
                source = ROOT / producer
                shutil.copyfile(source, workflow_root / source.name)


def test_exact_aggregate_succeeds() -> None:
    result = validate_terminal(
        terminal="Metriplane / required",
        expected_sha=SHA,
        expected_dependencies=["linux", "macos"],
        results=_results(),
    )
    assert result["result"] == "success"
    assert result["sha"] == SHA


def test_aggregate_cli_has_no_third_party_import_requirement() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "tools" / "check_required_terminal.py"),
            "aggregate",
            "--terminal",
            "Metriplane / required",
            "--expected-sha",
            SHA,
            "--expected-dependency",
            "linux",
            "--expected-dependency",
            "macos",
            "--results-json",
            json.dumps(_results()),
        ],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "stale"])
def test_non_success_dependency_fails_closed(conclusion: str) -> None:
    results = _results()
    results["linux"]["result"] = conclusion
    with pytest.raises(TerminalValidationError, match="expected success"):
        validate_terminal(
            terminal="Metriplane / required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=results,
        )


def test_missing_extra_and_wrong_sha_fail_closed() -> None:
    missing = _results()
    missing.pop("linux")
    with pytest.raises(TerminalValidationError, match="dependency set mismatch"):
        validate_terminal(
            terminal="required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=missing,
        )
    extra = _results() | {"windows": {"result": "success", "sha": SHA}}
    with pytest.raises(TerminalValidationError, match="dependency set mismatch"):
        validate_terminal(
            terminal="required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=extra,
        )
    wrong_sha = _results()
    wrong_sha["macos"]["sha"] = "b" * 40
    with pytest.raises(TerminalValidationError, match="wrong SHA"):
        validate_terminal(
            terminal="required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=wrong_sha,
        )


def test_terminal_inventory_has_app_owned_main_health_and_release_handoff() -> None:
    policy = validate_policy(POLICY, WORKFLOWS)
    active = [item for item in policy["terminals"] if item["state"] == "active"]
    reserved = [item for item in policy["terminals"] if item["state"] == "reserved"]
    assert [item["name"] for item in active] == [
        "Metriplane / required",
        "Documentation / required",
        "Security / required",
        "Main health / required",
    ]
    assert active[-1]["producer"] == "github-app:metriplane-main-health-publisher"
    assert "transition" not in active[-1]
    assert reserved == [
        {
            "name": "Release / required",
            "owner": "MP2-007",
            "producer": None,
            "state": "reserved",
        }
    ]


def test_terminal_inventory_rejects_a_substituted_app_producer(tmp_path: Path) -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    main_health = next(
        item for item in policy["terminals"] if item["name"] == "Main health / required"
    )
    main_health["producer"] = "github-app:substituted-publisher"
    changed = tmp_path / "required-terminals.json"
    changed.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(TerminalValidationError, match="governed MP2-004"):
        validate_policy(changed, WORKFLOWS)


def test_terminal_inventory_rejects_retired_transition_metadata(tmp_path: Path) -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    main_health = next(
        item for item in policy["terminals"] if item["name"] == "Main health / required"
    )
    main_health["transition"] = {
        "actions_integration_id": 15368,
        "approval_variable": "MET77_APPROVED_HEAD_SHA",
        "base_sha": "9d5b4ffa5236521423196a84acc6a613f7f13108",
        "producer": ".github/workflows/main-health.yml",
        "pull_request": 86,
    }
    changed = tmp_path / "required-terminals.json"
    changed.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(TerminalValidationError, match="transition is not permitted"):
        validate_policy(changed, WORKFLOWS)


@pytest.mark.parametrize("suffix", (".yml", ".yaml"))
def test_duplicate_or_premature_producer_is_rejected(tmp_path: Path, suffix: str) -> None:
    workflow_root = tmp_path / "workflows"
    workflow_root.mkdir()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    _copy_workflow_producers(policy, workflow_root)
    duplicate = workflow_root / f"duplicate{suffix}"
    duplicate.write_text(
        "name: duplicate\njobs:\n  required:\n    name: Main health / required\n",
        encoding="utf-8",
    )
    with pytest.raises(TerminalValidationError, match="sole producer"):
        validate_policy(POLICY, workflow_root)
    duplicate.write_text(
        "name: early\njobs:\n  required:\n    name: Release / required\n",
        encoding="utf-8",
    )
    with pytest.raises(TerminalValidationError, match="producer-free"):
        validate_policy(POLICY, workflow_root)


@pytest.mark.parametrize(
    "job_name",
    (
        "    name: ${{ matrix.terminal }}\n",
        "    name: >-\n      ${{\n        matrix.terminal\n      }}\n",
        "    name: \"${{ contains('x}}', 'x') && matrix.terminal }}\"\n",
    ),
)
def test_dynamic_job_name_that_can_render_a_terminal_is_rejected(
    tmp_path: Path, job_name: str
) -> None:
    workflow_root = tmp_path / "workflows"
    workflow_root.mkdir()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    _copy_workflow_producers(policy, workflow_root)
    (workflow_root / "dynamic.yaml").write_text(
        "name: dynamic\njobs:\n  required:\n" + job_name,
        encoding="utf-8",
    )
    with pytest.raises(TerminalValidationError, match="dynamic job name"):
        validate_policy(POLICY, workflow_root)


def test_actions_have_three_canonical_aggregates_and_no_main_health_terminal() -> None:
    expected = {
        "ci.yml": "Metriplane / required",
        "docs.yml": "Documentation / required",
        "codeql.yml": "Security / required",
    }
    for filename, terminal in expected.items():
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
        producers = [job for job in workflow["jobs"].values() if job.get("name") == terminal]
        assert len(producers) == 1
        assert "always()" in str(producers[0].get("if", ""))
        assert "outputs.source_sha" in str(producers[0])

    main_health_producers: list[str] = []
    for workflow_path in WORKFLOWS.glob("*.y*ml"):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if any(
            job.get("name") == "Main health / required" for job in workflow.get("jobs", {}).values()
        ):
            main_health_producers.append(workflow_path.name)
    assert main_health_producers == []

    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    ci_trigger = ci.get("on", ci.get(True))
    assert ci_trigger["push"] == {"branches": ["main"]}

    docs = yaml.safe_load((WORKFLOWS / "docs.yml").read_text(encoding="utf-8"))
    trigger = docs.get("on", docs.get(True))
    assert trigger["pull_request"] is None
    assert "paths" not in trigger["push"]
    assert REQUIRED_WORKFLOWS == {
        "metriplane": ("Metriplane / required", "CI"),
        "documentation": ("Documentation / required", "Documentation"),
        "security": ("Security / required", "CodeQL"),
    }


def test_main_health_workflow_is_read_only_deep_observation() -> None:
    workflow_path = WORKFLOWS / "main-health.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    trigger = workflow.get("on", workflow.get(True))
    assert trigger == {
        "repository_dispatch": {"types": ["main-health-nightly", "main-health-weekly"]},
        "schedule": [{"cron": "23 3 * * 1-6"}, {"cron": "23 3 * * 0"}],
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "main-health-deep",
        "queue": "max",
        "cancel-in-progress": False,
    }
    assert set(workflow["jobs"]) == {"nightly", "weekly"}
    assert {workflow["jobs"][name]["name"] for name in ("nightly", "weekly")} == {
        "Main health deep / nightly",
        "Main health deep / weekly",
    }
    for name in ("nightly", "weekly"):
        job = workflow["jobs"][name]
        checkout = job["steps"][0]
        assert checkout["with"] == {
            "fetch-depth": 0,
            "persist-credentials": False,
            "ref": "${{ github.sha }}",
        }
        assert job["steps"][1] == {
            "name": "Verify exact provider SHA",
            "run": 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
        }
        assert job["timeout-minutes"] == 60
    text = workflow_path.read_text(encoding="utf-8")
    assert "Main health / required" not in text
    assert "check_met77_transition.py" not in text
    assert "PR_BODY" not in text
    assert "PR_TITLE" not in text
    assert "Independent exact-SHA review" not in text
    assert "MAIN_HEALTH_APP_PRIVATE_KEY" not in text
    assert "create-github-app-token" not in text
    assert "checks: write" not in text
    assert not (WORKFLOWS / "main-health-lease.yml").exists()


@pytest.mark.skipif(shutil.which("bash") is None, reason="Main Health runs on Bash runners")
def test_main_health_shell_steps_are_valid_bash() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "main-health.yml").read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            script = step.get("run")
            if script is None:
                continue
            completed = subprocess.run(
                ["bash", "-n"],
                input=script,
                check=False,
                capture_output=True,
                text=True,
            )
            assert completed.returncode == 0, completed.stderr


def test_policy_validation_does_not_mutate_input() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    original = copy.deepcopy(policy)
    validate_policy(POLICY, WORKFLOWS)
    assert policy == original


def _suite_source() -> dict[str, Any]:
    from tools import check_required_terminal as terminal

    return {
        "commit": SHA,
        "tree": "b" * 40,
        "tree_inventory": {"format": "git-ls-tree-r-z.v1", "bytes": 1024, "sha256": "d" * 64},
        "files": {name: {"bytes": 1, "sha256": "c" * 64} for name in terminal._SOURCE_FILES},
    }


def _suite_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    from tools import check_required_terminal as terminal

    root = tmp_path / "suite-reports"
    root.mkdir()
    source = _suite_source()
    collection = [f"tests/test_sample.py::test_{i}" for i in range(8)] + sorted(
        terminal._expected_skips("macos")
    )
    for system, version, index, count in terminal._coordinates():
        directory = root / terminal._artifact_name("123", "1", system, version, index)
        directory.mkdir()
        for filename in terminal._SUITE_FILES:
            (directory / filename).write_text(f"original {filename}\n", encoding="utf-8")
        expected_skips = terminal._expected_skips(system)
        outcomes = {}
        selected = collection[index::count]
        for node in selected:
            skip = expected_skips.get(node)
            phases = (
                ["setup", "teardown"]
                if skip and skip[0] == "setup"
                else ["setup", "call", "teardown"]
            )
            outcomes[node] = [
                {
                    "when": phase,
                    "outcome": "skipped" if skip and phase == skip[0] else "passed",
                    "duration": 0.01,
                    "diagnostic": f"Skipped: {skip[1]}" if skip and phase == skip[0] else "",
                    "skip_reason": skip[1] if skip and phase == skip[0] else None,
                    "xfail": None,
                }
                for phase in phases
            ]
        report = {
            "schema_version": terminal._SUITE_SCHEMA,
            "identity": {
                "source": source,
                "workflow": "CI",
                "repository": "Miko997/metriplane",
                "run_id": "123",
                "run_attempt": "1",
                "job": terminal._job_name(system, version),
                "platform": system,
                "python_version": version,
                "python_full": version + ".1",
                "pytest_version": "8.4.2",
                "runner_os": "Linux" if system == "linux" else "macOS",
                "runner_arch": "X64",
                "runner_image": system,
                "runner_image_version": "20260101.1",
            },
            "partition": {"index": index, "count": count},
            "collection": collection,
            "collection_sha256": terminal._digest(collection),
            "selected": selected,
            "execution_order": selected,
            "outcomes": outcomes,
            "errors": [],
            "warnings": [],
            "exit_code": 0,
            "elapsed_seconds": 1.0,
            "evidence": {
                name: terminal._file_identity(directory / name) for name in terminal._SUITE_FILES
            },
            "source_after": source,
        }
        (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return root, source


def _check_suite(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    from tools import check_required_terminal as terminal

    return terminal._validate_suite_reports(
        root, source=source, run_id="123", attempt="1", repository="Miko997/metriplane"
    )


def test_complete_ten_report_suite_proves_each_platform_and_partition(tmp_path: Path) -> None:
    root, source = _suite_fixture(tmp_path)
    result = _check_suite(root, source)
    assert result["result"] == "success"
    assert result["sha"] == SHA
    assert len(result["reports"]) == 10
    assert result["collection_count"] == 25
    assert result["source"] == source
    assert result["totals"] == {
        "linux-py3.12": {"passed": 10, "skipped": 15, "failed": 0, "total": 25},
        "linux-py3.13": {"passed": 10, "skipped": 15, "failed": 0, "total": 25},
        "macos-py3.12": {"passed": 8, "skipped": 17, "failed": 0, "total": 25},
        "macos-py3.13": {"passed": 8, "skipped": 17, "failed": 0, "total": 25},
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-artifact",
        "extra-artifact",
        "extra-member",
        "missing-member",
        "tampered-log",
        "tampered-junit",
        "symlink-artifact",
        "symlink-member",
        "duplicate-json",
        "nonfinite-json",
    ],
)
def test_suite_rejects_incomplete_or_untrusted_artifact_closure(
    tmp_path: Path, mutation: str
) -> None:
    root, source = _suite_fixture(tmp_path)
    directory = root / "ci-suite-123-1-macos-py3.12-shard0"
    report_path = directory / "report.json"
    if mutation == "missing-artifact":
        shutil.rmtree(directory)
    elif mutation == "extra-artifact":
        (root / "ci-suite-123-0-linux-py3.12-shard0").mkdir()
    elif mutation == "extra-member":
        (directory / "unexpected").write_text("extra")
    elif mutation == "missing-member":
        (directory / "stdout.txt").unlink()
    elif mutation in ("tampered-log", "tampered-junit"):
        (directory / ("stdout.txt" if mutation == "tampered-log" else "junit.xml")).write_text(
            "tamper"
        )
    elif mutation == "symlink-artifact":
        other = tmp_path / "original-artifact"
        directory.rename(other)
        directory.symlink_to(other, target_is_directory=True)
    elif mutation == "symlink-member":
        other = tmp_path / "original-report"
        report_path.rename(other)
        report_path.symlink_to(other)
    elif mutation == "duplicate-json":
        report_path.write_text(
            report_path.read_text().replace("{", '{"schema_version":"duplicate",', 1)
        )
    elif mutation == "nonfinite-json":
        report_path.write_text(
            report_path.read_text().replace('"elapsed_seconds": 1.0', '"elapsed_seconds": NaN')
        )
    with pytest.raises(TerminalValidationError):
        _check_suite(root, source)


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "source-after",
        "run",
        "attempt",
        "workflow",
        "repository",
        "job",
        "platform",
        "python",
        "python-full",
        "pytest",
        "runner-os",
        "runner-image",
        "index",
        "boolean-index",
        "count",
        "collection-duplicate",
        "collection-reorder",
        "collection-digest",
        "selection-hole",
        "selection-overlap",
        "selection-reorder",
        "execution-order",
        "missing-node",
        "extra-node",
        "missing-call",
        "duplicate-phase",
        "setup-failure",
        "call-failure",
        "teardown-failure",
        "unexpected-skip",
        "xfail",
        "xpass",
        "wrong-skip-reason",
        "wrong-skip-phase",
        "missing-required-skip",
        "exit",
        "warning",
        "collection-error",
        "negative-duration",
        "nonfinite-duration",
        "extra-report-field",
        "extra-phase-field",
        "bad-evidence-size",
    ],
)
def test_suite_rejects_partial_stale_or_relabelled_results(tmp_path: Path, mutation: str) -> None:
    from tools import check_required_terminal as terminal

    root, source = _suite_fixture(tmp_path)
    report_path = root / "ci-suite-123-1-linux-py3.12-shard0" / "report.json"
    report = json.loads(report_path.read_text())
    node = report["selected"][0]
    phases = report["outcomes"][node]
    identity_keys = {
        "source": "source",
        "run": "run_id",
        "attempt": "run_attempt",
        "workflow": "workflow",
        "repository": "repository",
        "job": "job",
        "platform": "platform",
        "python": "python_version",
        "python-full": "python_full",
        "pytest": "pytest_version",
        "runner-os": "runner_os",
        "runner-image": "runner_image_version",
    }
    if mutation in identity_keys:
        report["identity"][identity_keys[mutation]] = "" if mutation == "runner-image" else "wrong"
    elif mutation == "source-after":
        report["source_after"] = None
    elif mutation in ("index", "boolean-index", "count"):
        report["partition"]["count" if mutation == "count" else "index"] = {
            "index": 1,
            "boolean-index": False,
            "count": 4,
        }[mutation]
    elif mutation == "collection-duplicate":
        report["collection"].append(node)
    elif mutation == "collection-reorder":
        report["collection"].reverse()
        report["selected"] = list(report["collection"])
        report["execution_order"] = list(report["collection"])
        report["collection_sha256"] = terminal._digest(report["collection"])
    elif mutation == "collection-digest":
        report["collection_sha256"] = "0" * 64
    elif mutation == "selection-hole":
        report["selected"].pop()
    elif mutation == "selection-overlap":
        report["selected"].append(node)
    elif mutation == "selection-reorder":
        report["selected"].reverse()
    elif mutation == "execution-order":
        report["execution_order"].reverse()
    elif mutation == "missing-node":
        del report["outcomes"][node]
    elif mutation == "extra-node":
        report["outcomes"]["unexpected"] = phases
    elif mutation == "missing-call":
        phases.pop(1)
    elif mutation == "duplicate-phase":
        phases.append(copy.deepcopy(phases[-1]))
    elif mutation in ("setup-failure", "call-failure", "teardown-failure"):
        phases[{"setup-failure": 0, "call-failure": 1, "teardown-failure": 2}[mutation]][
            "outcome"
        ] = "failed"
    elif mutation == "unexpected-skip":
        phases[1].update(outcome="skipped", skip_reason="not supported today")
    elif mutation in ("xfail", "xpass"):
        phases[1].update(
            outcome="skipped" if mutation == "xfail" else "passed", xfail="known defect"
        )
    elif mutation in ("wrong-skip-reason", "wrong-skip-phase", "missing-required-skip"):
        skipped = next(
            p for rows in report["outcomes"].values() for p in rows if p["outcome"] == "skipped"
        )
        if mutation == "wrong-skip-reason":
            skipped["skip_reason"] = "other reason"
        elif mutation == "wrong-skip-phase":
            skipped["when"] = "teardown"
        else:
            skipped.update(outcome="passed", skip_reason=None)
    elif mutation == "exit":
        report["exit_code"] = 2
    elif mutation == "warning":
        report["warnings"] = ["new warning"]
    elif mutation == "collection-error":
        report["errors"] = ["collection failed"]
    elif mutation in ("negative-duration", "nonfinite-duration"):
        phases[0]["duration"] = -1 if mutation == "negative-duration" else float("inf")
    elif mutation == "extra-report-field":
        report["waive"] = True
    elif mutation == "extra-phase-field":
        phases[0]["waive"] = True
    elif mutation == "bad-evidence-size":
        report["evidence"]["stdout.txt"]["bytes"] = True
    report_path.write_text(json.dumps(report))
    with pytest.raises(TerminalValidationError):
        _check_suite(root, source)


def test_suite_rejects_shard_environment_drift(tmp_path: Path) -> None:
    root, source = _suite_fixture(tmp_path)
    path = root / "ci-suite-123-1-macos-py3.12-shard3" / "report.json"
    report = json.loads(path.read_text())
    report["identity"]["runner_image_version"] = "different-image"
    path.write_text(json.dumps(report))
    with pytest.raises(TerminalValidationError, match="environments disagree"):
        _check_suite(root, source)


def _run_fixture_shard(tmp_path: Path, text: str, index: int, count: int) -> dict[str, Any]:
    import os

    fixture = tmp_path / "fixture"
    fixture.mkdir(exist_ok=True)
    (fixture / "test_sample.py").write_text(text, encoding="utf-8")
    (fixture / "pytest.ini").write_text("[pytest]\nfilterwarnings = error\nxfail_strict = true\n")
    output = tmp_path / f"shard-{index}"
    output.mkdir()
    script = (
        "import json,runpy; from pathlib import Path; "
        f"m=runpy.run_path({str(ROOT / 'tools/check_required_terminal.py')!r}); "
        f"r=m['_run_pytest_shard'](Path({str(output)!r}), {{'source':{{'fixture':True}}}},"
        f"{index},{count},pytest_args=['--rootdir', {str(fixture)!r},'-c',"
        f"{str(fixture / 'pytest.ini')!r},{str(fixture / 'test_sample.py')!r}]); "
        f"Path({str(output / 'result.json')!r}).write_text(json.dumps(r))"
    )
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=fixture,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads((output / "result.json").read_text())


def test_real_plugin_preserves_normal_order_nested_collection_and_isolated_fixtures(
    tmp_path: Path,
) -> None:
    text = """import json, os, subprocess, sys
from pathlib import Path
import pytest

@pytest.fixture(scope="session", params=["second", "first"])
def shared(request):
    return {"value": request.param, "seen": []}

@pytest.mark.parametrize("value", [3, 1, 2, 0])
def test_order(shared, value):
    shared["seen"].append(value)
    assert len(shared["seen"]) == len(set(shared["seen"]))


def test_nested(tmp_path):
    assert not os.environ.get("PYTEST_ADDOPTS")
    assert not os.environ.get("PYTEST_PLUGINS")
    (tmp_path / "test_nested.py").write_text("def test_a(): pass\\ndef test_b(): pass\\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\\n")
    child = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=tmp_path, capture_output=True, text=True)
    assert child.returncode == 0, child.stderr
    assert "2 tests collected" in child.stdout
"""
    normal = _run_fixture_shard(tmp_path, text, 0, 1)
    assert normal["exit_code"] == 0
    selected = []
    for index in range(4):
        separate = tmp_path / f"runner-{index}"
        separate.mkdir()
        report = _run_fixture_shard(separate, text, index, 4)
        assert report["exit_code"] == 0
        assert report["errors"] == report["warnings"] == []
        assert report["collection"] == normal["collection"]
        assert report["selected"] == normal["collection"][index::4]
        assert set(report["outcomes"]) == set(report["selected"])
        selected.extend(report["selected"])
    assert len(selected) == len(set(selected)) == len(normal["collection"])
    assert set(selected) == set(normal["collection"])


@pytest.mark.parametrize(
    "body,expected",
    [
        ("assert False", "failed"),
        ("pytest.skip('original reason')", "skipped"),
        ("pytest.xfail('original xfail')", "skipped"),
        ("warnings.warn('original warning')", "failed"),
    ],
)
def test_real_plugin_retains_original_negative_outcomes(
    tmp_path: Path, body: str, expected: str
) -> None:
    report = _run_fixture_shard(
        tmp_path, f"import pytest,warnings\ndef test_case():\n    {body}\n", 0, 1
    )
    phases = report["outcomes"][report["selected"][0]]
    assert [p["when"] for p in phases] == ["setup", "call", "teardown"]
    assert phases[1]["outcome"] == expected
    if "pytest.skip" in body:
        assert phases[1]["skip_reason"] == "original reason"
    if "pytest.xfail" in body:
        assert phases[1]["xfail"] == "original xfail"
    if expected == "failed":
        assert report["exit_code"] != 0
    assert "original" in phases[1]["diagnostic"] or body == "assert False"


def test_real_plugin_rejects_unplanned_collection_filtering(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "conftest.py").write_text("""def pytest_collection_modifyitems(config, items):
    removed = items.pop()
    config.hook.pytest_deselected(items=[removed])
""")
    report = _run_fixture_shard(tmp_path, "def test_a(): pass\ndef test_b(): pass\n", 0, 1)
    assert "unexpected deselection" in report["errors"]
    assert "duplicate or filtered original collection" in report["errors"]


def test_hosted_shard_cli_rejects_non_hosted_or_selector_execution(tmp_path: Path) -> None:
    import os

    env = dict(os.environ)
    env.pop("GITHUB_WORKFLOW", None)
    command = [
        sys.executable,
        str(ROOT / "tools/check_required_terminal.py"),
        "shard-run",
        "--platform",
        "linux",
        "--python-version",
        "3.13",
        "--shard-index",
        "0",
        "--shard-count",
        "1",
        "--report-dir",
        str(tmp_path / "report"),
    ]
    for extra in ([], ["-k", "one"]):
        proc = subprocess.run(command + extra, cwd=ROOT, env=env, capture_output=True, text=True)
        assert proc.returncode != 0
        assert not (tmp_path / "report").exists()


def test_ci_shards_and_fast_validation_preserve_required_closure() -> None:
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    trigger = ci.get("on", ci.get(True))
    assert trigger["pull_request"]["types"] == [
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "edited",
    ]
    assert ci["concurrency"] == {
        "group": "ci-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}",
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }
    jobs = ci["jobs"]
    for name in ("test", "linux-python313", "macos-regressions"):
        assert jobs[name]["needs"] == "fast-validation"
        assert "PLAYWRIGHT_BROWSERS_PATH" not in jobs[name]["env"]
        assert all("runner." not in str(value) for value in jobs[name]["env"].values())
        steps = jobs[name]["steps"]
        source_steps = [step for step in steps if step.get("id") == "source"]
        assert len(source_steps) == 1
        source = source_steps[0]
        cache = "empty-browser-cache" if name == "macos-regressions" else "playwright-browsers"
        export = (
            f'printf \'%s\\n\' "PLAYWRIGHT_BROWSERS_PATH=$RUNNER_TEMP/{cache}" >> "$GITHUB_ENV"'
        )
        assert export in source["run"].splitlines()
        source_index = steps.index(source)
        for index, step in enumerate(steps):
            if step is not source:
                assert "PLAYWRIGHT_BROWSERS_PATH" not in str(step)
            if "playwright install" in str(step) or "shard-run" in str(step):
                assert index > source_index
        uploads = [
            s
            for s in jobs[name]["steps"]
            if str(s.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        assert len(uploads) == 1 and uploads[0]["if"] == "always()"
        assert uploads[0]["with"]["if-no-files-found"] == "error"
        assert "github.run_attempt" in uploads[0]["with"]["name"]
    assert jobs["macos-regressions"]["strategy"] == {
        "fail-fast": False,
        "matrix": {"python-version": ["3.12", "3.13"], "shard-index": [0, 1, 2, 3]},
    }
    assert "outputs" not in jobs["macos-regressions"]
    assert set(jobs["suite-evidence"]["needs"]) == {"test", "linux-python313", "macos-regressions"}
    assert jobs["suite-evidence"]["if"] == "always()"
    assert "suite-evidence" in jobs["metriplane-required"]["needs"]
    assert "fast-validation" in jobs["metriplane-required"]["needs"]
    fast = str(jobs["fast-validation"])
    for command in (
        "ruff check .",
        "ruff format --check .",
        "mypy",
        "EVENT_HEAD",
        "pr-readback.json",
    ):
        assert command in fast
    text = (WORKFLOWS / "ci.yml").read_text()
    for preserved in (
        "Check required release fixtures",
        "Run doctor",
        "Check dashboard JavaScript syntax",
        "Check ROS 2 adapter/package structure",
        "Verify archived v0.2.0 release tree",
        "Verify current copies of frozen v0.2.0 evidence payload",
        "Check shell script syntax",
        "Verify import",
    ):
        assert preserved in text
    assert "PYTEST_ADDOPTS" not in text and "PYTEST_PLUGINS" not in text


def test_codeql_requires_both_language_jobs_with_observed_source() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "codeql.yml").read_text())
    jobs = workflow["jobs"]
    assert set(jobs) == {"analyze-python", "analyze-javascript", "security-required"}
    assert jobs["analyze-python"]["name"] == "CodeQL (python)"
    assert jobs["analyze-javascript"]["name"] == "CodeQL (javascript-typescript)"
    assert jobs["security-required"]["needs"] == ["analyze-python", "analyze-javascript"]
    for name in ("analyze-python", "analyze-javascript"):
        assert "strategy" not in jobs[name]
        assert jobs[name]["outputs"]["source_sha"] == "${{ steps.source.outputs.sha }}"
        assert f"needs.{name}.outputs.source_sha" in str(jobs["security-required"])


def test_ci_owned_shell_steps_are_valid_bash() -> None:
    for filename in ("ci.yml", "codeql.yml", "pr-contract.yml"):
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text())
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if "run" in step:
                    proc = subprocess.run(
                        ["bash", "-n"], input=step["run"], capture_output=True, text=True
                    )
                    assert proc.returncode == 0, f"{filename}: {proc.stderr}"


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "dirty-before",
        "dirty-after",
        "wrong-job",
        "wrong-python",
        "report-exists",
        "report-symlink",
        "report-in-source",
        "report-parent-traversal",
        "addopts",
        "plugins",
        "installed-profile",
    ],
)
def test_hosted_shard_start_and_readback_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    import argparse
    import os
    import platform
    from tools import check_required_terminal as terminal

    # The real public driver validates a private clean Git source and a fake test
    # backend. It never runs the repository suite or contacts a provider.
    tmp_path = tmp_path.resolve()
    source_root = tmp_path / "source"
    source_root.mkdir()
    for filename in terminal._SOURCE_FILES:
        path = source_root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("immutable source\n")
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture source",
        ],
    ):
        subprocess.run(argv, cwd=source_root, check=True, capture_output=True)
    actual_source = terminal._source_identity(source_root)
    system = "macos" if sys.platform == "darwin" else "linux"
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    count = 4 if system == "macos" else 1
    root, _ = _suite_fixture(tmp_path)
    template_dir = root / terminal._artifact_name("123", "1", system, version, 0)
    template = json.loads((template_dir / "report.json").read_text())
    monkeypatch.chdir(source_root)
    monkeypatch.setattr(terminal, "__file__", str(source_root / "tools/check_required_terminal.py"))
    for key, value in {
        "GITHUB_WORKFLOW": "CI",
        "GITHUB_SHA": actual_source["commit"],
        "GITHUB_REPOSITORY": "Miko997/metriplane",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_JOB": terminal._job_name(system, version),
        "RUNNER_OS": "macOS" if system == "macos" else "Linux",
        "RUNNER_ARCH": "X64",
        "ImageOS": system,
        "ImageVersion": "20260101.1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PLAYWRIGHT_BROWSERS_PATH": str(tmp_path / "browsers"),
    }.items():
        monkeypatch.setenv(key, value)
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "METRIPLANE_TEST_PROFILE",
        "METRIPLANE_MP2_010_MATERIALIZATION_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    calls = []

    def fake_pytest(
        directory: Path, identity: dict[str, Any], index: int, total: int
    ) -> dict[str, Any]:
        calls.append((index, total))
        assert identity["python_full"] == platform.python_version()
        assert identity["source"] == actual_source
        for name in terminal._SUITE_FILES:
            shutil.copyfile(template_dir / name, directory / name)
        report = copy.deepcopy(template)
        report["identity"] = identity
        report["source_after"] = actual_source
        if mutation == "dirty-after":
            (source_root / "uv.lock").write_text("tamper after execution")
        return report

    monkeypatch.setattr(terminal, "_run_pytest_shard", fake_pytest)
    output = tmp_path / "report"
    if mutation == "dirty-before":
        (source_root / "uv.lock").write_text("tamper before execution")
    elif mutation == "wrong-job":
        monkeypatch.setenv("GITHUB_JOB", "another-job")
    elif mutation == "wrong-python":
        version = "3.12" if version == "3.13" else "3.13"
    elif mutation == "report-exists":
        output.mkdir()
    elif mutation == "report-symlink":
        output.symlink_to(root, target_is_directory=True)
    elif mutation == "report-in-source":
        output = source_root / "new-report"
    elif mutation == "report-parent-traversal":
        output = tmp_path / "source" / ".." / "report"
    elif mutation == "addopts":
        monkeypatch.setenv("PYTEST_ADDOPTS", "-k one")
    elif mutation == "plugins":
        monkeypatch.setenv("PYTEST_PLUGINS", "other_plugin")
    elif mutation == "installed-profile":
        monkeypatch.setenv("METRIPLANE_TEST_PROFILE", "installed")
    args = argparse.Namespace(
        platform=system, python_version=version, shard_index=0, shard_count=count, report_dir=output
    )
    if mutation == "none":
        result = terminal._shard_run(args)
        assert result["sha"] == actual_source["commit"]
        assert json.loads((output / "report.json").read_text())["source_after"] == actual_source
        assert calls == [(0, count)]
    else:
        with pytest.raises((TerminalValidationError, FileExistsError)):
            terminal._shard_run(args)
        assert calls == ([(0, count)] if mutation == "dirty-after" else [])
        if mutation == "dirty-after":
            retained = json.loads((output / "report.json").read_text())
            assert retained["source_after"] is None
            assert retained["errors"] and "source readback failed" in retained["errors"][0]
    assert not os.environ.get("PYTEST_ADDOPTS") or mutation == "addopts"


def test_real_plugin_retains_setup_skip_and_teardown_failure(tmp_path: Path) -> None:
    text = """import pytest
@pytest.fixture
def unavailable():
    pytest.skip("setup reason")
@pytest.fixture
def broken_teardown():
    yield
    assert False, "teardown reason"
def test_skipped(unavailable): pass
def test_teardown(broken_teardown): pass
"""
    report = _run_fixture_shard(tmp_path, text, 0, 1)
    assert report["exit_code"] != 0
    first, second = [report["outcomes"][n] for n in report["selected"]]
    assert [p["when"] for p in first] == ["setup", "teardown"]
    assert first[0]["skip_reason"] == "setup reason"
    assert [p["outcome"] for p in second] == ["passed", "passed", "failed"]
    assert "teardown reason" in second[-1]["diagnostic"]


@pytest.mark.parametrize(
    "text",
    [
        "def test_broken(: pass\n",
        "def test_interrupt(): raise KeyboardInterrupt()\n",
        "import pytest\n@pytest.mark.xfail(strict=True)\ndef test_xpass(): pass\n",
    ],
)
def test_real_plugin_never_relabels_collection_interrupt_or_xpass(
    tmp_path: Path, text: str
) -> None:
    report = _run_fixture_shard(tmp_path, text, 0, 1)
    assert report["exit_code"] != 0
    if "broken" in text or "Interrupt" in text:
        assert report["errors"]
    else:
        phases = report["outcomes"][report["selected"][0]]
        assert phases[1]["outcome"] == "failed"
        assert "XPASS" in phases[1]["diagnostic"]


def test_suite_aggregate_cli_is_stdlib_only_and_binds_its_actual_source(tmp_path: Path) -> None:
    import os
    from tools import check_required_terminal as terminal

    root, _ = _suite_fixture(tmp_path)
    repo = tmp_path / "source"
    repo.mkdir()
    for name in terminal._SOURCE_FILES:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    source = terminal._source_identity(repo)
    for path in root.glob("*/report.json"):
        report = json.loads(path.read_text())
        report["identity"]["source"] = source
        report["source_after"] = source
        path.write_text(json.dumps(report))
    env = dict(os.environ)
    env.update(
        GITHUB_WORKFLOW="CI",
        GITHUB_REPOSITORY="Miko997/metriplane",
        GITHUB_SHA=source["commit"],
        GITHUB_RUN_ID="123",
        GITHUB_RUN_ATTEMPT="1",
    )
    command = [
        sys.executable,
        "-S",
        str(repo / "tools/check_required_terminal.py"),
        "shard-aggregate",
        "--reports-root",
        str(root),
        "--expected-sha",
        source["commit"],
        "--expected-run-id",
        "123",
        "--expected-run-attempt",
        "1",
    ]
    proc = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    aggregate = json.loads(proc.stdout)
    assert len(aggregate["reports"]) == 10
    assert aggregate["source"] == source
    assert aggregate["totals"]["linux-py3.12"]["skipped"] == 15
    wrong = list(command)
    wrong[-1] = "2"
    proc = subprocess.run(wrong, cwd=repo, env=env, capture_output=True, text=True)
    assert proc.returncode != 0 and "hosted identity" in proc.stderr
    wrong = list(command)
    wrong[2] = str(ROOT / "tools/check_required_terminal.py")
    proc = subprocess.run(wrong, cwd=repo, env=env, capture_output=True, text=True)
    assert proc.returncode != 0 and "checked-out owner" in proc.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "encoding",
        "negative-bytes",
        "boolean-bytes",
        "malformed-digest",
        "wrong-digest",
        "wrong-byte-count",
    ],
)
def test_source_inventory_digest_is_a_closed_required_identity(
    tmp_path: Path, mutation: str
) -> None:
    root, source = _suite_fixture(tmp_path)
    path = root / "ci-suite-123-1-linux-py3.12-shard0" / "report.json"
    report = json.loads(path.read_text())
    binding = report["identity"]["source"]["tree_inventory"]
    if mutation == "missing":
        del report["identity"]["source"]["tree_inventory"]
    elif mutation == "extra":
        binding["omitted_paths"] = []
    elif mutation == "encoding":
        binding["format"] = "newline-sorted-paths"
    elif mutation == "negative-bytes":
        binding["bytes"] = -1
    elif mutation == "boolean-bytes":
        binding["bytes"] = True
    elif mutation == "malformed-digest":
        binding["sha256"] = "not a digest"
    elif mutation == "wrong-digest":
        binding["sha256"] = "e" * 64
    else:
        binding["bytes"] += 1
    path.write_text(json.dumps(report))
    with pytest.raises(TerminalValidationError):
        _check_suite(root, source)


def test_source_digest_reconstructs_exact_nul_inventory_including_unusual_names(
    tmp_path: Path,
) -> None:
    import hashlib
    from tools import check_required_terminal as terminal

    repo = tmp_path / "source"
    repo.mkdir()
    for filename in (*terminal._SOURCE_FILES, "ordinary.txt", "with\ttab\nand-newline.txt"):
        path = repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("immutable source\n")
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    source = terminal._source_identity(repo)
    raw = subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD"], cwd=repo)
    rebuilt = subprocess.check_output(["git", "ls-tree", "-r", "-z", source["commit"]], cwd=repo)
    assert raw == rebuilt and raw.endswith(b"\0")
    assert b"with\ttab\nand-newline.txt\0" in raw
    assert source["tree_inventory"] == {
        "format": "git-ls-tree-r-z.v1",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    terminal._validate_source_identity(source)
    # A tracked file outside the six special control files changes the complete
    # source digest, despite those six raw file identities remaining identical.
    (repo / "ordinary.txt").write_text("new exact source\n")
    subprocess.run(["git", "add", "ordinary.txt"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "changed source",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    changed = terminal._source_identity(repo)
    assert changed["files"] == source["files"]
    assert changed["tree_inventory"]["sha256"] != source["tree_inventory"]["sha256"]
