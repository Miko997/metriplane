# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Countersign an isolated task attestation as the exact Codex executor.

This creates no owner authorization. It only completes a fresh task instance
already signed by the separately isolated provider attestor.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metriplane.release_control import ProviderAttestationVerifier, canonical_json, sha256_json
from tools.delegated_task_authority import validate_delegated_task
from tools.ed25519_envelope import sign_envelope
from tools.program_delegation import validate_program_grant
from tools.task_delegation import DelegationError

EXECUTOR_ID = "01a096e0-4e21-7a11-9f0f-fb303387c5c0"
OWNER_ID = "96778fbb-c8ff-42b3-9217-7cac45dcd097"
REPOSITORY = "Miko997/metriplane"
PROJECT_ID = "cf53f98f-0965-4360-a66e-530457e40354"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise DelegationError("delegated task input is unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise DelegationError("delegated task input is not an object")
    return value


def complete(
    *,
    partial: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    authority: Mapping[str, Any],
    catalog: Mapping[str, Any],
    private_key_path: Path,
    evaluated_at: str,
    live: bool,
) -> dict[str, Any]:
    if private_key_path.resolve(strict=True).is_relative_to(Path(__file__).resolve().parents[1]):
        raise DelegationError("delegate private key must remain outside the repository")
    if (
        set(partial)
        != {
            "schema_version",
            "synthetic",
            "program_grant",
            "subject",
            "subject_digest",
            "attestor_signature",
        }
        or partial.get("schema_version") != "metriplane.task-delegation.v2"
    ):
        raise DelegationError("isolated task attestation shape is not exact")
    grant = partial["program_grant"]
    subject = partial["subject"]
    attestor = partial["attestor_signature"]
    if not all(isinstance(value, Mapping) for value in (grant, subject, attestor)):
        raise DelegationError("isolated task attestation is malformed")
    if partial.get("subject_digest") != sha256_json(subject):
        raise DelegationError("isolated task attestation subject digest differs")
    scope = subject.get("scope")
    if not isinstance(scope, Mapping):
        raise DelegationError("isolated task scope is absent")
    program = validate_program_grant(
        grant,
        authority,
        catalog,
        repository=REPOSITORY,
        project_id=PROJECT_ID,
        grantor_id=OWNER_ID,
        executor_id=EXECUTOR_ID,
        evaluated_at=evaluated_at,
        live=live,
    )
    if (
        partial.get("synthetic") is not (not live)
        or subject.get("attestor_key_id") != program["attestor_key_id"]
        or not isinstance(attestor, Mapping)
        or {key: attestor.get(key) for key in ("provider", "actor_id", "key_id")}
        != {
            "provider": "metriplane-health",
            "actor_id": "metriplane-health",
            "key_id": program["attestor_key_id"],
        }
    ):
        raise DelegationError("isolated task attestor is outside the approved grant")
    if not ProviderAttestationVerifier(
        keys={
            ("metriplane-health", "metriplane-health"): bytes.fromhex(
                program["attestor_public_key_hex"]
            )
        }
    ).verify(attestor, subject_digest=partial["subject_digest"]):
        raise DelegationError("isolated task attestor signature is not trusted")
    delegate_signature = {
        "provider": "codex_goal",
        "actor_id": EXECUTOR_ID,
        "key_id": program["delegate_key_id"],
        "signature": sign_envelope(
            private_key_path,
            provider="codex_goal",
            actor_id=EXECUTOR_ID,
            subject_digest=partial["subject_digest"],
        ).hex(),
    }
    result = dict(partial)
    result["delegate_signature"] = delegate_signature
    validate_delegated_task(
        result,
        authority,
        catalog,
        snapshot,
        task_id=scope.get("task_id"),
        linear_issue=scope.get("linear_issue"),
        repository=REPOSITORY,
        project_id=PROJECT_ID,
        base_sha=scope.get("base_sha"),
        base_tree=scope.get("base_tree"),
        grantor_id=OWNER_ID,
        executor_id=EXECUTOR_ID,
        evaluated_at=evaluated_at,
        live=live,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attested-request", type=Path, required=True)
    parser.add_argument("--linear-snapshot", type=Path, required=True)
    parser.add_argument("--authority-keyring", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--delegate-key", type=Path, required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--fixture-mode", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = complete(
            partial=_read(args.attested_request),
            snapshot=_read(args.linear_snapshot),
            authority=_read(args.authority_keyring),
            catalog=_read(args.catalog),
            private_key_path=args.delegate_key,
            evaluated_at=args.evaluated_at,
            live=not args.fixture_mode,
        )
        descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(result))
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError) as exc:
        print(f"delegated task completion blocked: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
