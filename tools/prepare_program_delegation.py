# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Prepare one owner-signed, bounded v0.5 program grant on qualified main.

Run this locally as Miko. It never prints or stores the passphrase, and the
private key stays outside Git. The resulting public grant still requires a
separate protected PR and exact-main qualification before it has authority.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from metriplane.release_control import canonical_json, sha256_json
from tools.complete_delegated_task import EXECUTOR_ID, OWNER_ID, PROJECT_ID, REPOSITORY
from tools.ed25519_envelope import sign_envelope
from tools.program_delegation import _implementation_tasks, program_grant_id, validate_program_grant
from tools.task_delegation import DelegationError, key_id

GRANT_PATH = Path("docs/status/v05-program-delegation.json")
AUTHORITY_PATH = Path("docs/status/task-delegation-authority.json")
CATALOG_PATH = Path("docs/status/task-work-orders.json")


def _run(*argv: str, cwd: Path) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise DelegationError("protected-main readback failed")
    return result.stdout.strip()


def _qualified_main(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=root) != "main":
        raise DelegationError("owner grant must start from the local main branch")
    if _run("git", "status", "--porcelain", cwd=root):
        raise DelegationError("owner grant requires a clean source tree")
    head = _run("git", "rev-parse", "HEAD", cwd=root)
    remote_main = _run("git", "ls-remote", "origin", "refs/heads/main", cwd=root).split()
    if len(remote_main) != 2 or remote_main[0] != head:
        raise DelegationError("local main is not exact protected main")
    state_encoded = _run(
        "gh",
        "api",
        f"repos/{REPOSITORY}/contents/state.json?ref=metriplane-main-health-state",
        "--jq",
        ".content",
        cwd=root,
    )
    try:
        state = json.loads(base64.b64decode(state_encoded))
    except (ValueError, TypeError) as exc:
        raise DelegationError("protected Main Health state is malformed") from exc
    if state.get("status") != "green" or state.get("last_good_sha") != head:
        raise DelegationError("Main Health is not current on the exact protected main")
    records = []
    for path in (AUTHORITY_PATH, CATALOG_PATH):
        git_bytes = subprocess.run(
            ["git", "show", f"{head}:{path.as_posix()}"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if git_bytes.returncode != 0 or git_bytes.stdout != (root / path).read_bytes():
            raise DelegationError("authority input differs from protected main")
        try:
            records.append(json.loads(git_bytes.stdout))
        except ValueError as exc:
            raise DelegationError("authority input is malformed") from exc
    return records[0], records[1]


def _public_identity(public_key_hex: str) -> dict[str, str]:
    if len(public_key_hex) != 64 or public_key_hex != public_key_hex.lower():
        raise DelegationError("machine public key must be 32 lowercase hex bytes")
    return {"key_id": key_id(public_key_hex), "public_key_hex": public_key_hex}


def prepare_grant(
    *,
    authority: dict[str, Any],
    catalog: dict[str, Any],
    delegate_public_key_hex: str,
    attestor_public_key_hex: str,
    owner_key: Path,
    issued_at: str,
    expires_at: str,
    passphrase: str,
) -> dict[str, Any]:
    if not owner_key.is_absolute():
        raise DelegationError("owner key path must be absolute")
    delegate = _public_identity(delegate_public_key_hex)
    attestor = _public_identity(attestor_public_key_hex)
    signing_key_id = next(
        (
            row["key_id"]
            for row in authority.get("keys", [])
            if row.get("provider") == "linear"
            and row.get("actor_id") == OWNER_ID
            and row.get("role") == "repository_owner"
            and row.get("status") == "active"
            and row.get("trust_class") == "production"
            and row.get("repository") == REPOSITORY
            and row.get("project_id") == PROJECT_ID
        ),
        None,
    )
    if signing_key_id is None:
        raise DelegationError("approved production owner key is absent")
    subject: dict[str, Any] = {
        "grantor": {"provider": "linear", "actor_id": OWNER_ID, "role": "repository_owner"},
        "delegate": {"kind": "codex_goal", "executor_id": EXECUTOR_ID, **delegate},
        "attestor": {
            "kind": "isolated_provider_attestor",
            "service": "metriplane-health",
            **attestor,
        },
        "scope": {
            "repository": REPOSITORY,
            "project_id": PROJECT_ID,
            "milestone": "v0.5",
            "task_ids": _implementation_tasks(catalog),
            "permitted_actions": ["materialize_task_work_order", "request_owner_normal_merge"],
            "prohibited_actions": [
                "owner_emergency_repair",
                "publication",
                "release_decision",
                "repository_settings",
                "subdelegation",
            ],
        },
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signing_key_id": signing_key_id,
    }
    subject["grant_id"] = program_grant_id(subject)
    subject_digest = sha256_json(subject)
    signature = sign_envelope(
        owner_key,
        provider="linear",
        actor_id=OWNER_ID,
        subject_digest=subject_digest,
        passphrase=passphrase,
    )
    grant = {
        "schema_version": "metriplane.program-delegation.v1",
        "synthetic": False,
        "subject": subject,
        "subject_digest": subject_digest,
        "signature": {
            "provider": "linear",
            "actor_id": OWNER_ID,
            "key_id": signing_key_id,
            "signature": signature.hex(),
        },
    }
    validate_program_grant(
        grant,
        authority,
        catalog,
        repository=REPOSITORY,
        project_id=PROJECT_ID,
        grantor_id=OWNER_ID,
        executor_id=EXECUTOR_ID,
        evaluated_at=issued_at,
        live=True,
    )
    return grant


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--owner-key", type=Path, required=True)
    parser.add_argument("--delegate-public-key-hex", required=True)
    parser.add_argument("--attestor-public-key-hex", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        root = args.repository_root.resolve(strict=True)
        owner_key = args.owner_key.resolve(strict=True)
        if owner_key.is_relative_to(root):
            raise DelegationError("owner private key must remain outside the repository")
        if args.out.resolve() != root / GRANT_PATH:
            raise DelegationError("grant output must be the canonical repository path")
        authority, catalog = _qualified_main(root)
        issued = datetime.now(UTC).replace(microsecond=0)
        expires = issued + timedelta(days=30)
        passphrase = getpass.getpass("Owner key passphrase (not stored): ")
        grant = prepare_grant(
            authority=authority,
            catalog=catalog,
            delegate_public_key_hex=args.delegate_public_key_hex,
            attestor_public_key_hex=args.attestor_public_key_hex,
            owner_key=owner_key,
            issued_at=issued.isoformat().replace("+00:00", "Z"),
            expires_at=expires.isoformat().replace("+00:00", "Z"),
            passphrase=passphrase,
        )
        descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(grant))
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"owner program grant blocked: {exc}", file=sys.stderr)
        return 3
    print(f"Created signed public grant at {GRANT_PATH}; protected PR still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
