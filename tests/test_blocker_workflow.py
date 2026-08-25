# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_blockers.py"
SCHEMA_PATH = ROOT / "schemas" / "metriplane.blockers.v1.schema.json"
REGISTRY_PATH = ROOT / "docs" / "status" / "blockers.json"
DOC_PATH = ROOT / "docs" / "maintainers" / "blocker-workflow.md"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-gates.yml"
REPOSITORY = "Miko997/metriplane"
PULL_REQUEST = 81
HEAD_SHA = "a" * 40
COMMIT_SHA = "b" * 40
MERGE_SHA = "c" * 40
ACTION_ACTOR = "github:100"
REVIEWER_ACTOR = "github:200"
REPORTER_ACTOR = "github:300"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "metriplane_blocker_checker_under_test", TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _registry(blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "metriplane.blockers.v1",
        "policy_version": "MP2-006.v1",
        "blockers": blockers,
    }


def _base_blocker(identifier: str = "MPBLK-0001") -> dict[str, Any]:
    return {
        "id": identifier,
        "title": "Synthetic governed blocker",
        "owner": "release-maintainers",
        "reported_by_actor_id": REPORTER_ACTOR,
        "opened_at": "2026-08-25T10:00:00Z",
        "initial_severity": "P0",
        "severity": "P0",
        "initial_security": False,
        "security": False,
        "status": "open",
        "source": "synthetic:test",
        "acceptance_ids": ["MP2-006.A01", "MP2-006.A02"],
        "downgrade": None,
        "closure": None,
    }


def _evidence(repo: Path, name: str, kind: str) -> dict[str, str]:
    path = repo / "proof" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{kind}:{name}\n", encoding="utf-8")
    return {
        "path": path.relative_to(repo).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "kind": kind,
        "producer_actor_id": "github:400",
    }


def _bind_action(blocker: dict[str, Any], action: str) -> None:
    record = blocker[action]
    subject = (
        tool._downgrade_subject(blocker, record)
        if action == "downgrade"
        else tool._closure_subject(blocker, record)
    )
    record["approval"]["subject_sha256"] = tool._sha256(subject)


def _valid_downgrade(repo: Path) -> dict[str, Any]:
    blocker = _base_blocker()
    blocker["severity"] = "P2"
    blocker["downgrade"] = {
        "from_severity": "P0",
        "to_severity": "P2",
        "from_security": False,
        "to_security": False,
        "changed_by_actor_id": ACTION_ACTOR,
        "changed_at": "2026-08-25T11:00:00Z",
        "reproduction_evidence": [_evidence(repo, "reproduction.txt", "reproduction")],
        "control_evidence": [_evidence(repo, "control.txt", "control")],
        "approval": {
            "provider": "github",
            "repository": REPOSITORY,
            "pull_request": PULL_REQUEST,
            "subject_sha256": "0" * 64,
        },
    }
    _bind_action(blocker, "downgrade")
    return blocker


def _valid_closure(repo: Path) -> dict[str, Any]:
    blocker = _base_blocker()
    blocker["status"] = "closed"
    blocker["closure"] = {
        "closed_by_actor_id": ACTION_ACTOR,
        "closed_at": "2026-08-25T13:00:00Z",
        "resolution_evidence": [_evidence(repo, "resolution.txt", "resolution")],
        "control_evidence": [_evidence(repo, "closure-control.txt", "control")],
        "approval": {
            "provider": "github",
            "repository": REPOSITORY,
            "pull_request": PULL_REQUEST,
            "subject_sha256": "0" * 64,
        },
    }
    _bind_action(blocker, "closure")
    return blocker


