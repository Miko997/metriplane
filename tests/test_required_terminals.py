# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

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


def _workflow_python_snippet(filename: str, marker: str) -> str:
    workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            for snippet in re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", step.get("run", ""), re.DOTALL):
                if marker in snippet:
                    return str(snippet)
    raise AssertionError(f"missing embedded Python marker {marker!r} in {filename}")


def _results() -> dict[str, dict[str, str]]:
    return {
        "linux": {"result": "success", "sha": SHA},
        "macos": {"result": "success", "sha": SHA},
    }


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


def test_terminal_inventory_has_four_sole_producers_and_release_handoff() -> None:
    policy = validate_policy(POLICY, WORKFLOWS)
    active = [item for item in policy["terminals"] if item["state"] == "active"]
    reserved = [item for item in policy["terminals"] if item["state"] == "reserved"]
    assert [item["name"] for item in active] == [
        "Metriplane / required",
        "Documentation / required",
        "Security / required",
        "Main health / required",
    ]
    assert reserved == [
        {
            "name": "Release / required",
            "owner": "MP2-007",
            "producer": None,
            "state": "reserved",
        }
    ]


@pytest.mark.parametrize("suffix", (".yml", ".yaml"))
def test_duplicate_or_premature_producer_is_rejected(tmp_path: Path, suffix: str) -> None:
    workflow_root = tmp_path / "workflows"
    workflow_root.mkdir()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    for terminal in policy["terminals"]:
        if terminal["producer"]:
            source = ROOT / terminal["producer"]
            shutil.copyfile(source, workflow_root / source.name)
    duplicate = workflow_root / f"duplicate{suffix}"
    duplicate.write_text(
        "name: duplicate\njobs:\n  required:\n    name: Metriplane / required\n",
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
    for terminal in policy["terminals"]:
        if terminal["producer"]:
            source = ROOT / terminal["producer"]
            shutil.copyfile(source, workflow_root / source.name)
    (workflow_root / "dynamic.yaml").write_text(
        "name: dynamic\njobs:\n  required:\n" + job_name,
        encoding="utf-8",
    )
    with pytest.raises(TerminalValidationError, match="dynamic job name"):
        validate_policy(POLICY, workflow_root)


def test_workflows_have_always_run_exact_aggregate_jobs() -> None:
    expected = {
        "ci.yml": "Metriplane / required",
        "docs.yml": "Documentation / required",
        "codeql.yml": "Security / required",
        "main-health.yml": "Main health / required",
    }
    for filename, terminal in expected.items():
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
        jobs = workflow["jobs"]
        producers = [job for job in jobs.values() if job.get("name") == terminal]
        assert len(producers) == 1
        assert "always()" in str(producers[0].get("if", "")) or filename == "main-health.yml"
        aggregate = str(producers[0])
        assert "outputs.source_sha" in aggregate or "outputs.measured_sha" in aggregate

    docs = yaml.safe_load((WORKFLOWS / "docs.yml").read_text(encoding="utf-8"))
    trigger = docs.get("on", docs.get(True))
    assert trigger["pull_request"] is None
    assert "paths" not in trigger["push"]

    health = yaml.safe_load((WORKFLOWS / "main-health.yml").read_text(encoding="utf-8"))
    health_trigger = health.get("on", health.get(True))
    assert "pull_request" not in health_trigger
    assert "pull_request_target" not in health_trigger
    assert health_trigger["workflow_run"]["workflows"] == ["CI"]
    assert "workflow_dispatch" not in health_trigger
    assert health_trigger["repository_dispatch"]["types"] == [
        "main-health-nightly",
        "main-health-weekly",
    ]
    assert {item["cron"] for item in health_trigger["schedule"]} == {
        "*/5 * * * *",
        "23 3 * * 0",
        "23 3 * * 1-6",
    }
    concurrency_group = str(health["concurrency"]["group"])
    assert concurrency_group == "main-health-serialized"
    assert health["concurrency"]["queue"] == "max"
    assert "github.event.workflow_run.event" in health["run-name"]
    assert "github.event.workflow_run.head_branch" in health["run-name"]
    assert "github.event.action" in health["run-name"]
    assert "candidate-health" not in health["jobs"]
    assert health["jobs"]["scheduled-deep"]["permissions"] == {"contents": "read"}
    for job_name in ("scheduled-deep", "persist-health", "reconcile-candidate-statuses"):
        job_if = str(health["jobs"][job_name]["if"])
        assert "github.event_name == 'repository_dispatch'" in job_if
    scheduled_checkout = health["jobs"]["scheduled-deep"]["steps"][0]
    reconcile_checkout = next(
        step
        for step in health["jobs"]["reconcile-candidate-statuses"]["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    terminal_checkout = health["jobs"]["main-health-required"]["steps"][0]
    assert scheduled_checkout["with"]["ref"] == (
        "${{ needs.invalidate-writer.outputs.measured_sha }}"
    )
    assert reconcile_checkout["with"]["ref"] == "refs/heads/main"
    assert terminal_checkout["with"]["ref"] == "refs/heads/main"
    assert health["jobs"]["persist-health"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert health["jobs"]["invalidate-writer"]["permissions"] == {"contents": "read"}
    candidate_permissions = {
        "contents": "read",
        "pull-requests": "read",
    }
    assert health["jobs"]["invalidate-candidate-statuses"]["permissions"] == (candidate_permissions)
    assert health["jobs"]["main-health-required"]["permissions"] == {"contents": "read"}
    assert health["jobs"]["reconcile-candidate-statuses"]["permissions"] == {
        "actions": "read",
        **candidate_permissions,
    }
    publisher_jobs = (
        "invalidate-writer",
        "persist-health",
        "invalidate-candidate-statuses",
        "reconcile-candidate-statuses",
    )
    for job_name in publisher_jobs:
        job = health["jobs"][job_name]
        assert job["environment"] == "main-health-publisher"
        assert job["concurrency"] == {
            "group": "main-health-check-writer",
            "queue": "max",
        }
        publisher = job["steps"][0]
        assert publisher["id"] == "publisher"
        assert publisher["uses"] == (
            "actions/create-github-app-token@fee1f7d63c2ff003460e3d139729b119787bc349"
        )
        assert publisher["with"] == {
            "app-id": "${{ vars.MAIN_HEALTH_APP_ID }}",
            "private-key": "${{ secrets.MAIN_HEALTH_APP_PRIVATE_KEY }}",
            "permission-actions": "read",
            "permission-checks": "write",
            "permission-contents": "write",
            "permission-pull-requests": "read",
        }
    reconcile = "\n".join(
        step.get("run", "") for step in health["jobs"]["reconcile-candidate-statuses"]["steps"]
    )
    assert "validate-git" in reconcile
    assert "state=open" in reconcile
    assert "Main health admission / required" in reconcile
    assert "github-check-set" in reconcile
    assert "github-check-get" in reconcile
    assert "github-check-expire" in reconcile
    reconcile_step = next(
        step
        for step in health["jobs"]["reconcile-candidate-statuses"]["steps"]
        if step.get("name") == "Reconcile every open pull request head"
    )
    assert reconcile_step["env"]["PERSIST_RESULT"] == "${{ needs.persist-health.result }}"
    assert '"$PERSIST_RESULT" == success' in reconcile
    assert "\"$SCHEDULE\" == '*/5 * * * *'" in reconcile
    assert '[[ "$admission_ready" == true ]]' in reconcile
    assert '"$state_available" == true ]]' in reconcile
    assert "Main health writer / latest" in reconcile
    assert '"$expected_main_sha" "Main health writer / latest" "$writer_snapshot"' in reconcile
    assert 'job.get("name") == "persist-health"' in reconcile
    assert 'cmp -s "$run_before" "$run_after"' in reconcile
    assert 'cmp -s "$state_before" "$state_after"' in reconcile
    assert 'cmp -s "$writer_before" "$writer_after"' in reconcile
    assert 'cmp -s "$latest_before" "$latest_after"' in reconcile
    assert 'cmp -s "$writer_snapshot" "$boundary_writer"' in reconcile
    assert "while [[ $page -le 10 ]]" in reconcile
    assert "runs?branch=main&per_page=100&page=${page}" in reconcile
    assert "Main Health / workflow_run / push / main" in reconcile
    assert "Main Health / repository_dispatch / main-health-nightly / main" in reconcile
    assert "Main Health / repository_dispatch / main-health-weekly / main" in reconcile
    assert "Main Health / schedule / 23 3 * * 0 / main" in reconcile
    assert "Main Health / schedule / 23 3 * * 1-6 / main" in reconcile
    assert '"$(jq -er \'.head_sha\' "$latest_snapshot")" == "$expected_main_sha"' in reconcile
    assert 'cmp -s "$latest_snapshot" "$boundary_latest"' in reconcile
    assert reconcile.count('gh api "repos/${GITHUB_REPOSITORY}/pulls/${number}"') >= 2
    assert 'check_run.get("conclusion") == "success"' in reconcile
    assert "latest writer check is not an exact provider attestation" in reconcile
    assert 'leases="$RUNNER_TEMP/main-health-success-leases.jsonl"' in reconcile
    assert ': > "$leases"' in reconcile
    assert "main-health-expire" in reconcile
    assert "for replica in 1 2" in reconcile
    assert "deadline_epoch=$((provider_epoch + 240))" in reconcile
    assert "mh1:${lease_sha}:${GITHUB_RUN_ID}" in reconcile
    assert "Main health lease closer / ${replica}" in reconcile
    assert "lease_marker_binding" in reconcile
    assert "verify_closer_run" in reconcile
    assert "main-health lease closer is not provider-active" in reconcile
    assert "github-provider-clock" in reconcile
    assert "deadline_epoch - provider_epoch < 60" in reconcile
    assert "Main health publisher exited" in reconcile
    assert "cleanup_successes" in reconcile
    assert reconcile.count("while true; do") >= 1
    assert "provider_epoch >= deadline_epoch" in reconcile
    assert health["jobs"]["reconcile-candidate-statuses"]["concurrency"] == {
        "group": "main-health-check-writer",
        "queue": "max",
    }
    dispatch_index = reconcile.index("main-health-expire")
    marker_index = reconcile.index("! lease_marker_binding")
    active_index = reconcile.index('verify_closer_run 2 "$closer_run_2" "$closer_attempt_2"')
    success_index = reconcile.index('"$lease_sha" success "$external_id"')
    assert dispatch_index < marker_index < active_index < success_index
    invalidator = "\n".join(
        step.get("run", "") for step in health["jobs"]["invalidate-candidate-statuses"]["steps"]
    )
    assert "Main health admission invalidated" in invalidator
    assert "github-check-set" in invalidator
    assert "failed=0" in invalidator
    assert 'exit "$failed"' in invalidator
    assert health["jobs"]["persist-health"]["outputs"]["state_commit"] == (
        "${{ steps.publish.outputs.state_commit }}"
    )
    assert health["jobs"]["reconcile-candidate-statuses"]["needs"] == [
        "invalidate-candidate-statuses",
        "persist-health",
    ]
    writer = "\n".join(step.get("run", "") for step in health["jobs"]["persist-health"]["steps"])
    assert "stop_the_line.py ingest" in writer
    assert 'test "$DEEP_SHA" = "$RUN_SHA"' in writer
    assert 'test -z "$DEEP_SHA" || test "$DEEP_SHA" = "$RUN_SHA"' in writer
    assert 'test "$RUN_SHA" = "$(git rev-parse HEAD)"' in writer
    assert "git rev-parse origin/main" in writer
    assert "actions/runs?head_sha=${RUN_SHA}&per_page=100" in writer
    assert "actions/runs/${run_id}/attempts/${run_attempt}/jobs?per_page=100" in writer
    assert writer.count("--paginate") == 3
    assert "cmp -s" in writer
    assert "observe_main_health.py invalidate" in writer
    assert "github.event.workflow_run.run_attempt" in str(health["jobs"]["persist-health"]["steps"])
    assert "tools/observe_main_health.py" in writer
    assert '--name "Main health writer / latest"' in writer
    assert "mhw1:${MEASURED_SHA}:${GITHUB_RUN_ID}" in writer
    assert "Main health state committed" in writer
    assert REQUIRED_WORKFLOWS == {
        "metriplane": ("Metriplane / required", "CI"),
        "documentation": ("Documentation / required", "Documentation"),
        "security": ("Security / required", "CodeQL"),
    }
    assert '"obligations": json.loads(obligations)' in writer
    assert "stop_the_line.py candidate" in reconcile
    assert "stop_the_line.py repair-candidate" not in reconcile
    assert health["jobs"]["persist-health"]["needs"] == [
        "scheduled-deep",
        "invalidate-writer",
    ]
    assert health["jobs"]["scheduled-deep"]["needs"] == "invalidate-writer"

    lease = yaml.safe_load((WORKFLOWS / "main-health-lease.yml").read_text(encoding="utf-8"))
    lease_trigger = lease.get("on", lease.get(True))
    assert lease_trigger == {"repository_dispatch": {"types": ["main-health-expire"]}}
    arm = lease["jobs"]["arm-and-wait"]
    expiry = lease["jobs"]["expire-successes"]
    assert arm["environment"] == "main-health-publisher"
    assert expiry["environment"] == "main-health-publisher"
    assert "github.actor == format" in arm["if"]
    assert "github.event.sender.login == format" in arm["if"]
    assert expiry["needs"] == "arm-and-wait"
    assert expiry["concurrency"] == {
        "group": "main-health-check-writer",
        "queue": "max",
    }
    for job in (arm, expiry):
        publisher = job["steps"][0]
        assert publisher["with"] == {
            "app-id": "${{ vars.MAIN_HEALTH_APP_ID }}",
            "private-key": "${{ secrets.MAIN_HEALTH_APP_PRIVATE_KEY }}",
            "permission-checks": "write",
        }
    arm_script = "\n".join(step.get("run", "") for step in arm["steps"])
    expiry_script = "\n".join(step.get("run", "") for step in expiry["steps"])
    assert "deadline_epoch" in arm_script
    assert "main-health lease deadline is inconsistent" in arm_script
    assert "mh1-closer:" in arm_script
    assert "github-check-get" in arm_script
    assert "github-check-set" in arm_script
    assert "while true" in arm_script
    assert "github-provider-clock" in arm_script
    assert "github-check-expire" in expiry_script
    assert "Main health admission expired" in expiry_script
    all_health_workflows = (WORKFLOWS / "main-health.yml").read_text(encoding="utf-8") + (
        WORKFLOWS / "main-health-lease.yml"
    ).read_text(encoding="utf-8")
    assert "/statuses" not in all_health_workflows
    assert "permission-statuses" not in all_health_workflows

    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    ci_trigger = ci.get("on", ci.get(True))
    assert "edited" in ci_trigger["pull_request"]["types"]
    for job_name in ("test", "macos-regressions", "linux-python313"):
        assert ci["jobs"][job_name]["outputs"]["source_sha"]
    assert "metriplane-main-health-state" in (WORKFLOWS / "main-health.yml").read_text(
        encoding="utf-8"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="Main Health runs on a Bash runner")
def test_main_health_observer_step_is_valid_bash() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "main-health.yml").read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["persist-health"]["steps"]
        if item.get("name") == "Observe exact protected-main terminals"
    )
    completed = subprocess.run(
        ["bash", "-n"],
        input=step["run"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="Main Health runs on a Bash runner")
def test_main_health_candidate_reconciliation_step_is_valid_bash() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "main-health.yml").read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["reconcile-candidate-statuses"]["steps"]
        if item.get("name") == "Reconcile every open pull request head"
    )
    completed = subprocess.run(
        ["bash", "-n"],
        input=step["run"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_main_health_embedded_python_is_valid() -> None:
    expected = {"main-health.yml": 8, "main-health-lease.yml": 2}
    for filename, expected_count in expected.items():
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
        snippets: list[str] = []
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                snippets.extend(
                    re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", step.get("run", ""), re.DOTALL)
                )
        assert len(snippets) == expected_count
        for index, snippet in enumerate(snippets):
            compile(snippet, f"{filename}-heredoc-{index}.py", "exec")


def test_main_health_closers_require_one_shared_provider_deadline(tmp_path: Path) -> None:
    snippet = _workflow_python_snippet(
        "main-health-lease.yml", "main-health lease deadline is inconsistent"
    )
    head_sha = "b" * 40
    nonce = "c" * 32
    deadline = "2026-08-26T06:04:00Z"
    deadline_epoch = int(datetime.fromisoformat(deadline).astimezone(UTC).timestamp())
    payload = {
        "deadline": deadline,
        "deadline_epoch": deadline_epoch,
        "leases": [
            {
                "check_run_id": 42,
                "external_id": f"mh1:{head_sha}:123:1:{nonce}:{deadline_epoch}",
                "head_sha": head_sha,
            }
        ],
        "nonce": nonce,
        "origin_run_attempt": "1",
        "origin_run_id": "123",
        "replica": 1,
    }
    metadata = tmp_path / "metadata.tsv"
    args = [sys.executable, "-", json.dumps(payload), str(metadata)]
    accepted = subprocess.run(args, input=snippet, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0, accepted.stderr
    lease_external_id = f"mh1:{head_sha}:123:1:{nonce}:{deadline_epoch}"
    assert accepted.stdout == f"{head_sha}\t42\t{lease_external_id}\n"
    assert metadata.read_text(encoding="utf-8").endswith(f"\t{deadline}\t{deadline_epoch}\n")

    payload["deadline"] = "2026-08-26T06:04:01Z"
    rejected = subprocess.run(
        [sys.executable, "-", json.dumps(payload), str(metadata)],
        input=snippet,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "deadline is inconsistent" in rejected.stderr


def test_main_health_lease_marker_binds_exact_shared_generation(tmp_path: Path) -> None:
    snippet = _workflow_python_snippet(
        "main-health.yml", "main-health lease marker is not provider-bound"
    )
    head_sha = "b" * 40
    nonce = "c" * 32
    deadline_epoch = "1787724240"
    target = "https://github.com/Miko997/metriplane/actions/runs/456"
    marker = {
        "app": {"id": 4722589, "slug": "metriplane-main-health-publisher"},
        "conclusion": "success",
        "details_url": target,
        "external_id": (f"mh1-closer:{head_sha}:123:1:{nonce}:{deadline_epoch}:1:42:456:1"),
        "head_sha": head_sha,
        "id": 100,
        "name": "Main health lease closer / 1",
        "output": {"summary": "armed", "title": "Main health lease closer armed"},
        "status": "completed",
    }
    marker_path = tmp_path / "marker.json"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    args: list[str] = [
        sys.executable,
        "-",
        str(marker_path),
        head_sha,
        "42",
        "123",
        "1",
        nonce,
        deadline_epoch,
        "1",
        "Miko997/metriplane",
    ]
    accepted = subprocess.run(args, input=snippet, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout == "456\t1\n"

    rejected_args = [*args]
    rejected_args[8] = str(int(deadline_epoch) + 1)
    rejected = subprocess.run(
        rejected_args, input=snippet, capture_output=True, text=True, check=False
    )
    assert rejected.returncode != 0
    assert "not provider-bound" in rejected.stderr


def test_main_health_success_requires_active_waiting_closer(tmp_path: Path) -> None:
    snippet = _workflow_python_snippet(
        "main-health.yml", "main-health lease closer is not provider-active"
    )
    nonce = "c" * 32
    run = {
        "actor": {"login": "publisher[bot]"},
        "conclusion": None,
        "display_title": f"Main Health Lease / 123/1 / {nonce} / 1",
        "event": "repository_dispatch",
        "head_branch": "main",
        "id": 456,
        "path": ".github/workflows/main-health-lease.yml",
        "run_attempt": 1,
        "status": "in_progress",
        "triggering_actor": {"login": "publisher[bot]"},
    }
    jobs = {
        "jobs": [
            {
                "conclusion": None,
                "name": "Main health lease closer / 1",
                "status": "in_progress",
                "steps": [
                    {
                        "name": "Arm lease and wait for shared deadline",
                        "status": "in_progress",
                    }
                ],
            }
        ]
    }
    run_path = tmp_path / "run.json"
    jobs_path = tmp_path / "jobs.json"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
    args = [
        sys.executable,
        "-",
        str(run_path),
        str(jobs_path),
        "1",
        "456",
        "1",
        nonce,
        "123",
        "1",
        "publisher[bot]",
    ]
    accepted = subprocess.run(args, input=snippet, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0, accepted.stderr

    run["status"] = "completed"
    run["conclusion"] = "success"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    rejected = subprocess.run(args, input=snippet, capture_output=True, text=True, check=False)
    assert rejected.returncode != 0
    assert "not provider-active" in rejected.stderr


def test_publisher_is_third_closer_for_the_shared_deadline() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "main-health.yml").read_text(encoding="utf-8"))
    script = next(
        item["run"]
        for item in workflow["jobs"]["reconcile-candidate-statuses"]["steps"]
        if item.get("name") == "Reconcile every open pull request head"
    )
    success_index = script.index('"$lease_sha" success "$external_id"')
    wait_index = script.index("while true; do", success_index)
    expiry_index = script.index('"Main health admission expired"', wait_index)
    assert success_index < wait_index < expiry_index
    assert script.count('verify_closer_run 1 "$closer_run_1" "$closer_attempt_1"') >= 2
    assert script.count('verify_closer_run 2 "$closer_run_2" "$closer_attempt_2"') >= 2
    assert '"$closer_run_1" != "$closer_run_2"' in script


@pytest.mark.skipif(shutil.which("bash") is None, reason="Main Health runs on a Bash runner")
@pytest.mark.parametrize(
    ("job_name", "step_name"),
    (
        ("arm-and-wait", "Arm lease and wait for shared deadline"),
        ("expire-successes", "Expire exact check-run generations"),
    ),
)
def test_main_health_lease_step_is_valid_bash(job_name: str, step_name: str) -> None:
    workflow = yaml.safe_load((WORKFLOWS / "main-health-lease.yml").read_text(encoding="utf-8"))
    step = next(
        item for item in workflow["jobs"][job_name]["steps"] if item.get("name") == step_name
    )
    completed = subprocess.run(
        ["bash", "-n"],
        input=step["run"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_policy_validation_does_not_mutate_input() -> None:
    before = json.loads(POLICY.read_text(encoding="utf-8"))
    snapshot = copy.deepcopy(before)
    validate_policy(POLICY, WORKFLOWS)
    assert before == snapshot
