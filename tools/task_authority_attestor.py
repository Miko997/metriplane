# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Isolated, read-only task observation signer for one protected v0.5 task.

This command is deliberately inoperative until a protected owner program
grant and systemd-isolated Linear/Ed25519 credentials have been established.
It never signs an owner grant or a delegate request, and never changes GitHub
or Linear state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, canonical_json, sha256_json
from tools.check_work_order_catalog import SOURCE_SHA256
from tools.ed25519_envelope import sign_envelope
from tools.linear_work_order_provider import LinearGraphqlReader, observe_project_graph
from tools.main_health_broker import (
    AppAuthenticator,
    BrokerConfig,
    GitHubApi,
    HealthReconciler,
    StateBranch,
    _credential_is_private,
    _load_object,
    _main_ref,
    validate_clock,
)
from tools.protected_source import read_protected_blob
from tools.task_attestation_builder import prepare_task_observation
from tools.task_delegation import DelegationError

REPOSITORY = "Miko997/metriplane"
PROJECT_ID = "cf53f98f-0965-4360-a66e-530457e40354"
OWNER_ID = "96778fbb-c8ff-42b3-9217-7cac45dcd097"
EXECUTOR_ID = "01a096e0-4e21-7a11-9f0f-fb303387c5c0"
CATALOG_PATH = "docs/status/task-work-orders.json"
AUTHORITY_PATH = "docs/status/task-delegation-authority.json"
GRANT_PATH = "docs/status/v05-program-delegation.json"


class AttestorError(ValueError):
    """The attestor cannot issue a truthful exact-main task observation."""


class _NoSpool:
    """Prevent the read-only attestor from touching the broker's durable DB."""

    def __getattr__(self, name: str) -> Any:
        raise AttestorError(f"task attestor attempted broker spool operation: {name}")


def _private_credential(name: str) -> Path:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory or not Path(directory).is_absolute():
        raise AttestorError("systemd credential directory is unavailable")
    path = Path(directory) / name
    if not _credential_is_private(path):
        raise AttestorError("attestor credential is outside the isolated boundary")
    return path


def _sign_attestation(private_key_path: Path, *, subject_digest: str) -> bytes:
    return sign_envelope(
        private_key_path,
        provider="metriplane-health",
        actor_id="metriplane-health",
        subject_digest=subject_digest,
    )


def _read_json_blob(api: GitHubApi, *, token: str, main_sha: str, path: str) -> tuple[bytes, dict]:
    raw = read_protected_blob(api, repository=REPOSITORY, main_sha=main_sha, path=path, token=token)
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AttestorError("protected task authority JSON is invalid") from exc
    if not isinstance(value, dict):
        raise AttestorError("protected task authority JSON is not an object")
    return raw, value


