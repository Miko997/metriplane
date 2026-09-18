# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Only disposable fixture keys are used; no owner credential is opened."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.ed25519_envelope import EnvelopeSigningError
from tools.prepare_program_delegation import prepare_grant
from tools.program_delegation import validate_program_grant
from tools.task_delegation import DelegationError

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "docs/status/task-work-orders.json").read_bytes())
OWNER = "96778fbb-c8ff-42b3-9217-7cac45dcd097"
EXECUTOR = "01a096e0-4e21-7a11-9f0f-fb303387c5c0"
PROJECT = "cf53f98f-0965-4360-a66e-530457e40354"
REPOSITORY = "Miko997/metriplane"
ISSUED = "2026-09-18T12:00:00Z"
EXPIRES = "2026-10-18T12:00:00Z"
PASSPHRASE = "disposable-test-only-passphrase"


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    key = tmp_path / "disposable-owner.pem"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "ED25519",
            "-aes-256-cbc",
            "-pass",
            f"pass:{PASSPHRASE}",
            "-out",
            str(key),
        ],
        check=True,
        capture_output=True,
    )
    public_der = subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(key),
            "-passin",
            f"pass:{PASSPHRASE}",
            "-pubout",
            "-outform",
            "DER",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert public_der[:12].hex() == "302a300506032b6570032100"
    public = public_der[12:]
    authority = {
        "schema_version": "metriplane.task-delegation-authority.v1",
        "keys": [
            {
                "key_id": hashlib.sha256(public).hexdigest(),
                "provider": "linear",
                "actor_id": OWNER,
                "public_key_hex": public.hex(),
                "role": "repository_owner",
                "repository": REPOSITORY,
                "project_id": PROJECT,
                "not_before": "2026-09-18T00:00:00Z",
                "not_after": "2027-09-18T00:00:00Z",
                "status": "active",
                "trust_class": "production",
            }
        ],
        "revoked_delegation_ids": [],
    }
    return key, authority


def _prepare(key: Path, authority: dict, **overrides: object) -> dict:
    args = {
        "authority": authority,
        "catalog": CATALOG,
        "delegate_public_key_hex": "11" * 32,
        "attestor_public_key_hex": "22" * 32,
        "owner_key": key,
        "issued_at": ISSUED,
        "expires_at": EXPIRES,
        "passphrase": PASSPHRASE,
    }
    args.update(overrides)
    return prepare_grant(**args)


def test_encrypted_fixture_key_prepares_exact_scope_and_verified_signature(tmp_path: Path) -> None:
    key, authority = _fixture(tmp_path)
    grant = _prepare(key, authority)
    assert grant["synthetic"] is False
    assert grant["subject"]["scope"]["task_ids"] == sorted(
        row["task_id"]
        for row in CATALOG["tasks"]
        if row["first_required_release"] == "v0.5" and row["role"] == "implementation"
    )
    assert "MP2-049" not in grant["subject"]["scope"]["task_ids"]
    assert (
        grant["subject"]["delegate"]["public_key_hex"]
        != grant["subject"]["attestor"]["public_key_hex"]
    )
    validate_program_grant(
        grant,
        authority,
        CATALOG,
        repository=REPOSITORY,
        project_id=PROJECT,
        grantor_id=OWNER,
        executor_id=EXECUTOR,
        evaluated_at=ISSUED,
        live=True,
    )
    changed = copy.deepcopy(grant)
    changed["subject"]["scope"]["repository"] = "other/repository"
    with pytest.raises(DelegationError):
        validate_program_grant(
            changed,
            authority,
            CATALOG,
            repository=REPOSITORY,
            project_id=PROJECT,
            grantor_id=OWNER,
            executor_id=EXECUTOR,
            evaluated_at=ISSUED,
            live=True,
        )


def test_wrong_passphrase_never_produces_a_grant(tmp_path: Path) -> None:
    key, authority = _fixture(tmp_path)
    with pytest.raises(EnvelopeSigningError, match="signing failed"):
        _prepare(key, authority, passphrase="not-the-fixture-passphrase")
    with pytest.raises(EnvelopeSigningError, match="passphrase is invalid"):
        _prepare(key, authority, passphrase="x" * 8192)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delegate_public_key_hex", "gg" * 32),
        ("attestor_public_key_hex", "11" * 32),
        ("expires_at", "2028-01-01T00:00:00Z"),
    ],
)
def test_invalid_scope_or_key_is_rejected(tmp_path: Path, field: str, value: str) -> None:
    key, authority = _fixture(tmp_path)
    with pytest.raises((DelegationError, ValueError)):
        _prepare(key, authority, **{field: value})


def test_revoked_owner_key_is_rejected_without_output(tmp_path: Path) -> None:
    key, authority = _fixture(tmp_path)
    authority["keys"][0]["status"] = "revoked"
    with pytest.raises(DelegationError, match="approved production owner key is absent"):
        _prepare(key, authority)
