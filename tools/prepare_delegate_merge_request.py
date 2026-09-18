# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Prepare one short-lived Codex machine request, never a GitHub review.

This is usable only after the protected owner program grant and exact-base
READY work order exist. It reads GitHub with the caller's existing read token,
signs with the *delegate* key, and creates one private local package. Moving
that package into the App-owned inbox is a separately reviewed host action.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from metriplane.release_control import canonical_json, sha256_json
from tools import main_health_broker as broker
from tools import stop_the_line
from tools.delegated_merge import (
    merge_request_id,
    select_delegate_admission,
    validate_delegate_package_at_base,
)
from tools.ed25519_envelope import sign_envelope

REPOSITORY = "Miko997/metriplane"
PROJECT_ID = "cf53f98f-0965-4360-a66e-530457e40354"
EXECUTOR_ID = "01a096e0-4e21-7a11-9f0f-fb303387c5c0"
STATE_BRANCH = "metriplane-main-health-state"
RULESET_IDS = (20613848, 21487681, 21500579, 21533351, 21633569, 22071973, 22170798)


class RequestPreparationError(ValueError):
    """The exact provider or task context cannot justify a machine request."""


def _gh(path: str, *, paginated: bool = False) -> Any:
    def request(target: str) -> Any:
        result = subprocess.run(
            ["gh", "api", target], capture_output=True, text=True, check=False, timeout=30
        )
        if result.returncode != 0:
            raise RequestPreparationError("GitHub provider read failed")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RequestPreparationError("GitHub provider returned malformed JSON") from exc

    if not paginated:
        return request(path)
    items: list[Any] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 101):
        rows = request(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(rows, list):
            raise RequestPreparationError("GitHub provider pagination is malformed")
        items.extend(rows)
        if len(rows) < 100:
            return items
    raise RequestPreparationError("GitHub provider pagination exceeded its bound")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RequestPreparationError("delegate request input is unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise RequestPreparationError("delegate request input is not an object")
    return value


def _config() -> broker.BrokerConfig:
    # IDs are the protected public broker policy; private credential paths are
    # deliberately unused by this read-only rootless preparation command.
    return broker.BrokerConfig(
        admission_ruleset_id=21500579,
        app_id=broker.APP_INTEGRATION_ID,
        app_slug=broker.APP_SLUG,
        core_ruleset_id=20613848,
        credential_path=Path("/unused/merge.pem"),
        main_update_ruleset_id=21633569,
        max_clock_skew_seconds=30,
        poll_seconds=60,
        release_lease_ruleset_id=22071973,
        release_tag_ruleset_id=22170798,
        repository=REPOSITORY,
        settings_app_id=1,
        settings_app_slug=broker.SETTINGS_APP_SLUG,
        settings_credential_path=Path("/unused/settings.pem"),
        state_branch=STATE_BRANCH,
        state_protection_ruleset_id=21487681,
        state_root=Path("/unused/state"),
        state_writer_ruleset_id=21533351,
    )


def prepare(
    *,
    repository_root: Path,
    pull_number: int,
    work_order_path: Path,
    delegation_path: Path,
    snapshot_path: Path,
    dependencies_path: Path,
    commands_path: Path,
    resolution_path: Path,
    delegate_key_path: Path,
) -> dict[str, Any]:
    if pull_number <= 0 or not delegate_key_path.is_absolute():
        raise RequestPreparationError("PR identity or delegate key path is invalid")
    root = repository_root.resolve(strict=True)
    if delegate_key_path.resolve(strict=True).is_relative_to(root):
        raise RequestPreparationError("delegate key must remain outside the repository")
    local_base = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    remote_main = _gh(f"repos/{REPOSITORY}/git/ref/heads/main")
    if remote_main.get("object", {}).get("sha") != local_base:
        raise RequestPreparationError("repository root is not exact protected main")
    pull = _gh(f"repos/{REPOSITORY}/pulls/{pull_number}")
    if not isinstance(pull, dict) or pull.get("base", {}).get("sha") != local_base:
        raise RequestPreparationError("pull request does not target exact protected main")
    head_sha = pull.get("head", {}).get("sha")
    commit = _gh(f"repos/{REPOSITORY}/git/commits/{head_sha}")
    if commit.get("sha") != head_sha:
        raise RequestPreparationError("PR head commit is not exact")
    head_tree = commit.get("tree", {}).get("sha")
    if not isinstance(head_tree, str):
        raise RequestPreparationError("PR head tree is absent")
    files = _gh(f"repos/{REPOSITORY}/pulls/{pull_number}/files", paginated=True)
    changed_paths = stop_the_line._github_changed_paths(pull, files)
    collaborators = _gh(f"repos/{REPOSITORY}/collaborators?affiliation=all", paginated=True)
    invitations = _gh(f"repos/{REPOSITORY}/invitations", paginated=True)
    normalized_collaborators, normalized_invitations = (
        stop_the_line._github_collaboration_inventory(collaborators, invitations)
    )
    owner = [
        item
        for item in normalized_collaborators
        if item["login"].casefold() == "miko997" and item["permission"] == "admin"
    ]
    if len(owner) != 1:
        raise RequestPreparationError("GitHub owner collaboration state is ambiguous")
    rulesets = {
        identifier: _gh(f"repos/{REPOSITORY}/rulesets/{identifier}") for identifier in RULESET_IDS
    }
    ruleset_digests = broker.validate_hosted_rulesets(config=_config(), rulesets=rulesets)
    state_ref = _gh(f"repos/{REPOSITORY}/git/ref/heads/{STATE_BRANCH}")
    state_commit = state_ref.get("object", {}).get("sha")
    if not isinstance(state_commit, str):
        raise RequestPreparationError("protected Main Health state commit is absent")
    state_object = _gh(f"repos/{REPOSITORY}/contents/state.json?ref={state_commit}")
    if state_object.get("encoding") != "base64":
        raise RequestPreparationError("protected Main Health state is not base64-bound")
    try:
        state = json.loads(base64.b64decode(state_object["content"], validate=False))
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RequestPreparationError("protected Main Health state is malformed") from exc
    if not isinstance(state, dict) or state.get("status") != "green":
        raise RequestPreparationError("protected Main Health is not green")
    state["state_commit"] = state_commit
    context = {
        "changed_paths_digest": broker.digest(changed_paths),
        "collaboration_digest": broker.digest(
            {
                "collaborators": normalized_collaborators,
                "pending_invitations": normalized_invitations,
            }
        ),
        "ruleset_digests": dict(sorted(ruleset_digests.items(), key=lambda pair: int(pair[0]))),
    }
    package: dict[str, Any] = {
        "schema_version": "metriplane.delegate-merge-package.v1",
        "request": {},
        "work_order": _read(work_order_path),
        "delegation": _read(delegation_path),
        "linear_snapshot": _read(snapshot_path),
        "dependencies": _read(dependencies_path),
        "commands": _read(commands_path),
        "resolution": _read(resolution_path),
    }
    with tempfile.TemporaryDirectory(prefix="delegate-request-validation-") as temporary:
        work_order, validation = validate_delegate_package_at_base(
            package,
            exact_base_root=root,
            temporary_root=Path(temporary),
            provider_now=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    grant = _read(root / broker.DELEGATE_PROGRAM_GRANT_PATH)
    authority = _read(root / "docs/status/task-delegation-authority.json")
    catalog = _read(root / "docs/status/task-work-orders.json")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    subject = {
        "grant_id": grant["subject"]["grant_id"],
        "repository": REPOSITORY,
        "project_id": PROJECT_ID,
        "executor_id": EXECUTOR_ID,
        "task_id": work_order["task_id"],
        "linear_issue": work_order["linear_issue"],
        "work_order_id": work_order["materialization_id"],
        "work_order_digest": sha256_json(work_order),
        "pull_request": pull_number,
        "base_sha": local_base,
        "head_sha": head_sha,
        "head_tree": head_tree,
        "changed_paths_digest": context["changed_paths_digest"],
        "collaboration_digest": context["collaboration_digest"],
        "ruleset_digests": context["ruleset_digests"],
        "state_commit": state_commit,
        "health_generation": state["generation"],
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + dt.timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nonce": secrets.token_hex(32),
    }
    subject["request_id"] = merge_request_id(subject)
    subject_digest = sha256_json(subject)
    package["request"] = {
        "schema_version": "metriplane.delegate-merge-request.v1",
        "subject": subject,
        "subject_digest": subject_digest,
        "signature": {
            "provider": "codex_goal",
            "actor_id": EXECUTOR_ID,
            "key_id": grant["subject"]["delegate"]["key_id"],
            "signature": sign_envelope(
                delegate_key_path,
                provider="codex_goal",
                actor_id=EXECUTOR_ID,
                subject_digest=subject_digest,
            ).hex(),
        },
    }
    select_delegate_admission(
        package["request"],
        grant=grant,
        authority=authority,
        catalog=catalog,
        work_order=work_order,
        validated_work_order=validation,
        pull=pull,
        head_tree=head_tree,
        changed_paths=changed_paths,
        owner_context=context,
        state=state,
        provider_now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        owner_id=int(owner[0]["id"]),
    )
    if _gh(f"repos/{REPOSITORY}/git/ref/heads/main").get("object", {}).get("sha") != local_base:
        raise RequestPreparationError("protected main changed during request preparation")
    if (
        _gh(f"repos/{REPOSITORY}/git/ref/heads/{STATE_BRANCH}").get("object", {}).get("sha")
        != state_commit
    ):
        raise RequestPreparationError("Main Health state changed during request preparation")
    if _gh(f"repos/{REPOSITORY}/pulls/{pull_number}").get("head", {}).get("sha") != head_sha:
        raise RequestPreparationError("PR head changed during request preparation")
    return package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--work-order", required=True, type=Path)
    parser.add_argument("--delegation", required=True, type=Path)
    parser.add_argument("--linear-snapshot", required=True, type=Path)
    parser.add_argument("--dependencies", required=True, type=Path)
    parser.add_argument("--commands", required=True, type=Path)
    parser.add_argument("--resolution", required=True, type=Path)
    parser.add_argument("--delegate-key", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.repository_root.resolve(strict=True)
        if args.out.resolve().is_relative_to(root):
            raise RequestPreparationError(
                "delegate request output must remain outside the repository"
            )
        result = prepare(
            repository_root=root,
            pull_number=args.pull_request,
            work_order_path=args.work_order,
            delegation_path=args.delegation,
            snapshot_path=args.linear_snapshot,
            dependencies_path=args.dependencies,
            commands_path=args.commands,
            resolution_path=args.resolution,
            delegate_key_path=args.delegate_key,
        )
        descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(result) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"delegate merge request blocked: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