def _synthetic_provider_payload(
    blocker: dict[str, Any],
    action: str,
    *,
    review_state: str = "APPROVED",
    head_sha: str = HEAD_SHA,
    review_commit: str | None = None,
    review_body: str | None = None,
    reviewed_at: str = "2026-08-25T14:00:00Z",
    reviewer_id: int = 200,
    pull_author_id: int = 100,
    commit_author_id: int | None = 100,
    commit_committer_id: int | None = 101,
    reviewer_permission: str = "write",
    merged: bool = False,
    merge_sha: str | None = None,
    extra_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    approval = blocker[action]["approval"]
    marker = tool._approval_marker(
        repository=approval["repository"],
        pull_request=approval["pull_request"],
        change_sha=head_sha,
        blocker_id=blocker["id"],
        action=action,
        subject_sha256=approval["subject_sha256"],
    )

    def actor(actor_id: int | None, login: str) -> dict[str, Any] | None:
        if actor_id is None:
            return None
        return {"id": actor_id, "login": login, "type": "User"}

    review = {
        "id": 900,
        "state": review_state,
        "commit_id": head_sha if review_commit is None else review_commit,
        "body": marker if review_body is None else review_body,
        "submitted_at": reviewed_at,
        "user": actor(reviewer_id, "synthetic-reviewer"),
    }
    return {
        "pull": {
            "number": PULL_REQUEST,
            "base": {"repo": {"full_name": REPOSITORY}},
            "head": {"sha": head_sha},
            "user": actor(pull_author_id, "synthetic-author"),
            "state": "closed" if merged else "open",
            "merged": merged,
            "merged_at": "2026-08-25T15:00:00Z" if merged else None,
            "merge_commit_sha": merge_sha,
            "commits": 1,
        },
        "files": [{"filename": "docs/status/blockers.json"}],
        "commits": [{"sha": COMMIT_SHA}],
        "commit": {
            "sha": COMMIT_SHA,
            "files": [{"filename": "docs/status/blockers.json"}],
            "author": actor(commit_author_id, "synthetic-commit-author"),
            "committer": actor(commit_committer_id, "synthetic-committer"),
        },
        "reviews": [review, *(extra_reviews or [])],
        "permissions": {
            "synthetic-reviewer": {
                "permission": reviewer_permission,
                "user": actor(reviewer_id, "synthetic-reviewer"),
            }
        },
    }


def _synthetic_provider_get(payload: dict[str, Any]) -> Any:
    def get(path: str, _token: str) -> Any:
        if path == f"repos/{REPOSITORY}/pulls/{PULL_REQUEST}":
            return copy.deepcopy(payload["pull"])
        if path.startswith(f"repos/{REPOSITORY}/pulls/{PULL_REQUEST}/files?"):
            return copy.deepcopy(payload["files"])
        if path.startswith(f"repos/{REPOSITORY}/pulls/{PULL_REQUEST}/commits?"):
            page = int(path.rsplit("page=", 1)[1])
            pages = payload.get("pull_commit_pages")
            if pages is not None:
                return copy.deepcopy(pages[page - 1] if page <= len(pages) else [])
            return copy.deepcopy(payload["commits"] if page == 1 else [])
        if path.startswith(f"repos/{REPOSITORY}/commits/{COMMIT_SHA}?"):
            page = int(path.rsplit("page=", 1)[1])
            detail = copy.deepcopy(payload["commit"])
            pages = payload.get("commit_pages")
            if pages is not None:
                detail["files"] = copy.deepcopy(pages[page - 1] if page <= len(pages) else [])
            elif page > 1:
                detail["files"] = []
            return detail
        if path.startswith(f"repos/{REPOSITORY}/pulls/{PULL_REQUEST}/reviews?"):
            return copy.deepcopy(payload["reviews"])
        permission_prefix = f"repos/{REPOSITORY}/collaborators/"
        if path.startswith(permission_prefix) and path.endswith("/permission"):
            login = path.removeprefix(permission_prefix).removesuffix("/permission")
            return copy.deepcopy(payload["permissions"].get(login, {}))
        raise AssertionError(f"unexpected synthetic provider path: {path}")

    return get


def _run(
    repo: Path,
    value: dict[str, Any] | None = None,
    *,
    provider: dict[str, Any] | None = None,
    token: bool = True,
    context_repository: str | None = None,
    context_pull_request: int | None = None,
    context_change_sha: str | None = None,
    context_base_sha: str | None = None,
    validated_sha: str | None = None,
    require_merged_approval: bool = False,
    include_pull_context: bool = True,
) -> tuple[int, dict[str, Any]]:
    registry = repo / "registry.json"
    _write_json(registry, _registry([]) if value is None else value)
    has_action = bool(
        value
        and any(
            blocker.get("downgrade") is not None or blocker.get("closure") is not None
            for blocker in value.get("blockers", [])
        )
    )
    if validated_sha is None and (
        has_action or provider is not None or context_repository is not None
    ):
        validated_sha = _commit_fixture(repo, "fixture validation")
    if (
        provider is not None
        and "pull" in provider
        and include_pull_context
        and validated_sha is not None
        and validated_sha != HEAD_SHA
    ):
        provider = copy.deepcopy(provider)
        provider["pull"]["head"]["sha"] = validated_sha
        for review in provider["reviews"]:
            if review.get("commit_id") == HEAD_SHA:
                review["commit_id"] = validated_sha
            body = review.get("body")
            if isinstance(body, str):
                review["body"] = body.replace(
                    f"change_sha={HEAD_SHA}", f"change_sha={validated_sha}"
                )
    argv = [
        "--registry",
        str(registry),
        "--schema",
        str(SCHEMA_PATH),
        "--repo-root",
        str(repo),
        "--json",
    ]
    if (provider is not None and include_pull_context) or context_repository is not None:
        argv.extend(
            [
                "--github-repository",
                context_repository or REPOSITORY,
                "--github-pull-request",
                str(context_pull_request or PULL_REQUEST),
                "--github-change-sha",
                context_change_sha or validated_sha or HEAD_SHA,
            ]
        )
        if context_base_sha is not None:
            argv.extend(["--github-base-sha", context_base_sha])
    elif provider is not None:
        argv.extend(["--github-repository", REPOSITORY])
    if validated_sha is not None:
        argv.extend(["--validated-sha", validated_sha])
    if require_merged_approval:
        argv.append("--require-merged-approval")
    stdout = io.StringIO()
    provider_get = (
        _synthetic_provider_get(provider)
        if provider is not None
        else mock.Mock(side_effect=AssertionError("provider must not be invoked"))
    )
    with (
        mock.patch.object(tool, "_github_get", side_effect=provider_get),
        mock.patch.dict(os.environ, {"GITHUB_TOKEN": "synthetic-test-token" if token else ""}),
        contextlib.redirect_stdout(stdout),
    ):
        result = tool.main(argv)
    return cast(int, result), cast(dict[str, Any], json.loads(stdout.getvalue()))


def _commit_fixture(repo: Path, message: str) -> str:
    if not (repo / ".git").is_dir():
        subprocess.run(["/usr/bin/git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["/usr/bin/git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Blocker fixture",
            "-c",
            "user.email=blocker-fixture@example.invalid",
            "commit",
            "--quiet",
            "--no-verify",
            "--allow-empty",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit_base_registry(repo: Path, registry: dict[str, Any]) -> str:
    _write_json(repo / "docs" / "status" / "blockers.json", registry)
    return _commit_fixture(repo, "fixture base")


def test_production_registry_is_valid_nonblocking_and_does_not_invoke_provider(
    tmp_path: Path,
) -> None:
    result, report = _run(tmp_path, json.loads(REGISTRY_PATH.read_text(encoding="utf-8")))
    assert result == 0
    assert report["valid"] is True
    assert report["release_blocked"] is False
    assert report["blocking_ids"] == []


def test_open_p0_p1_and_security_block_release(tmp_path: Path) -> None:
    for severity, security in (("P0", False), ("P1", False), ("P2", True)):
        blocker = _base_blocker()
        blocker["initial_severity"] = blocker["severity"] = severity
        blocker["initial_security"] = blocker["security"] = security
        result, report = _run(tmp_path, _registry([blocker]))
        assert result == 1
        assert report["valid"] is True
        assert report["blocking_ids"] == ["MPBLK-0001"]


def test_open_p2_nonsecurity_does_not_block_release(tmp_path: Path) -> None:
    blocker = _base_blocker()
    blocker["initial_severity"] = blocker["severity"] = "P2"
    result, report = _run(tmp_path, _registry([blocker]))
    assert result == 0
    assert report["release_blocked"] is False


def test_closed_blocker_requires_resolution_control_and_approval(tmp_path: Path) -> None:
    missing = _base_blocker()
    missing["status"] = "closed"
    result, report = _run(tmp_path, _registry([missing]))
    assert result == 2
    assert any("closure record" in error for error in report["errors"])

    missing_control = _valid_closure(tmp_path)
    missing_control["closure"]["control_evidence"] = []
    result, _ = _run(tmp_path, _registry([missing_control]))
    assert result == 2


def test_provider_verified_synthetic_closure_fixture_passes(tmp_path: Path) -> None:
    blocker = _valid_closure(tmp_path)
    payload = _synthetic_provider_payload(blocker, "closure")
    result, report = _run(tmp_path, _registry([blocker]), provider=payload)
    assert result == 0
    assert report["valid"] is True


def test_downgrade_requires_reproduction_and_control_evidence(tmp_path: Path) -> None:
    for field in ("reproduction_evidence", "control_evidence"):
        blocker = _valid_downgrade(tmp_path)
        blocker["downgrade"][field] = []
        result, report = _run(tmp_path, _registry([blocker]))
        assert result == 2
        assert report["valid"] is False


def test_provider_verified_synthetic_downgrade_fixture_passes(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    result, report = _run(tmp_path, _registry([blocker]), provider=payload)
    assert result == 0
    assert report["valid"] is True


def test_fabricated_or_offline_approval_cannot_pass_production(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    absent = _synthetic_provider_payload(blocker, "downgrade")
    absent["reviews"] = []
    result, report = _run(tmp_path, _registry([blocker]), provider=absent)
    assert result == 2
    assert any("provider-authenticated APPROVED" in error for error in report["errors"])

    payload = _synthetic_provider_payload(blocker, "downgrade")
    result, report = _run(tmp_path, _registry([blocker]), provider=payload, token=False)
    assert result == 2
    assert any("provider token" in error for error in report["errors"])


def test_approval_context_rejects_wrong_repository_and_unbound_pull_request(
    tmp_path: Path,
) -> None:
    wrong_repo = _valid_downgrade(tmp_path)
    wrong_repo["downgrade"]["approval"]["repository"] = "other/repository"
    _bind_action(wrong_repo, "downgrade")
    result, report = _run(
        tmp_path,
        _registry([wrong_repo]),
        provider={},
        context_repository=REPOSITORY,
    )
    assert result == 2
    assert any("wrong repository" in error for error in report["errors"])

    wrong_pr = _valid_downgrade(tmp_path)
    wrong_pr["downgrade"]["approval"]["pull_request"] = 82
    _bind_action(wrong_pr, "downgrade")
    result, report = _run(tmp_path, _registry([wrong_pr]), provider={})
    assert result == 2
    assert any("current pull request" in error for error in report["errors"])


def test_unchanged_historical_action_reverifies_its_original_pull_request(
    tmp_path: Path,
) -> None:
    blocker = _valid_downgrade(tmp_path)
    registry = _registry([blocker])
    base_sha = _commit_base_registry(tmp_path, registry)
    payload = _synthetic_provider_payload(blocker, "downgrade")

    result, report = _run(
        tmp_path,
        registry,
        provider=payload,
        context_pull_request=99,
        context_base_sha=base_sha,
    )

    assert result == 0
    assert report["valid"] is True


def test_changed_action_must_bind_current_pull_request_and_available_base(
    tmp_path: Path,
) -> None:
    original = _valid_downgrade(tmp_path)
    base_sha = _commit_base_registry(tmp_path, _registry([original]))
    changed = copy.deepcopy(original)
    changed["reported_by_actor_id"] = "github:301"
    _bind_action(changed, "downgrade")

    result, report = _run(
        tmp_path,
        _registry([changed]),
        provider={},
        context_pull_request=99,
        context_base_sha=base_sha,
    )
    assert result == 2
    assert any("current pull request" in error for error in report["errors"])

    result, report = _run(
        tmp_path,
        _registry([original]),
        provider={},
        context_base_sha="c" * 40,
    )
    assert result == 2
    assert any("base SHA is not an available local commit" in error for error in report["errors"])


@pytest.mark.parametrize(("severity", "security"), [("P0", False), ("P2", True)])
def test_base_blocker_ids_are_append_only(tmp_path: Path, severity: str, security: bool) -> None:
    blocker = _base_blocker()
    blocker["initial_severity"] = blocker["severity"] = severity
    blocker["initial_security"] = blocker["security"] = security
    base_sha = _commit_base_registry(tmp_path, _registry([blocker]))

    result, report = _run(
        tmp_path,
        _registry([]),
        context_repository=REPOSITORY,
        context_base_sha=base_sha,
    )

    assert result == 2
    assert any("registry history is append-only" in error for error in report["errors"])


def test_initial_classification_and_retained_actions_cannot_be_rewritten(
    tmp_path: Path,
) -> None:
    blocker = _valid_downgrade(tmp_path)
    base_sha = _commit_base_registry(tmp_path, _registry([blocker]))

    rewritten = copy.deepcopy(blocker)
    rewritten["initial_severity"] = rewritten["severity"] = "P2"
    rewritten["initial_security"] = rewritten["security"] = True
    result, report = _run(
        tmp_path,
        _registry([rewritten]),
        context_repository=REPOSITORY,
        context_base_sha=base_sha,
    )
    assert result == 2
    assert any("immutable field initial_severity" in error for error in report["errors"])
    assert any("immutable field initial_security" in error for error in report["errors"])

    erased = copy.deepcopy(blocker)
    erased["severity"] = "P0"
    erased["downgrade"] = None
    result, report = _run(
        tmp_path,
        _registry([erased]),
        context_repository=REPOSITORY,
        context_base_sha=base_sha,
    )
    assert result == 2
    assert any("action history is append-only" in error for error in report["errors"])


def test_stale_wrong_subject_and_nonapproved_reviews_fail_closed(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)

    stale = _synthetic_provider_payload(blocker, "downgrade", review_commit="c" * 40)
    result, report = _run(tmp_path, _registry([blocker]), provider=stale)
    assert result == 2
    assert any("current head SHA" in error for error in report["errors"])

    wrong_subject = _synthetic_provider_payload(
        blocker,
        "downgrade",
        review_body="METRIPLANE_BLOCKER_APPROVAL_V1\nsubject_sha256=" + "f" * 64,
    )
    result, report = _run(tmp_path, _registry([blocker]), provider=wrong_subject)
    assert result == 2
    assert any("exact action subject" in error for error in report["errors"])

    dismissed = _synthetic_provider_payload(blocker, "downgrade", review_state="DISMISSED")
    result, report = _run(tmp_path, _registry([blocker]), provider=dismissed)
    assert result == 2
    assert any("APPROVED review" in error for error in report["errors"])


def test_malformed_provider_objects_return_invalid_report_without_traceback(
    tmp_path: Path,
) -> None:
    blocker = _valid_downgrade(tmp_path)
    malformed_pull = _synthetic_provider_payload(blocker, "downgrade")
    malformed_pull["pull"]["base"] = None
    result, report = _run(tmp_path, _registry([blocker]), provider=malformed_pull)
    assert result == 2
    assert report["valid"] is False
    assert any("wrong repository" in error for error in report["errors"])

    malformed_review = _synthetic_provider_payload(blocker, "downgrade")
    malformed_review["reviews"][0]["body"] = 42
    result, report = _run(tmp_path, _registry([blocker]), provider=malformed_review)
    assert result == 2
    assert report["valid"] is False
    assert any("exact action subject" in error for error in report["errors"])

    malformed_files = _synthetic_provider_payload(blocker, "downgrade")
    malformed_files["files"].append({"filename": []})
    result, report = _run(tmp_path, _registry([blocker]), provider=malformed_files)
    assert result == 2
    assert report["valid"] is False
    assert any("file inventory is malformed" in error for error in report["errors"])

    duplicate_files = _synthetic_provider_payload(blocker, "downgrade")
    duplicate_files["files"].append({"filename": "docs/status/blockers.json"})
    result, report = _run(tmp_path, _registry([blocker]), provider=duplicate_files)
    assert result == 2
    assert any("file inventory contains duplicates" in error for error in report["errors"])

    duplicate_commit_files = _synthetic_provider_payload(blocker, "downgrade")
    duplicate_commit_files["commit"]["files"].append({"filename": "docs/status/blockers.json"})
    result, report = _run(tmp_path, _registry([blocker]), provider=duplicate_commit_files)
    assert result == 2
    assert any("file inventory contains duplicates" in error for error in report["errors"])

    malformed_commit_files = _synthetic_provider_payload(blocker, "downgrade")
    malformed_commit_files["commit"]["files"].append({"filename": []})
    result, report = _run(tmp_path, _registry([blocker]), provider=malformed_commit_files)
    assert result == 2
    assert report["valid"] is False
    assert any("file inventory is malformed" in error for error in report["errors"])


@pytest.mark.parametrize("review_id", [None, 0, -1, False, "900"])
def test_malformed_review_ids_fail_closed(tmp_path: Path, review_id: Any) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    payload["reviews"][0]["id"] = review_id

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("malformed state, time, or identity" in error for error in report["errors"])


def test_review_states_and_timestamps_are_validated_fail_closed(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)

    unknown = _synthetic_provider_payload(blocker, "downgrade")
    unknown["reviews"].append(
        {
            "id": 901,
            "state": "ACCEPTED",
            "commit_id": HEAD_SHA,
            "body": "",
            "submitted_at": "2026-08-25T15:00:00Z",
            "user": {"id": 500, "login": "unknown-state", "type": "User"},
        }
    )
    result, report = _run(tmp_path, _registry([blocker]), provider=unknown)
    assert result == 2
    assert any("malformed state, time, or identity" in error for error in report["errors"])

    missing_time = _synthetic_provider_payload(blocker, "downgrade")
    missing_time["reviews"].append(
        {
            "id": 901,
            "state": "CHANGES_REQUESTED",
            "commit_id": HEAD_SHA,
            "body": "",
            "submitted_at": None,
            "user": copy.deepcopy(missing_time["reviews"][0]["user"]),
        }
    )
    result, report = _run(tmp_path, _registry([blocker]), provider=missing_time)
    assert result == 2
    assert any("malformed state, time, or identity" in error for error in report["errors"])

    malformed_time = _synthetic_provider_payload(blocker, "downgrade")
    malformed_time["reviews"][0]["submitted_at"] = "2026-02-30T14:00:00Z"
    result, report = _run(tmp_path, _registry([blocker]), provider=malformed_time)
    assert result == 2
    assert any("malformed state, time, or identity" in error for error in report["errors"])

    pending = _synthetic_provider_payload(blocker, "downgrade")
    pending["reviews"].append(
        {
            "id": 901,
            "state": "PENDING",
            "commit_id": HEAD_SHA,
            "body": "draft",
            "submitted_at": None,
            "user": copy.deepcopy(pending["reviews"][0]["user"]),
        }
    )
    result, report = _run(tmp_path, _registry([blocker]), provider=pending)
    assert result == 0
    assert report["valid"] is True


def test_current_requested_changes_and_predated_review_fail_closed(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    requested = {
        "id": 901,
        "state": "CHANGES_REQUESTED",
        "commit_id": HEAD_SHA,
        "body": "",
        "submitted_at": "2026-08-25T15:00:00Z",
        "user": {"id": 500, "login": "requester", "type": "User"},
    }
    payload = _synthetic_provider_payload(blocker, "downgrade", extra_reviews=[requested])
    result, report = _run(tmp_path, _registry([blocker]), provider=payload)
    assert result == 2
    assert any("requested changes" in error for error in report["errors"])

    predates = _synthetic_provider_payload(blocker, "downgrade", reviewed_at="2026-08-25T10:30:00Z")
    result, report = _run(tmp_path, _registry([blocker]), provider=predates)
    assert result == 2
    assert any("predates" in error for error in report["errors"])


def test_comment_does_not_clear_a_prior_changes_requested_decision(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    requested = {
        "id": 899,
        "state": "CHANGES_REQUESTED",
        "commit_id": HEAD_SHA,
        "body": "",
        "submitted_at": "2026-08-25T13:30:00Z",
        "user": {"id": 200, "login": "synthetic-reviewer", "type": "User"},
    }
    commented = {
        "id": 901,
        "state": "COMMENTED",
        "commit_id": HEAD_SHA,
        "body": "follow-up without approval",
        "submitted_at": "2026-08-25T15:00:00Z",
        "user": copy.deepcopy(requested["user"]),
    }
    payload = _synthetic_provider_payload(
        blocker,
        "downgrade",
        review_state="COMMENTED",
        extra_reviews=[requested, commented],
    )

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("requested changes" in error for error in report["errors"])


def test_dismissed_approval_fails_live_revalidation(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    dismissed = {
        "id": 901,
        "state": "DISMISSED",
        "commit_id": HEAD_SHA,
        "body": "",
        "submitted_at": "2026-08-25T15:00:00Z",
        "user": {"id": 200, "login": "synthetic-reviewer", "type": "User"},
    }
    payload = _synthetic_provider_payload(blocker, "downgrade", extra_reviews=[dismissed])

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("APPROVED review" in error for error in report["errors"])


def test_latest_review_tie_uses_numeric_provider_review_id(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    approved = payload["reviews"][0]
    approved["id"] = 9
    payload["reviews"].append(
        {
            "id": 10,
            "state": "CHANGES_REQUESTED",
            "commit_id": HEAD_SHA,
            "body": "",
            "submitted_at": approved["submitted_at"],
            "user": copy.deepcopy(approved["user"]),
        }
    )

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("requested changes" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("conflict", "provider_overrides"),
    [
        ("pull-author", {"pull_author_id": 200}),
        ("registry-author", {"commit_author_id": 200}),
        ("registry-committer", {"commit_committer_id": 200}),
    ],
)
def test_reviewer_must_differ_from_provider_authenticated_change_actors(
    tmp_path: Path, conflict: str, provider_overrides: dict[str, Any]
) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade", **provider_overrides)
    result, report = _run(tmp_path, _registry([blocker]), provider=payload)
    assert result == 2, conflict
    assert any("not independent" in error for error in report["errors"])


def test_reviewer_requires_provider_backed_repository_write_permission(
    tmp_path: Path,
) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade", reviewer_permission="read")

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("eligible repository write permission" in error for error in report["errors"])


def test_later_commit_file_page_cannot_hide_a_registry_change_actor(
    tmp_path: Path,
) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(
        blocker,
        "downgrade",
        commit_author_id=200,
    )
    payload["commit_pages"] = [
        [{"filename": f"generated/page-one-{index:03d}.txt"} for index in range(100)],
        [{"filename": "docs/status/blockers.json"}],
    ]

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("not independent" in error for error in report["errors"])


def test_provider_commit_cap_cannot_hide_registry_change_actors(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    payload["pull"]["commits"] = 251
    payload["pull_commit_pages"] = [
        [{"sha": f"{index:040x}"} for index in range(1, 101)],
        [{"sha": f"{index:040x}"} for index in range(101, 201)],
        [{"sha": f"{index:040x}"} for index in range(201, 251)],
    ]

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("verifiable REST inventory limit" in error for error in report["errors"])


@pytest.mark.parametrize("commit_count", [None, False, 0, "1"])
def test_provider_pull_commit_count_must_be_a_positive_integer(
    tmp_path: Path, commit_count: Any
) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    payload["pull"]["commits"] = commit_count

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("commit count is malformed" in error for error in report["errors"])


def test_provider_pull_commit_count_must_match_enumerated_commits(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    payload["pull"]["commits"] = 2

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("commit inventory count is incomplete" in error for error in report["errors"])


def test_provider_pull_commit_inventory_rejects_duplicate_shas(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    payload["pull"]["commits"] = 2
    payload["commits"] = [{"sha": COMMIT_SHA}, {"sha": COMMIT_SHA}]

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("commit inventory contains duplicates" in error for error in report["errors"])


def test_commit_file_cap_cannot_hide_registry_change_actors(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade")
    payload["commit_pages"] = [
        [{"filename": f"generated/page-{page:02d}-{index:03d}.txt"} for index in range(100)]
        for page in range(30)
    ]

    result, report = _run(tmp_path, _registry([blocker]), provider=payload)

    assert result == 2
    assert any("unverifiable REST limit" in error for error in report["errors"])


def test_release_validation_requires_merged_approval_ancestry(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    _write_json(tmp_path / "registry.json", _registry([blocker]))
    approval_head = _commit_fixture(tmp_path, "approved action head")
    merge_sha = _commit_fixture(tmp_path, "provider merge")
    release_sha = _commit_fixture(tmp_path, "release candidate")
    payload = _synthetic_provider_payload(
        blocker,
        "downgrade",
        head_sha=approval_head,
        merged=True,
        merge_sha=merge_sha,
    )

    result, report = _run(
        tmp_path,
        _registry([blocker]),
        provider=payload,
        validated_sha=release_sha,
        require_merged_approval=True,
        include_pull_context=False,
    )
    assert result == 0
    assert report["valid"] is True

    divergent_merge = _commit_fixture(tmp_path, "divergent copied approval")
    payload["pull"]["merge_commit_sha"] = divergent_merge
    result, report = _run(
        tmp_path,
        _registry([blocker]),
        provider=payload,
        validated_sha=release_sha,
        require_merged_approval=True,
        include_pull_context=False,
    )
    assert result == 2
    assert any("not an ancestor" in error for error in report["errors"])

    payload["pull"]["merged"] = False
    payload["pull"]["state"] = "open"
    payload["pull"]["merged_at"] = None
    result, report = _run(
        tmp_path,
        _registry([blocker]),
        provider=payload,
        validated_sha=release_sha,
        require_merged_approval=True,
        include_pull_context=False,
    )
    assert result == 2
    assert any("not verifiably merged" in error for error in report["errors"])


@pytest.mark.parametrize("field", ["reported_by_actor_id", "changed_by_actor_id"])
def test_reviewer_must_differ_from_reporter_and_action_actor(tmp_path: Path, field: str) -> None:
    blocker = _valid_downgrade(tmp_path)
    if field == "reported_by_actor_id":
        blocker[field] = REVIEWER_ACTOR
    else:
        blocker["downgrade"][field] = REVIEWER_ACTOR
    _bind_action(blocker, "downgrade")
    payload = _synthetic_provider_payload(blocker, "downgrade")
    result, report = _run(tmp_path, _registry([blocker]), provider=payload)
    assert result == 2
    assert any("not independent" in error for error in report["errors"])


def test_unlinked_or_cross_provider_actor_identity_fails_closed(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    blocker["reported_by_actor_id"] = "linear:reporter"
    _bind_action(blocker, "downgrade")
    payload = _synthetic_provider_payload(blocker, "downgrade")
    result, report = _run(tmp_path, _registry([blocker]), provider=payload)
    assert result == 2
    assert any("comparable provider-authenticated" in error for error in report["errors"])

    blocker = _valid_downgrade(tmp_path)
    payload = _synthetic_provider_payload(blocker, "downgrade", commit_author_id=None)
    result, report = _run(tmp_path, _registry([blocker]), provider=payload)
    assert result == 2
    assert any("no linked human identity" in error for error in report["errors"])


def test_reserved_linear_provider_fails_closed_without_live_verifier(tmp_path: Path) -> None:
    blocker = _valid_downgrade(tmp_path)
    blocker["downgrade"]["approval"]["provider"] = "linear"
    result, report = _run(tmp_path, _registry([blocker]))
    assert result == 2
    assert any("no configured live verifier" in error for error in report["errors"])


def test_evidence_paths_fail_closed_on_escape_symlink_and_hash_mismatch(tmp_path: Path) -> None:
    escaped = _valid_downgrade(tmp_path)
    escaped["downgrade"]["reproduction_evidence"][0]["path"] = "../outside.txt"
    result, report = _run(tmp_path, _registry([escaped]))
    assert result == 2
    assert any("repository-relative" in error for error in report["errors"])

    noncanonical = _valid_downgrade(tmp_path)
    path = noncanonical["downgrade"]["reproduction_evidence"][0]["path"]
    noncanonical["downgrade"]["reproduction_evidence"][0]["path"] = path.replace("/", "//", 1)
    result, report = _run(tmp_path, _registry([noncanonical]))
    assert result == 2
    assert any("repository-relative" in error for error in report["errors"])

    linked = _valid_downgrade(tmp_path)
    evidence_path = tmp_path / linked["downgrade"]["reproduction_evidence"][0]["path"]
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    evidence_path.unlink()
    evidence_path.symlink_to(outside)
    result, report = _run(tmp_path, _registry([linked]))
    assert result == 2
    assert any("tracked regular file" in error for error in report["errors"])

    mismatched = _valid_downgrade(tmp_path)
    mismatched["downgrade"]["control_evidence"][0]["sha256"] = "f" * 64
    result, report = _run(tmp_path, _registry([mismatched]))
    assert result == 2
    assert any("SHA-256 mismatch" in error for error in report["errors"])


def test_evidence_must_be_tracked_and_hashed_at_the_validated_commit(
    tmp_path: Path,
) -> None:
    blocker = _valid_downgrade(tmp_path)
    reproduction = tmp_path / blocker["downgrade"]["reproduction_evidence"][0]["path"]
    reproduction.unlink()
    (tmp_path / ".gitignore").write_text("proof/reproduction.txt\n", encoding="utf-8")
    validated_sha = _commit_fixture(tmp_path, "evidence without ignored reproduction")
    reproduction.write_text("reproduction:reproduction.txt\n", encoding="utf-8")

    result, report = _run(
        tmp_path,
        _registry([blocker]),
        validated_sha=validated_sha,
    )
    assert result == 2
    assert any("not tracked at the validated commit" in error for error in report["errors"])

    tracked = _valid_downgrade(tmp_path / "tracked")
    tracked_repo = tmp_path / "tracked"
    tracked_sha = _commit_fixture(tracked_repo, "tracked evidence")
    tracked_path = tracked_repo / tracked["downgrade"]["control_evidence"][0]["path"]
    tracked_path.write_text("current-worktree-only replacement\n", encoding="utf-8")
    tracked["downgrade"]["control_evidence"][0]["sha256"] = hashlib.sha256(
        tracked_path.read_bytes()
    ).hexdigest()
    _bind_action(tracked, "downgrade")

    result, report = _run(
        tracked_repo,
        _registry([tracked]),
        validated_sha=tracked_sha,
    )
    assert result == 2
    assert any("mismatch at validated commit" in error for error in report["errors"])


def test_report_is_deterministic_and_machine_readable(tmp_path: Path) -> None:
    blocker = _base_blocker()
    first = _run(tmp_path, _registry([blocker]))
    second = _run(tmp_path, _registry([blocker]))
    assert first == second
    assert first[1]["schema_version"] == "metriplane.blocker-check.v1"
    assert json.dumps(first[1], sort_keys=True, separators=(",", ":"))


def test_schema_checker_docs_trace_and_workflow_are_connected() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    docs = DOC_PATH.read_text(encoding="utf-8")
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    checker = TOOL_PATH.read_text(encoding="utf-8")
    assert schema["$id"] in checker
    for acceptance_id in ("MP2-006.A01", "MP2-006.A02"):
        assert acceptance_id in docs
    for path in (
        "schemas/metriplane.blockers.v1.schema.json",
        "docs/status/blockers.json",
        "tools/check_blockers.py",
        "tests/test_blocker_workflow.py",
    ):
        assert path in docs
        assert path in workflow
    for provider_binding in (
        "GITHUB_TOKEN",
        "pull_request_review",
        "fetch-depth: 0",
        "github.event.pull_request.number",
        "github.event.pull_request.head.sha",
        "github.event.pull_request.base.sha",
        "--validated-sha",
        "--require-merged-approval",
    ):
        assert provider_binding in workflow


def test_production_registry_has_no_live_downgrade_or_closure() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert registry["blockers"] == []


def test_schema_is_closed_and_checker_rejects_claimed_reviewer_fields(tmp_path: Path) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    for name in ("approval", "blocker", "closure", "downgrade", "evidence"):
        assert schema["$defs"][name]["additionalProperties"] is False
        assert set(schema["$defs"][name]["required"]) == set(schema["$defs"][name]["properties"])

    blocker = _valid_downgrade(tmp_path)
    blocker["downgrade"]["approval"]["reviewer_actor_id"] = "github:999"
    result, report = _run(tmp_path, _registry([blocker]))
    assert result == 2
    assert report["valid"] is False


def test_checker_rejects_duplicate_and_unsorted_ids(tmp_path: Path) -> None:
    first = _base_blocker("MPBLK-0002")
    first["initial_severity"] = first["severity"] = "P2"
    second = copy.deepcopy(first)
    second["id"] = "MPBLK-0001"
    result, report = _run(tmp_path, _registry([first, second]))
    assert result == 2
    assert any("sorted" in error for error in report["errors"])

    second["id"] = "MPBLK-0002"
    result, report = _run(tmp_path, _registry([first, second]))
    assert result == 2
    assert any("duplicate" in error for error in report["errors"])


def test_status_transition_and_subject_must_match_records(tmp_path: Path) -> None:
    closure = _valid_closure(tmp_path)
    closure["status"] = "controlled"
    result, report = _run(tmp_path, _registry([closure]))
    assert result == 2
    assert any("requires closed status" in error for error in report["errors"])

    transition = _valid_downgrade(tmp_path)
    transition["downgrade"]["to_severity"] = "P1"
    result, report = _run(tmp_path, _registry([transition]))
    assert result == 2
    assert any("does not match" in error for error in report["errors"])

    subject = _valid_downgrade(tmp_path)
    subject["downgrade"]["approval"]["subject_sha256"] = "f" * 64
    result, report = _run(tmp_path, _registry([subject]))
    assert result == 2
    assert any("exact record" in error for error in report["errors"])

    reporter = _valid_downgrade(tmp_path)
    reporter["reported_by_actor_id"] = "github:301"
    result, report = _run(tmp_path, _registry([reporter]))
    assert result == 2
    assert any("exact record" in error for error in report["errors"])


def test_criterion_result_evidence_contract_is_exact(tmp_path: Path) -> None:
    clear_result, clear = _run(tmp_path)
    blocked_result, blocked = _run(tmp_path, _registry([_base_blocker()]))
    invalid = _registry([])
    invalid["unknown"] = True
    invalid_result, invalid_report = _run(tmp_path, invalid)
    expected_keys = {
        "schema_version",
        "registry",
        "valid",
        "release_blocked",
        "blocking_ids",
        "error_count",
        "errors",
    }
    assert set(clear) == expected_keys
    assert set(blocked) == expected_keys
    assert set(invalid_report) == expected_keys
    assert (clear_result, blocked_result, invalid_result) == (0, 1, 2)