def _write_new(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def attest(*, config_path: Path, task_id: str) -> dict[str, Any]:
    if re.fullmatch(r"MP2-[0-9]{3}", task_id) is None:
        raise AttestorError("task identity is malformed")
    config = BrokerConfig.from_mapping(_load_object(config_path))
    if config.repository != REPOSITORY:
        raise AttestorError("broker repository identity is not canonical")
    app_credential = _private_credential("github-app-private-key.pem")
    linear_credential = _private_credential("linear-readonly-token")
    signing_credential = _private_credential("task-attestor-ed25519.pem")
    # The broker config names its own per-unit decrypted path. The attestor
    # has a different systemd credential directory and may use only that
    # unit's separately loaded copy of the same approved App credential.
    config = replace(config, credential_path=app_credential)
    try:
        linear_token = linear_credential.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise AttestorError("Linear read-only credential is unreadable") from exc
    api = GitHubApi()
    installation = AppAuthenticator(api, config).mint()
    token = installation.token
    provider_now = api.provider_now(token)
    validate_clock(
        local_now=dt.datetime.now(dt.timezone.utc),
        provider_now=provider_now,
        max_clock_skew_seconds=config.max_clock_skew_seconds,
    )
    state_branch = StateBranch(api=api, config=config, token=token)
    health = HealthReconciler(
        api=api,
        config=config,
        spool=_NoSpool(),
        state_branch=state_branch,
        token=token,
    )
    state = health.verify_current_health(provider_now)
    main_sha = state.get("last_good_sha")
    if not isinstance(main_sha, str) or _main_ref(api, config=config, token=token) != main_sha:
        raise AttestorError("protected main is not exact-current in Main Health")
    main_commit = api.request(f"repos/{REPOSITORY}/git/commits/{main_sha}", token=token).value
    if not isinstance(main_commit, dict) or main_commit.get("sha") != main_sha:
        raise AttestorError("protected main commit response is not exact")
    tree = main_commit.get("tree")
    if not isinstance(tree, dict) or not isinstance(tree.get("sha"), str):
        raise AttestorError("protected main tree identity is unavailable")
    main_tree = tree["sha"]

    catalog_raw, catalog = _read_json_blob(api, token=token, main_sha=main_sha, path=CATALOG_PATH)
    if hashlib.sha256(catalog_raw).hexdigest() != SOURCE_SHA256:
        raise AttestorError("protected task catalog differs from the frozen authority")
    _authority_raw, authority = _read_json_blob(
        api, token=token, main_sha=main_sha, path=AUTHORITY_PATH
    )
    grant_raw, grant = _read_json_blob(api, token=token, main_sha=main_sha, path=GRANT_PATH)
    if grant_raw != canonical_json(grant):
        raise AttestorError("protected owner program grant is not canonical")
    graph = observe_project_graph(
        catalog,
        project_id=PROJECT_ID,
        issue_reader=LinearGraphqlReader(linear_token).issue,
    )
    captured = dt.datetime.strptime(graph["captured_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )
    if abs((dt.datetime.now(dt.timezone.utc) - captured).total_seconds()) > 60:
        raise AttestorError("Linear provider observation is outside the local clock boundary")
    subject, snapshot = prepare_task_observation(
        catalog=catalog,
        authority=authority,
        grant=grant,
        graph=graph,
        task_id=task_id,
        repository=REPOSITORY,
        project_id=PROJECT_ID,
        grantor_id=OWNER_ID,
        executor_id=EXECUTOR_ID,
        base_sha=main_sha,
        base_tree=main_tree,
        live=True,
    )
    digest = sha256_json(subject)
    signature = {
        "provider": "metriplane-health",
        "actor_id": "metriplane-health",
        "key_id": subject["attestor_key_id"],
        "signature": _sign_attestation(signing_credential, subject_digest=digest).hex(),
    }
    public_hex = grant["subject"]["attestor"]["public_key_hex"]
    if not ProviderAttestationVerifier(
        keys={("metriplane-health", "metriplane-health"): bytes.fromhex(public_hex)}
    ).verify(signature, subject_digest=digest):
        raise AttestorError("isolated signer does not match the owner-approved attestor key")
    if _main_ref(api, config=config, token=token) != main_sha or state_branch.read().get(
        "state_commit"
    ) != state.get("state_commit"):
        raise AttestorError("protected main or Main Health changed during attestation")
    partial = {
        "schema_version": "metriplane.task-delegation.v2",
        "synthetic": False,
        "program_grant": grant,
        "subject": subject,
        "subject_digest": digest,
        "attestor_signature": signature,
    }
    output = config.state_root / "task-attestations" / task_id / subject["delegation_id"]
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    _write_new(output / "linear-snapshot.json", snapshot)
    _write_new(output / "attested-task-request.json", partial)
    return {
        "task_id": task_id,
        "base_sha": main_sha,
        "base_tree": main_tree,
        "delegation_id": subject["delegation_id"],
        "state_commit": state["state_commit"],
        "state_generation": state["generation"],
        "output_directory": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    try:
        result = attest(config_path=args.config, task_id=args.task_id)
    except (AttestorError, DelegationError, ConnectionError, ValueError, OSError) as exc:
        print(f"task attestation blocked: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
