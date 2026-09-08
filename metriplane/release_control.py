# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Deterministic, fail-closed release qualification primitives.

The module owns the cumulative release state machine.  Command-line tools are
thin adapters around these primitives; publication remains a consumer of a
closed qualification record and never creates release authority itself.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

MILESTONES: Final[tuple[str, ...]] = (
    "v0.4",
    "v0.5",
    "v0.6",
    "v0.7",
    "v0.8",
    "v0.9",
    "v1.0",
)
STAGES: Final[tuple[str, ...]] = (
    "roles",
    "task-state",
    "staging",
    "targets",
    "predecessor",
    "source-freeze",
    "candidate",
    "qualification",
    "approval",
    "prepromotion",
    "promotion",
    "reconciliation",
    "retention",
    "closed",
)
TERMINAL_RESULTS: Final[frozenset[str]] = frozenset(
    {"PASS", "FAIL", "BLOCKED", "CANCELLED", "SKIPPED"}
)
RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "data",
        "invocation_id",
        "payload_digest",
        "record_id",
        "record_type",
        "schema_version",
        "sequence",
        "signatures",
        "status",
        "synthetic",
    }
)
RECORD_VERSION: Final[str] = "metriplane.release-record.v1"
AUTHORITY_POLICY_VERSION: Final[str] = "metriplane.release-authority-policy.v1"
RELEASE_TARGETS_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "docs/status/release-targets.json"
)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_INVOCATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")
_NODE_ED25519_VERIFY = r"""
const crypto = require("node:crypto");
const fs = require("node:fs");
const [publicKeyHex, signatureHex] = process.argv.slice(1);
try {
  if (!/^[0-9a-f]{64}$/.test(publicKeyHex) || !/^[0-9a-f]{128}$/.test(signatureHex)) {
    process.exit(2);
  }
  const publicKeyDer = Buffer.concat([
    Buffer.from("302a300506032b6570032100", "hex"),
    Buffer.from(publicKeyHex, "hex"),
  ]);
  const publicKey = crypto.createPublicKey({key: publicKeyDer, format: "der", type: "spki"});
  const valid = crypto.verify(
    null,
    fs.readFileSync(0),
    publicKey,
    Buffer.from(signatureHex, "hex"),
  );
  process.exit(valid ? 0 : 1);
} catch {
  process.exit(2);
}
"""


class ReleaseControlError(ValueError):
    """A release operation cannot proceed without weakening its contract."""


def _verify_ed25519_with_node(
    public_key: bytes,
    signature: bytes,
    message: bytes,
) -> bool:
    """Use the GitHub runner's built-in Node crypto when Python crypto is absent."""

    node = shutil.which("node")
    if node is None:
        return False
    try:
        completed = subprocess.run(
            [node, "--eval", _NODE_ED25519_VERIFY, public_key.hex(), signature.hex()],
            input=message,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


@dataclass(frozen=True)
class ProviderAttestationVerifier:
    """Verify Ed25519 provider attestations against a public trust root."""

    keys: Mapping[tuple[str, str], bytes]
    keyring_digest: str | None = None

    @classmethod
    def from_keyring(
        cls,
        path: Path,
        *,
        expected_digest: str | None = None,
    ) -> ProviderAttestationVerifier:
        keyring = read_json(path)
        if set(keyring) != {"keys", "schema_version"} or keyring["schema_version"] != (
            "metriplane.provider-attestation-keyring.v1"
        ):
            raise ReleaseControlError("provider attestation keyring shape is not closed")
        rows = keyring["keys"]
        if not isinstance(rows, list) or not rows:
            raise ReleaseControlError("provider attestation keyring has no trusted keys")
        expected_fields = {"actor_id", "provider", "public_key_hex"}
        parsed: dict[tuple[str, str], bytes] = {}
        identities: list[tuple[str, str]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != expected_fields:
                raise ReleaseControlError("provider attestation key row shape is not closed")
            provider = row["provider"]
            actor_id = row["actor_id"]
            public_key_hex = row["public_key_hex"]
            if not isinstance(provider, str) or provider not in {"github", "linear"}:
                raise ReleaseControlError("provider attestation key names an unsupported provider")
            _require_nonempty_string(actor_id, "provider attestation key actor")
            if (
                not isinstance(public_key_hex, str)
                or re.fullmatch(r"[0-9a-f]{64}", public_key_hex) is None
            ):
                raise ReleaseControlError(
                    "provider attestation public key is not canonical Ed25519 hex"
                )
            identity = (provider, actor_id)
            if identity in parsed:
                raise ReleaseControlError("provider attestation key identity is duplicated")
            parsed[identity] = bytes.fromhex(public_key_hex)
            identities.append(identity)
        if identities != sorted(identities):
            raise ReleaseControlError("provider attestation keys are not canonically ordered")
        keyring_digest = sha256_json(keyring)
        if expected_digest is not None and keyring_digest != _require_digest(
            expected_digest, "provider attestation keyring"
        ):
            raise ReleaseControlError("provider attestation keyring digest mismatch")
        return cls(keys=parsed, keyring_digest=keyring_digest)

    def verify(self, signature: Mapping[str, Any], *, subject_digest: str) -> bool:
        provider = signature.get("provider")
        actor_id = signature.get("actor_id")
        if not isinstance(provider, str) or not isinstance(actor_id, str):
            return False
        key = self.keys.get((provider, actor_id))
        signature_value = signature.get("signature")
        if (
            key is None
            or len(key) != 32
            or not isinstance(signature_value, str)
            or re.fullmatch(r"[0-9a-f]{128}", signature_value) is None
        ):
            return False
        message = canonical_json(
            {
                "actor_id": actor_id,
                "provider": provider,
                "subject_digest": subject_digest,
            }
        )
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
        except ImportError:
            return _verify_ed25519_with_node(
                key,
                bytes.fromhex(signature_value),
                message,
            )
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(bytes.fromhex(signature_value), message)
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True


def canonical_json(value: object) -> bytes:
    """Return the one canonical JSON representation used for release identity."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseControlError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_bytes(canonical_json(value))


RELEASE_BUILD_RECIPE: Final[Mapping[str, Any]] = {
    "artifact_count": 2,
    "build": [
        "python",
        "-m",
        "build",
        "--no-isolation",
        "--sdist",
        "--wheel",
        "--outdir",
        "<out-dir>",
        "<source-dir>",
    ],
    "backend": "setuptools.build_meta",
    "toolchain": {"build": "1.5.0", "setuptools": "82.0.1", "twine": "6.2.0"},
    "uv": "0.12.0",
    "python": ["3.12", "3.13"],
    "fingerprint": [
        "tools.release_artifacts.create_manifest",
        "tools.release_artifacts.verify_manifest",
    ],
    "inspect": "tools.release_artifacts.inspect_sdist",
    "schema_version": "metriplane.release-artifact-build-recipe.v1",
    "twine": ["python", "-m", "twine", "check", "--strict", "<artifacts>"],
}
RELEASE_BUILD_RECIPE_DIGEST: Final[str] = sha256_json(RELEASE_BUILD_RECIPE)
_SOURCE_REGISTRY_INPUTS: Final[Mapping[str, str]] = {
    "environment_registry_digest": "docs/status/supported-environments.json",
    "evidence_store_registry_digest": "docs/status/release-evidence-stores.json",
    "obligation_registry_digest": "docs/status/release-test-obligations.json",
    "readiness_registry_digest": "docs/status/release-readiness.json",
    "scenario_registry_digest": "docs/status/release-scenarios.json",
    "target_registry_digest": "docs/status/release-targets.json",
    "task_state_policy_digest": "docs/status/release-task-state-policy.json",
}
_SOURCE_VERSION_PATHS: Final[tuple[str, ...]] = (
    "metriplane/__init__.py",
    "pyproject.toml",
    "uv.lock",
)


def release_authority_policy_digest(provider_attestation_keyring_digest: str) -> str:
    """Return the protected policy identity for one immutable provider keyring."""

    keyring_digest = _require_digest(
        provider_attestation_keyring_digest,
        "provider attestation keyring",
    )
    return sha256_json(
        {
            "provider_attestation_keyring_digest": keyring_digest,
            "schema_version": AUTHORITY_POLICY_VERSION,
        }
    )


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ReleaseControlError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_invocation(value: object) -> str:
    if not isinstance(value, str) or _INVOCATION.fullmatch(value) is None:
        raise ReleaseControlError("invocation_id is missing or invalid")
    return value


def _closed_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseControlError(f"JSON input repeats a key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    """Read one regular JSON object without following a symlink."""

    if not path.is_file() or path.is_symlink():
        raise ReleaseControlError(f"input is missing or not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_closed_json_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseControlError(f"cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseControlError(f"JSON input must be an object: {path}")
    return value


def write_immutable_json(path: Path, value: object) -> str:
    """Create canonical JSON exactly once and return its byte digest."""

    payload = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except FileExistsError as exc:
        raise ReleaseControlError(f"refusing to overwrite retained output: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return sha256_bytes(payload)


def make_record(
    record_type: str,
    data: Mapping[str, Any],
    *,
    invocation_id: str,
    sequence: int,
    synthetic: bool,
    status: str = "PASS",
    signatures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Create a digest-bound release record with no implicit clock input."""

    if not record_type.startswith("release-") and record_type not in {
        "linear-release-snapshot",
        "provider-run-termination",
    }:
        raise ReleaseControlError(f"invalid release record type: {record_type!r}")
    _require_invocation(invocation_id)
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ReleaseControlError("sequence must be a positive integer")
    if not isinstance(status, str) or status not in TERMINAL_RESULTS | {
        "OPEN",
        "READY",
        "INVALIDATED",
    }:
        raise ReleaseControlError(f"invalid release status: {status!r}")
    normalized_signatures = [dict(signature) for signature in signatures]
    body: dict[str, Any] = {
        "data": dict(data),
        "invocation_id": invocation_id,
        "payload_digest": sha256_json(data),
        "record_type": record_type,
        "schema_version": RECORD_VERSION,
        "sequence": sequence,
        "signatures": normalized_signatures,
        "status": status,
        "synthetic": synthetic,
    }
    body["record_id"] = sha256_json(body)
    return body


def validate_record(record: Mapping[str, Any], expected_type: str | None = None) -> None:
    """Validate the closed record envelope and all digest bindings."""

    if set(record) != RECORD_KEYS:
        missing = sorted(RECORD_KEYS - set(record))
        extra = sorted(set(record) - RECORD_KEYS)
        raise ReleaseControlError(
            f"release record shape mismatch; missing={missing}; extra={extra}"
        )
    if record["schema_version"] != RECORD_VERSION:
        raise ReleaseControlError("unsupported release record schema version")
    if expected_type is not None and record["record_type"] != expected_type:
        raise ReleaseControlError(
            f"record type is {record['record_type']!r}, expected {expected_type!r}"
        )
    if not isinstance(record["data"], dict):
        raise ReleaseControlError("release record data must be an object")
    if record["payload_digest"] != sha256_json(record["data"]):
        raise ReleaseControlError("release record payload digest mismatch")
    _require_invocation(record["invocation_id"])
    if isinstance(record["sequence"], bool) or not isinstance(record["sequence"], int):
        raise ReleaseControlError("release record sequence must be an integer")
    if record["sequence"] < 1:
        raise ReleaseControlError("release record sequence must be positive")
    if not isinstance(record["synthetic"], bool):
        raise ReleaseControlError("release record synthetic flag must be boolean")
    if not isinstance(record["signatures"], list):
        raise ReleaseControlError("release record signatures must be an array")
    status = record["status"]
    if not isinstance(status, str) or status not in TERMINAL_RESULTS | {
        "OPEN",
        "READY",
        "INVALIDATED",
    }:
        raise ReleaseControlError("release record has an invalid status")
    claimed_id = _require_digest(record["record_id"], "record_id")
    unsigned = dict(record)
    del unsigned["record_id"]
    if claimed_id != sha256_json(unsigned):
        raise ReleaseControlError("release record identity mismatch")


def signature_subject_digest(record: Mapping[str, Any]) -> str:
    """Bind authority to the complete decision envelope, excluding signatures."""

    fields = (
        "data",
        "invocation_id",
        "payload_digest",
        "record_type",
        "schema_version",
        "sequence",
        "status",
        "synthetic",
    )
    if any(field not in record for field in fields):
        raise ReleaseControlError("signature subject record is incomplete")
    return sha256_json({field: record[field] for field in fields})


def _validated_signature(
    signature: Mapping[str, Any],
    *,
    subject_digest: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> tuple[str, str]:
    exact = {"actor_id", "algorithm", "provider", "signature", "subject_digest", "synthetic"}
    if not isinstance(signature, Mapping):
        raise ReleaseControlError("signature is not an object")
    if set(signature) != exact:
        raise ReleaseControlError("signature shape is not closed")
    if signature["subject_digest"] != subject_digest:
        raise ReleaseControlError("signature is not bound to the decision envelope")
    actor_id = signature["actor_id"]
    if not isinstance(actor_id, str) or not actor_id:
        raise ReleaseControlError("signature actor is missing")
    algorithm = signature["algorithm"]
    if not isinstance(algorithm, str) or algorithm not in {
        "provider-attestation-v1",
        "test-sha256-v1",
    }:
        raise ReleaseControlError("signature algorithm is not allowed")
    provider = signature["provider"]
    if not isinstance(provider, str):
        raise ReleaseControlError("signature provider is invalid")
    synthetic = signature["synthetic"]
    if not isinstance(synthetic, bool):
        raise ReleaseControlError("signature synthetic flag must be boolean")
    signature_value = signature["signature"]
    if not isinstance(signature_value, str) or len(signature_value) < 16:
        raise ReleaseControlError("signature value is missing")
    if live:
        if synthetic is not False:
            raise ReleaseControlError("synthetic signatures cannot authorize live release work")
        if provider not in {"github", "linear"}:
            raise ReleaseControlError("live signatures require provider authority")
        if algorithm != "provider-attestation-v1":
            raise ReleaseControlError("test signatures cannot authorize live release work")
        if attestation_verifier is None:
            raise ReleaseControlError("live provider attestation has no trusted verifier")
        if attestation_verifier.keyring_digest is None:
            raise ReleaseControlError("live provider attestation trust root has no digest identity")
        if not attestation_verifier.verify(signature, subject_digest=subject_digest):
            raise ReleaseControlError("live provider attestation authentication failed")
        return provider, actor_id
    if (
        synthetic is not True
        or provider != "test-fixture"
        or algorithm != "test-sha256-v1"
        or signature_value != sha256_json({"actor_id": actor_id, "subject_digest": subject_digest})
    ):
        raise ReleaseControlError("synthetic signature authentication failed")
    return provider, actor_id


def _validated_record_signers(
    record: Mapping[str, Any],
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> set[tuple[str, str]]:
    signatures = record["signatures"]
    if live and not signatures:
        raise ReleaseControlError("live release authority has no authenticated signature")
    return {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in signatures
    }


def _parse_utc_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReleaseControlError(f"{label} is not a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReleaseControlError(f"{label} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ReleaseControlError(f"{label} is not a UTC timestamp")
    return parsed


def _role_binding_identity(
    value: object,
    *,
    expected_role: str,
    label: str,
) -> tuple[tuple[str, str], tuple[str, str]]:
    fields = {
        "actor_id",
        "backup_actor_id",
        "conflict_free",
        "provenance_digest",
        "provider",
        "role",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseControlError(f"{label} role binding shape is not closed")
    if value["role"] != expected_role or value["conflict_free"] is not True:
        raise ReleaseControlError(f"{label} role binding is not conflict-free authority")
    provider = value["provider"]
    if not isinstance(provider, str) or provider not in {"github", "linear"}:
        raise ReleaseControlError(f"{label} role binding provider is invalid")
    actor_id = _require_nonempty_string(value["actor_id"], f"{label} actor")
    backup_actor_id = _require_nonempty_string(
        value["backup_actor_id"],
        f"{label} backup actor",
    )
    _require_digest(value["provenance_digest"], f"{label} provenance")
    primary = (provider, actor_id)
    backup = (provider, backup_actor_id)
    if primary == backup:
        raise ReleaseControlError(f"{label} primary and backup authority are identical")
    return primary, backup


def validate_role_assignments(
    record: Mapping[str, Any],
    *,
    live: bool,
    expected_milestone: str | None = None,
    expected_run_id: str | None = None,
    expected_authority_policy_digest: str | None = None,
    check_conflicts: bool = False,
    check_freshness: bool = False,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, tuple[str, str]]:
    validate_record(record, "release-role-assignments")
    if record["status"] != "PASS":
        raise ReleaseControlError("release role assignments are not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic role assignments cannot authorize a live release")
    data = record["data"]
    required = {
        "author_id",
        "authorized_executor_id",
        "non_author_reviewer_id",
        "publisher_id",
        "task_id",
    }
    optional = {"milestone", "run_id", "valid_from", "valid_until"}
    live_fields = {
        "author_provider",
        "authority_policy_digest",
        "independent_assurance",
        "infrastructure_owner",
        "non_author_reviewer",
        "operator",
        "provider_attestation_keyring_digest",
        "publisher",
        "signing_method",
    }
    if (
        not required <= set(data) <= required | optional | live_fields
        or data["task_id"] != "MP2-007"
    ):
        raise ReleaseControlError("release role assignment shape or task binding is invalid")
    actor_ids: dict[str, str] = {}
    for key in required - {"task_id"}:
        actor = data[key]
        if not isinstance(actor, str) or not actor:
            raise ReleaseControlError(f"role {key} has no actor")
        actor_ids[key] = actor

    actors: dict[str, tuple[str, str]]
    authority_identities: list[tuple[str, str]] = []
    if live:
        required_live = live_fields | optional
        if not required_live <= set(data):
            raise ReleaseControlError("live release role assignment is incomplete")
        if data["signing_method"] != "provider-attestation-v1":
            raise ReleaseControlError("live release role signing method is invalid")
        keyring_digest = _require_digest(
            data["provider_attestation_keyring_digest"],
            "release role provider attestation keyring",
        )
        policy_digest = _require_digest(
            data["authority_policy_digest"],
            "release role authority policy",
        )
        if expected_authority_policy_digest is None:
            raise ReleaseControlError("live release role authority policy identity is not supplied")
        if policy_digest != _require_digest(
            expected_authority_policy_digest,
            "expected release authority policy",
        ):
            raise ReleaseControlError("release role authority policy binding mismatch")
        if attestation_verifier is None or attestation_verifier.keyring_digest is None:
            raise ReleaseControlError("live release role trust-root identity is not supplied")
        if keyring_digest != attestation_verifier.keyring_digest:
            raise ReleaseControlError("release role provider keyring binding mismatch")
        if policy_digest != release_authority_policy_digest(keyring_digest):
            raise ReleaseControlError("release role authority policy does not bind its keyring")

        author_provider = data["author_provider"]
        if not isinstance(author_provider, str) or author_provider not in {"github", "linear"}:
            raise ReleaseControlError("release author provider is invalid")
        operator, operator_backup = _role_binding_identity(
            data["operator"], expected_role="release_operator", label="operator"
        )
        reviewer, reviewer_backup = _role_binding_identity(
            data["non_author_reviewer"],
            expected_role="non_author_reviewer",
            label="non-author reviewer",
        )
        infrastructure_owner, infrastructure_backup = _role_binding_identity(
            data["infrastructure_owner"],
            expected_role="infrastructure_owner",
            label="infrastructure owner",
        )
        publisher, publisher_backup = _role_binding_identity(
            data["publisher"], expected_role="publisher", label="publisher"
        )
        if (
            operator[1] != actor_ids["authorized_executor_id"]
            or reviewer[1] != actor_ids["non_author_reviewer_id"]
            or publisher[1] != actor_ids["publisher_id"]
        ):
            raise ReleaseControlError("release role binding disagrees with its actor identity")
        assurance = data["independent_assurance"]
        assurance_identities: list[tuple[str, str]] = []
        if not isinstance(assurance, Mapping):
            raise ReleaseControlError("independent assurance assignment is invalid")
        if set(assurance) == {"applicability"} and assurance["applicability"] == "not_applicable":
            pass
        elif (
            set(assurance) == {"applicability", "binding"}
            and assurance["applicability"] == "required"
        ):
            assurance_identities.extend(
                _role_binding_identity(
                    assurance["binding"],
                    expected_role="independent_assurance_verifier",
                    label="independent assurance",
                )
            )
        else:
            raise ReleaseControlError("independent assurance assignment shape is not closed")
        actors = {
            "author_id": (author_provider, actor_ids["author_id"]),
            "authorized_executor_id": operator,
            "non_author_reviewer_id": reviewer,
            "publisher_id": publisher,
        }
        authority_identities = [
            *actors.values(),
            operator_backup,
            reviewer_backup,
            infrastructure_owner,
            infrastructure_backup,
            publisher_backup,
            *assurance_identities,
        ]
    else:
        actors = {key: ("test-fixture", actor_id) for key, actor_id in actor_ids.items()}

    if actors["author_id"] == actors["non_author_reviewer_id"]:
        raise ReleaseControlError("the release author cannot be the non-author reviewer")
    if expected_milestone is not None and data.get("milestone") != expected_milestone:
        raise ReleaseControlError("release role assignment milestone binding mismatch")
    if expected_run_id is not None and data.get("run_id") != expected_run_id:
        raise ReleaseControlError("release role assignment run binding mismatch")
    if check_conflicts:
        if actors["non_author_reviewer_id"] in {
            actors["author_id"],
            actors["authorized_executor_id"],
            actors["publisher_id"],
        }:
            raise ReleaseControlError("release role assignment reviewer has an actor conflict")
        if live and len(authority_identities) != len(set(authority_identities)):
            raise ReleaseControlError("release role assignment contains an authority conflict")
    if check_freshness:
        valid_from = _parse_utc_timestamp(data.get("valid_from"), "role validity start")
        valid_until = _parse_utc_timestamp(data.get("valid_until"), "role validity end")
        now = datetime.now(UTC)
        if valid_until <= valid_from or not valid_from <= now < valid_until:
            raise ReleaseControlError("release role assignment is outside its validity window")
    signers = {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in record["signatures"]
    }
    if live and actors["authorized_executor_id"] not in signers:
        raise ReleaseControlError("authorized executor lacks a digest-bound live delegation")
    return actors


def validate_approval(
    record: Mapping[str, Any],
    roles: Mapping[str, tuple[str, str]],
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    """Require a conflict-free, digest-bound decision by a distinct reviewer."""

    validate_record(record, "release-approval")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic approval cannot authorize a live release")
    data = record["data"]
    expected = {"author_id", "candidate_digest", "conflicts", "decision", "reviewer_id"}
    if set(data) != expected:
        raise ReleaseControlError("release approval shape is not closed")
    _require_digest(data["candidate_digest"], "candidate_digest")
    if data["decision"] != "APPROVED" or data["conflicts"] != []:
        raise ReleaseControlError("release approval is not conflict-free and approved")
    author_identity = roles["author_id"]
    reviewer_identity = roles["non_author_reviewer_id"]
    if data["author_id"] != author_identity[1]:
        raise ReleaseControlError("approval author does not match the role assignment")
    reviewer = data["reviewer_id"]
    if reviewer_identity == author_identity or reviewer != reviewer_identity[1]:
        raise ReleaseControlError("approval is not from the assigned non-author reviewer")
    signers = {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in record["signatures"]
    }
    if reviewer_identity not in signers:
        raise ReleaseControlError("approval lacks the reviewer's digest-bound signature")


def validate_task_state_observation(
    record: Mapping[str, Any],
    roles: Mapping[str, tuple[str, str]],
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    """Require the assigned live executor and an allowed implementation state."""

    validate_record(record, "release-task-state-observation")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic task state cannot authorize live release work")
    data = record["data"]
    if set(data) != {"assignee_id", "issue_id", "state", "task_id"}:
        raise ReleaseControlError("release task-state observation shape is not closed")
    if data["issue_id"] != "MET-154" or data["task_id"] != "MP2-007":
        raise ReleaseControlError("release task-state observation names the wrong task")
    if data["state"] != "In Progress":
        raise ReleaseControlError("release task is not in an executable state")
    executor_identity = roles["authorized_executor_id"]
    if data["assignee_id"] != executor_identity[1]:
        raise ReleaseControlError("release task assignee is not the authorized executor")
    signers = {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in record["signatures"]
    }
    if live and executor_identity not in signers:
        raise ReleaseControlError("live task state lacks provider-authenticated assignee proof")


def validate_cumulative_milestones(milestones: Sequence[str]) -> None:
    if tuple(milestones) != MILESTONES:
        raise ReleaseControlError("release milestones must be the cumulative v0.4 through v1.0 set")


def new_attempt(
    *,
    milestone: str,
    version: str,
    candidate_digest: str,
    predecessor_digest: str,
) -> dict[str, Any]:
    if milestone not in MILESTONES:
        raise ReleaseControlError(f"unknown cumulative release milestone: {milestone}")
    if not version.startswith(f"{milestone}."):
        raise ReleaseControlError("candidate version must be a patch in its declared milestone")
    return {
        "candidate_digest": _require_digest(candidate_digest, "candidate_digest"),
        "events": [],
        "milestone": milestone,
        "predecessor_digest": _require_digest(predecessor_digest, "predecessor_digest"),
        "version": version,
    }


def advance_attempt(
    attempt: Mapping[str, Any],
    *,
    stage: str,
    result: str,
    evidence_digest: str,
) -> dict[str, Any]:
    """Advance exactly one stage; failed stages terminalize the attempt."""

    if stage not in STAGES:
        raise ReleaseControlError(f"unknown release stage: {stage}")
    if result not in TERMINAL_RESULTS:
        raise ReleaseControlError("release stage result is not terminal")
    events = attempt.get("events")
    if not isinstance(events, list):
        raise ReleaseControlError("release attempt events are invalid")
    if events and events[-1]["result"] != "PASS":
        raise ReleaseControlError("a terminalized failed release attempt cannot advance")
    expected = STAGES[len(events)] if len(events) < len(STAGES) else None
    if stage != expected:
        raise ReleaseControlError(f"release stage {stage!r} is out of order; expected {expected!r}")
    advanced = dict(attempt)
    advanced["events"] = [
        *events,
        {
            "evidence_digest": _require_digest(evidence_digest, "evidence_digest"),
            "result": result,
            "stage": stage,
        },
    ]
    return advanced


def record_target_burn(
    *, target: str, milestone: str, version: str, reason: str, observation_digest: str
) -> dict[str, str]:
    if milestone not in MILESTONES or not version.startswith(f"{milestone}."):
        raise ReleaseControlError("burn target version is outside its milestone")
    if not target or not reason:
        raise ReleaseControlError("a target burn requires target and reason")
    return {
        "milestone": milestone,
        "observation_digest": _require_digest(observation_digest, "observation_digest"),
        "reason": reason,
        "target": target,
        "version": version,
    }


def resolve_burn_with_patch(burn: Mapping[str, str], patch_version: str) -> dict[str, str]:
    milestone = burn["milestone"]
    if patch_version == burn["version"] or not patch_version.startswith(f"{milestone}."):
        raise ReleaseControlError("a burn requires a new patch in the same milestone")
    resolved = dict(burn)
    resolved["resolution"] = "NEW_PATCH_REQUIRED"
    resolved["resolved_by"] = patch_version
    return resolved


def validate_predecessor(record: Mapping[str, Any], *, first_milestone: bool) -> None:
    validate_record(record, "release-predecessor")
    data = record["data"]
    required = {"candidate_milestone", "closed_decision_digest", "lkg_digest", "version"}
    if set(data) != required:
        raise ReleaseControlError("predecessor shape is not closed")
    _require_digest(data["lkg_digest"], "lkg_digest")
    _require_digest(data["closed_decision_digest"], "closed_decision_digest")
    if first_milestone and data["version"] != "v0.3.0":
        raise ReleaseControlError("v0.4 must resolve the actual v0.3.0 predecessor")
    if not first_milestone and data["candidate_milestone"] not in MILESTONES[1:]:
        raise ReleaseControlError("later release predecessor milestone is invalid")


def candidate_identity(
    *, source_digest: str, artifacts: Mapping[str, str], build_invocation_id: str
) -> dict[str, Any]:
    _require_invocation(build_invocation_id)
    source = _require_digest(source_digest, "source_digest")
    if not artifacts:
        raise ReleaseControlError("candidate identity requires immutable artifacts")
    normalized = {
        name: _require_digest(digest, f"artifact {name}")
        for name, digest in sorted(artifacts.items())
    }
    value: dict[str, Any] = {
        "artifacts": normalized,
        "build_invocation_id": build_invocation_id,
        "source_digest": source,
    }
    value["candidate_digest"] = sha256_json(value)
    return value


def finalize_cells(
    required_cells: Sequence[str], results: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    if not required_cells or len(required_cells) != len(set(required_cells)):
        raise ReleaseControlError("required release cells must be a nonempty unique list")
    if set(required_cells) != set(results):
        raise ReleaseControlError("release cell matrix is incomplete or contains extras")
    cells: list[dict[str, str]] = []
    for cell in required_cells:
        result = results[cell]
        if set(result) != {"evidence_digest", "result"}:
            raise ReleaseControlError(f"release cell {cell} shape is not closed")
        if result["result"] not in TERMINAL_RESULTS:
            raise ReleaseControlError(f"release cell {cell} is not terminal")
        cells.append(
            {
                "cell": cell,
                "evidence_digest": _require_digest(
                    result["evidence_digest"], f"release cell {cell} evidence"
                ),
                "result": result["result"],
            }
        )
    return {"cells": cells, "ready": all(cell["result"] == "PASS" for cell in cells)}


def build_promotion_plan(
    *,
    candidate_digest: str,
    approval_digest: str,
    controls_digest: str,
    target_state_digest: str,
    attempt_index_epoch: int,
    publisher_id: str,
    publisher_actions: Sequence[str],
    expires_at: int,
) -> dict[str, Any]:
    """Bind every promotion input before any publisher action can run."""

    if attempt_index_epoch < 0 or expires_at < 1:
        raise ReleaseControlError("promotion checkpoint and expiry are invalid")
    if (
        not publisher_id
        or not publisher_actions
        or len(publisher_actions) != len(set(publisher_actions))
    ):
        raise ReleaseControlError("promotion publisher actions must be nonempty and unique")
    plan: dict[str, Any] = {
        "approval_digest": _require_digest(approval_digest, "approval_digest"),
        "attempt_index_epoch": attempt_index_epoch,
        "candidate_digest": _require_digest(candidate_digest, "candidate_digest"),
        "controls_digest": _require_digest(controls_digest, "controls_digest"),
        "expires_at": expires_at,
        "publisher_actions": list(publisher_actions),
        "publisher_id": publisher_id,
        "target_state_digest": _require_digest(target_state_digest, "target_state_digest"),
    }
    plan["plan_digest"] = sha256_json(plan)
    return plan


def validate_promotion_plan(
    plan: Mapping[str, Any],
    *,
    now: int,
    candidate_digest: str,
    approval_digest: str,
    publisher_id: str,
) -> None:
    exact = {
        "approval_digest",
        "attempt_index_epoch",
        "candidate_digest",
        "controls_digest",
        "expires_at",
        "plan_digest",
        "publisher_actions",
        "publisher_id",
        "target_state_digest",
    }
    if set(plan) != exact:
        raise ReleaseControlError("promotion plan shape is not closed")
    unsigned = dict(plan)
    claimed = unsigned.pop("plan_digest")
    if claimed != sha256_json(unsigned):
        raise ReleaseControlError("promotion plan digest mismatch")
    if plan["candidate_digest"] != candidate_digest or plan["approval_digest"] != approval_digest:
        raise ReleaseControlError("promotion plan is bound to different release authority")
    if plan["publisher_id"] != publisher_id:
        raise ReleaseControlError("promotion plan names a different publisher")
    if not isinstance(plan["expires_at"], int) or plan["expires_at"] <= now:
        raise ReleaseControlError("promotion plan is expired")


def validate_lkg_invalidation(
    record: Mapping[str, Any],
    roles: Mapping[str, tuple[str, str]],
    *,
    live: bool,
    candidate_digest: str,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    """Fence an LKG only through a signed non-author contradiction decision."""

    validate_record(record, "release-approval-decision")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic invalidation cannot fence a live LKG")
    data = record["data"]
    required = {"author_id", "candidate_digest", "decision", "reason", "reviewer_id"}
    if set(data) != required or data["decision"] != "INVALIDATED" or not data["reason"]:
        raise ReleaseControlError("LKG invalidation decision is incomplete")
    if data["candidate_digest"] != candidate_digest:
        raise ReleaseControlError("LKG invalidation names a different candidate")
    author_identity = roles["author_id"]
    reviewer_identity = roles["non_author_reviewer_id"]
    if data["author_id"] != author_identity[1]:
        raise ReleaseControlError("LKG invalidation author does not match assigned roles")
    reviewer = data["reviewer_id"]
    if reviewer != reviewer_identity[1] or reviewer_identity == author_identity:
        raise ReleaseControlError("LKG invalidation is not a non-author decision")
    signers = {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in record["signatures"]
    }
    if reviewer_identity not in signers:
        raise ReleaseControlError("LKG invalidation lacks the reviewer's signature")


def append_cas_event(
    journal: Path,
    event: Mapping[str, Any],
    *,
    expected_epoch: int,
) -> dict[str, Any]:
    """Append one immutable journal event with an epoch compare-and-swap fence."""

    if expected_epoch < 0:
        raise ReleaseControlError("expected epoch cannot be negative")
    journal.mkdir(parents=True, exist_ok=True)
    existing = sorted(journal.glob("*.json"))
    actual_epoch = len(existing)
    record = dict(event)
    record["epoch"] = expected_epoch + 1
    if actual_epoch == expected_epoch + 1:
        committed = read_json(existing[-1])
        if committed == record:
            return committed
    if actual_epoch != expected_epoch:
        raise ReleaseControlError(
            f"compare-and-swap failed: expected epoch {expected_epoch}, actual {actual_epoch}"
        )
    path = journal / f"{expected_epoch + 1:08d}.json"
    write_immutable_json(path, record)
    return record


def acquire_promotion_lock(
    journal: Path,
    *,
    owner: str,
    expected_epoch: int,
    now: int,
    lease_seconds: int,
    dead_owner_proof: str | None = None,
) -> dict[str, Any]:
    if not owner or lease_seconds < 1:
        raise ReleaseControlError("promotion lock owner and positive lease are required")
    existing = sorted(journal.glob("*.json")) if journal.exists() else []
    if existing:
        latest = read_json(existing[-1])
        if int(latest["lease_until"]) > now:
            raise ReleaseControlError("promotion lock is still leased")
        if dead_owner_proof is None:
            raise ReleaseControlError("expired promotion lock requires dead-owner proof")
        _require_digest(dead_owner_proof, "dead_owner_proof")
    event: dict[str, Any] = {
        "dead_owner_proof": dead_owner_proof,
        "lease_until": now + lease_seconds,
        "owner": owner,
    }
    return append_cas_event(journal, event, expected_epoch=expected_epoch)


def require_lock_owner(journal: Path, *, owner: str, epoch: int, now: int) -> None:
    path = journal / f"{epoch:08d}.json"
    latest = sorted(journal.glob("*.json"))
    if not latest or latest[-1] != path:
        raise ReleaseControlError("promotion lock epoch is stale")
    record = read_json(path)
    if record["owner"] != owner or int(record["lease_until"]) <= now:
        raise ReleaseControlError("promotion lock does not authorize this mutation")


def reconcile_publication(
    candidate_artifacts: Mapping[str, str], observations: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    if set(candidate_artifacts) != set(observations):
        missing = sorted(set(candidate_artifacts) - set(observations))
        extra = sorted(set(observations) - set(candidate_artifacts))
        return {
            "conflicts": [{"extra": extra, "missing": missing, "type": "TARGET_SET"}],
            "ok": False,
        }
    conflicts: list[dict[str, str]] = []
    for target, expected_digest in sorted(candidate_artifacts.items()):
        _require_digest(expected_digest, f"candidate target {target}")
        observation = observations[target]
        if set(observation) != {"digest", "state"}:
            conflicts.append({"target": target, "type": "OBSERVATION_SHAPE"})
            continue
        if observation["state"] != "IMMUTABLE" or observation["digest"] != expected_digest:
            conflicts.append(
                {
                    "actual": observation["digest"],
                    "expected": expected_digest,
                    "state": observation["state"],
                    "target": target,
                    "type": "BYTE_MISMATCH",
                }
            )
    return {"conflicts": conflicts, "ok": not conflicts}


def retain_two_store_evidence(
    record: Mapping[str, Any],
    *,
    store_a: Path,
    store_b: Path,
    index_journal: Path,
    expected_index_epoch: int,
    recovery_output: Path | None = None,
    recovery_invocation_id: str | None = None,
    recovery_sequence: int = 1,
) -> dict[str, Any]:
    """Write, read, and hash-verify both stores before indexing the receipt."""

    validate_record(record)
    record_id = str(record["record_id"])
    receipts: list[dict[str, str]] = []
    try:
        for store_name, store in (("store-a", store_a), ("store-b", store_b)):
            path = store / f"{record_id}.json"
            expected_digest = sha256_json(record)
            if path.exists():
                if path.is_symlink() or sha256_json(read_json(path)) != expected_digest:
                    raise ReleaseControlError(f"{store_name} contains conflicting retained bytes")
                digest = expected_digest
            else:
                digest = write_immutable_json(path, record)
            if sha256_json(read_json(path)) != digest:
                raise ReleaseControlError(f"{store_name} read-back digest mismatch")
            receipts.append({"digest": digest, "store": store_name})
        if receipts[0]["digest"] != receipts[1]["digest"]:
            raise ReleaseControlError("independent evidence stores retained different bytes")
        index = append_cas_event(
            index_journal,
            {"receipts": receipts, "record_id": record_id},
            expected_epoch=expected_index_epoch,
        )
    except (OSError, ReleaseControlError) as exc:
        if recovery_output is not None:
            if recovery_invocation_id is None:
                raise ReleaseControlError("recovery output requires a new invocation id") from exc
            envelope = recovery_envelope(
                operation="retain-two-store-evidence",
                invocation_id=recovery_invocation_id,
                sequence=recovery_sequence,
                committed_digest=receipts[0]["digest"] if receipts else None,
                failure=str(exc),
            )
            write_immutable_json(recovery_output, envelope)
        raise
    return {"index": index, "receipts": receipts}


def recovery_envelope(
    *,
    operation: str,
    invocation_id: str,
    sequence: int,
    committed_digest: str | None,
    failure: str,
) -> dict[str, Any]:
    _require_invocation(invocation_id)
    if sequence < 1 or not operation or not failure:
        raise ReleaseControlError("recovery envelope fields are incomplete")
    if committed_digest is not None:
        _require_digest(committed_digest, "committed_digest")
    value: dict[str, Any] = {
        "committed_digest": committed_digest,
        "failure": failure,
        "invocation_id": invocation_id,
        "operation": operation,
        "sequence": sequence,
    }
    value["recovery_digest"] = sha256_json(value)
    return value


def audit_release_repository(repository: Path, *, live: bool) -> dict[str, Any]:
    """Audit the framework; live mode always names unresolved external authority."""

    required = [
        repository / ".github/workflows/release-required.yml",
        repository / "docs/status/release-readiness.json",
        repository / "docs/status/release-targets.json",
        repository / "docs/status/release-evidence-stores.json",
        repository / "metriplane/release_control.py",
    ]
    missing = [path.relative_to(repository).as_posix() for path in required if not path.is_file()]
    schemas = sorted((repository / "schemas").glob("metriplane.release-*.v1.schema.json"))
    blockers: list[dict[str, Any]] = []
    if missing:
        blockers.append({"code": "MISSING_FRAMEWORK_FILE", "paths": missing})
    if len(schemas) < 47:
        blockers.append({"code": "INCOMPLETE_RELEASE_SCHEMAS", "observed": len(schemas)})
    if live:
        blockers.extend(
            [
                {"code": "LIVE_NON_AUTHOR_APPROVAL_REQUIRED"},
                {"code": "EXTERNAL_TWO_STORE_READBACK_AND_CAS_PROOF_REQUIRED"},
                {"code": "HOSTED_PROTECTION_AND_REAL_MERGE_PROOF_REQUIRED"},
            ]
        )
    return {
        "blockers": blockers,
        "mode": "live" if live else "fixture",
        "schema_count": len(schemas),
        "status": "BLOCKED_NOT_READY" if blockers else "READY",
    }


def _release_input(
    path: Path,
    expected_type: str,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    record = read_json(path)
    validate_record(record, expected_type)
    if record["status"] not in {"PASS", "READY"}:
        raise ReleaseControlError(f"{expected_type} is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError(f"synthetic {expected_type} cannot satisfy a live release")
    _validated_record_signers(record, live=live, attestation_verifier=attestation_verifier)
    if expected_type in {"release-source-freeze", "release-artifact-manifest"}:
        producer = (
            "freeze_release_source.py"
            if expected_type == "release-source-freeze"
            else "build_release_artifacts.py"
        )
        validate_release_producer_journal(record, path, producer=producer)
    return record


def _release_data(
    record: Mapping[str, Any], expected_fields: set[str], label: str
) -> dict[str, Any]:
    data = record["data"]
    if not isinstance(data, dict) or set(data) != expected_fields:
        raise ReleaseControlError(f"{label} data shape is not closed")
    return data


def _passing_record(
    record: Mapping[str, Any],
    expected_type: str,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    validate_record(record, expected_type)
    if record["status"] != "PASS":
        raise ReleaseControlError(f"{expected_type} is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError(f"synthetic {expected_type} cannot authorize a live release")
    _validated_record_signers(record, live=live, attestation_verifier=attestation_verifier)
    data = record["data"]
    if not isinstance(data, dict):
        raise ReleaseControlError(f"{expected_type} data is not an object")
    return data


def _evidence_record_index(root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    if root.is_symlink() or not root.is_dir():
        raise ReleaseControlError("release evidence root is missing or unsafe")
    indexed: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(root)
        parent = root
        for part in relative.parts[:-1]:
            parent /= part
            if parent.is_symlink():
                raise ReleaseControlError(f"release evidence traverses a symlink: {path}")
        digest = _regular_file_digest(path)
        record = read_json(path)
        validate_record(record)
        indexed.setdefault(digest, []).append((path, record))
    return indexed


def _resolved_evidence_record(
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    digest: object,
    expected_type: str,
    label: str,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    required_digest = _require_digest(digest, label)
    matches = indexed.get(required_digest, ())
    if not matches:
        raise ReleaseControlError(f"{label} does not resolve to retained bytes")
    records: list[dict[str, Any]] = []
    for _path, candidate in matches:
        _passing_record(
            candidate,
            expected_type,
            live=live,
            attestation_verifier=attestation_verifier,
        )
        records.append(candidate)
    first = records[0]
    if any(candidate != first for candidate in records[1:]):
        raise ReleaseControlError(f"{label} resolves ambiguously")
    return first


def _candidate_record_for_digest(
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    candidate_digest: str,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for entries in indexed.values():
        for _path, record in entries:
            if record.get("record_type") != "release-candidate-identity":
                continue
            data = _passing_record(
                record,
                "release-candidate-identity",
                live=live,
                attestation_verifier=attestation_verifier,
            )
            if data.get("candidate_digest") == candidate_digest:
                matches.append(record)
    if len(matches) != 1:
        raise ReleaseControlError("qualification candidate identity does not resolve exactly once")
    return matches[0]


def _role_assignment_record_for_gate(
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    milestone = gate.get("milestone")
    run_id = gate.get("run_id")
    if not isinstance(milestone, str) or milestone not in MILESTONES:
        raise ReleaseControlError("approval gate milestone is invalid")
    _require_nonempty_string(run_id, "approval gate run id")
    matches: list[dict[str, Any]] = []
    for entries in indexed.values():
        for _path, record in entries:
            if record.get("record_type") != "release-role-assignments":
                continue
            role_data = record.get("data")
            if (
                isinstance(role_data, dict)
                and role_data.get("milestone") == milestone
                and role_data.get("run_id") == run_id
            ):
                matches.append(record)
    if len(matches) != 1:
        raise ReleaseControlError(
            "approval role assignments do not resolve exactly once for the gate run"
        )
    return matches[0]


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseControlError(f"{label} must be a nonempty string")
    return value


def _require_canonical_string_inventory(
    value: object, label: str, *, nonempty: bool = True
) -> list[str]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or value != sorted(set(value))
    ):
        raise ReleaseControlError(f"{label} is not a canonical string inventory")
    return value


_FINALIZER: Final[str] = "finalize_release_candidate_identity.py"
_CANDIDATE_VALIDATOR: Final[str] = "validate_release_candidate_identity.py"
_CANDIDATE_NAME: Final[str] = "candidate-identity.json"
_FINALIZATION_INPUTS: Final[Mapping[str, str]] = {
    "gate-input.json": "release-gate-input",
    "source-freeze.json": "release-source-freeze",
    "predecessor.json": "release-predecessor",
    "artifact-manifest.json": "release-artifact-manifest",
    "target-resolution.json": "release-target-resolution",
}
_CANDIDATE_FIELDS: Final[set[str]] = {
    "artifact_manifest_digest",
    "artifact_set_digest",
    "build_invocation_id",
    "candidate_digest",
    "evaluation_adoption_digest",
    "evaluation_adoption_mode",
    "gate_input_digest",
    "milestone",
    "package_version",
    "predecessor_digest",
    "release_tag",
    "source_freeze_digest",
    "finalization_intent_digest",
    "control_journal_locator",
    "final_directory",
}


def _canonical_absolute_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReleaseControlError(label + " is not an absolute canonical path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ReleaseControlError(label + " is not an absolute canonical path")
    return path


def _candidate_payload_digest(data: Mapping[str, Any]) -> str:
    return sha256_json(
        {k: v for k, v in data.items() if k not in {"candidate_digest", "final_directory"}}
    )


def _validate_candidate_predecessor(
    predecessor: Mapping[str, Any], gate: Mapping[str, Any]
) -> None:
    required = {"candidate_milestone", "closed_decision_digest", "lkg_digest", "version"}
    later = {
        "predecessor_milestone",
        "qualification_digest",
        "reconciliation_digest",
        "chain_head",
        "pointer_envelope_digest",
        "pointer_index_receipt_digest",
        "completion_digest",
    }
    milestone = gate["milestone"]
    if milestone not in MILESTONES[:-1] or predecessor.get("candidate_milestone") != milestone:
        raise ReleaseControlError("ordinary candidate predecessor milestone is invalid")
    if not required <= set(predecessor) <= required | later:
        raise ReleaseControlError("candidate predecessor shape is not closed")
    expected = "v0.3" if milestone == "v0.4" else MILESTONES[MILESTONES.index(milestone) - 1]
    version = predecessor["version"]
    if (
        gate["expected_predecessor_milestone"]
        not in ({"v0.3", "v0.3.0"} if milestone == "v0.4" else {expected})
        or not isinstance(version, str)
        or re.fullmatch(re.escape(expected) + r"\.[0-9]+", version) is None
    ):
        raise ReleaseControlError("candidate predecessor version or gate binding is invalid")
    if milestone == "v0.4":
        if version != "v0.3.0" or set(predecessor) != required:
            raise ReleaseControlError("v0.4 requires the exact four-field v0.3.0 predecessor")
    elif (
        set(predecessor) != required | later
        or predecessor["predecessor_milestone"] != expected
        or predecessor["completion_digest"] is not None
    ):
        raise ReleaseControlError(
            "later candidate predecessor evidence/applicability is incomplete"
        )
    for key in set(predecessor) - {
        "candidate_milestone",
        "version",
        "predecessor_milestone",
        "completion_digest",
    }:
        _require_digest(predecessor[key], "candidate predecessor " + key)


def _build_candidate_identity_payload(
    gate: Mapping[str, Any],
    source: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    artifact: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    finalization_intent_digest: str,
    control_journal_locator: str,
    release_root: Path,
    no_evaluation_adoption: bool,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    """Compute the single candidate identity from fixed records and original intent."""
    gate_data, target_data = _validate_release_source_inputs(
        gate, target, live=live, attestation_verifier=attestation_verifier
    )
    typed = [
        (source, "release-source-freeze"),
        (predecessor, "release-predecessor"),
        (artifact, "release-artifact-manifest"),
    ]
    for record, kind in typed:
        _passing_record(record, kind, live=live, attestation_verifier=attestation_verifier)
    if {r["synthetic"] for r in (gate, source, predecessor, artifact, target)} != {not live}:
        raise ReleaseControlError("candidate inputs mix authority modes")
    if no_evaluation_adoption is not True:
        raise ReleaseControlError("ordinary candidate requires explicit no-evaluation-adoption")
    _validate_candidate_predecessor(predecessor["data"], gate_data)
    freeze = _release_data(
        source,
        {
            "build_recipe_digest",
            "dirty",
            "freeze_digest",
            "frozen_at",
            "gate_input_digest",
            "milestone",
            "registry_inputs",
            "release_notes_digest",
            "source_sha",
            "source_tree",
            "version_metadata_digest",
            "workflow_inputs",
            "invocation_root_locator",
            "producer_intent_digest",
        },
        "candidate source freeze",
    )
    if (
        freeze["dirty"] is not False
        or freeze["invocation_root_locator"] != "invocations"
        or freeze["milestone"] != gate_data["milestone"]
        or freeze["gate_input_digest"] != sha256_json(gate)
        or freeze["freeze_digest"]
        != sha256_json({k: v for k, v in freeze.items() if k != "freeze_digest"})
        or freeze["build_recipe_digest"] != RELEASE_BUILD_RECIPE_DIGEST
    ):
        raise ReleaseControlError("candidate source freeze semantic binding mismatch")
    _parse_utc_timestamp(freeze["frozen_at"], "candidate source freeze")
    for key in ("source_sha", "source_tree"):
        if not isinstance(freeze[key], str) or re.fullmatch(r"[0-9a-f]{40}", freeze[key]) is None:
            raise ReleaseControlError("candidate source Git identity is invalid")
    for key in ("release_notes_digest", "version_metadata_digest", "producer_intent_digest"):
        _require_digest(freeze[key], "candidate source " + key)
    for key in ("registry_inputs", "workflow_inputs"):
        rows = freeze[key]
        if not isinstance(rows, list) or not rows:
            raise ReleaseControlError("candidate source inventory is missing")
        names = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"path", "schema_id", "sha256"}:
                raise ReleaseControlError("candidate source inventory is not closed")
            _journal_path(Path("/"), row["path"])
            _require_nonempty_string(row["schema_id"], "candidate source schema")
            _require_digest(row["sha256"], "candidate source member")
            names.append(row["path"])
        if names != sorted(set(names)):
            raise ReleaseControlError("candidate source inventory is not canonical")
    manifest = artifact["data"]
    _validate_artifact_manifest_payload(manifest, expected_milestone=gate_data["milestone"])
    if (
        manifest["source_freeze_digest"] != sha256_json(source)
        or manifest["source_digest"] != freeze["freeze_digest"]
        or manifest["build_recipe_digest"] != freeze["build_recipe_digest"]
        or manifest["target_resolution_digest"] != sha256_json(target)
    ):
        raise ReleaseControlError("candidate artifact/source/target bindings differ")
    release_root = _canonical_absolute_path(str(release_root), "release root")
    locator = _canonical_absolute_path(control_journal_locator, "control journal locator")
    run_id = gate_data["run_id"]
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", run_id) is None
        or release_root.name != target_data["selected_release_tag"]
        or locator
        != release_root.parent
        / ".control"
        / run_id
        / "invocations/candidate-finalization/001/invocation.json"
    ):
        raise ReleaseControlError("candidate release root, run or control locator mismatch")
    data: dict[str, Any] = {
        "artifact_manifest_digest": sha256_json(artifact),
        "artifact_set_digest": manifest["artifact_set_digest"],
        "build_invocation_id": manifest["build_invocation_id"],
        "evaluation_adoption_digest": None,
        "evaluation_adoption_mode": "none",
        "gate_input_digest": sha256_json(gate),
        "milestone": gate_data["milestone"],
        "package_version": target_data["selected_package_version"],
        "predecessor_digest": sha256_json(predecessor),
        "release_tag": target_data["selected_release_tag"],
        "source_freeze_digest": sha256_json(source),
        "finalization_intent_digest": _require_digest(
            finalization_intent_digest, "finalization intent"
        ),
        "control_journal_locator": str(locator),
    }
    data["candidate_digest"] = _candidate_payload_digest(data)
    data["final_directory"] = str(release_root / data["candidate_digest"])
    _validate_candidate_identity_payload(
        data, expected_digest=data["candidate_digest"], expected_milestone=data["milestone"]
    )
    return data


def _validate_candidate_identity_payload(
    candidate: Mapping[str, Any], *, expected_digest: str, expected_milestone: str
) -> None:
    expected_fields = _CANDIDATE_FIELDS
    if set(candidate) != expected_fields:
        raise ReleaseControlError("qualification candidate identity data shape is not closed")
    for field in expected_fields - {
        "build_invocation_id",
        "control_journal_locator",
        "final_directory",
        "evaluation_adoption_digest",
        "evaluation_adoption_mode",
        "milestone",
        "package_version",
        "release_tag",
    }:
        _require_digest(candidate[field], f"qualification candidate {field}")
    adoption_digest = candidate["evaluation_adoption_digest"]
    if adoption_digest is not None:
        _require_digest(adoption_digest, "qualification candidate evaluation adoption")
    if (
        candidate["candidate_digest"] != expected_digest
        or candidate["milestone"] != expected_milestone
        or candidate["milestone"] not in MILESTONES
        or candidate["release_tag"] != candidate["package_version"]
        or not isinstance(candidate["package_version"], str)
        or re.fullmatch(r"v(?:0\.[3-9]|1\.0)\.[0-9]+", candidate["package_version"]) is None
        or not candidate["package_version"].startswith(f"{expected_milestone}.")
        or not isinstance(candidate["evaluation_adoption_mode"], str)
        or candidate["evaluation_adoption_mode"] not in {"none", "adopted"}
        or (candidate["evaluation_adoption_mode"] == "none")
        != (candidate["evaluation_adoption_digest"] is None)
    ):
        raise ReleaseControlError("qualification candidate identity bindings are invalid")
    _require_invocation(candidate["build_invocation_id"])
    if candidate["candidate_digest"] != _candidate_payload_digest(candidate):
        raise ReleaseControlError("candidate semantic identity digest mismatch")
    final = _canonical_absolute_path(candidate["final_directory"], "candidate final directory")
    locator = _canonical_absolute_path(
        candidate["control_journal_locator"], "candidate control locator"
    )
    if (
        final.name != candidate["candidate_digest"]
        or final.parent.name != candidate["release_tag"]
        or locator.parts[-4:] != ("invocations", "candidate-finalization", "001", "invocation.json")
        or locator.parents[4] != final.parent.parent / ".control"
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", locator.parents[3].name) is None
    ):
        raise ReleaseControlError("candidate final path or control locator binding mismatch")


def _validate_artifact_manifest_payload(
    artifact: Mapping[str, Any], *, expected_milestone: str
) -> list[dict[str, Any]]:
    expected_fields = {
        "artifact_set_digest",
        "artifacts",
        "build_invocation_id",
        "build_recipe_digest",
        "milestone",
        "source_digest",
        "source_freeze_digest",
        "target_resolution_digest",
        "invocation_root_locator",
        "producer_intent_digest",
    }
    if set(artifact) != expected_fields:
        raise ReleaseControlError("qualified artifact manifest data shape is not closed")
    if artifact["milestone"] != expected_milestone:
        raise ReleaseControlError("qualified artifact manifest milestone binding mismatch")
    _require_invocation(artifact["build_invocation_id"])
    if artifact["invocation_root_locator"] != "invocations":
        raise ReleaseControlError("qualified artifact manifest invocation locator is invalid")
    for field in expected_fields - {
        "artifacts",
        "build_invocation_id",
        "milestone",
        "invocation_root_locator",
    }:
        _require_digest(artifact[field], f"qualified artifact manifest {field}")
    rows = artifact["artifacts"]
    if not isinstance(rows, list) or len(rows) != 2:
        raise ReleaseControlError("qualified artifact manifest is not one wheel and one sdist")
    expected_media = {
        ".whl": "application/vnd.pypa.wheel+zip",
        ".tar.gz": "application/gzip",
    }
    names: list[str] = []
    suffixes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"media_type", "path", "sha256", "size"}:
            raise ReleaseControlError("qualified artifact manifest row shape is not closed")
        name = row["path"]
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ReleaseControlError("qualified artifact manifest path is unsafe")
        suffix = ".tar.gz" if name.endswith(".tar.gz") else Path(name).suffix
        if suffix not in expected_media or row["media_type"] != expected_media[suffix]:
            raise ReleaseControlError("qualified artifact manifest media type is invalid")
        _require_digest(row["sha256"], f"qualified artifact {name}")
        if isinstance(row["size"], bool) or not isinstance(row["size"], int) or row["size"] < 1:
            raise ReleaseControlError("qualified artifact manifest size is invalid")
        names.append(name)
        suffixes.add(suffix)
    if names != sorted(set(names)) or suffixes != set(expected_media):
        raise ReleaseControlError("qualified artifact manifest inventory is not canonical")
    if artifact["artifact_set_digest"] != sha256_json(rows):
        raise ReleaseControlError("qualified artifact set digest mismatch")
    return rows


def _validate_qualification_plan_payload(
    plan: Mapping[str, Any], *, candidate: Mapping[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    expected_fields = {
        "attempt_count",
        "candidate_digest",
        "candidate_manifest_digest",
        "cells",
        "delta_digest",
        "delta_test_map_digest",
        "expected_terminal_result",
        "gate_instance_digest",
        "milestone",
        "plan_digest",
        "predecessor_digest",
        "readiness_digest",
        "scenario_catalog_digest",
    }
    if set(plan) != expected_fields:
        raise ReleaseControlError("release qualification plan data shape is not closed")
    for field in expected_fields - {
        "attempt_count",
        "cells",
        "expected_terminal_result",
        "milestone",
    }:
        _require_digest(plan[field], f"release qualification plan {field}")
    attempt_count = plan["attempt_count"]
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 1:
        raise ReleaseControlError("release qualification plan attempt count is invalid")
    unsigned_plan = dict(plan)
    claimed_plan_digest = unsigned_plan.pop("plan_digest")
    if claimed_plan_digest != sha256_json(unsigned_plan):
        raise ReleaseControlError("release qualification plan digest mismatch")
    if plan["expected_terminal_result"] != "PASS":
        raise ReleaseControlError("release qualification plan terminal result is invalid")
    if candidate is not None and (
        plan["candidate_digest"] != candidate["candidate_digest"]
        or plan["candidate_manifest_digest"] != candidate["artifact_manifest_digest"]
        or plan["predecessor_digest"] != candidate["predecessor_digest"]
        or plan["milestone"] != candidate["milestone"]
    ):
        raise ReleaseControlError("release qualification plan candidate binding mismatch")
    cells = plan["cells"]
    if not isinstance(cells, list) or not cells:
        raise ReleaseControlError("release qualification plan cells are malformed")
    expected_cell_fields = {
        "cell_id",
        "environment_id",
        "obligation_ids",
        "profile_id",
        "scenario_ids",
    }
    cell_index: dict[str, dict[str, Any]] = {}
    for cell in cells:
        if not isinstance(cell, dict) or set(cell) != expected_cell_fields:
            raise ReleaseControlError("release qualification plan cell shape is not closed")
        cell_id = _require_nonempty_string(cell["cell_id"], "qualification plan cell id")
        if cell_id in cell_index:
            raise ReleaseControlError("release qualification plan cell ids are not unique")
        _require_nonempty_string(cell["environment_id"], "qualification plan environment")
        _require_nonempty_string(cell["profile_id"], "qualification plan profile")
        _require_canonical_string_inventory(
            cell["obligation_ids"], "qualification plan obligations"
        )
        _require_canonical_string_inventory(cell["scenario_ids"], "qualification plan scenarios")
        cell_index[cell_id] = cell
    if list(cell_index) != sorted(cell_index):
        raise ReleaseControlError("release qualification plan cells are not canonical")
    return cell_index


def _validate_cell_result_payload(
    record: Mapping[str, Any],
    *,
    plan_cell: Mapping[str, Any],
    attempt_id: str,
    candidate_digest: str,
    plan_digest: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    cell = _passing_record(
        record,
        "release-cell-result",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "artifact_digest",
        "attempt_id",
        "candidate_digest",
        "cell_id",
        "completed_at",
        "counts",
        "environment_id",
        "junit_digest",
        "obligation_ids",
        "plan_digest",
        "profile_id",
        "result",
        "runner_identity",
        "scenario_ids",
        "started_at",
        "stderr_digest",
        "stdout_digest",
        "unexpected_outcomes",
    }
    if set(cell) != expected_fields:
        raise ReleaseControlError("release qualification cell result data shape is not closed")
    if (
        cell["attempt_id"] != attempt_id
        or cell["candidate_digest"] != candidate_digest
        or cell["cell_id"] != plan_cell["cell_id"]
        or cell["environment_id"] != plan_cell["environment_id"]
        or cell["obligation_ids"] != plan_cell["obligation_ids"]
        or cell["plan_digest"] != plan_digest
        or cell["profile_id"] != plan_cell["profile_id"]
        or cell["scenario_ids"] != plan_cell["scenario_ids"]
        or cell["result"] != "PASS"
        or cell["unexpected_outcomes"] != []
    ):
        raise ReleaseControlError("release qualification cell result binding mismatch")
    for field in (
        "artifact_digest",
        "junit_digest",
        "plan_digest",
        "stderr_digest",
        "stdout_digest",
    ):
        _require_digest(cell[field], f"release qualification cell {field}")
    _require_nonempty_string(cell["runner_identity"], "release qualification cell runner")
    _require_canonical_string_inventory(cell["obligation_ids"], "release cell obligations")
    _require_canonical_string_inventory(cell["scenario_ids"], "release cell scenarios")
    counts = cell["counts"]
    count_fields = {
        "deselected",
        "failed",
        "passed",
        "retried",
        "skipped",
        "xfailed",
        "xpassed",
    }
    if (
        not isinstance(counts, dict)
        or set(counts) != count_fields
        or any(type(counts[field]) is not int or counts[field] < 0 for field in count_fields)
        or counts["passed"] < 1
        or any(counts[field] != 0 for field in count_fields - {"passed"})
    ):
        raise ReleaseControlError("release qualification cell counts are not a clean PASS")
    started_at = _parse_utc_timestamp(cell["started_at"], "release cell start")
    completed_at = _parse_utc_timestamp(cell["completed_at"], "release cell completion")
    if completed_at < started_at:
        raise ReleaseControlError("release qualification cell completion precedes its start")
    return cell


def _validate_retention_payload(
    retention: Mapping[str, Any], *, expected_input_digest: str, expected_phase: str, label: str
) -> None:
    expected_fields = {
        "all_content_equal",
        "input_digest",
        "phase",
        "receipt_set_digest",
        "retained_at",
        "stores",
    }
    if set(retention) != expected_fields:
        raise ReleaseControlError(f"{label} data shape is not closed")
    if (
        retention["all_content_equal"] is not True
        or retention["input_digest"] != expected_input_digest
        or retention["phase"] != expected_phase
    ):
        raise ReleaseControlError(f"{label} does not bind the canonical input and phase")
    _require_digest(retention["input_digest"], f"{label} input")
    _require_digest(retention["receipt_set_digest"], f"{label} receipt set")
    _parse_utc_timestamp(retention["retained_at"], f"{label} retention time")
    stores = retention["stores"]
    if not isinstance(stores, list) or len(stores) != 2:
        raise ReleaseControlError(f"{label} requires exactly two store receipts")
    expected_store_fields = {
        "content_digest",
        "hold_receipt_digest",
        "independence_group",
        "namespace",
        "object_key",
        "put_receipt_digest",
        "read_back_digest",
        "store_id",
    }
    store_ids: list[str] = []
    independence_groups: list[str] = []
    for store in stores:
        if not isinstance(store, dict) or set(store) != expected_store_fields:
            raise ReleaseControlError(f"{label} store shape is not closed")
        for field in (
            "content_digest",
            "hold_receipt_digest",
            "put_receipt_digest",
            "read_back_digest",
        ):
            _require_digest(store[field], f"{label} {field}")
        if (
            store["content_digest"] != expected_input_digest
            or store["read_back_digest"] != expected_input_digest
        ):
            raise ReleaseControlError(f"{label} store read-back differs from the canonical input")
        store_ids.append(_require_nonempty_string(store["store_id"], f"{label} store id"))
        independence_groups.append(
            _require_nonempty_string(store["independence_group"], f"{label} independence group")
        )
        _require_nonempty_string(store["namespace"], f"{label} namespace")
        _require_nonempty_string(store["object_key"], f"{label} object key")
    if store_ids != ["payload-store-a", "payload-store-b"]:
        raise ReleaseControlError(f"{label} stores are missing or not canonical")
    if len(set(independence_groups)) != 2:
        raise ReleaseControlError(f"{label} stores are not independently administered")
    if retention["receipt_set_digest"] != sha256_json(stores):
        raise ReleaseControlError(f"{label} receipt-set digest mismatch")


def _validate_observed_store_readbacks(
    stores: Sequence[Mapping[str, Any]],
    *,
    expected_digest: str,
    readbacks: Mapping[str, Path] | None,
    label: str,
) -> None:
    expected_store_ids = {"payload-store-a", "payload-store-b"}
    if not isinstance(readbacks, Mapping) or set(readbacks) != expected_store_ids:
        raise ReleaseControlError(f"{label} requires two explicit observed store readbacks")
    if any(not isinstance(path, Path) for path in readbacks.values()):
        raise ReleaseControlError(f"{label} readback paths must be Path values")
    paths = [readbacks[store_id] for store_id in sorted(expected_store_ids)]
    if paths[0] == paths[1]:
        raise ReleaseControlError(f"{label} readback paths are not independent observations")
    try:
        if paths[0].resolve(strict=True) == paths[1].resolve(strict=True) or os.path.samefile(
            paths[0], paths[1]
        ):
            raise ReleaseControlError(f"{label} readbacks resolve to the same file")
    except (OSError, RuntimeError) as exc:
        raise ReleaseControlError(f"{label} readback path cannot be resolved: {exc}") from exc
    stores_by_id = {store["store_id"]: store for store in stores}
    for store_id, path in readbacks.items():
        observed_digest = _regular_file_digest(path)
        store = stores_by_id[store_id]
        if (
            observed_digest != expected_digest
            or store["content_digest"] != observed_digest
            or store["read_back_digest"] != observed_digest
        ):
            raise ReleaseControlError(f"{label} observed bytes differ for {store_id}")


def _validate_attempt_coordination(
    record: Mapping[str, Any],
    *,
    indexed: Mapping[str, Sequence[tuple[Path, dict[str, Any]]]],
    attempt: Mapping[str, Any],
    expected_cell_ids: list[str],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> set[str]:
    coordination = _passing_record(
        record,
        "release-attempt-coordination",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "attempt_id",
        "candidate_digest",
        "cells",
        "coordination_result",
        "hard_runner_losses",
        "milestone",
        "provider",
        "qualification_plan_digest",
    }
    if set(coordination) != expected_fields:
        raise ReleaseControlError("release attempt coordination data shape is not closed")
    if (
        coordination["attempt_id"] != attempt["attempt_id"]
        or coordination["candidate_digest"] != attempt["candidate_digest"]
        or coordination["milestone"] != attempt["milestone"]
        or coordination["qualification_plan_digest"] != attempt["qualification_plan_digest"]
        or coordination["coordination_result"] != "PASS"
        or coordination["hard_runner_losses"] != []
        or coordination["provider"] != "github"
    ):
        raise ReleaseControlError("release attempt coordination binding mismatch")
    cells = coordination["cells"]
    if not isinstance(cells, list) or len(cells) != len(expected_cell_ids):
        raise ReleaseControlError("release attempt coordination cell matrix is incomplete")
    observed_cell_ids: list[str] = []
    job_ids: set[str] = set()
    provider_run_ids: set[str] = set()
    termination_digests: set[str] = set()
    expected_cell_fields = {
        "cell_id",
        "job_id",
        "provider_run_id",
        "provider_termination_digest",
        "status",
    }
    for cell in cells:
        if not isinstance(cell, dict) or set(cell) != expected_cell_fields:
            raise ReleaseControlError("release attempt coordination cell shape is not closed")
        cell_id = _require_nonempty_string(cell["cell_id"], "coordination cell id")
        job_id = _require_nonempty_string(cell["job_id"], "coordination job id")
        provider_run_id = _require_nonempty_string(
            cell["provider_run_id"], "coordination provider run id"
        )
        if job_id in job_ids or provider_run_id in provider_run_ids or cell["status"] != "terminal":
            raise ReleaseControlError("release attempt coordination is not uniquely terminal")
        observed_cell_ids.append(cell_id)
        job_ids.add(job_id)
        provider_run_ids.add(provider_run_id)
        termination_digest = _require_digest(
            cell["provider_termination_digest"], "release attempt provider termination"
        )
        if termination_digest in termination_digests:
            raise ReleaseControlError("release attempt provider terminations are not unique")
        termination_digests.add(termination_digest)
        termination = _resolved_evidence_record(
            indexed,
            termination_digest,
            "provider-run-termination",
            "release attempt provider termination",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        termination_data = _passing_record(
            termination,
            "provider-run-termination",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        if (
            set(termination_data) != {"job_id", "provider_run_id", "state", "tool"}
            or termination_data["state"] != "success"
            or termination_data["job_id"] != job_id
            or termination_data["provider_run_id"] != provider_run_id
            or not isinstance(termination_data["tool"], str)
            or re.fullmatch(
                r"[A-Za-z0-9._-]*(?:[Pp]rovider|[Gg]it[Hh]ub)[A-Za-z0-9._-]*",
                termination_data["tool"],
            )
            is None
        ):
            raise ReleaseControlError("release attempt provider termination is not successful")
    if observed_cell_ids != expected_cell_ids:
        raise ReleaseControlError("release attempt coordination cell inventory mismatch")
    return termination_digests


def _validate_attempt_evidence_manifest(
    record: Mapping[str, Any],
    *,
    attempt: Mapping[str, Any],
    required_digests: set[str],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    manifest = _passing_record(
        record,
        "release-evidence-manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "candidate_digest",
        "entries",
        "invocation_journal_digests",
        "manifest_digest",
        "phase",
        "scope_id",
        "scope_kind",
    }
    if set(manifest) != expected_fields:
        raise ReleaseControlError("release attempt evidence manifest data shape is not closed")
    if (
        manifest["candidate_digest"] != attempt["candidate_digest"]
        or manifest["phase"] != "attempt"
        or manifest["scope_id"] != attempt["attempt_id"]
        or manifest["scope_kind"] != "release-attempt"
    ):
        raise ReleaseControlError("release attempt evidence manifest binding mismatch")
    _require_digest(manifest["manifest_digest"], "release attempt evidence manifest")
    journals = manifest["invocation_journal_digests"]
    if (
        not isinstance(journals, list)
        or not journals
        or any(not isinstance(digest, str) for digest in journals)
        or journals != sorted(set(journals))
    ):
        raise ReleaseControlError("release attempt invocation journals are not canonical")
    for digest in journals:
        _require_digest(digest, "release attempt invocation journal")
    entries = manifest["entries"]
    if not isinstance(entries, list) or not entries:
        raise ReleaseControlError("release attempt evidence manifest has no entries")
    expected_entry_fields = {"media_type", "path", "role", "sha256", "size"}
    paths: list[str] = []
    observed_digests: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != expected_entry_fields:
            raise ReleaseControlError("release attempt evidence manifest entry is malformed")
        path = _require_nonempty_string(entry["path"], "release attempt evidence path")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReleaseControlError("release attempt evidence path is unsafe")
        _require_nonempty_string(entry["media_type"], "release attempt evidence media type")
        _require_nonempty_string(entry["role"], "release attempt evidence role")
        size = entry["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ReleaseControlError("release attempt evidence size is invalid")
        paths.append(path)
        observed_digests.append(_require_digest(entry["sha256"], "release attempt evidence entry"))
    if paths != sorted(set(paths)):
        raise ReleaseControlError("release attempt evidence paths are not canonical")
    if any(observed_digests.count(digest) != 1 for digest in required_digests):
        raise ReleaseControlError(
            "release attempt evidence manifest does not close required inputs"
        )


def _validate_attempt_index_payload(
    record: Mapping[str, Any],
    *,
    attempt: Mapping[str, Any],
    expected_manifest_digest: str,
    retention_digest: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    index = _passing_record(
        record,
        "release-attempt-index",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "backend_id",
        "committed_head",
        "disposition",
        "entry_manifest_digest",
        "entry_receipts_digest",
        "generation",
        "milestone",
        "operation_id",
        "previous_head",
        "read_back_digest",
        "scope_id",
        "scope_kind",
        "sequence",
        "stage",
        "token",
    }
    if set(index) != expected_fields:
        raise ReleaseControlError("release attempt index data shape is not closed")
    for field in (
        "committed_head",
        "entry_manifest_digest",
        "entry_receipts_digest",
        "read_back_digest",
    ):
        _require_digest(index[field], f"release attempt index {field}")
    if index["previous_head"] is not None:
        _require_digest(index["previous_head"], "release attempt index previous head")
    for field in ("generation", "sequence"):
        if isinstance(index[field], bool) or not isinstance(index[field], int) or index[field] < 1:
            raise ReleaseControlError(f"release attempt index {field} is invalid")
    if (
        index["backend_id"] != "attempt-index"
        or index["committed_head"] != index["read_back_digest"]
        or not isinstance(index["disposition"], str)
        or index["disposition"] not in {"committed", "idempotent"}
        or index["entry_manifest_digest"] != expected_manifest_digest
        or index["entry_receipts_digest"] != retention_digest
        or index["milestone"] != attempt["milestone"]
        or index["operation_id"] != attempt["attempt_id"]
        or index["scope_id"] != attempt["candidate_digest"]
        or index["scope_kind"] != "release_candidate"
        or index["sequence"] != record["sequence"]
        or index["stage"] != "qualification-attempt"
    ):
        raise ReleaseControlError("release attempt index semantic binding mismatch")
    _require_nonempty_string(index["token"], "release attempt index token")


def _validate_clean_warning_summary(
    record: Mapping[str, Any],
    *,
    candidate_digest: str,
    expected_subject_digest: str,
    label: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    warning = _passing_record(
        record,
        "release-warning-summary",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "candidate_digest",
        "deselection_count",
        "policy_digest",
        "result",
        "retry_count",
        "skip_count",
        "subject_digest",
        "summary_digest",
        "unexpected_warning_count",
        "warnings",
        "xfail_count",
        "xpass_count",
    }
    if set(warning) != expected_fields:
        raise ReleaseControlError(f"{label} data shape is not closed")
    for field in ("policy_digest", "subject_digest", "summary_digest"):
        _require_digest(warning[field], f"{label} {field}")
    count_fields = (
        "deselection_count",
        "retry_count",
        "skip_count",
        "unexpected_warning_count",
        "xfail_count",
        "xpass_count",
    )
    if (
        warning["candidate_digest"] != candidate_digest
        or warning["subject_digest"] != expected_subject_digest
        or warning["result"] != "PASS"
        or any(type(warning[field]) is not int or warning[field] != 0 for field in count_fields)
    ):
        raise ReleaseControlError(f"{label} is not clean")
    warnings = warning["warnings"]
    if warnings != []:
        raise ReleaseControlError(f"{label} warning inventory is not empty")


def validate_release_qualification_record(
    record: Mapping[str, Any],
    *,
    evidence_root: Path,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
    attempt_retention_readbacks: Mapping[str, Mapping[str, Path]] | None = None,
) -> None:
    data = _passing_record(
        record,
        "release-qualification",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "attempt_digests",
        "attempt_index_receipt_digests",
        "attempt_retention_receipt_digests",
        "candidate_digest",
        "executed_cell_ids",
        "expected_cell_ids",
        "plan_digest",
        "qualification_digest",
        "result",
        "terminal_results",
        "unexpected_outcomes",
        "warning_summary_digest",
    }
    if set(data) != expected_fields:
        raise ReleaseControlError("release qualification data shape is not closed")
    if data["result"] != "PASS" or data["unexpected_outcomes"] != []:
        raise ReleaseControlError("release qualification is not a clean PASS")
    expected_cells = data["expected_cell_ids"]
    executed_cells = data["executed_cell_ids"]
    if (
        not isinstance(expected_cells, list)
        or not expected_cells
        or any(not isinstance(cell, str) or not cell for cell in expected_cells)
        or expected_cells != sorted(expected_cells)
        or len(expected_cells) != len(set(expected_cells))
        or executed_cells != expected_cells
    ):
        raise ReleaseControlError("release qualification cell inventory is incomplete")
    terminals = data["terminal_results"]
    if not isinstance(terminals, list) or len(terminals) != len(expected_cells):
        raise ReleaseControlError("release qualification terminal matrix is incomplete")
    terminal_ids: list[str] = []
    for row in terminals:
        if not isinstance(row, dict) or set(row) != {"cell_id", "result", "result_digest"}:
            raise ReleaseControlError("release qualification terminal row is malformed")
        cell_id = row["cell_id"]
        if not isinstance(cell_id, str) or not cell_id:
            raise ReleaseControlError("release qualification terminal cell id is invalid")
        terminal_ids.append(cell_id)
        if row["result"] != "PASS":
            raise ReleaseControlError("release qualification contains a non-passing terminal")
        _require_digest(row["result_digest"], "qualification terminal result")
    if terminal_ids != expected_cells:
        raise ReleaseControlError("release qualification terminals do not match expected cells")
    for field in (
        "attempt_digests",
        "attempt_index_receipt_digests",
        "attempt_retention_receipt_digests",
    ):
        values = data[field]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))
        ):
            raise ReleaseControlError(f"release qualification {field} is incomplete")
        for value in values:
            _require_digest(value, f"release qualification {field}")
    for field in (
        "candidate_digest",
        "plan_digest",
        "qualification_digest",
        "warning_summary_digest",
    ):
        _require_digest(data[field], f"release qualification {field}")

    indexed = _evidence_record_index(evidence_root)
    plan_record = _resolved_evidence_record(
        indexed,
        data["plan_digest"],
        "release-qualification-plan",
        "release qualification plan",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    plan = _passing_record(
        plan_record,
        "release-qualification-plan",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    milestone = plan.get("milestone")
    if not isinstance(milestone, str) or milestone not in MILESTONES:
        raise ReleaseControlError("release qualification plan milestone is invalid")
    candidate_record = _candidate_record_for_digest(
        indexed,
        data["candidate_digest"],
        live=live,
        attestation_verifier=attestation_verifier,
    )
    candidate = _passing_record(
        candidate_record,
        "release-candidate-identity",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    _validate_candidate_identity_payload(
        candidate,
        expected_digest=data["candidate_digest"],
        expected_milestone=milestone,
    )
    plan_cells = _validate_qualification_plan_payload(plan, candidate=candidate)
    if list(plan_cells) != expected_cells:
        raise ReleaseControlError("release qualification plan cell inventory mismatch")

    attempts = [
        _resolved_evidence_record(
            indexed,
            digest,
            "release-attempt",
            "release qualification attempt",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for digest in data["attempt_digests"]
    ]
    if plan["attempt_count"] != len(attempts):
        raise ReleaseControlError("release qualification attempt count mismatch")
    observed_attempt_ids: list[str] = []
    observed_index_receipts: list[str] = []
    observed_retention_receipts: list[str] = []
    latest_cells: list[dict[str, Any]] | None = None
    for attempt_record in attempts:
        attempt = _release_data(
            attempt_record,
            {
                "attempt_id",
                "candidate_digest",
                "cells",
                "coordination_digest",
                "index_receipt_digest",
                "milestone",
                "qualification_plan_digest",
                "result",
                "retention_receipts_digest",
                "warning_summary_digest",
            },
            "release qualification attempt",
        )
        if (
            attempt["result"] != "PASS"
            or attempt["candidate_digest"] != data["candidate_digest"]
            or attempt["qualification_plan_digest"] != data["plan_digest"]
            or attempt["milestone"] != milestone
        ):
            raise ReleaseControlError("release qualification attempt binding mismatch")
        attempt_id = _require_nonempty_string(attempt["attempt_id"], "release attempt id")
        observed_attempt_ids.append(attempt_id)
        attempt_cells = attempt["cells"]
        if not isinstance(attempt_cells, list) or len(attempt_cells) != len(expected_cells):
            raise ReleaseControlError("release qualification attempt cell matrix is incomplete")
        observed_cell_ids: list[str] = []
        observed_cell_digests: set[str] = set()
        validated_attempt_cells: list[dict[str, Any]] = []
        for cell_row in attempt_cells:
            if not isinstance(cell_row, dict) or set(cell_row) != {
                "cell_id",
                "result",
                "result_digest",
            }:
                raise ReleaseControlError("release qualification attempt cell is malformed")
            cell_id = _require_nonempty_string(
                cell_row["cell_id"], "release qualification attempt cell id"
            )
            result_digest = _require_digest(
                cell_row["result_digest"], "release qualification attempt cell"
            )
            if cell_row["result"] != "PASS" or result_digest in observed_cell_digests:
                raise ReleaseControlError("release qualification attempt cell is not a unique PASS")
            observed_cell_ids.append(cell_id)
            observed_cell_digests.add(result_digest)
            plan_cell = plan_cells.get(cell_id)
            if plan_cell is None:
                raise ReleaseControlError("release qualification attempt names an unknown cell")
            cell_record = _resolved_evidence_record(
                indexed,
                result_digest,
                "release-cell-result",
                "release qualification cell result",
                live=live,
                attestation_verifier=attestation_verifier,
            )
            _validate_cell_result_payload(
                cell_record,
                plan_cell=plan_cell,
                attempt_id=attempt_id,
                candidate_digest=data["candidate_digest"],
                plan_digest=data["plan_digest"],
                live=live,
                attestation_verifier=attestation_verifier,
            )
            validated_attempt_cells.append(cell_row)
        if observed_cell_ids != expected_cells:
            raise ReleaseControlError("release qualification attempt cell inventory mismatch")

        coordination_digest = _require_digest(
            attempt["coordination_digest"], "release attempt coordination"
        )
        coordination_record = _resolved_evidence_record(
            indexed,
            coordination_digest,
            "release-attempt-coordination",
            "release attempt coordination",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        termination_digests = _validate_attempt_coordination(
            coordination_record,
            indexed=indexed,
            attempt=attempt,
            expected_cell_ids=expected_cells,
            live=live,
            attestation_verifier=attestation_verifier,
        )
        retention_digest = _require_digest(
            attempt["retention_receipts_digest"], "release attempt retention receipt"
        )
        retention_record = _resolved_evidence_record(
            indexed,
            retention_digest,
            "release-retention-receipts",
            "release qualification retention receipt",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        retention = _passing_record(
            retention_record,
            "release-retention-receipts",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        index_digest = _require_digest(
            attempt["index_receipt_digest"], "release attempt index receipt"
        )
        index_record = _resolved_evidence_record(
            indexed,
            index_digest,
            "release-attempt-index",
            "release qualification index receipt",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        index = _passing_record(
            index_record,
            "release-attempt-index",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        manifest_digest = _require_digest(
            index.get("entry_manifest_digest"), "release attempt evidence manifest"
        )
        manifest_record = _resolved_evidence_record(
            indexed,
            manifest_digest,
            "release-evidence-manifest",
            "release attempt evidence manifest",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        _validate_attempt_evidence_manifest(
            manifest_record,
            attempt=attempt,
            required_digests={
                data["plan_digest"],
                coordination_digest,
                *observed_cell_digests,
                *termination_digests,
            },
            live=live,
            attestation_verifier=attestation_verifier,
        )
        _validate_retention_payload(
            retention,
            expected_input_digest=manifest_digest,
            expected_phase="attempt",
            label="release qualification retention receipt",
        )
        if live or attempt_retention_readbacks is not None:
            readbacks = (
                attempt_retention_readbacks.get(retention_digest)
                if attempt_retention_readbacks is not None
                else None
            )
            _validate_observed_store_readbacks(
                retention["stores"],
                expected_digest=manifest_digest,
                readbacks=readbacks,
                label="release qualification retention receipt",
            )
        _validate_attempt_index_payload(
            index_record,
            attempt=attempt,
            expected_manifest_digest=manifest_digest,
            retention_digest=retention_digest,
            live=live,
            attestation_verifier=attestation_verifier,
        )
        attempt_warning = _resolved_evidence_record(
            indexed,
            attempt["warning_summary_digest"],
            "release-warning-summary",
            "release attempt warning summary",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        attempt_subject = dict(attempt)
        del attempt_subject["warning_summary_digest"]
        _validate_clean_warning_summary(
            attempt_warning,
            candidate_digest=data["candidate_digest"],
            expected_subject_digest=sha256_json(attempt_subject),
            label="release attempt warning summary",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        observed_index_receipts.append(index_digest)
        observed_retention_receipts.append(retention_digest)
        latest_cells = validated_attempt_cells

    if observed_attempt_ids != sorted(set(observed_attempt_ids)):
        raise ReleaseControlError("release qualification attempt ids are not canonical")
    if observed_index_receipts != data["attempt_index_receipt_digests"]:
        raise ReleaseControlError("release qualification index receipt bindings mismatch")
    if observed_retention_receipts != data["attempt_retention_receipt_digests"]:
        raise ReleaseControlError("release qualification retention receipt bindings mismatch")
    if attempt_retention_readbacks is not None and set(attempt_retention_readbacks) != set(
        observed_retention_receipts
    ):
        raise ReleaseControlError("release qualification readback receipt inventory mismatch")
    if latest_cells is None or latest_cells != terminals:
        raise ReleaseControlError("release qualification terminals are not the final attempt")
    warning_record = _resolved_evidence_record(
        indexed,
        data["warning_summary_digest"],
        "release-warning-summary",
        "release qualification warning summary",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualification_subject = dict(data)
    del qualification_subject["warning_summary_digest"]
    _validate_clean_warning_summary(
        warning_record,
        candidate_digest=data["candidate_digest"],
        expected_subject_digest=sha256_json(qualification_subject),
        label="release qualification warning summary",
        live=live,
        attestation_verifier=attestation_verifier,
    )


def _required_release_targets(milestone: str) -> list[str]:
    registry = read_json(RELEASE_TARGETS_PATH)
    if set(registry) != {"milestones", "owner", "schema_version"}:
        raise ReleaseControlError("release target registry shape is not closed")
    if (
        registry["owner"] != "MP2-007"
        or registry["schema_version"] != "metriplane.release-targets.v1"
    ):
        raise ReleaseControlError("release target registry identity is invalid")
    rows = registry["milestones"]
    if not isinstance(rows, list) or len(rows) != len(MILESTONES):
        raise ReleaseControlError("release target milestone inventory is incomplete")
    observed_milestones: list[str] = []
    selected: list[str] | None = None
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "predecessor",
            "required_targets",
            "version_line",
        }:
            raise ReleaseControlError("release target milestone row is malformed")
        milestone_id = row["id"]
        targets = row["required_targets"]
        if not isinstance(milestone_id, str):
            raise ReleaseControlError("release target milestone id is invalid")
        if (
            not isinstance(targets, list)
            or not targets
            or any(not isinstance(target, str) or not target for target in targets)
            or targets != sorted(set(targets))
        ):
            raise ReleaseControlError("release target requirement inventory is not canonical")
        observed_milestones.append(milestone_id)
        if milestone_id == milestone:
            selected = targets
    if tuple(observed_milestones) != MILESTONES or selected is None:
        raise ReleaseControlError("release target milestone bindings are invalid")
    return selected


def validate_publication_reconciliation_record(
    record: Mapping[str, Any],
    *,
    evidence_root: Path,
    live: bool,
    expected_authority_policy_digest: str | None = None,
    attestation_verifier: ProviderAttestationVerifier | None = None,
    retention_readbacks: Mapping[str, Path] | None = None,
    attempt_retention_readbacks: Mapping[str, Mapping[str, Path]] | None = None,
) -> None:
    data = _passing_record(
        record,
        "release-publication-reconciliation",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "approval_digest",
        "burn_required",
        "candidate_digest",
        "evidence_manifest_digest",
        "expected_artifacts",
        "lock_receipt_digest",
        "milestone",
        "observations_digest",
        "partial_targets",
        "promotion_digest",
        "qualification_digest",
        "reconciliation_digest",
        "result",
        "staged_retention_receipts_digest",
        "targets",
    }
    if set(data) != expected_fields:
        raise ReleaseControlError("publication reconciliation data shape is not closed")
    if data["result"] != "RECONCILED" or data["burn_required"] is not False:
        raise ReleaseControlError("publication reconciliation is not cleanly reconciled")
    if data["partial_targets"] != []:
        raise ReleaseControlError("publication reconciliation contains partial targets")
    for field in expected_fields - {
        "burn_required",
        "expected_artifacts",
        "milestone",
        "partial_targets",
        "result",
        "targets",
    }:
        _require_digest(data[field], f"publication reconciliation {field}")
    if data["milestone"] not in MILESTONES:
        raise ReleaseControlError("publication reconciliation milestone is invalid")
    artifacts = data["expected_artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) < 2:
        raise ReleaseControlError("publication reconciliation has no closed artifact set")
    artifact_names: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {
            "media_type",
            "path",
            "sha256",
            "size",
        }:
            raise ReleaseControlError("publication reconciliation artifact row is malformed")
        path = artifact["path"]
        if not isinstance(path, str) or not path or Path(path).name != path:
            raise ReleaseControlError("publication reconciliation artifact path is unsafe")
        if not isinstance(artifact["media_type"], str) or not artifact["media_type"]:
            raise ReleaseControlError("publication reconciliation artifact media type is missing")
        _require_digest(artifact["sha256"], f"publication reconciliation artifact {path}")
        size = artifact["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ReleaseControlError("publication reconciliation artifact size is invalid")
        artifact_names.append(path)
    if artifact_names != sorted(set(artifact_names)):
        raise ReleaseControlError("publication reconciliation artifacts are not canonical")
    targets = data["targets"]
    if not isinstance(targets, list) or not targets:
        raise ReleaseControlError("publication reconciliation has no target observations")
    target_ids: list[str] = []
    for target in targets:
        if not isinstance(target, dict) or set(target) != {
            "conflict_digest",
            "exact_match",
            "target_id",
        }:
            raise ReleaseControlError("publication reconciliation target row is malformed")
        target_id = target["target_id"]
        if not isinstance(target_id, str) or not target_id:
            raise ReleaseControlError("publication reconciliation target id is missing")
        if target["exact_match"] is not True or target["conflict_digest"] is not None:
            raise ReleaseControlError("publication reconciliation target is not an exact match")
        target_ids.append(target_id)
    if target_ids != sorted(set(target_ids)):
        raise ReleaseControlError("publication reconciliation targets are not canonical")
    if target_ids != _required_release_targets(data["milestone"]):
        raise ReleaseControlError(
            "publication reconciliation does not cover every required release target"
        )

    indexed = _evidence_record_index(evidence_root)
    dependency_types = {
        "approval_digest": "release-approval",
        "evidence_manifest_digest": "release-evidence-manifest",
        "lock_receipt_digest": "release-promotion-lock",
        "observations_digest": "release-publication-observations",
        "promotion_digest": "release-promotion",
        "qualification_digest": "release-qualification",
        "staged_retention_receipts_digest": "release-retention-receipts",
    }
    dependencies = {
        field: _resolved_evidence_record(
            indexed,
            data[field],
            record_type,
            f"publication reconciliation {field}",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for field, record_type in dependency_types.items()
    }
    validate_release_qualification_record(
        dependencies["qualification_digest"],
        evidence_root=evidence_root,
        live=live,
        attestation_verifier=attestation_verifier,
        attempt_retention_readbacks=attempt_retention_readbacks,
    )
    approval = _passing_record(
        dependencies["approval_digest"],
        "release-approval",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    approval_decision = _resolved_evidence_record(
        indexed,
        approval.get("approval_decision_digest"),
        "release-approval-decision",
        "publication reconciliation approval decision",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    dependencies["approval_decision_digest"] = approval_decision
    gate_instance = _resolved_evidence_record(
        indexed,
        approval.get("gate_instance_digest"),
        "release-gate-instance",
        "publication reconciliation approval gate instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    gate = _passing_record(
        gate_instance,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    role_assignments = _role_assignment_record_for_gate(indexed, gate)
    validate_release_approval_record(
        dependencies["approval_digest"],
        approval_decision=approval_decision,
        gate_instance=gate_instance,
        qualification=dependencies["qualification_digest"],
        role_assignments=role_assignments,
        no_prepublication_rubric=True,
        live=live,
        expected_authority_policy_digest=expected_authority_policy_digest,
        attestation_verifier=attestation_verifier,
    )
    candidate_record = _candidate_record_for_digest(
        indexed,
        data["candidate_digest"],
        live=live,
        attestation_verifier=attestation_verifier,
    )
    candidate = _passing_record(
        candidate_record,
        "release-candidate-identity",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    _validate_candidate_identity_payload(
        candidate,
        expected_digest=data["candidate_digest"],
        expected_milestone=data["milestone"],
    )
    artifact_manifest_record = _resolved_evidence_record(
        indexed,
        candidate["artifact_manifest_digest"],
        "release-artifact-manifest",
        "publication reconciliation qualified artifact manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    artifact_manifest = _passing_record(
        artifact_manifest_record,
        "release-artifact-manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualified_artifacts = _validate_artifact_manifest_payload(
        artifact_manifest, expected_milestone=data["milestone"]
    )
    if artifacts != qualified_artifacts:
        raise ReleaseControlError(
            "publication reconciliation artifacts differ from the qualified candidate"
        )
    if candidate["artifact_set_digest"] != artifact_manifest["artifact_set_digest"]:
        raise ReleaseControlError("publication reconciliation candidate artifact-set mismatch")
    if (
        candidate["build_invocation_id"] != artifact_manifest["build_invocation_id"]
        or candidate["source_freeze_digest"] != artifact_manifest["source_freeze_digest"]
    ):
        raise ReleaseControlError("publication reconciliation candidate build binding mismatch")
    evidence_manifest = _passing_record(
        dependencies["evidence_manifest_digest"],
        "release-evidence-manifest",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    lock = _passing_record(
        dependencies["lock_receipt_digest"],
        "release-promotion-lock",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    observations = _passing_record(
        dependencies["observations_digest"],
        "release-publication-observations",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    promotion = _passing_record(
        dependencies["promotion_digest"],
        "release-promotion",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualification = _passing_record(
        dependencies["qualification_digest"],
        "release-qualification",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    retention = _passing_record(
        dependencies["staged_retention_receipts_digest"],
        "release-retention-receipts",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    manifest_fields = {
        "candidate_digest",
        "entries",
        "invocation_journal_digests",
        "manifest_digest",
        "phase",
        "scope_id",
        "scope_kind",
    }
    if set(evidence_manifest) != manifest_fields:
        raise ReleaseControlError(
            "publication reconciliation evidence manifest shape is not closed"
        )
    entries = evidence_manifest["entries"]
    journals = evidence_manifest["invocation_journal_digests"]
    if (
        not isinstance(entries, list)
        or not entries
        or not isinstance(journals, list)
        or not journals
        or any(not isinstance(digest, str) for digest in journals)
        or journals != sorted(set(journals))
    ):
        raise ReleaseControlError("publication reconciliation evidence manifest is incomplete")
    entry_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "media_type",
            "path",
            "role",
            "sha256",
            "size",
        }:
            raise ReleaseControlError(
                "publication reconciliation evidence manifest entry is malformed"
            )
        if (
            not isinstance(entry["media_type"], str)
            or not entry["media_type"]
            or not isinstance(entry["path"], str)
            or not entry["path"]
            or Path(entry["path"]).is_absolute()
            or ".." in Path(entry["path"]).parts
            or not isinstance(entry["role"], str)
            or not entry["role"]
            or isinstance(entry["size"], bool)
            or not isinstance(entry["size"], int)
            or entry["size"] < 0
        ):
            raise ReleaseControlError(
                "publication reconciliation evidence manifest entry is invalid"
            )
        _require_digest(entry["sha256"], "publication evidence manifest entry")
        entry_paths.append(entry["path"])
    if entry_paths != sorted(set(entry_paths)):
        raise ReleaseControlError("publication evidence manifest paths are not canonical")
    manifest_digest = _require_digest(
        evidence_manifest["manifest_digest"], "publication evidence manifest"
    )
    if manifest_digest != sha256_json({"entries": entries, "invocation_journal_digests": journals}):
        raise ReleaseControlError("publication evidence manifest digest mismatch")
    for digest in journals:
        _require_digest(digest, "publication evidence invocation journal")
    if (
        evidence_manifest["phase"] != "qualified-publication"
        or evidence_manifest["scope_kind"] != "release-candidate"
        or evidence_manifest["scope_id"] != candidate["package_version"]
    ):
        raise ReleaseControlError("publication evidence manifest candidate scope mismatch")
    lock_fields = {
        "acquired_index_head",
        "approval_digest",
        "attempt_index_checkpoint_digest",
        "backend_id",
        "candidate_digest",
        "controls_digest",
        "dead_owner_proof_digest",
        "epoch",
        "expected_index_head",
        "lease_expires_at",
        "lease_started_at",
        "lock_token",
        "mutation_started",
        "operation_id",
        "owner",
        "promotion_plan_digest",
        "recovery_authorization_digest",
        "state",
        "target_state_digest",
    }
    if set(lock) != lock_fields or lock["backend_id"] != "attempt-index":
        raise ReleaseControlError("publication reconciliation promotion lock shape is not closed")
    if isinstance(lock["epoch"], bool) or not isinstance(lock["epoch"], int) or lock["epoch"] < 1:
        raise ReleaseControlError("publication reconciliation promotion lock epoch is invalid")
    for field in (
        "acquired_index_head",
        "approval_digest",
        "attempt_index_checkpoint_digest",
        "controls_digest",
        "expected_index_head",
        "promotion_plan_digest",
        "target_state_digest",
    ):
        _require_digest(lock[field], f"publication reconciliation promotion lock {field}")
    lock_started_at = _parse_utc_timestamp(lock["lease_started_at"], "promotion lock lease start")
    lock_expires_at = _parse_utc_timestamp(lock["lease_expires_at"], "promotion lock lease expiry")
    if lock_expires_at <= lock_started_at:
        raise ReleaseControlError("publication reconciliation promotion lock lease is invalid")
    for field in ("lock_token", "operation_id", "owner"):
        _require_nonempty_string(lock[field], f"publication reconciliation promotion lock {field}")
    for field in ("dead_owner_proof_digest", "recovery_authorization_digest"):
        if lock[field] is not None:
            _require_digest(lock[field], f"publication reconciliation promotion lock {field}")
    promotion_fields = {
        "actions",
        "candidate_digest",
        "completed_at",
        "lock_receipt_digest",
        "mode",
        "mutation_started",
        "operation_id",
        "promotion_plan_digest",
        "publisher_id",
        "record_kind",
        "result",
        "started_at",
        "target_state_digest",
    }
    if set(promotion) != promotion_fields:
        raise ReleaseControlError("publication reconciliation promotion shape is not closed")
    if (
        promotion["mode"] != "execute"
        or promotion["record_kind"] != "promotion_execution"
        or not isinstance(promotion["actions"], list)
        or not promotion["actions"]
    ):
        raise ReleaseControlError("publication reconciliation promotion is malformed")
    promotion_started_at = _parse_utc_timestamp(promotion["started_at"], "promotion start")
    promotion_completed_at = _parse_utc_timestamp(promotion["completed_at"], "promotion completion")
    if (
        promotion_started_at < lock_started_at
        or promotion_completed_at < promotion_started_at
        or promotion_completed_at > lock_expires_at
    ):
        raise ReleaseControlError("publication reconciliation promotion timing is invalid")
    promotion_target_ids: list[str] = []
    for action in promotion["actions"]:
        if not isinstance(action, dict) or set(action) != {
            "action",
            "observed_digest",
            "result",
            "target_id",
        }:
            raise ReleaseControlError("publication reconciliation promotion action is malformed")
        if (
            not isinstance(action["action"], str)
            or not action["action"]
            or not isinstance(action["target_id"], str)
            or not action["target_id"]
            or action["result"] != "PASS"
        ):
            raise ReleaseControlError("publication reconciliation promotion action did not pass")
        _require_digest(action["observed_digest"], "publication promotion action")
        promotion_target_ids.append(action["target_id"])
    if promotion_target_ids != sorted(set(promotion_target_ids)):
        raise ReleaseControlError("publication reconciliation promotion actions are not canonical")
    observation_fields = {
        "all_targets_observed",
        "artifact_manifest_digest",
        "candidate_digest",
        "lock_receipt_digest",
        "observation_digest",
        "observed_at",
        "promotion_digest",
        "targets",
    }
    if set(observations) != observation_fields:
        raise ReleaseControlError("publication reconciliation observation shape is not closed")
    for field in (
        "artifact_manifest_digest",
        "lock_receipt_digest",
        "observation_digest",
        "promotion_digest",
    ):
        _require_digest(observations[field], f"publication reconciliation observation {field}")
    _parse_utc_timestamp(observations["observed_at"], "publication observation time")
    _validate_retention_payload(
        retention,
        expected_input_digest=data["evidence_manifest_digest"],
        expected_phase="qualified-publication",
        label="publication reconciliation retention",
    )
    if live or retention_readbacks is not None:
        _validate_observed_store_readbacks(
            retention["stores"],
            expected_digest=data["evidence_manifest_digest"],
            readbacks=retention_readbacks,
            label="publication reconciliation retention",
        )
    candidate_digest = data["candidate_digest"]
    candidate_bindings = {
        "approval": approval.get("candidate_digest"),
        "evidence manifest": evidence_manifest.get("candidate_digest"),
        "lock": lock.get("candidate_digest"),
        "observations": observations.get("candidate_digest"),
        "promotion": promotion.get("candidate_digest"),
        "qualification": qualification.get("candidate_digest"),
        "candidate identity": candidate.get("candidate_digest"),
    }
    for label, observed_candidate in candidate_bindings.items():
        if observed_candidate != candidate_digest:
            raise ReleaseControlError(f"publication reconciliation {label} candidate mismatch")
    if (
        lock.get("approval_digest") != data["approval_digest"]
        or approval.get("qualification_digest", data["qualification_digest"])
        != data["qualification_digest"]
        or promotion.get("lock_receipt_digest") != data["lock_receipt_digest"]
        or observations.get("lock_receipt_digest") != data["lock_receipt_digest"]
        or observations.get("promotion_digest") != data["promotion_digest"]
        or observations.get("artifact_manifest_digest") != candidate["artifact_manifest_digest"]
        or promotion.get("operation_id") != lock.get("operation_id")
        or promotion.get("promotion_plan_digest") != lock.get("promotion_plan_digest")
        or promotion.get("target_state_digest") != lock.get("target_state_digest")
        or promotion.get("publisher_id") != lock.get("owner")
    ):
        raise ReleaseControlError("publication reconciliation control binding mismatch")
    if (
        lock.get("state") != "COMMITTED"
        or lock.get("mutation_started") is not True
        or promotion.get("result") != "PUBLISHED"
        or promotion.get("mutation_started") is not True
        or observations.get("all_targets_observed") is not True
        or evidence_manifest.get("phase") != "qualified-publication"
    ):
        raise ReleaseControlError("publication reconciliation dependencies are not final")

    expected = {artifact["path"]: (artifact["sha256"], artifact["size"]) for artifact in artifacts}
    manifest_artifacts = [
        {
            "media_type": entry["media_type"],
            "path": entry["path"],
            "sha256": entry["sha256"],
            "size": entry["size"],
        }
        for entry in entries
        if entry["role"] == "release-artifact"
    ]
    if manifest_artifacts != artifacts:
        raise ReleaseControlError(
            "publication reconciliation evidence entries differ from qualified artifacts"
        )
    if retention["input_digest"] != data["evidence_manifest_digest"]:
        raise ReleaseControlError("publication reconciliation retention input binding mismatch")
    if promotion_target_ids != target_ids:
        raise ReleaseControlError("publication reconciliation promotion target set differs")
    observation_targets = observations.get("targets")
    if not isinstance(observation_targets, list) or not observation_targets:
        raise ReleaseControlError("publication reconciliation observations have no targets")
    observed_target_ids: list[str] = []
    for target in observation_targets:
        if not isinstance(target, dict) or set(target) != {
            "artifacts",
            "availability",
            "immutability",
            "provider_receipt_digest",
            "raw_result_digest",
            "target_id",
            "uri",
        }:
            raise ReleaseControlError("publication reconciliation observation target is malformed")
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ReleaseControlError("publication reconciliation observation target id is missing")
        if target.get("availability") != "present" or target.get("immutability") != "immutable":
            raise ReleaseControlError("publication reconciliation observed a non-final target")
        _require_digest(
            target["provider_receipt_digest"], "publication observation provider receipt"
        )
        _require_digest(target["raw_result_digest"], "publication observation raw result")
        if not isinstance(target["uri"], str) or not target["uri"]:
            raise ReleaseControlError("publication reconciliation observation URI is missing")
        observed_artifacts = target.get("artifacts")
        if not isinstance(observed_artifacts, list) or len(observed_artifacts) != len(expected):
            raise ReleaseControlError(
                "publication reconciliation observed artifact set is incomplete"
            )
        observed_artifact_set: dict[str, tuple[object, object]] = {}
        for artifact in observed_artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {
                "expected_digest",
                "name",
                "observed_digest",
                "size",
            }:
                raise ReleaseControlError(
                    "publication reconciliation observed artifact is malformed"
                )
            name = artifact["name"]
            if not isinstance(name, str) or name in observed_artifact_set:
                raise ReleaseControlError(
                    "publication reconciliation observed artifact name is invalid"
                )
            if artifact["expected_digest"] != artifact["observed_digest"]:
                raise ReleaseControlError("publication reconciliation observed bytes differ")
            observed_artifact_set[name] = (artifact["observed_digest"], artifact["size"])
        if observed_artifact_set != expected:
            raise ReleaseControlError("publication reconciliation observed artifact set differs")
        observed_target_ids.append(target_id)
    if observed_target_ids != target_ids:
        raise ReleaseControlError("publication reconciliation observed target set differs")


def validate_release_gate_instance_record(
    record: Mapping[str, Any],
    *,
    candidate_identity_record: Mapping[str, Any],
    predecessor_record: Mapping[str, Any],
    task_state_policy: Mapping[str, Any],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    gate = _passing_record(
        record,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    candidate = _passing_record(
        candidate_identity_record,
        "release-candidate-identity",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    predecessor = _passing_record(
        predecessor_record,
        "release-predecessor",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    bindings = {
        "candidate identity": (
            gate.get("candidate_identity_digest"),
            sha256_json(candidate_identity_record),
        ),
        "candidate": (gate.get("candidate_digest"), candidate.get("candidate_digest")),
        "predecessor": (gate.get("predecessor_digest"), sha256_json(predecessor_record)),
        "candidate predecessor": (
            candidate.get("predecessor_digest"),
            sha256_json(predecessor_record),
        ),
        "milestone": (gate.get("milestone"), candidate.get("milestone")),
        "package version": (gate.get("package_version"), candidate.get("package_version")),
        "release tag": (gate.get("release_tag"), candidate.get("release_tag")),
        "gate input": (gate.get("gate_input_digest"), candidate.get("gate_input_digest")),
        "task-state policy": (
            gate.get("task_state_policy_digest"),
            sha256_json(task_state_policy),
        ),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"release gate {label} binding mismatch")
    if predecessor.get("candidate_milestone") != gate.get("milestone"):
        raise ReleaseControlError("release gate predecessor milestone mismatch")


def validate_release_qualification_plan_record(
    record: Mapping[str, Any],
    *,
    gate_instance: Mapping[str, Any],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    plan = _passing_record(
        record,
        "release-qualification-plan",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    gate = _passing_record(
        gate_instance,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    _validate_qualification_plan_payload(plan)
    bindings = {
        "gate instance": (plan["gate_instance_digest"], sha256_json(gate_instance)),
        "candidate": (plan["candidate_digest"], gate.get("candidate_digest")),
        "predecessor": (plan["predecessor_digest"], gate.get("predecessor_digest")),
        "milestone": (plan["milestone"], gate.get("milestone")),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"release qualification plan {label} binding mismatch")


def _validate_release_approval_decision_record(
    record: Mapping[str, Any],
    *,
    approval: Mapping[str, Any],
    gate: Mapping[str, Any],
    qualification: Mapping[str, Any],
    roles: Mapping[str, tuple[str, str]],
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None,
    expected_authority_policy_digest: str | None,
) -> None:
    decision = _passing_record(
        record,
        "release-approval-decision",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    expected_fields = {
        "approval_kind",
        "author_id",
        "authority_policy_digest",
        "candidate_digest",
        "conflicts",
        "decision",
        "expires_at",
        "issued_at",
        "milestone",
        "qualification_digest",
        "reviewer_id",
        "rubric_result_digest",
        "signing_method",
    }
    live_fields = {"provider_attestation_keyring_digest"}
    allowed_fields = expected_fields | live_fields
    if (live and set(decision) != allowed_fields) or (
        not live
        and frozenset(decision) not in {frozenset(expected_fields), frozenset(allowed_fields)}
    ):
        raise ReleaseControlError("release approval decision data shape is not closed")
    if (
        decision["approval_kind"] != "non_author_release_decision"
        or decision["decision"] != "APPROVED"
        or decision["conflicts"] != []
        or decision["signing_method"] != "provider-attestation-v1"
    ):
        raise ReleaseControlError("release approval decision is not a clean approval")
    policy_digest = _require_digest(
        decision["authority_policy_digest"], "approval decision authority policy"
    )
    if live:
        if expected_authority_policy_digest is None:
            raise ReleaseControlError("approval decision authority policy identity is not supplied")
        if policy_digest != _require_digest(
            expected_authority_policy_digest,
            "expected approval authority policy",
        ):
            raise ReleaseControlError("release approval decision authority policy binding mismatch")
        if attestation_verifier is None or attestation_verifier.keyring_digest is None:
            raise ReleaseControlError("approval decision trust-root identity is not supplied")
        decision_keyring_digest = _require_digest(
            decision["provider_attestation_keyring_digest"],
            "approval decision provider attestation keyring",
        )
        if decision_keyring_digest != attestation_verifier.keyring_digest:
            raise ReleaseControlError("release approval decision provider keyring binding mismatch")
        if policy_digest != release_authority_policy_digest(decision_keyring_digest):
            raise ReleaseControlError("release approval authority policy does not bind its keyring")
    _require_digest(decision["candidate_digest"], "approval decision candidate")
    _require_digest(decision["qualification_digest"], "approval decision qualification")
    _require_nonempty_string(decision["author_id"], "approval decision author")
    _require_nonempty_string(decision["reviewer_id"], "approval decision reviewer")
    if decision["milestone"] not in MILESTONES:
        raise ReleaseControlError("release approval decision milestone is invalid")
    if decision["rubric_result_digest"] is not None:
        _require_digest(decision["rubric_result_digest"], "approval decision rubric")
    issued_at = _parse_utc_timestamp(decision["issued_at"], "approval decision issue time")
    expires_at = _parse_utc_timestamp(decision["expires_at"], "approval decision expiry")
    if expires_at <= issued_at:
        raise ReleaseControlError("release approval decision validity window is invalid")
    if live and not issued_at <= datetime.now(UTC) < expires_at:
        raise ReleaseControlError("release approval decision is not currently valid")
    author_identity = roles["author_id"]
    reviewer_identity = roles["non_author_reviewer_id"]
    bindings = {
        "author": (decision["author_id"], author_identity[1]),
        "reviewer": (decision["reviewer_id"], reviewer_identity[1]),
        "approval author": (decision["author_id"], approval["author_id"]),
        "approval reviewer": (decision["reviewer_id"], approval["reviewer_id"]),
        "candidate": (decision["candidate_digest"], approval["candidate_digest"]),
        "gate candidate": (decision["candidate_digest"], gate.get("candidate_digest")),
        "milestone": (decision["milestone"], gate.get("milestone")),
        "qualification": (decision["qualification_digest"], sha256_json(qualification)),
        "approval rubric": (decision["rubric_result_digest"], approval["rubric_result_digest"]),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"release approval decision {label} binding mismatch")
    if reviewer_identity == author_identity:
        raise ReleaseControlError("release approval decision is not independent")
    signers = _validated_record_signers(
        record,
        live=live,
        attestation_verifier=attestation_verifier,
    )
    if reviewer_identity not in signers:
        raise ReleaseControlError("release approval decision lacks reviewer authority")


def validate_release_approval_record(
    record: Mapping[str, Any],
    *,
    approval_decision: Mapping[str, Any],
    gate_instance: Mapping[str, Any],
    qualification: Mapping[str, Any],
    role_assignments: Mapping[str, Any],
    no_prepublication_rubric: bool,
    live: bool,
    expected_authority_policy_digest: str | None = None,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    approval = _passing_record(
        record,
        "release-approval",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    gate = _passing_record(
        gate_instance,
        "release-gate-instance",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    qualification_data = _passing_record(
        qualification,
        "release-qualification",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    basic = {"author_id", "candidate_digest", "conflicts", "decision", "reviewer_id"}
    extended = {
        "approval_decision_digest",
        "gate_instance_digest",
        "qualification_digest",
        "rubric_result_digest",
    }
    if set(approval) != basic | extended:
        raise ReleaseControlError("release approval data shape is not closed")
    if approval["decision"] != "APPROVED" or approval["conflicts"] != []:
        raise ReleaseControlError("release approval is not conflict-free and approved")
    milestone = gate.get("milestone")
    run_id = gate.get("run_id")
    if not isinstance(milestone, str) or milestone not in MILESTONES:
        raise ReleaseControlError("release approval gate milestone is invalid")
    run_id = _require_nonempty_string(run_id, "release approval gate run id")
    roles = validate_role_assignments(
        role_assignments,
        live=live,
        expected_milestone=milestone,
        expected_run_id=run_id,
        expected_authority_policy_digest=expected_authority_policy_digest,
        check_conflicts=True,
        check_freshness=live,
        attestation_verifier=attestation_verifier,
    )
    author = approval["author_id"]
    reviewer = approval["reviewer_id"]
    author_identity = roles["author_id"]
    reviewer_identity = roles["non_author_reviewer_id"]
    if author != author_identity[1]:
        raise ReleaseControlError("release approval author does not match assigned roles")
    if reviewer_identity == author_identity or reviewer != reviewer_identity[1]:
        raise ReleaseControlError("release approval is not from the assigned non-author reviewer")
    if approval["candidate_digest"] != gate.get("candidate_digest") or approval[
        "candidate_digest"
    ] != qualification_data.get("candidate_digest"):
        raise ReleaseControlError("release approval candidate binding mismatch")
    if approval["gate_instance_digest"] != sha256_json(gate_instance):
        raise ReleaseControlError("release approval gate-instance binding mismatch")
    if approval["qualification_digest"] != sha256_json(qualification):
        raise ReleaseControlError("release approval qualification binding mismatch")
    if no_prepublication_rubric and approval.get("rubric_result_digest") is not None:
        raise ReleaseControlError("prepublication approval unexpectedly names a rubric result")
    if not no_prepublication_rubric:
        _require_digest(approval["rubric_result_digest"], "approval rubric result")
    decision_digest = _require_digest(approval["approval_decision_digest"], "approval decision")
    if decision_digest != sha256_json(approval_decision):
        raise ReleaseControlError("release approval decision does not resolve to exact bytes")
    _validate_release_approval_decision_record(
        approval_decision,
        approval=approval,
        gate=gate,
        qualification=qualification,
        roles=roles,
        live=live,
        attestation_verifier=attestation_verifier,
        expected_authority_policy_digest=expected_authority_policy_digest,
    )
    signers = {
        _validated_signature(
            signature,
            subject_digest=signature_subject_digest(record),
            live=live,
            attestation_verifier=attestation_verifier,
        )
        for signature in record["signatures"]
    }
    if reviewer_identity not in signers:
        raise ReleaseControlError("release approval lacks reviewer-authenticated authority")


def validate_release_candidate_identity_record(
    record: Mapping[str, Any],
    *,
    predecessor_record: Mapping[str, Any],
    candidate_dir: Path,
    no_evaluation_adoption: bool,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
    _active_invocation: ReleaseInvocation | None = None,
) -> None:
    """Recompute identity and require the original committed finalization evidence."""
    _validate_candidate_public(
        record,
        predecessor_record=predecessor_record,
        candidate_dir=candidate_dir,
        no_evaluation_adoption=no_evaluation_adoption,
        live=live,
        attestation_verifier=attestation_verifier,
        active_invocation=_active_invocation,
    )


def _regular_file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ReleaseControlError(f"artifact is missing or not a regular file: {path}")
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ReleaseControlError(f"cannot read artifact bytes: {path}") from exc


def validate_release_artifact_files(
    record: Mapping[str, Any],
    artifacts: Path,
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None = None,
    record_path: Path | None = None,
) -> None:
    """Bind every publishable byte and filename to the frozen-source manifest."""

    validate_record(record, "release-artifact-manifest")
    if record["status"] != "PASS":
        raise ReleaseControlError("artifact manifest is not passing authority")
    if live and record["synthetic"] is not False:
        raise ReleaseControlError("synthetic artifact manifests cannot authorize live publication")
    _validated_record_signers(
        record,
        live=live,
        attestation_verifier=attestation_verifier,
    )
    manifest_path = (
        artifacts.parent / "artifact-manifest.json" if record_path is None else record_path
    )
    if _safe_release_bytes(manifest_path) != canonical_json(record):
        raise ReleaseControlError("artifact manifest retained bytes mismatch")
    validate_release_producer_journal(record, manifest_path, producer="build_release_artifacts.py")
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise ReleaseControlError("artifact directory is missing or unsafe")
    data = _release_data(
        record,
        {
            "artifact_set_digest",
            "artifacts",
            "build_invocation_id",
            "build_recipe_digest",
            "invocation_root_locator",
            "producer_intent_digest",
            "milestone",
            "source_digest",
            "source_freeze_digest",
            "target_resolution_digest",
        },
        "release artifact manifest",
    )
    rows = data["artifacts"]
    if not isinstance(rows, list) or len(rows) != 2:
        raise ReleaseControlError("artifact manifest must name exactly one wheel and one sdist")
    expected_names: set[str] = set()
    expected_types = {
        ".whl": "application/vnd.pypa.wheel+zip",
        ".tar.gz": "application/gzip",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"media_type", "path", "sha256", "size"}:
            raise ReleaseControlError("artifact manifest row shape is not closed")
        name = row["path"]
        if not isinstance(name, str) or Path(name).name != name or name in expected_names:
            raise ReleaseControlError("artifact manifest contains an unsafe or duplicate filename")
        suffix = ".tar.gz" if name.endswith(".tar.gz") else Path(name).suffix
        if suffix not in expected_types or row["media_type"] != expected_types[suffix]:
            raise ReleaseControlError(f"artifact media type does not match filename: {name}")
        path = artifacts / name
        digest = _regular_file_digest(path)
        if digest != _require_digest(row["sha256"], f"artifact {name}"):
            raise ReleaseControlError(f"artifact digest differs from frozen manifest: {name}")
        if isinstance(row["size"], bool) or row["size"] != path.stat().st_size:
            raise ReleaseControlError(f"artifact size differs from frozen manifest: {name}")
        expected_names.add(name)
    if [row["path"] for row in rows] != sorted(expected_names):
        raise ReleaseControlError("artifact manifest rows are not canonically ordered")
    observed_entries = list(artifacts.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in observed_entries):
        raise ReleaseControlError("artifact directory contains an unsafe non-artifact entry")
    observed_names = {path.name for path in observed_entries}
    if observed_names != expected_names:
        raise ReleaseControlError("artifact directory membership differs from frozen manifest")
    if data["artifact_set_digest"] != sha256_json(rows):
        raise ReleaseControlError("artifact set digest does not bind the manifest rows")


def validate_release_retention_receipts(
    receipts: Mapping[str, Any],
    *,
    inputs: Sequence[Path],
    manifest: Path | None,
    invocation_root: Path | None,
    through_stage: str | None,
    live: bool,
    readbacks: Mapping[str, Path] | None = None,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    """Validate two independent read-backs against the supplied canonical input."""

    validate_record(receipts, "release-retention-receipts")
    if receipts["status"] != "PASS":
        raise ReleaseControlError("retention receipt set is not passing")
    if live and receipts["synthetic"] is not False:
        raise ReleaseControlError("synthetic retention receipts cannot authorize a live release")
    _validated_record_signers(
        receipts,
        live=live,
        attestation_verifier=attestation_verifier,
    )
    data = _release_data(
        receipts,
        {
            "all_content_equal",
            "input_digest",
            "phase",
            "receipt_set_digest",
            "retained_at",
            "stores",
        },
        "release retention receipts",
    )
    if data["all_content_equal"] is not True:
        raise ReleaseControlError("retention stores did not report identical content")
    stores = data["stores"]
    if not isinstance(stores, list) or len(stores) != 2:
        raise ReleaseControlError("retention requires exactly two store receipts")
    if [row.get("store_id") for row in stores if isinstance(row, dict)] != [
        "payload-store-a",
        "payload-store-b",
    ]:
        raise ReleaseControlError("retention stores are missing or not canonically ordered")
    independence_groups: set[str] = set()
    input_digest = _require_digest(data["input_digest"], "retained input")
    required_store_fields = {
        "content_digest",
        "hold_receipt_digest",
        "independence_group",
        "namespace",
        "object_key",
        "put_receipt_digest",
        "read_back_digest",
        "store_id",
    }
    for row in stores:
        if not isinstance(row, dict) or set(row) != required_store_fields:
            raise ReleaseControlError("retention store receipt shape is not closed")
        group = row["independence_group"]
        if not isinstance(group, str) or not group.strip():
            raise ReleaseControlError("retention store independence group is missing")
        independence_groups.add(group)
        for field in (
            "content_digest",
            "hold_receipt_digest",
            "put_receipt_digest",
            "read_back_digest",
        ):
            _require_digest(row[field], f"retention {field}")
        if row["content_digest"] != input_digest or row["read_back_digest"] != input_digest:
            raise ReleaseControlError("retention read-back differs from the canonical input")
    if len(independence_groups) != 2:
        raise ReleaseControlError("retention stores are not independently administered")
    if data["receipt_set_digest"] != sha256_json(stores):
        raise ReleaseControlError("retention receipt-set digest mismatch")

    supplied_digests: list[str] = []
    for path in inputs:
        record = read_json(path)
        validate_record(record)
        _validated_record_signers(
            record,
            live=live,
            attestation_verifier=attestation_verifier,
        )
        supplied_digests.append(_regular_file_digest(path))
    if manifest is not None:
        manifest_record = _release_input(
            manifest,
            "release-evidence-manifest",
            live=live,
            attestation_verifier=attestation_verifier,
        )
        manifest_digest = _regular_file_digest(manifest)
        entries = manifest_record["data"].get("entries")
        if not isinstance(entries, list):
            raise ReleaseControlError("evidence manifest entries are missing")
        listed = {
            entry.get("sha256")
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("sha256"), str)
        }
        if any(digest not in listed for digest in supplied_digests):
            raise ReleaseControlError("retained input is absent from the evidence manifest")
        expected_input_digest = manifest_digest
    elif len(supplied_digests) == 1:
        expected_input_digest = supplied_digests[0]
    elif supplied_digests:
        expected_input_digest = sha256_json(sorted(supplied_digests))
    else:
        raise ReleaseControlError("retention validation has no canonical input")
    if input_digest != expected_input_digest:
        raise ReleaseControlError("retention receipts bind a different canonical input")
    if live or readbacks is not None:
        _validate_observed_store_readbacks(
            stores,
            expected_digest=expected_input_digest,
            readbacks=readbacks,
            label="release retention",
        )
    if (invocation_root is None) != (through_stage is None):
        raise ReleaseControlError("invocation-root and through-stage must be supplied together")
    if invocation_root is not None and (
        invocation_root.is_symlink() or not invocation_root.is_dir() or not through_stage
    ):
        raise ReleaseControlError("retention invocation journal is missing or unsafe")


def _validated_readiness_blockers(readiness_registry: Mapping[str, Any]) -> list[str]:
    raw_blockers = readiness_registry.get("blockers")
    if not isinstance(raw_blockers, list):
        raise ReleaseControlError("readiness registry blockers must be a list")
    codes: list[str] = []
    required_fields = {"code", "resolver"}
    count_fields = {"required_count", "resolved_count"}
    for blocker in raw_blockers:
        if not isinstance(blocker, dict):
            raise ReleaseControlError("readiness registry blocker must be an object")
        fields = set(blocker)
        if not required_fields.issubset(fields) or not fields.issubset(
            required_fields | count_fields
        ):
            raise ReleaseControlError("readiness registry blocker shape is not closed")
        if bool(fields & count_fields) and not count_fields.issubset(fields):
            raise ReleaseControlError("readiness registry blocker counts are incomplete")
        code = _require_nonempty_string(blocker["code"], "readiness blocker code")
        _require_nonempty_string(blocker["resolver"], "readiness blocker resolver")
        if count_fields.issubset(fields):
            required_count = blocker["required_count"]
            resolved_count = blocker["resolved_count"]
            if (
                isinstance(required_count, bool)
                or not isinstance(required_count, int)
                or required_count < 0
                or isinstance(resolved_count, bool)
                or not isinstance(resolved_count, int)
                or resolved_count < 0
                or resolved_count > required_count
            ):
                raise ReleaseControlError("readiness registry blocker counts are invalid")
        codes.append(code)
    if codes != sorted(set(codes)):
        raise ReleaseControlError("readiness registry blockers are not canonical")
    return codes


def build_release_readiness_record(
    *,
    gate_input: Mapping[str, Any],
    gate_instance: Mapping[str, Any],
    candidate_identity_record: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    linear_snapshot: Mapping[str, Any],
    source_freeze: Mapping[str, Any],
    impact_manifest: Mapping[str, Any],
    artifact_manifest: Mapping[str, Any],
    delta: Mapping[str, Any],
    delta_test_map: Mapping[str, Any],
    readiness_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one deterministic readiness decision from exact, cross-bound inputs."""

    if not isinstance(readiness_registry, Mapping):
        raise ReleaseControlError("readiness registry must be an object")

    typed = (
        (gate_input, "release-gate-input"),
        (gate_instance, "release-gate-instance"),
        (candidate_identity_record, "release-candidate-identity"),
        (predecessor, "release-predecessor"),
        (linear_snapshot, "linear-release-snapshot"),
        (source_freeze, "release-source-freeze"),
        (impact_manifest, "release-impact-manifest"),
        (artifact_manifest, "release-artifact-manifest"),
        (delta, "release-capability-delta"),
        (delta_test_map, "release-delta-test-map"),
    )
    for record, expected_type in typed:
        validate_record(record, expected_type)
        if record["status"] not in {"PASS", "READY"}:
            raise ReleaseControlError(f"{expected_type} is not passing authority")
    synthetic_modes = {record["synthetic"] for record, _ in typed}
    if len(synthetic_modes) != 1:
        raise ReleaseControlError("readiness inputs mix live and synthetic authority")

    gate_input_data = gate_input["data"]
    gate = gate_instance["data"]
    candidate = candidate_identity_record["data"]
    predecessor_data = predecessor["data"]
    linear = linear_snapshot["data"]
    freeze = source_freeze["data"]
    impact = impact_manifest["data"]
    artifact = artifact_manifest["data"]
    delta_data = delta["data"]
    mapping = delta_test_map["data"]
    if not all(
        isinstance(value, dict)
        for value in (
            gate_input_data,
            gate,
            candidate,
            predecessor_data,
            linear,
            freeze,
            impact,
            artifact,
            delta_data,
            mapping,
        )
    ):
        raise ReleaseControlError("readiness subject data must be closed objects")
    exact_shapes = (
        (
            gate_input_data,
            {
                "environment_registry_digest",
                "evidence_store_registry_digest",
                "expected_predecessor_milestone",
                "gate_input_digest",
                "linear_snapshot_digest",
                "milestone",
                "obligation_registry_digest",
                "readiness_registry_digest",
                "role_assignments_digest",
                "run_id",
                "scenario_registry_digest",
                "target_burn_digest",
                "target_burn_index_receipt_digest",
                "target_registry_digest",
                "target_resolution_digest",
                "task_state_policy_digest",
            },
            "gate input",
        ),
        (
            gate,
            {
                "candidate_digest",
                "candidate_identity_digest",
                "environment_registry_digest",
                "evidence_store_preflight_digest",
                "evidence_store_registry_digest",
                "frozen_source_sha",
                "gate_input_digest",
                "instance_digest",
                "linear_snapshot_digest",
                "main_health_digest",
                "main_health_history_digest",
                "milestone",
                "obligation_registry_digest",
                "package_version",
                "predecessor_digest",
                "release_tag",
                "repository_protection_digest",
                "run_id",
                "scenario_registry_digest",
                "target_registry_digest",
                "task_state_policy_digest",
            },
            "gate instance",
        ),
        (candidate, _CANDIDATE_FIELDS, "candidate identity"),
        (
            linear,
            {
                "required_bom_ids",
                "required_bom_snapshot_digest",
                "state",
                "task_id",
                "tool",
            },
            "Linear snapshot",
        ),
        (
            freeze,
            {
                "build_recipe_digest",
                "dirty",
                "freeze_digest",
                "frozen_at",
                "gate_input_digest",
                "milestone",
                "registry_inputs",
                "release_notes_digest",
                "source_sha",
                "source_tree",
                "version_metadata_digest",
                "workflow_inputs",
                "invocation_root_locator",
                "producer_intent_digest",
            },
            "source freeze",
        ),
        (
            impact,
            {
                "author_id",
                "base_sha",
                "changes",
                "head_sha",
                "manifest_digest",
                "milestone",
                "release_tag",
                "source_freeze_digest",
                "target_resolution_digest",
                "unclassified_paths",
            },
            "impact manifest",
        ),
        (
            artifact,
            {
                "artifact_set_digest",
                "artifacts",
                "build_invocation_id",
                "build_recipe_digest",
                "milestone",
                "source_digest",
                "source_freeze_digest",
                "target_resolution_digest",
                "invocation_root_locator",
                "producer_intent_digest",
            },
            "artifact manifest",
        ),
        (
            delta_data,
            {
                "added",
                "candidate_sha",
                "changed",
                "delta_digest",
                "impact_manifest_digest",
                "milestone",
                "predecessor_digest",
                "removed",
            },
            "capability delta",
        ),
        (
            mapping,
            {
                "delta_digest",
                "environment_registry_digest",
                "impact_manifest_digest",
                "map_digest",
                "mappings",
                "milestone",
                "obligation_registry_digest",
                "scenario_registry_digest",
                "unmapped_capabilities",
            },
            "delta test map",
        ),
    )
    for value, expected_fields, label in exact_shapes:
        if set(value) != expected_fields:
            raise ReleaseControlError(f"readiness {label} data shape is not closed")
    _validate_candidate_identity_payload(
        candidate,
        expected_digest=candidate["candidate_digest"],
        expected_milestone=candidate["milestone"],
    )
    predecessor_required = {
        "candidate_milestone",
        "closed_decision_digest",
        "lkg_digest",
        "version",
    }
    predecessor_allowed = predecessor_required | {
        "chain_head",
        "completion_digest",
        "pointer_envelope_digest",
        "pointer_index_receipt_digest",
        "predecessor_milestone",
        "qualification_digest",
        "reconciliation_digest",
    }
    if not predecessor_required <= set(predecessor_data) <= predecessor_allowed:
        raise ReleaseControlError("readiness predecessor data shape is not closed")
    if freeze["dirty"] is not False:
        raise ReleaseControlError("readiness source freeze is dirty")
    for subject in (freeze, artifact):
        if subject["invocation_root_locator"] != "invocations":
            raise ReleaseControlError("readiness producer invocation locator is unsafe")
        _require_digest(subject["producer_intent_digest"], "readiness producer intent")
    for field in (
        "build_recipe_digest",
        "freeze_digest",
        "gate_input_digest",
        "release_notes_digest",
        "version_metadata_digest",
    ):
        _require_digest(freeze[field], f"readiness source freeze {field}")
    for field in ("source_sha", "source_tree"):
        value = freeze[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ReleaseControlError(f"readiness source freeze {field} is not a Git SHA")
    if (
        not isinstance(freeze["registry_inputs"], list)
        or not freeze["registry_inputs"]
        or not isinstance(freeze["workflow_inputs"], list)
        or not freeze["workflow_inputs"]
    ):
        raise ReleaseControlError("readiness source freeze input inventory is incomplete")
    if impact["unclassified_paths"] != []:
        raise ReleaseControlError("readiness impact manifest has unclassified paths")
    if not isinstance(impact["author_id"], str) or not impact["author_id"].strip():
        raise ReleaseControlError("readiness impact manifest author is missing")
    if not isinstance(impact["changes"], list):
        raise ReleaseControlError("readiness impact manifest changes are not an array")
    for field in ("manifest_digest", "source_freeze_digest", "target_resolution_digest"):
        _require_digest(impact[field], f"readiness impact manifest {field}")
    for field in ("base_sha", "head_sha"):
        value = impact[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ReleaseControlError(f"readiness impact manifest {field} is not a Git SHA")
    task_id = linear["task_id"]
    tool = linear["tool"]
    if linear["state"] != "In Progress":
        raise ReleaseControlError("readiness Linear decision is not open and running")
    if not isinstance(task_id, str) or not task_id:
        raise ReleaseControlError("readiness Linear task id is missing")
    if not isinstance(tool, str) or "linear" not in tool.lower():
        raise ReleaseControlError("readiness Linear snapshot tool is not provider-bound")
    artifact_rows = artifact["artifacts"]
    if not isinstance(artifact_rows, list) or len(artifact_rows) != 2:
        raise ReleaseControlError("readiness artifact manifest is not one wheel and one sdist")
    artifact_names: list[str] = []
    artifact_suffixes: set[str] = set()
    artifact_media = {
        ".whl": "application/vnd.pypa.wheel+zip",
        ".tar.gz": "application/gzip",
    }
    for row in artifact_rows:
        if not isinstance(row, dict) or set(row) != {"media_type", "path", "sha256", "size"}:
            raise ReleaseControlError("readiness artifact manifest row is malformed")
        name = row["path"]
        if not isinstance(name, str) or Path(name).name != name:
            raise ReleaseControlError("readiness artifact manifest path is unsafe")
        suffix = ".tar.gz" if name.endswith(".tar.gz") else Path(name).suffix
        if suffix not in artifact_media or row["media_type"] != artifact_media[suffix]:
            raise ReleaseControlError("readiness artifact media type is invalid")
        artifact_suffixes.add(suffix)
        artifact_names.append(name)
        _require_digest(row["sha256"], f"readiness artifact {name}")
        if isinstance(row["size"], bool) or not isinstance(row["size"], int) or row["size"] < 1:
            raise ReleaseControlError("readiness artifact manifest size is invalid")
    if artifact_names != sorted(set(artifact_names)):
        raise ReleaseControlError("readiness artifact manifest is not canonical")
    if artifact_suffixes != set(artifact_media):
        raise ReleaseControlError("readiness artifact manifest lacks a wheel or sdist")
    if artifact["artifact_set_digest"] != sha256_json(artifact_rows):
        raise ReleaseControlError("readiness artifact-set digest mismatch")

    delta_capability_ids: list[str] = []
    for disposition, before_required, after_required in (
        ("added", False, True),
        ("changed", True, True),
        ("removed", True, False),
    ):
        rows = delta_data[disposition]
        if not isinstance(rows, list):
            raise ReleaseControlError(f"readiness {disposition} capability delta is malformed")
        disposition_ids: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "after_digest",
                "before_digest",
                "capability_id",
            }:
                raise ReleaseControlError(
                    f"readiness {disposition} capability delta row is malformed"
                )
            capability_id = row["capability_id"]
            if not isinstance(capability_id, str) or not capability_id:
                raise ReleaseControlError("readiness capability delta id is missing")
            before = row["before_digest"]
            after = row["after_digest"]
            if before_required:
                _require_digest(before, f"readiness {disposition} before digest")
            elif before is not None:
                raise ReleaseControlError(
                    f"readiness {disposition} capability has an unexpected before digest"
                )
            if after_required:
                _require_digest(after, f"readiness {disposition} after digest")
            elif after is not None:
                raise ReleaseControlError(
                    f"readiness {disposition} capability has an unexpected after digest"
                )
            if disposition == "changed" and before == after:
                raise ReleaseControlError("readiness changed capability has identical digests")
            disposition_ids.append(capability_id)
        if disposition_ids != sorted(set(disposition_ids)):
            raise ReleaseControlError(
                f"readiness {disposition} capability inventory is not canonical"
            )
        delta_capability_ids.extend(disposition_ids)
    if len(delta_capability_ids) != len(set(delta_capability_ids)):
        raise ReleaseControlError("readiness capability delta repeats an id across dispositions")

    mappings = mapping["mappings"]
    if not isinstance(mappings, list) or not mappings:
        raise ReleaseControlError("readiness delta test mappings are missing or malformed")
    mapped_capability_ids: list[str] = []
    for row in mappings:
        if not isinstance(row, dict) or set(row) != {
            "capability_id",
            "environment_ids",
            "obligation_ids",
            "scenario_ids",
        }:
            raise ReleaseControlError("readiness delta test mapping row is malformed")
        capability_id = row["capability_id"]
        if not isinstance(capability_id, str) or not capability_id:
            raise ReleaseControlError("readiness delta test mapping capability is missing")
        for field in ("environment_ids", "obligation_ids", "scenario_ids"):
            values = row[field]
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value for value in values)
                or values != sorted(set(values))
            ):
                raise ReleaseControlError(f"readiness delta test mapping {field} is not canonical")
        mapped_capability_ids.append(capability_id)
    if mapped_capability_ids != sorted(set(mapped_capability_ids)):
        raise ReleaseControlError("readiness mapped capability inventory is not canonical")
    if mapped_capability_ids != sorted(delta_capability_ids):
        raise ReleaseControlError("readiness mapped capabilities do not equal the capability delta")
    if mapping["unmapped_capabilities"] != []:
        raise ReleaseControlError("readiness has unmapped changed capabilities")

    bindings = {
        "gate input record": (gate.get("gate_input_digest"), sha256_json(gate_input)),
        "candidate identity": (
            gate.get("candidate_identity_digest"),
            sha256_json(candidate_identity_record),
        ),
        "gate candidate": (gate.get("candidate_digest"), candidate.get("candidate_digest")),
        "gate input": (gate.get("gate_input_digest"), candidate.get("gate_input_digest")),
        "package version": (gate.get("package_version"), candidate.get("package_version")),
        "release tag": (gate.get("release_tag"), candidate.get("release_tag")),
        "gate predecessor": (gate.get("predecessor_digest"), sha256_json(predecessor)),
        "candidate predecessor": (candidate.get("predecessor_digest"), sha256_json(predecessor)),
        "gate Linear snapshot": (gate.get("linear_snapshot_digest"), sha256_json(linear_snapshot)),
        "gate-input Linear snapshot": (
            gate_input_data.get("linear_snapshot_digest"),
            sha256_json(linear_snapshot),
        ),
        "gate-input milestone": (gate_input_data.get("milestone"), gate.get("milestone")),
        "gate-input run": (gate_input_data.get("run_id"), gate.get("run_id")),
        "gate-input environment registry": (
            gate_input_data.get("environment_registry_digest"),
            gate.get("environment_registry_digest"),
        ),
        "gate-input evidence-store registry": (
            gate_input_data.get("evidence_store_registry_digest"),
            gate.get("evidence_store_registry_digest"),
        ),
        "gate-input obligation registry": (
            gate_input_data.get("obligation_registry_digest"),
            gate.get("obligation_registry_digest"),
        ),
        "gate-input scenario registry": (
            gate_input_data.get("scenario_registry_digest"),
            gate.get("scenario_registry_digest"),
        ),
        "gate-input target registry": (
            gate_input_data.get("target_registry_digest"),
            gate.get("target_registry_digest"),
        ),
        "gate-input task-state policy": (
            gate_input_data.get("task_state_policy_digest"),
            gate.get("task_state_policy_digest"),
        ),
        "gate-input readiness registry": (
            gate_input_data.get("readiness_registry_digest"),
            sha256_json(readiness_registry),
        ),
        "source-freeze gate input": (
            freeze.get("gate_input_digest"),
            sha256_json(gate_input),
        ),
        "source-freeze source": (freeze.get("source_sha"), gate.get("frozen_source_sha")),
        "source-freeze milestone": (freeze.get("milestone"), gate.get("milestone")),
        "candidate artifact manifest": (
            candidate.get("artifact_manifest_digest"),
            sha256_json(artifact_manifest),
        ),
        "candidate artifact set": (
            candidate.get("artifact_set_digest"),
            artifact.get("artifact_set_digest"),
        ),
        "candidate build invocation": (
            candidate.get("build_invocation_id"),
            artifact.get("build_invocation_id"),
        ),
        "candidate source freeze": (
            candidate.get("source_freeze_digest"),
            sha256_json(source_freeze),
        ),
        "artifact source freeze": (
            artifact.get("source_freeze_digest"),
            sha256_json(source_freeze),
        ),
        "artifact source identity": (artifact.get("source_digest"), freeze.get("freeze_digest")),
        "impact source freeze": (impact.get("source_freeze_digest"), sha256_json(source_freeze)),
        "impact source": (impact.get("head_sha"), freeze.get("source_sha")),
        "impact milestone": (impact.get("milestone"), gate.get("milestone")),
        "impact release tag": (impact.get("release_tag"), candidate.get("release_tag")),
        "impact target resolution": (
            impact.get("target_resolution_digest"),
            artifact.get("target_resolution_digest"),
        ),
        "delta predecessor": (delta_data.get("predecessor_digest"), sha256_json(predecessor)),
        "delta source": (delta_data.get("candidate_sha"), gate.get("frozen_source_sha")),
        "delta map": (mapping.get("delta_digest"), delta_data.get("delta_digest")),
        "impact manifest": (
            delta_data.get("impact_manifest_digest"),
            sha256_json(impact_manifest),
        ),
        "mapped impact manifest": (
            mapping.get("impact_manifest_digest"),
            sha256_json(impact_manifest),
        ),
        "environment registry": (
            mapping.get("environment_registry_digest"),
            gate.get("environment_registry_digest"),
        ),
        "obligation registry": (
            mapping.get("obligation_registry_digest"),
            gate.get("obligation_registry_digest"),
        ),
        "scenario registry": (
            mapping.get("scenario_registry_digest"),
            gate.get("scenario_registry_digest"),
        ),
    }
    for label, (observed, expected) in bindings.items():
        if observed != expected:
            raise ReleaseControlError(f"readiness {label} binding mismatch")
    milestone_values = (
        gate_input_data.get("milestone"),
        gate.get("milestone"),
        candidate.get("milestone"),
        freeze.get("milestone"),
        impact.get("milestone"),
        artifact.get("milestone"),
        delta_data.get("milestone"),
        mapping.get("milestone"),
        predecessor_data.get("candidate_milestone"),
    )
    if (
        any(not isinstance(value, str) or value not in MILESTONES for value in milestone_values)
        or len(set(milestone_values)) != 1
    ):
        raise ReleaseControlError("readiness milestone bindings disagree")
    milestone = milestone_values[0]
    package_version = candidate.get("package_version")
    if (
        not isinstance(package_version, str)
        or re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", package_version) is None
        or not package_version.startswith(f"{milestone}.")
        or candidate.get("release_tag") != package_version
    ):
        raise ReleaseControlError("readiness package version or release tag is invalid")
    distribution_version = package_version.removeprefix("v")
    expected_sdist = f"metriplane-{distribution_version}.tar.gz"
    expected_wheel_prefix = f"metriplane-{distribution_version}-"
    if (
        expected_sdist not in artifact_names
        or sum(
            name.startswith(expected_wheel_prefix) and name.endswith(".whl")
            for name in artifact_names
        )
        != 1
    ):
        raise ReleaseControlError("readiness artifact filenames do not match the package version")
    required_bom_ids = linear.get("required_bom_ids")
    if (
        not isinstance(required_bom_ids, list)
        or not required_bom_ids
        or any(not isinstance(item, str) or not item.strip() for item in required_bom_ids)
        or len(set(required_bom_ids)) != len(required_bom_ids)
    ):
        raise ReleaseControlError("Linear snapshot has no exact required BOM identifiers")
    if required_bom_ids != sorted(required_bom_ids):
        raise ReleaseControlError("Linear snapshot required BOM identifiers are not canonical")
    if task_id not in required_bom_ids:
        raise ReleaseControlError("Linear decision task is absent from the required BOM")
    required_bom_snapshot_digest = _require_digest(
        linear.get("required_bom_snapshot_digest"),
        "Linear required BOM snapshot",
    )
    if required_bom_snapshot_digest != sha256_json(required_bom_ids):
        raise ReleaseControlError("Linear required BOM snapshot digest mismatch")

    blockers = _validated_readiness_blockers(readiness_registry)
    evidence = readiness_registry.get("evidence_resolution")
    registry_ready = (
        readiness_registry.get("framework") == "READY"
        and readiness_registry.get("live_release") == "READY"
        and isinstance(evidence, dict)
        and evidence.get("status") == "READY"
    )
    if not registry_ready and not blockers:
        blockers = ["RELEASE_READINESS_REGISTRY_NOT_READY"]
    data = {
        "artifact_manifest_digest": candidate["artifact_manifest_digest"],
        "candidate_digest": candidate["candidate_digest"],
        "delta_digest": delta_data["delta_digest"],
        "delta_test_map_digest": mapping["map_digest"],
        "disposition": "READY" if registry_ready and not blockers else "BLOCKED_NOT_READY",
        "gate_instance_digest": gate["instance_digest"],
        "linear_snapshot_digest": gate["linear_snapshot_digest"],
        "main_health_digest": gate["main_health_digest"],
        "predecessor_digest": gate["predecessor_digest"],
        "readiness_digest": sha256_json(readiness_registry),
        "required_bom_ids": required_bom_ids,
        "required_bom_snapshot_digest": required_bom_snapshot_digest,
        "store_preflight_digest": gate["evidence_store_preflight_digest"],
        "unresolved_blockers": blockers,
    }
    invocation_id = f"release-readiness-{sha256_json(data)[:24]}"
    return make_record(
        "release-readiness",
        data,
        invocation_id=invocation_id,
        sequence=1,
        synthetic=bool(next(iter(synthetic_modes))),
        status="READY" if data["disposition"] == "READY" else "BLOCKED",
    )


def _safe_release_bytes(path: Path) -> bytes:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ReleaseControlError(f"release input traverses a symlink: {path}")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ReleaseControlError(f"release input is not a regular file: {path}")
            data = stream.read()
            after = os.fstat(stream.fileno())
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReleaseControlError(f"release input is unavailable: {path}") from exc
    identities = {(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) for s in (before, after, current)}
    if (
        len(identities) != 1
        or len(data) != current.st_size
        or any(part.is_symlink() for part in (path, *path.parents))
    ):
        raise ReleaseControlError(f"release input changed while reading: {path}")
    return data


def _source_git(repository: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseControlError("cannot inspect the bound Git source") from exc
    return result.stdout


def _source_repository(repository: Path | None) -> Path:
    location = Path.cwd() if repository is None else repository
    if any(p.is_symlink() for p in (location, *location.parents)):
        raise ReleaseControlError("source repository traverses a symlink")
    return Path(_source_git(location, "rev-parse", "--show-toplevel").decode().strip())


def _source_state(repository: Path, source_sha: str) -> str:
    if not isinstance(source_sha, str) or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ReleaseControlError("source SHA is not an exact Git commit")
    if _source_git(repository, "rev-parse", "HEAD").decode().strip() != source_sha:
        raise ReleaseControlError("source SHA differs from checked-out HEAD")
    if _source_git(repository, "status", "--porcelain=v1", "--untracked-files=no"):
        raise ReleaseControlError("source has a dirty tracked tree")
    return _source_git(repository, "rev-parse", "HEAD^{tree}").decode().strip()


def _source_blob(repository: Path, source_sha: str, name: str) -> bytes:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name:
        raise ReleaseControlError("source input path is unsafe")
    entry = _source_git(repository, "ls-tree", "-z", source_sha, "--", name)
    try:
        identity, actual = entry.rstrip(b"\0").split(b"\t")
        mode, kind, object_id = identity.split(b" ")
    except ValueError as exc:
        raise ReleaseControlError(f"source input is not a unique tracked file: {name}") from exc
    if mode not in {b"100644", b"100755"} or kind != b"blob" or actual.decode() != name:
        raise ReleaseControlError(f"source input is not a regular tracked blob: {name}")
    data = _source_git(repository, "cat-file", "blob", object_id.decode())
    if _safe_release_bytes(repository / name) != data:
        raise ReleaseControlError(f"source input bytes differ from the bound tree: {name}")
    return data


def _source_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_closed_json_object)
        canonical_json(value)
    except (ValueError, UnicodeError) as exc:
        raise ReleaseControlError(f"invalid closed JSON input: {label}") from exc
    if not isinstance(value, dict):
        raise ReleaseControlError(f"source input must be an object: {label}")
    return value


def _source_version(raw: bytes) -> str:
    try:
        tree = ast.parse(raw)
        values = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
        ]
    except (ValueError, SyntaxError) as exc:
        raise ReleaseControlError("package version must be one literal assignment") from exc
    if len(values) != 1 or not isinstance(values[0], str):
        raise ReleaseControlError("package version must be one literal assignment")
    return values[0]


def _validate_source_build_metadata(project_bytes: bytes, lock_bytes: bytes) -> None:
    try:
        project = tomllib.loads(project_bytes.decode())
        lock = tomllib.loads(lock_bytes.decode())
        required = RELEASE_BUILD_RECIPE["toolchain"]
        if project["build-system"] != {
            "requires": [f"setuptools=={required['setuptools']}"],
            "build-backend": RELEASE_BUILD_RECIPE["backend"],
        }:
            raise ReleaseControlError("frozen source build backend differs from the recipe")
        if (
            project["tool"]["setuptools"]["dynamic"]["version"]
            != {"attr": "metriplane.__version__"}
            or project["tool"]["uv"]["required-version"] != "==" + RELEASE_BUILD_RECIPE["uv"]
        ):
            raise ReleaseControlError("frozen source version or uv policy differs from the recipe")
        for name, version in required.items():
            packages = [row for row in lock["package"] if row["name"] == name]
            if (
                len(packages) != 1
                or packages[0]["version"] != version
                or (f"{name}=={version}" not in project["dependency-groups"]["dev"])
            ):
                raise ReleaseControlError(f"frozen source does not pin recipe tool {name}")
    except (KeyError, TypeError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseControlError("frozen source build/lock metadata is incomplete") from exc


def validate_release_build_environment(repository: Path) -> None:
    """Require the one recorded recipe to use the installed locked backend."""
    _validate_source_build_metadata(
        _safe_release_bytes(repository / "pyproject.toml"),
        _safe_release_bytes(repository / "uv.lock"),
    )
    if f"{sys.version_info.major}.{sys.version_info.minor}" not in RELEASE_BUILD_RECIPE["python"]:
        raise ReleaseControlError("unsupported release build Python")
    for name, version in RELEASE_BUILD_RECIPE["toolchain"].items():
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ReleaseControlError(f"release build tool is missing: {name}") from exc
        if installed != version:
            raise ReleaseControlError(f"release build tool is not the locked identity: {name}")


def _validate_release_source_inputs(
    gate: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Share the exact gate/target wire validation across source and candidate owners."""
    gate_data = _passing_record(
        gate, "release-gate-input", live=live, attestation_verifier=attestation_verifier
    )
    target_data = _passing_record(
        target, "release-target-resolution", live=live, attestation_verifier=attestation_verifier
    )
    if gate["synthetic"] != target["synthetic"] or gate["synthetic"] is not (not live):
        raise ReleaseControlError("source inputs have inconsistent authority modes")
    gate_fields = set(_SOURCE_REGISTRY_INPUTS) | {
        "expected_predecessor_milestone",
        "gate_input_digest",
        "linear_snapshot_digest",
        "milestone",
        "role_assignments_digest",
        "run_id",
        "target_burn_digest",
        "target_burn_index_receipt_digest",
        "target_resolution_digest",
    }
    _release_data(gate, gate_fields, "source gate input")
    target_fields = {
        "burn_lineage_digest",
        "burn_target_ids",
        "initial_package_version",
        "initial_release_tag",
        "milestone",
        "observations_digest",
        "prior_burn_digests",
        "requires_new_burn",
        "resolution_digest",
        "resolution_rule",
        "selected_package_version",
        "selected_release_tag",
    }
    _release_data(target, target_fields, "source target resolution")
    for field in gate_fields - {
        "milestone",
        "run_id",
        "expected_predecessor_milestone",
        "target_burn_index_receipt_digest",
    }:
        _require_digest(gate_data[field], f"source gate {field}")
    if gate_data["target_burn_index_receipt_digest"] is not None:
        _require_digest(gate_data["target_burn_index_receipt_digest"], "source gate burn receipt")
    _require_nonempty_string(
        gate_data["expected_predecessor_milestone"], "source predecessor milestone"
    )
    if (
        not isinstance(gate_data["run_id"], str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", gate_data["run_id"]) is None
    ):
        raise ReleaseControlError("source gate run identity is invalid")
    milestone = gate_data["milestone"]
    if milestone not in MILESTONES or target_data["milestone"] != milestone:
        raise ReleaseControlError("source gate and target milestone binding mismatch")
    if gate_data["gate_input_digest"] != sha256_json(
        {k: v for k, v in gate_data.items() if k != "gate_input_digest"}
    ):
        raise ReleaseControlError("source gate semantic digest mismatch")
    if gate_data["target_resolution_digest"] != sha256_json(target):
        raise ReleaseControlError("source target record binding mismatch")
    if target_data["resolution_digest"] != sha256_json(
        {k: v for k, v in target_data.items() if k != "resolution_digest"}
    ):
        raise ReleaseControlError("source target semantic digest mismatch")
    for field in (
        "initial_package_version",
        "initial_release_tag",
        "selected_package_version",
        "selected_release_tag",
    ):
        value = target_data[field]
        if (
            not isinstance(value, str)
            or re.fullmatch(r"v(?:0\.[3-9]|1\.0)\.[0-9]+", value) is None
            or value.rsplit(".", 1)[0] != milestone
        ):
            raise ReleaseControlError(f"source target {field} is outside the milestone")
    if (
        target_data["selected_package_version"] != target_data["selected_release_tag"]
        or target_data["initial_package_version"] != target_data["initial_release_tag"]
    ):
        raise ReleaseControlError("source target package/tag identities differ")
    if (
        type(target_data["requires_new_burn"]) is not bool
        or target_data["resolution_rule"] != "next_unused_same_milestone_patch"
    ):
        raise ReleaseControlError("source target resolution rule is invalid")
    for field in ("burn_lineage_digest", "observations_digest"):
        _require_digest(target_data[field], "source target " + field)
    for field in ("burn_target_ids", "prior_burn_digests"):
        rows = target_data[field]
        if (
            not isinstance(rows, list)
            or any(not isinstance(v, str) or not v.strip() for v in rows)
            or len(set(rows)) != len(rows)
        ):
            raise ReleaseControlError("source target inventory is invalid: " + field)
        if field == "prior_burn_digests":
            for value in rows:
                _require_digest(value, "source prior burn")
    return gate_data, target_data


def _source_freeze_payload(
    gate_path: Path,
    source_sha: str,
    *,
    repository: Path,
    frozen_at: str,
    producer_intent_digest: str,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None,
) -> tuple[dict[str, Any], bool]:
    tree = _source_state(repository, source_sha)
    _parse_utc_timestamp(frozen_at, "source freeze clock")
    _require_digest(producer_intent_digest, "source producer intent")
    gate = _source_json(_safe_release_bytes(gate_path), "gate input")
    target_path = gate_path.parent / "target-resolution.json"
    target = _source_json(_safe_release_bytes(target_path), "target resolution")
    gate_data, target_data = _validate_release_source_inputs(
        gate, target, live=live, attestation_verifier=attestation_verifier
    )
    milestone = gate_data["milestone"]
    registry_refs = []
    for field, name in sorted(_SOURCE_REGISTRY_INPUTS.items(), key=lambda row: row[1]):
        raw = _source_blob(repository, source_sha, name)
        registry = _source_json(raw, name)
        schema_id = registry.get("schema_version")
        if not isinstance(schema_id, str) or not schema_id.startswith("metriplane."):
            raise ReleaseControlError("source registry schema identity is missing: " + name)
        digest = sha256_bytes(raw)
        if digest != gate_data[field]:
            raise ReleaseControlError("source registry differs from gate input: " + name)
        registry_refs.append({"path": name, "schema_id": schema_id, "sha256": digest})
    metadata = {name: _source_blob(repository, source_sha, name) for name in _SOURCE_VERSION_PATHS}
    if _source_version(metadata["metriplane/__init__.py"]) != target_data[
        "selected_package_version"
    ].removeprefix("v"):
        raise ReleaseControlError("source package version differs from the selected target")
    _validate_source_build_metadata(metadata["pyproject.toml"], metadata["uv.lock"])
    workflows = (
        _source_git(
            repository, "ls-tree", "-r", "-z", "--name-only", source_sha, "--", ".github/workflows"
        )
        .decode()
        .split("\0")
    )
    workflow_refs = [
        {
            "path": name,
            "schema_id": "application/vnd.github-actions.workflow+yaml",
            "sha256": sha256_bytes(_source_blob(repository, source_sha, name)),
        }
        for name in sorted(name for name in workflows if name)
    ]
    if not workflow_refs:
        raise ReleaseControlError("source has no tracked workflow inventory")
    note = "docs/releases/" + target_data["selected_release_tag"] + "-release-notes.md"
    data: dict[str, Any] = {
        "build_recipe_digest": RELEASE_BUILD_RECIPE_DIGEST,
        "dirty": False,
        "frozen_at": frozen_at,
        "gate_input_digest": sha256_json(gate),
        "milestone": milestone,
        "registry_inputs": registry_refs,
        "release_notes_digest": sha256_bytes(_source_blob(repository, source_sha, note)),
        "source_sha": source_sha,
        "source_tree": tree,
        "version_metadata_digest": sha256_json(
            [{"path": name, "sha256": sha256_bytes(raw)} for name, raw in sorted(metadata.items())]
        ),
        "workflow_inputs": workflow_refs,
        "invocation_root_locator": "invocations",
        "producer_intent_digest": producer_intent_digest,
    }
    data["freeze_digest"] = sha256_json(data)
    if _source_state(repository, source_sha) != tree:
        raise ReleaseControlError("source tree changed during capture")
    if _safe_release_bytes(gate_path) != canonical_json(gate) or _safe_release_bytes(
        target_path
    ) != canonical_json(target):
        raise ReleaseControlError("source input records changed or are not canonical JSON bytes")
    return data, gate["synthetic"]


def build_release_source_freeze_record(
    gate_path: Path,
    source_sha: str,
    *,
    frozen_at: str,
    invocation_id: str,
    sequence: int,
    producer_intent_digest: str,
    repository: Path | None = None,
    live: bool = True,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> dict[str, Any]:
    """Capture real Git and input bytes; output remains staged until its journal commits."""
    data, synthetic = _source_freeze_payload(
        gate_path,
        source_sha,
        repository=_source_repository(repository),
        frozen_at=frozen_at,
        producer_intent_digest=producer_intent_digest,
        live=live,
        attestation_verifier=attestation_verifier,
    )
    if live:
        raise ReleaseControlError(
            "source-freeze output attestation and upstream live producer qualification remain unbound"
        )
    return make_record(
        "release-source-freeze",
        data,
        invocation_id=invocation_id,
        sequence=sequence,
        synthetic=synthetic,
    )


def validate_release_source_freeze_record(
    record: Mapping[str, Any],
    record_path: Path,
    *,
    repository: Path | None = None,
    live: bool = True,
    attestation_verifier: ProviderAttestationVerifier | None = None,
) -> None:
    """Recompute source identity and require exactly one completed producer journal."""
    data = _passing_record(
        record, "release-source-freeze", live=live, attestation_verifier=attestation_verifier
    )
    actual, _ = _source_freeze_payload(
        record_path.parent / "gate-input.json",
        data.get("source_sha", ""),
        repository=_source_repository(repository),
        frozen_at=data.get("frozen_at", ""),
        producer_intent_digest=data.get("producer_intent_digest", ""),
        live=live,
        attestation_verifier=attestation_verifier,
    )
    if data != actual or _safe_release_bytes(record_path) != canonical_json(record):
        raise ReleaseControlError(
            "source-freeze semantic projection or exact retained bytes mismatch"
        )
    validate_release_producer_journal(record, record_path, producer="freeze_release_source.py")


_INVOCATION_STAGES: Final[Mapping[str, str]] = {
    "freeze_release_source.py": "source-freeze",
    "build_release_artifacts.py": "artifact-build",
    "validate_release_source_freeze.py": "source-freeze-validation",
    "validate_release_artifact_manifest.py": "artifact-manifest-validation",
    _FINALIZER: "candidate-finalization",
    _CANDIDATE_VALIDATOR: "validate-release-candidate-identity",
}
_INTENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "invocation_id",
        "sequence",
        "tool",
        "tool_version",
        "argv",
        "started_at",
        "inputs",
        "environment",
        "planned_outputs",
        "previous_invocation_digest",
        "predecessor",
    }
)
_JOURNAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "argv",
        "completed_at",
        "exit_code",
        "inputs",
        "invocation_digest",
        "outputs",
        "previous_invocation_digest",
        "started_at",
        "stderr_digest",
        "stdout_digest",
        "terminal_status",
        "tool",
        "tool_version",
    }
)


@dataclass(frozen=True)
class ReleaseInvocation:
    """Reserved local evidence; it grants no provider or release authority."""

    directory: Path
    root: Path
    intent: Mapping[str, Any]


@dataclass(frozen=True)
class CandidateFinalizationInvocation(ReleaseInvocation):
    """The exact finalizer owns external control and a separately derived subject root."""

    @property
    def staging_root(self) -> Path:
        return Path(self.intent["finalization"]["staging_root"])

    @property
    def release_root(self) -> Path:
        return Path(self.intent["finalization"]["release_root"])


def _release_object_identity(path: Path) -> dict[str, int]:
    _run_relative(path.parent, path)
    value = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(value.st_mode):
        raise ReleaseControlError("release object is not a directory: " + str(path))
    return {"device": value.st_dev, "inode": value.st_ino, "mode": stat.S_IMODE(value.st_mode)}


def _candidate_inventory(root: Path) -> list[dict[str, Any]]:
    """Read a closed tree without following links or accepting special files."""
    _release_object_identity(root)
    rows: list[dict[str, Any]] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        before = _release_object_identity(directory)
        for path in sorted(directory.iterdir()):
            name = _run_relative(root, path)
            info = path.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                rows.append({"path": name, "kind": "directory", **_release_object_identity(path)})
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                raw = _safe_release_bytes(path)
                after = path.stat(follow_symlinks=False)
                if (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_mode,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ReleaseControlError("candidate member changed during inventory")
                rows.append(
                    {
                        "path": name,
                        "kind": "file",
                        "sha256": sha256_bytes(raw),
                        "size": len(raw),
                        "mode": stat.S_IMODE(info.st_mode),
                    }
                )
            else:
                raise ReleaseControlError("candidate tree contains a link or special file: " + name)
        if before != _release_object_identity(directory):
            raise ReleaseControlError("candidate directory changed during inventory")
    return sorted(rows, key=lambda row: row["path"])


def _candidate_open_directory(path: Path) -> int:
    """Open each directory component without following a substituted ancestor."""
    if not path.is_absolute() or ".." in path.parts:
        raise ReleaseControlError("candidate directory path is not canonical absolute")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in path.parts[1:]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _finalization_witness(path: Path) -> dict[str, Any]:
    """Observe opaque bytes through held directories; stop at the first unsafe object."""

    def unreadable(value: os.stat_result | None) -> dict[str, Any]:
        return {
            "state": "UNREADABLE",
            "sha256": None,
            "size": None,
            "object": None
            if value is None
            else {
                "device": value.st_dev,
                "inode": value.st_ino,
                "mode": value.st_mode,
                "size": value.st_size,
                "mtime_ns": value.st_mtime_ns,
            },
        }

    if not path.is_absolute() or ".." in path.parts:
        return unreadable(None)
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    value = None
    try:
        for index, name in enumerate(path.parts[1:], start=1):
            try:
                value = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                return {"state": "ABSENT", "sha256": None, "size": None, "object": None}
            if index != len(path.parts) - 1:
                if not stat.S_ISDIR(value.st_mode):
                    return unreadable(value)
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                actual = os.fstat(child)
                if (actual.st_dev, actual.st_ino) != (value.st_dev, value.st_ino):
                    os.close(child)
                    return unreadable(value)
                os.close(descriptor)
                descriptor = child
                continue
            if not stat.S_ISREG(value.st_mode):
                return unreadable(value)
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            with os.fdopen(child, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode):
                    return unreadable(before)
                raw = stream.read()
                after = os.fstat(stream.fileno())
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (
                len(
                    {
                        (v.st_dev, v.st_ino, v.st_mode, v.st_size, v.st_mtime_ns)
                        for v in (value, before, after, current)
                    }
                )
                != 1
                or len(raw) != current.st_size
            ):
                return unreadable(current)
            return {"state": "RAW", "sha256": sha256_bytes(raw), "size": len(raw), "object": None}
    except OSError:
        return unreadable(value)
    finally:
        os.close(descriptor)
    return unreadable(value)


def _finalization_history(stage: Path, sequence: int) -> list[dict[str, Any]]:
    return [
        {
            "sequence": number,
            "intent": _finalization_witness(stage / f"{number:03d}" / "intent.json"),
            "terminal": _finalization_witness(stage / f"{number:03d}" / "invocation.json"),
            "commit": _finalization_witness(stage / f"{number:03d}" / "terminal-commit.json"),
        }
        for number in range(1, sequence)
    ]


def _validate_finalization_context(context: CandidateFinalizationInvocation) -> None:
    value = context.intent["finalization"]
    fields = {
        "schema_version",
        "staging_root",
        "release_root",
        "identity_name",
        "control_journal_locator",
        "staging_identity",
        "parent_identities",
        "inventory",
        "records",
        "capture_error",
        "history",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value["schema_version"] != "metriplane.candidate-finalization-context.v1"
        or context.intent["tool"] != _FINALIZER
        or value["identity_name"] != _CANDIDATE_NAME
    ):
        raise ReleaseControlError("candidate finalization context is not closed")
    staging = _canonical_absolute_path(value["staging_root"], "staging root")
    release = _canonical_absolute_path(value["release_root"], "release root")
    control = context.root
    if (
        staging.parent != release.parent / ".staging"
        or control != release.parent / ".control" / staging.name
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", staging.name) is None
        or value["control_journal_locator"]
        != str(control / "invocations/candidate-finalization/001/invocation.json")
        or re.fullmatch(r"v0\.[4-9]\.[0-9]+", release.name) is None
    ):
        raise ReleaseControlError("candidate finalization two-root layout differs")
    if (
        not isinstance(value["capture_error"], str)
        or not isinstance(value["inventory"], list)
        or not isinstance(value["parent_identities"], dict)
        or not isinstance(value["records"], dict)
        or not isinstance(value["history"], list)
        or len(value["history"]) != context.intent["sequence"] - 1
    ):
        raise ReleaseControlError("candidate finalization snapshot shape is invalid")
    names = []
    for row in value["inventory"]:
        if not isinstance(row, dict):
            raise ReleaseControlError("candidate inventory row is invalid")
        fields = (
            {"path", "kind", "device", "inode", "mode"}
            if row.get("kind") == "directory"
            else {"path", "kind", "sha256", "size", "mode"}
        )
        if set(row) != fields or row["kind"] not in {"file", "directory"}:
            raise ReleaseControlError("candidate inventory row is not closed")
        _journal_path(Path("/"), row["path"])
        for key in fields - {"path", "kind", "sha256"}:
            if type(row[key]) is not int or row[key] < 0:
                raise ReleaseControlError("candidate inventory numeric identity is invalid")
        if row["kind"] == "file":
            _require_digest(row["sha256"], "candidate inventory file")
        names.append(row["path"])
    if names != sorted(set(names)) or _CANDIDATE_NAME in names:
        raise ReleaseControlError("candidate pre-effect inventory is not canonical")
    if not value["capture_error"] and context.intent["sequence"] == 1:
        for obj in [value["staging_identity"], *value["parent_identities"].values()]:
            if (
                not isinstance(obj, dict)
                or set(obj) != {"device", "inode", "mode"}
                or any(type(n) is not int or n < 0 for n in obj.values())
            ):
                raise ReleaseControlError("candidate object identity is invalid")
        expected_parents = {str(staging.parent), str(release.parent), str(release), str(control)}
        if set(value["parent_identities"]) != expected_parents:
            raise ReleaseControlError("candidate parent identity set differs")
        if (
            len(
                {
                    obj["device"]
                    for obj in [value["staging_identity"], *value["parent_identities"].values()]
                }
            )
            != 1
        ):
            raise ReleaseControlError("candidate objects are not on the same filesystem")
    for number, prior in enumerate(value["history"], 1):
        if (
            not isinstance(prior, dict)
            or set(prior) != {"sequence", "intent", "terminal", "commit"}
            or prior["sequence"] != number
        ):
            raise ReleaseControlError("candidate diagnostic history is not contiguous")
        for name in ("intent", "terminal", "commit"):
            witness = prior[name]
            if (
                not isinstance(witness, dict)
                or set(witness) != {"state", "sha256", "size", "object"}
                or witness["state"] not in {"RAW", "ABSENT", "UNREADABLE"}
            ):
                raise ReleaseControlError("candidate historical witness is not closed")
            if witness["state"] == "RAW":
                _require_digest(witness["sha256"], "candidate opaque history")
                if (
                    type(witness["size"]) is not int
                    or witness["size"] < 0
                    or witness["object"] is not None
                ):
                    raise ReleaseControlError("candidate raw witness is invalid")
            elif witness["sha256"] is not None or witness["size"] is not None:
                raise ReleaseControlError("non-raw candidate witness grants bytes")
    prior = context.intent["predecessor"]
    if context.intent["sequence"] > 1:
        expected = {
            "sequence": context.intent["sequence"] - 1,
            "intent_digest": value["history"][-1]["intent"]["sha256"],
            "terminal_digest": value["history"][-1]["terminal"]["sha256"],
            "disposition": "FINALIZATION_DIAGNOSTIC",
        }
        if (
            prior != expected
            or context.intent["previous_invocation_digest"] != expected["terminal_digest"]
        ):
            raise ReleaseControlError("candidate diagnostic predecessor binding mismatch")


def _begin_candidate_finalization(
    tool: str, argv: Sequence[str], directory: Path
) -> CandidateFinalizationInvocation:
    from metriplane import __version__

    staging = _canonical_absolute_path(_command_value(argv, "work-dir"), "staging root")
    release = _canonical_absolute_path(_command_value(argv, "release-root"), "release root")
    directory = _canonical_absolute_path(str(directory), "finalization invocation")
    sequence = int(directory.name) if directory.name.isascii() and directory.name.isdecimal() else 0
    if (
        sequence < 1
        or directory.name != f"{sequence:03d}"
        or directory.parent.name != "candidate-finalization"
        or directory.parent.parent.name != "invocations"
        or staging.parent != release.parent / ".staging"
        or directory.parents[2] != release.parent / ".control" / staging.name
        or _command_value(argv, "identity-name") != _CANDIDATE_NAME
    ):
        raise ReleaseControlError("finalization arguments do not use the fixed protocol paths")
    for path in (staging, release, directory):
        _run_relative(path.parent, path)
    for flag, name in [
        ("gate-input", "gate-input.json"),
        ("source-freeze", "source-freeze.json"),
        ("predecessor", "predecessor.json"),
        ("artifact-manifest", "artifact-manifest.json"),
    ]:
        if _canonical_absolute_path(_command_value(argv, flag), flag) != staging / name:
            raise ReleaseControlError("finalization input is outside its fixed staging location")
    existing = _journal_sequences(directory.parent)
    if sequence != len(existing) + 1:
        raise ReleaseControlError("finalization sequence collides or has gaps")
    root = directory.parents[2]
    # Exclusive reservation is retained even if capture or the intent write is interrupted.
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    history = _finalization_history(directory.parent, sequence)
    snapshot: dict[str, Any] = {
        "schema_version": "metriplane.candidate-finalization-context.v1",
        "staging_root": str(staging),
        "release_root": str(release),
        "identity_name": _CANDIDATE_NAME,
        "control_journal_locator": str(directory.parent / "001/invocation.json"),
        "staging_identity": None,
        "parent_identities": {},
        "inventory": [],
        "records": {},
        "capture_error": "",
        "history": history,
    }
    inputs = []
    if sequence == 1:
        try:
            snapshot["staging_identity"] = _release_object_identity(staging)
            snapshot["parent_identities"] = {
                str(p): _release_object_identity(p)
                for p in (staging.parent, release.parent, release, root)
            }
            snapshot["inventory"] = _candidate_inventory(staging)
            for name, kind in _FINALIZATION_INPUTS.items():
                raw = _safe_release_bytes(staging / name)
                record = _source_json(raw, "captured " + name)
                if raw != canonical_json(record):
                    raise ReleaseControlError("captured finalization input is not canonical")
                snapshot["records"][name] = record
                inputs.append(
                    {
                        "path": str(staging / name),
                        "schema_id": "metriplane." + kind + ".v1",
                        "sha256": sha256_bytes(raw),
                    }
                )
        except (OSError, ReleaseControlError) as exc:
            snapshot["capture_error"] = str(exc)
    predecessor = (
        None
        if not history
        else {
            "sequence": sequence - 1,
            "intent_digest": history[-1]["intent"]["sha256"],
            "terminal_digest": history[-1]["terminal"]["sha256"],
            "disposition": "FINALIZATION_DIAGNOSTIC",
        }
    )
    intent: dict[str, Any] = {
        "schema_version": "metriplane.release-invocation-intent.v1",
        "sequence": sequence,
        "tool": tool,
        "tool_version": __version__,
        "argv": [tool, *argv],
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "inputs": sorted(inputs, key=lambda row: row["path"]),
        "environment": {
            "working_directory": str(Path.cwd()),
            "python": sys.version.split()[0],
            "fixture_mode": "1"
            if os.environ.get("METRIPLANE_RELEASE_FIXTURE_MODE") == "1"
            else "0",
            "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH", ""),
            "python_hash_seed": os.environ.get("PYTHONHASHSEED", ""),
        },
        "planned_outputs": [
            {"path": _CANDIDATE_NAME, "schema_id": "metriplane.release-candidate-identity.v1"}
        ],
        "previous_invocation_digest": None
        if predecessor is None
        else predecessor["terminal_digest"],
        "predecessor": predecessor,
        "finalization": snapshot,
    }
    intent["invocation_id"] = _intent_identity(intent)
    _durable_json(directory / "intent.json", intent)
    context = _validate_intent(directory)
    if not isinstance(context, CandidateFinalizationInvocation):
        raise ReleaseControlError("finalization intent did not create its typed context")
    return context


def _check_finalization_observation(context: CandidateFinalizationInvocation) -> None:
    if context.intent["finalization"]["history"] != _finalization_history(
        context.directory.parent, context.intent["sequence"]
    ):
        raise ReleaseControlError("candidate historical raw/absence/unreadability witness changed")


def _finalization_history_contradictions(context: CandidateFinalizationInvocation) -> list[int]:
    """Diagnose older contradictions without making the new observation unrecordable."""
    contradicted = []
    for row in context.intent["finalization"]["history"]:
        directory = context.directory.parent / f"{row['sequence']:03d}"
        try:
            prior = _validate_intent(directory)
        except (OSError, ReleaseControlError):
            continue
        if not isinstance(prior, CandidateFinalizationInvocation) or prior.intent["finalization"][
            "history"
        ] != _finalization_history(directory.parent, row["sequence"]):
            contradicted.append(row["sequence"])
    return contradicted


def _check_finalization_history(context: CandidateFinalizationInvocation) -> None:
    _check_finalization_observation(context)
    if _finalization_history_contradictions(context):
        raise ReleaseControlError("earlier candidate diagnostic witness was contradicted")


def _candidate_identity_for_context(
    context: CandidateFinalizationInvocation, source_root: Path | None = None
) -> dict[str, Any]:
    """Derive only from the safely parsed original pre-effect intent, never a retry."""
    if context.intent["sequence"] != 1 or context.intent["finalization"]["capture_error"]:
        raise ReleaseControlError("candidate identity requires complete original capture")
    value = context.intent["finalization"]
    records = value["records"]
    if set(records) != set(_FINALIZATION_INPUTS):
        raise ReleaseControlError("candidate original intent lacks its exact five records")
    if source_root is not None:
        for name in _FINALIZATION_INPUTS:
            if _safe_release_bytes(source_root / name) != canonical_json(records[name]):
                raise ReleaseControlError(
                    "candidate input bytes differ from original intent: " + name
                )
    data = _build_candidate_identity_payload(
        records["gate-input.json"],
        records["source-freeze.json"],
        records["predecessor.json"],
        records["artifact-manifest.json"],
        records["target-resolution.json"],
        finalization_intent_digest=sha256_json(context.intent),
        control_journal_locator=value["control_journal_locator"],
        release_root=context.release_root,
        no_evaluation_adoption="--no-evaluation-adoption" in context.intent["argv"],
        live=context.intent["environment"]["fixture_mode"] != "1",
    )
    return make_record(
        "release-candidate-identity",
        data,
        invocation_id=context.intent["invocation_id"],
        sequence=1,
        synthetic=context.intent["environment"]["fixture_mode"] == "1",
    )


def _validate_finalization_bound(
    context: CandidateFinalizationInvocation,
    *,
    outputs: list[dict[str, str]] | None = None,
    output_root: Path | None = None,
) -> None:
    _check_finalization_history(context)
    value = context.intent["finalization"]
    if context.intent["sequence"] != 1:
        raise ReleaseControlError("candidate finalizer retries are diagnostic only")
    if value["capture_error"]:
        raise ReleaseControlError("candidate input capture failed: " + value["capture_error"])
    argv = context.intent["argv"][1:]
    for flag, path in [
        ("work-dir", context.staging_root),
        ("release-root", context.release_root),
        ("invocation-dir", context.directory),
        *[
            (name.removesuffix(".json"), context.staging_root / name)
            for name in _FINALIZATION_INPUTS
            if name != "target-resolution.json"
        ],
    ]:
        if _command_value(argv, flag) != str(path):
            raise ReleaseControlError("candidate historical argv differs from its captured roots")
    if _command_value(argv, "identity-name") != _CANDIDATE_NAME:
        raise ReleaseControlError("candidate identity basename differs")
    expected_inputs = sorted(
        [
            {
                "path": str(context.staging_root / name),
                "schema_id": "metriplane." + kind + ".v1",
                "sha256": sha256_json(value["records"][name]),
            }
            for name, kind in _FINALIZATION_INPUTS.items()
        ],
        key=lambda row: row["path"],
    )
    if context.intent["inputs"] != expected_inputs or context.intent["planned_outputs"] != [
        {"path": _CANDIDATE_NAME, "schema_id": "metriplane.release-candidate-identity.v1"}
    ]:
        raise ReleaseControlError("candidate exact captured inputs/output plan differ")
    record = _candidate_identity_for_context(context)
    if outputs is not None:
        expected = [
            {
                "path": _CANDIDATE_NAME,
                "schema_id": "metriplane.release-candidate-identity.v1",
                "sha256": sha256_json(record),
            }
        ]
        root = Path(record["data"]["final_directory"]) if output_root is None else output_root
        if outputs != expected or _safe_release_bytes(root / _CANDIDATE_NAME) != canonical_json(
            record
        ):
            raise ReleaseControlError("candidate output differs from original computed identity")


def _verify_finalization_source(context: CandidateFinalizationInvocation) -> dict[str, Any]:
    _validate_finalization_bound(context)
    value = context.intent["finalization"]
    for name, identity in value["parent_identities"].items():
        if _release_object_identity(Path(name)) != identity:
            raise ReleaseControlError("candidate source/destination/control parent was substituted")
    if _release_object_identity(context.staging_root) != value["staging_identity"]:
        raise ReleaseControlError("candidate staging directory object was substituted")
    if _candidate_inventory(context.staging_root) != value["inventory"]:
        raise ReleaseControlError("candidate immutable staging inventory changed")
    record = _candidate_identity_for_context(context, context.staging_root)
    inputs = value["records"]
    validate_release_producer_journal(
        inputs["source-freeze.json"],
        context.staging_root / "source-freeze.json",
        producer="freeze_release_source.py",
    )
    validate_release_artifact_files(
        inputs["artifact-manifest.json"],
        context.staging_root / "artifacts",
        live=context.intent["environment"]["fixture_mode"] != "1",
    )
    _validate_candidate_journal_tree(context.staging_root)
    return record


def _rename_candidate_exclusive(
    source_parent_fd: int, source_name: str, destination_parent_fd: int, destination_name: str
) -> None:
    """One native same-device exclusive rename; no replacement or copy fallback."""
    import ctypes

    for name in (source_name, destination_name):
        if not name or Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ReleaseControlError("exclusive candidate rename requires basenames")
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "linux":
        symbol, flag = "renameat2", 1  # Linux RENAME_NOREPLACE.
    elif sys.platform == "darwin":
        symbol, flag = "renameatx_np", 4  # Darwin RENAME_EXCL.
    else:
        raise ReleaseControlError("exclusive candidate rename is unsupported on this platform")
    try:
        operation = getattr(library, symbol)
    except AttributeError as exc:
        raise ReleaseControlError("native exclusive candidate rename is unavailable") from exc
    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    if (
        operation(
            source_parent_fd,
            os.fsencode(source_name),
            destination_parent_fd,
            os.fsencode(destination_name),
            flag,
        )
        != 0
    ):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), source_name, None, destination_name)


def _durable_candidate_identity(directory_fd: int, record: Mapping[str, Any]) -> None:
    """Create only in the captured staging object, even if its namespace is replaced."""
    descriptor = os.open(
        _CANDIDATE_NAME,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
        dir_fd=directory_fd,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json(record))
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(directory_fd)


def _fsync_candidate_tree(
    root: Path,
    *,
    directory_fd: int,
    expected_identity: Mapping[str, int],
    inventory: Sequence[Mapping[str, Any]],
) -> None:
    if _release_object_identity(root) != expected_identity:
        raise ReleaseControlError("candidate fsync root namespace was substituted")
    root_fd = os.dup(directory_fd)
    try:
        info = os.fstat(root_fd)
        if {
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode),
        } != expected_identity:
            raise ReleaseControlError("candidate fsync root was substituted")
        identities = {row["path"]: row for row in inventory if row["kind"] == "directory"}
        # Each walk starts at the held original root and checks every intermediate inode.
        for row in sorted(inventory, key=lambda v: len(Path(v["path"]).parts), reverse=True):
            descriptor = os.dup(root_fd)
            try:
                parts = Path(row["path"]).parts
                for index, name in enumerate(parts):
                    leaf = index == len(parts) - 1
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                    if not leaf or row["kind"] == "directory":
                        flags |= os.O_DIRECTORY
                    child = os.open(name, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
                    info = os.fstat(descriptor)
                    if not leaf or row["kind"] == "directory":
                        expected = identities[Path(*parts[: index + 1]).as_posix()]
                        if {
                            "device": info.st_dev,
                            "inode": info.st_ino,
                            "mode": stat.S_IMODE(info.st_mode),
                        } != {key: expected[key] for key in ("device", "inode", "mode")}:
                            raise ReleaseControlError("candidate fsync directory was substituted")
                    else:
                        if not stat.S_ISREG(info.st_mode):
                            raise ReleaseControlError("candidate fsync subject is not regular")
                        with os.fdopen(os.dup(descriptor), "rb") as stream:
                            raw = stream.read()
                        if (
                            len(raw) != row["size"]
                            or sha256_bytes(raw) != row["sha256"]
                            or stat.S_IMODE(info.st_mode) != row["mode"]
                        ):
                            raise ReleaseControlError("candidate fsync bytes or mode differ")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


def _install_candidate_identity(
    context: CandidateFinalizationInvocation, outputs: list[dict[str, str]]
) -> None:
    record = _verify_finalization_source(context)
    _validate_finalization_bound(context, outputs=outputs, output_root=context.directory / "staged")
    source = context.staging_root
    destination = Path(record["data"]["final_directory"])
    value = context.intent["finalization"]
    descriptors = []
    try:
        for path in (source.parent, destination.parent, context.root):
            fd = _candidate_open_directory(path)
            descriptors.append(fd)
            info = os.fstat(fd)
            if {
                "device": info.st_dev,
                "inode": info.st_ino,
                "mode": stat.S_IMODE(info.st_mode),
            } != value["parent_identities"][str(path)]:
                raise ReleaseControlError("opened candidate rename parent identity differs")
        staging_fd = os.open(
            source.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[0]
        )
        descriptors.append(staging_fd)
        info = os.fstat(staging_fd)
        if {
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode),
        } != value["staging_identity"]:
            raise ReleaseControlError("opened candidate staging object differs")
        _durable_candidate_identity(staging_fd, record)
        expected = value["inventory"] + [
            {
                "path": _CANDIDATE_NAME,
                "kind": "file",
                "sha256": sha256_json(record),
                "size": len(canonical_json(record)),
                "mode": 0o400,
            }
        ]
        if _candidate_inventory(source) != sorted(expected, key=lambda row: row["path"]):
            raise ReleaseControlError("candidate source inventory changed before exclusive rename")
        info = os.stat(source.name, dir_fd=descriptors[0], follow_symlinks=False)
        if {
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode),
        } != value["staging_identity"]:
            raise ReleaseControlError("candidate source basename was substituted")
        for path in (source.parent, destination.parent):
            if _release_object_identity(path) != value["parent_identities"][str(path)]:
                raise ReleaseControlError("candidate parent changed before exclusive rename")
        _rename_candidate_exclusive(descriptors[0], source.name, descriptors[1], destination.name)
        _verify_finalized_candidate_inventory(context, record)
        _fsync_candidate_tree(
            destination,
            directory_fd=staging_fd,
            expected_identity=value["staging_identity"],
            inventory=expected,
        )
        for fd in descriptors:
            os.fsync(fd)
        _fsync_candidate_tree(
            context.root,
            directory_fd=descriptors[2],
            expected_identity=value["parent_identities"][str(context.root)],
            inventory=_candidate_inventory(context.root),
        )
        _verify_finalized_candidate_inventory(context, record)
    finally:
        for fd in descriptors:
            os.close(fd)


def _candidate_success_line(record: Mapping[str, Any]) -> bytes:
    data = record["data"]
    return (
        canonical_json(
            {
                "status": "PASS",
                "candidate_id": data["candidate_digest"],
                "candidate_dir": data["final_directory"],
                "identity_record": str(Path(data["final_directory"]) / _CANDIDATE_NAME),
            }
        )
        + b"\n"
    )


def _finalization_diagnostic(context: CandidateFinalizationInvocation) -> dict[str, Any]:
    _check_finalization_observation(context)
    contradicted = _finalization_history_contradictions(context)
    witness = context.intent["finalization"]["history"][0]["terminal"]
    result: dict[str, Any] = {
        "schema_version": "metriplane.candidate-finalization-diagnostic.v1",
        "status": "BLOCKED",
        "classification": "UNTRUSTED_OR_INCOMPLETE_ORIGINAL_INTENT",
        "original_intent": context.intent["finalization"]["history"][0]["intent"],
        "original_terminal": {
            "witness": witness,
            "disposition": witness["state"]
            if witness["state"] != "RAW"
            else "UNVERIFIABLE_ORIGINAL_INTENT",
        },
        "history_consistency": "CONTRADICTED" if contradicted else "CONSISTENT",
        "contradicted_sequences": contradicted,
        "staging_observation": _finalization_witness(context.staging_root),
        "candidate_id": None,
        "candidate_dir": None,
    }
    if contradicted:
        result["classification"] = "HISTORICAL_WITNESS_CONTRADICTION"
        return result
    try:
        original = _validate_intent(context.directory.parent / "001")
        if not isinstance(original, CandidateFinalizationInvocation):
            return result
        _validate_finalization_bound(original)
        record = _candidate_identity_for_context(original)
    except (OSError, ReleaseControlError):
        return result
    if witness["state"] == "RAW":
        try:
            terminal = _validate_terminal(original)
            disposition = "VALID_" + terminal["status"]
            if terminal["status"] == "PASS":
                receipt = {
                    "schema_version": "metriplane.candidate-terminal-commit.v1",
                    "intent_sha256": sha256_json(original.intent),
                    "terminal_sha256": sha256_json(terminal),
                }
                committed = _finalization_witness(original.directory / "terminal-commit.json")
                disposition += (
                    "_COMMITTED"
                    if (
                        committed["state"] == "RAW"
                        and committed["sha256"] == sha256_json(receipt)
                        and committed["size"] == len(canonical_json(receipt))
                    )
                    else "_UNCOMMITTED"
                )
        except (OSError, ReleaseControlError):
            disposition = "INVALID_OR_PARTIAL"
        result["original_terminal"]["disposition"] = disposition
    final = Path(record["data"]["final_directory"])
    result.update(candidate_id=record["data"]["candidate_digest"], candidate_dir=str(final))
    staging_exists, final_exists = os.path.lexists(original.staging_root), os.path.lexists(final)
    if staging_exists and final_exists:
        result["classification"] = "BOTH_STAGING_AND_FINAL"
    elif not staging_exists and not final_exists:
        result["classification"] = "NEITHER_STAGING_NOR_FINAL"
    else:
        root = original.staging_root if staging_exists else final
        try:
            if (
                _release_object_identity(root)
                != original.intent["finalization"]["staging_identity"]
            ):
                raise ReleaseControlError("original directory object differs")
            has_identity = os.path.lexists(root / _CANDIDATE_NAME)
            expected = list(original.intent["finalization"]["inventory"])
            if has_identity:
                expected.append(
                    {
                        "path": _CANDIDATE_NAME,
                        "kind": "file",
                        "sha256": sha256_json(record),
                        "size": len(canonical_json(record)),
                        "mode": 0o400,
                    }
                )
            if _candidate_inventory(root) != sorted(expected, key=lambda row: row["path"]):
                raise ReleaseControlError("original inventory differs")
            result["classification"] = (
                ("STAGING_WITH_IDENTITY" if has_identity else "STAGING_WITHOUT_IDENTITY")
                if staging_exists
                else ("FINAL_WITH_IDENTITY" if has_identity else "CONFLICT")
            )
        except (OSError, ReleaseControlError):
            result["classification"] = "CONFLICT"
    return result


_CANDIDATE_APPEND_STAGES: Final[Mapping[str, str]] = {
    "source-freeze-validation": "validate_release_source_freeze.py",
    "artifact-manifest-validation": "validate_release_artifact_manifest.py",
    "validate-release-candidate-identity": _CANDIDATE_VALIDATOR,
}


def _validate_candidate_journal_tree(
    root: Path,
    active_invocation: ReleaseInvocation | None = None,
    *,
    captured_names: set[str] | None = None,
) -> None:
    journals = root / "invocations"
    _release_object_identity(journals)
    expected_stages = {
        "source-freeze": "freeze_release_source.py",
        "artifact-build": "build_release_artifacts.py",
        **_CANDIDATE_APPEND_STAGES,
    }
    for stage in sorted(journals.iterdir()):
        if stage.name not in expected_stages:
            raise ReleaseControlError("candidate has an unknown invocation stage")
        _release_object_identity(stage)
        sequences = _journal_sequences(stage)
        if not sequences:
            raise ReleaseControlError("candidate has an empty invocation stage")
        for directory in sequences:
            context = _validate_intent(directory)
            if context.intent["tool"] != expected_stages[stage.name] or context.root != root:
                raise ReleaseControlError("candidate journal tool/root differs")
            name = directory.relative_to(root).as_posix()
            appended = captured_names is not None and name not in captured_names
            if appended and stage.name not in _CANDIDATE_APPEND_STAGES:
                raise ReleaseControlError("candidate appended a producer journal")
            active = active_invocation is not None and directory == active_invocation.directory
            if active:
                if (
                    context != active_invocation
                    or context.intent["tool"] != _CANDIDATE_VALIDATOR
                    or context.root != root
                    or read_json(directory / "worker.pid") != {"pid": os.getpid()}
                    or os.path.lexists(directory / "invocation.json")
                ):
                    raise ReleaseControlError(
                        "candidate active validator context is not the exact current worker"
                    )
                _validate_bound_invocation(context)
            else:
                _validate_terminal(context)
            if appended or active:
                # Negative evidence is allowed only for this exact validator subject.
                _validate_bound_invocation(context)
                names = {p.name for p in directory.iterdir()}
                required = {"intent.json", "stdout", "stderr"}
                allowed = required | {
                    "worker.pid",
                    "staged",
                    "worker-result.json",
                    "invocation.json",
                    "partial-files.json",
                }
                if not required <= names <= allowed or (
                    not active and "invocation.json" not in names
                ):
                    raise ReleaseControlError("appended validator journal members are not closed")
                terminal = None if active else read_json(directory / "invocation.json")
                if (active or (terminal is not None and terminal["status"] == "PASS")) and not {
                    "worker.pid",
                    "staged",
                } <= names:
                    raise ReleaseControlError("passing or active validator lacks worker evidence")
                if "worker.pid" in names:
                    pid = read_json(directory / "worker.pid")
                    if set(pid) != {"pid"} or type(pid["pid"]) is not int or pid["pid"] <= 0:
                        raise ReleaseControlError("appended validator worker identity is invalid")
                if "staged" in names:
                    _release_object_identity(directory / "staged")
                    if "worker.pid" not in names or list((directory / "staged").iterdir()):
                        raise ReleaseControlError("read-only validator staged evidence is invalid")
                if terminal is not None:
                    code = terminal["data"]["exit_code"]
                    expected_status = (
                        "PASS"
                        if code == 0
                        else "CANCELLED"
                        if code >= 128
                        else "BLOCKED"
                        if code == 3
                        else "FAIL"
                    )
                    if (
                        terminal["status"] != expected_status
                        or terminal["data"]["outputs"] != []
                        or (code != 0 and "partial-files.json" not in names)
                        or (terminal["status"] == "FAIL" and "worker-result.json" not in names)
                    ):
                        raise ReleaseControlError("appended validator outcome evidence differs")
                if "worker-result.json" in names:
                    worker = read_json(directory / "worker-result.json")
                    if (
                        not {"worker.pid", "staged"} <= names
                        or type(worker.get("exit_code")) is not int
                        or worker["exit_code"] < 0
                        or set(worker)
                        != {"schema_version", "exit_code", "outputs", "producer_intent_digest"}
                        or worker["schema_version"] != "metriplane.release-worker-result.v1"
                        or worker["outputs"] != []
                        or worker["producer_intent_digest"] != sha256_json(context.intent)
                        or (
                            terminal is not None
                            and terminal["status"] not in {"BLOCKED", "CANCELLED"}
                            and worker["exit_code"] != terminal["data"]["exit_code"]
                        )
                    ):
                        raise ReleaseControlError("appended validator worker evidence differs")
                elif terminal is not None and terminal["status"] == "PASS":
                    raise ReleaseControlError("passing validator lacks its worker verdict")


def _verify_finalized_candidate_inventory(
    context: CandidateFinalizationInvocation,
    record: Mapping[str, Any],
    *,
    allow_appended: bool = False,
    active_invocation: ReleaseInvocation | None = None,
) -> None:
    expected_record = _candidate_identity_for_context(context)
    if record != expected_record:
        raise ReleaseControlError("final candidate identity differs from original computation")
    root = Path(expected_record["data"]["final_directory"])
    value = context.intent["finalization"]
    if os.path.lexists(context.staging_root):
        raise ReleaseControlError("candidate staging location remains after finalization")
    if _release_object_identity(root) != value["staging_identity"]:
        raise ReleaseControlError("candidate final directory object differs from captured staging")
    for name, identity in value["parent_identities"].items():
        if _release_object_identity(Path(name)) != identity:
            raise ReleaseControlError("candidate parent identity changed after finalization")
    expected = list(value["inventory"]) + [
        {
            "path": _CANDIDATE_NAME,
            "kind": "file",
            "sha256": sha256_json(record),
            "size": len(canonical_json(record)),
            "mode": 0o400,
        }
    ]
    expected.sort(key=lambda row: row["path"])
    actual = _candidate_inventory(root)
    if not allow_appended:
        if actual != expected:
            raise ReleaseControlError(
                "final candidate inventory differs from its exact captured tree"
            )
    else:
        original = {row["path"]: row for row in expected}
        current = {row["path"]: row for row in actual}
        if any(current.get(name) != row for name, row in original.items()):
            raise ReleaseControlError("captured candidate member was removed or mutated")
        for name in current.keys() - original.keys():
            parts = Path(name).parts
            if (
                len(parts) < 2
                or parts[0] != "invocations"
                or parts[1] not in _CANDIDATE_APPEND_STAGES
            ):
                raise ReleaseControlError("candidate contains an unauthorized appended member")
            if len(parts) >= 3 and "/".join(parts[:3]) in original:
                raise ReleaseControlError("a captured invocation acquired an unbound member")
        _validate_candidate_journal_tree(root, active_invocation, captured_names=set(original))
    _candidate_identity_for_context(context, root)
    records = value["records"]
    validate_release_producer_journal(
        records["source-freeze.json"],
        root / "source-freeze.json",
        producer="freeze_release_source.py",
    )
    validate_release_artifact_files(
        records["artifact-manifest.json"],
        root / "artifacts",
        live=context.intent["environment"]["fixture_mode"] != "1",
    )


def _validate_finalization_completion(context: CandidateFinalizationInvocation) -> None:
    if context.intent["sequence"] != 1:
        raise ReleaseControlError("only original finalization can complete")
    required = {
        "intent.json",
        "stdout",
        "stderr",
        "worker.pid",
        "staged",
        "worker-result.json",
        "invocation.json",
        "terminal-commit.json",
    }
    if {path.name for path in context.directory.iterdir()} != required:
        raise ReleaseControlError("original finalization control members are not closed")
    if {path.name for path in (context.directory / "staged").iterdir()} != {_CANDIDATE_NAME}:
        raise ReleaseControlError("original finalization staged evidence is not closed")
    if {path.name for path in context.root.iterdir()} != {"invocations"} or {
        path.name for path in (context.root / "invocations").iterdir()
    } != {"candidate-finalization"}:
        raise ReleaseControlError("original finalization control root has unknown members")
    terminal = _validate_terminal(context)
    if terminal["status"] != "PASS":
        raise ReleaseControlError("candidate original finalization did not pass")
    expected = {
        "schema_version": "metriplane.candidate-terminal-commit.v1",
        "intent_sha256": sha256_json(context.intent),
        "terminal_sha256": sha256_json(terminal),
    }
    if _safe_release_bytes(context.directory / "terminal-commit.json") != canonical_json(expected):
        raise ReleaseControlError("candidate terminal durability receipt is missing or differs")
    record = _candidate_identity_for_context(context)
    if _safe_release_bytes(context.directory / "stdout") != _candidate_success_line(record):
        raise ReleaseControlError(
            "candidate retained success result differs from committed identity"
        )
    for directory in _journal_sequences(context.directory.parent)[1:]:
        later = _validate_intent(directory)
        if not isinstance(later, CandidateFinalizationInvocation):
            raise ReleaseControlError("candidate control acquired an unknown invocation")
        _check_finalization_history(later)
        if _validate_terminal(later)["status"] != "BLOCKED":
            raise ReleaseControlError("candidate recovery journal grants unexpected authority")


def _validate_candidate_public(
    record: Mapping[str, Any],
    *,
    predecessor_record: Mapping[str, Any],
    candidate_dir: Path,
    no_evaluation_adoption: bool,
    live: bool,
    attestation_verifier: ProviderAttestationVerifier | None,
    active_invocation: ReleaseInvocation | None,
) -> None:
    candidate = _passing_record(
        record, "release-candidate-identity", live=live, attestation_verifier=attestation_verifier
    )
    _passing_record(
        predecessor_record,
        "release-predecessor",
        live=live,
        attestation_verifier=attestation_verifier,
    )
    _validate_candidate_identity_payload(
        candidate,
        expected_digest=candidate.get("candidate_digest", ""),
        expected_milestone=candidate.get("milestone", ""),
    )
    root = _canonical_absolute_path(str(candidate_dir), "supplied candidate directory")
    if (
        no_evaluation_adoption is not True
        or candidate["evaluation_adoption_mode"] != "none"
        or candidate["evaluation_adoption_digest"] is not None
        or str(root) != candidate["final_directory"]
        or candidate["predecessor_digest"] != sha256_json(predecessor_record)
    ):
        raise ReleaseControlError("candidate supplied inputs or evaluation policy differ")
    locator = _canonical_absolute_path(
        candidate["control_journal_locator"], "candidate control locator"
    )
    context = _validate_intent(locator.parent)
    if (
        not isinstance(context, CandidateFinalizationInvocation)
        or sha256_json(context.intent) != candidate["finalization_intent_digest"]
        or _candidate_identity_for_context(context) != record
    ):
        raise ReleaseControlError("candidate original intent/identity binding differs")
    _validate_finalization_completion(context)
    _verify_finalized_candidate_inventory(
        context, record, allow_appended=True, active_invocation=active_invocation
    )


def _invocation_stage(tool: str) -> str:
    if not isinstance(tool, str) or tool not in TOOL_CONTRACTS:
        raise ReleaseControlError("unknown invocation tool")
    return _INVOCATION_STAGES.get(tool, Path(tool).stem.replace("_", "-"))


def _run_relative(root: Path, path: Path) -> str:
    absolute = path.absolute()
    if any(p.is_symlink() for p in (absolute, *absolute.parents)) or ".." in absolute.parts:
        raise ReleaseControlError("invocation path is unsafe")
    try:
        name = absolute.relative_to(root).as_posix()
    except ValueError as exc:
        raise ReleaseControlError("invocation output is outside its run root") from exc
    if name in {"", "."}:
        raise ReleaseControlError("invocation output cannot be the run root")
    return name


def _journal_path(root: Path, name: object) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or (".." in Path(name).parts or Path(name).as_posix() != name or "\\" in name)
    ):
        raise ReleaseControlError("journal reference path is not run-relative")
    path = root / name
    _run_relative(root, path)
    return path


def _durable_json(path: Path, value: object) -> str:
    payload = canonical_json(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    # A failed write remains evidence, including a possibly incomplete intent/terminal.
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha256_bytes(payload)


def _intent_identity(intent: Mapping[str, Any]) -> str:
    return "release-" + sha256_json({k: v for k, v in intent.items() if k != "invocation_id"})


def _journal_sequences(stage: Path) -> list[Path]:
    if stage.is_symlink():
        raise ReleaseControlError("invocation stage is a symlink")
    paths = list(stage.iterdir()) if stage.exists() else []
    if any(re.fullmatch(r"[0-9]{3,}", p.name) is None for p in paths):
        raise ReleaseControlError("invocation sequence contains noncanonical entries")
    paths.sort(key=lambda p: int(p.name))
    if [p.name for p in paths] != [f"{i:03d}" for i in range(1, len(paths) + 1)] or any(
        p.is_symlink() or not p.is_dir() for p in paths
    ):
        raise ReleaseControlError("invocation sequence has gaps or unsafe entries")
    return paths


def _validate_intent(directory: Path) -> ReleaseInvocation:
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ReleaseControlError("invocation directory traverses a symlink")
    raw = _safe_release_bytes(directory / "intent.json")
    intent = _source_json(raw, "invocation intent")
    if (
        set(intent)
        != (
            _INTENT_FIELDS | {"finalization"}
            if intent.get("tool") == _FINALIZER
            else _INTENT_FIELDS
        )
        or intent["schema_version"] != "metriplane.release-invocation-intent.v1"
    ):
        raise ReleaseControlError("invocation intent shape is not closed")
    sequence = intent["sequence"]
    if type(sequence) is not int or sequence < 1 or directory.name != f"{sequence:03d}":
        raise ReleaseControlError("invocation sequence is not canonical")
    if (
        directory.parent.name != _invocation_stage(intent["tool"])
        or directory.parent.parent.name != "invocations"
    ):
        raise ReleaseControlError("invocation tool/stage binding mismatch")
    if raw != canonical_json(intent) or intent["invocation_id"] != _intent_identity(intent):
        raise ReleaseControlError("invocation intent identity mismatch")
    _parse_utc_timestamp(intent["started_at"], "invocation start")
    _require_nonempty_string(intent["tool_version"], "invocation tool version")
    if (
        not isinstance(intent["argv"], list)
        or not intent["argv"]
        or any(not isinstance(v, str) or not v for v in intent["argv"])
    ):
        raise ReleaseControlError("invocation argv is invalid")
    if Path(intent["argv"][0]).name != intent["tool"]:
        raise ReleaseControlError("invocation argv tool mismatch")
    environment = intent["environment"]
    if (
        not isinstance(environment, dict)
        or set(environment)
        != {"working_directory", "python", "fixture_mode", "source_date_epoch", "python_hash_seed"}
        or any(not isinstance(v, str) for v in environment.values())
        or environment["fixture_mode"] not in {"0", "1"}
    ):
        raise ReleaseControlError("invocation environment shape is not closed")
    if not Path(environment["working_directory"]).is_absolute():
        raise ReleaseControlError("invocation working directory is not absolute")
    for key, fields in [
        ("inputs", {"path", "schema_id", "sha256"}),
        ("planned_outputs", {"path", "schema_id"}),
    ]:
        values = intent[key]
        if not isinstance(values, list):
            raise ReleaseControlError("invocation input/output inventory is invalid")
        names = []
        for row in values:
            if not isinstance(row, dict) or set(row) != fields:
                raise ReleaseControlError("invocation input/output reference is not closed")
            _require_nonempty_string(row["path"], "invocation reference path")
            _require_nonempty_string(row["schema_id"], "invocation reference type")
            if key == "inputs":
                _require_digest(row["sha256"], "invocation input")
            else:
                _journal_path(directory.parents[2], row["path"])
            names.append(row["path"])
        if names != sorted(set(names)):
            raise ReleaseControlError("invocation references are not canonical")
    predecessor = intent["predecessor"]
    if intent["tool"] == _FINALIZER:
        context = CandidateFinalizationInvocation(directory, directory.parents[2], intent)
        if sequence == 1 and (
            predecessor is not None or intent["previous_invocation_digest"] is not None
        ):
            raise ReleaseControlError("original candidate has a predecessor")
        _validate_finalization_context(context)
        return context
    if sequence == 1:
        if predecessor is not None or intent["previous_invocation_digest"] is not None:
            raise ReleaseControlError("initial invocation has an unexpected predecessor")
    else:
        if (
            not isinstance(predecessor, dict)
            or set(predecessor) != {"sequence", "intent_digest", "terminal_digest", "disposition"}
            or predecessor["sequence"] != sequence - 1
        ):
            raise ReleaseControlError("invocation predecessor is not closed")
        _require_digest(predecessor["intent_digest"], "predecessor intent")
        if predecessor["disposition"] == "TERMINAL":
            _require_digest(predecessor["terminal_digest"], "predecessor terminal")
        elif (
            predecessor["disposition"] != "INTERRUPTED_MISSING_TERMINAL"
            or predecessor["terminal_digest"] is not None
        ):
            raise ReleaseControlError("invocation predecessor disposition is invalid")
        if intent["previous_invocation_digest"] != predecessor["terminal_digest"]:
            raise ReleaseControlError("invocation predecessor digest binding mismatch")
    return ReleaseInvocation(directory, directory.parents[2], intent)


def _validate_terminal_entry(context: ReleaseInvocation) -> dict[str, Any]:
    raw = _safe_release_bytes(context.directory / "invocation.json")
    record = _source_json(raw, "terminal invocation")
    validate_record(record, "release-stage-invocation")
    data = record["data"]
    if set(data) != _JOURNAL_FIELDS or raw != canonical_json(record):
        raise ReleaseControlError("terminal invocation shape or bytes are not canonical")
    intent = context.intent
    if (
        record["invocation_id"] != intent["invocation_id"]
        or record["sequence"] != intent["sequence"]
    ):
        raise ReleaseControlError("terminal invocation identity differs from intent")
    if record["synthetic"] is not (intent["environment"]["fixture_mode"] == "1"):
        raise ReleaseControlError("terminal invocation authority mode differs from intent")
    for key in ("argv", "tool", "tool_version", "started_at", "previous_invocation_digest"):
        if data[key] != intent[key]:
            raise ReleaseControlError("terminal invocation differs from intent: " + key)
    if data["invocation_digest"] != sha256_json(
        {k: v for k, v in data.items() if k != "invocation_digest"}
    ):
        raise ReleaseControlError("terminal invocation semantic digest mismatch")
    if _parse_utc_timestamp(data["completed_at"], "invocation completion") < _parse_utc_timestamp(
        data["started_at"], "invocation start"
    ):
        raise ReleaseControlError("invocation completion precedes start")
    if (
        data["terminal_status"] not in TERMINAL_RESULTS
        or record["status"] != data["terminal_status"]
        or type(data["exit_code"]) is not int
        or data["exit_code"] < 0
    ):
        raise ReleaseControlError("terminal invocation status/exit is invalid")
    if (data["terminal_status"] == "PASS") != (data["exit_code"] == 0):
        raise ReleaseControlError("terminal invocation PASS/exit mismatch")
    for name in ("stdout", "stderr"):
        if sha256_bytes(_safe_release_bytes(context.directory / name)) != data[name + "_digest"]:
            raise ReleaseControlError("terminal invocation diagnostic bytes mismatch")
    for key in ("inputs", "outputs"):
        rows = data[key]
        if not isinstance(rows, list):
            raise ReleaseControlError("terminal invocation references are invalid")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"path", "schema_id", "sha256"}:
                raise ReleaseControlError("terminal invocation reference is not closed")
            _require_nonempty_string(row["schema_id"], "terminal reference type")
            _require_digest(row["sha256"], "terminal reference digest")
            root = context.root
            if isinstance(context, CandidateFinalizationInvocation) and key == "outputs":
                if row["path"] != _CANDIDATE_NAME:
                    raise ReleaseControlError(
                        "finalization output reference is not the identity basename"
                    )
                root = Path(_candidate_identity_for_context(context)["data"]["final_directory"])
            path = _journal_path(root, row["path"])
            if row["path"] in seen or sha256_bytes(_safe_release_bytes(path)) != row["sha256"]:
                raise ReleaseControlError(
                    "terminal invocation reference bytes or uniqueness mismatch"
                )
            seen.add(row["path"])
    if data["inputs"] != _terminal_inputs(context):
        raise ReleaseControlError(
            "terminal does not bind its exact pre-effect intent and predecessor"
        )
    if data["terminal_status"] == "PASS":
        _validate_bound_invocation(context, outputs=data["outputs"])
    return record


def _validate_terminal(context: ReleaseInvocation) -> dict[str, Any]:
    """Read every predecessor with a strictly decreasing, nonrecursive sequence."""
    if isinstance(context, CandidateFinalizationInvocation):
        actual = _validate_intent(context.directory)
        if actual != context:
            raise ReleaseControlError("finalization intent changed during terminal readback")
        _check_finalization_observation(context)
        return _validate_terminal_entry(context)
    _journal_sequences(context.directory.parent)
    current = context
    required_terminal = True
    result = None
    while True:
        actual = _validate_intent(current.directory)
        if actual.intent != current.intent:
            raise ReleaseControlError("invocation intent changed during lineage readback")
        if required_terminal:
            terminal = _validate_terminal_entry(current)
            if result is None:
                result = terminal
        else:
            if os.path.lexists(current.directory / "invocation.json"):
                raise ReleaseControlError("interrupted predecessor acquired a conflicting terminal")
            _terminal_inputs(current)
        prior = current.intent["predecessor"]
        if prior is None:
            break
        required_terminal = prior["terminal_digest"] is not None
        current = _validate_intent(current.directory.parent / f"{prior['sequence']:03d}")
    assert result is not None
    return result


def _validate_bound_invocation(
    context: ReleaseInvocation,
    *,
    outputs: list[dict[str, str]] | None = None,
    output_root: Path | None = None,
) -> None:
    """Bind implemented commands to captured input bytes and their exact output plan.

    Historical argv is checked for consistency only. Relocated subjects always
    resolve from the current run root and fixed command-specific record names.
    """
    if _safe_release_bytes(context.directory / "intent.json") != canonical_json(context.intent):
        raise ReleaseControlError("reserved invocation intent changed before use")
    if isinstance(context, CandidateFinalizationInvocation):
        _validate_finalization_bound(context, outputs=outputs, output_root=output_root)
        return
    tool = context.intent["tool"]
    if tool not in _INVOCATION_STAGES:
        return
    argv = context.intent["argv"][1:]
    historical_cwd = Path(context.intent["environment"]["working_directory"])

    def historical_path(flag: str) -> Path:
        value = _command_value(argv, flag)
        if value is None:
            raise ReleaseControlError("invocation lacks required --" + flag)
        path = Path(value)
        if not path.is_absolute():
            path = historical_cwd / path
        if ".." in path.parts:
            raise ReleaseControlError("historical invocation path is not canonical")
        return path

    historical_directory = historical_path("invocation-dir")
    if historical_directory.parts[-3:] != context.directory.parts[-3:]:
        raise ReleaseControlError("invocation argv stage/sequence differs from its intent")
    historical_root = historical_directory.parents[2]
    if tool == "freeze_release_source.py":
        declared = [("gate-input", "gate-input.json", "release-gate-input")]
        implicit = [("target-resolution.json", "release-target-resolution")]
        planned = [("out", "source-freeze.json", "release-source-freeze")]
    elif tool == "build_release_artifacts.py":
        declared = [
            ("target-resolution", "target-resolution.json", "release-target-resolution"),
            ("source-freeze", "source-freeze.json", "release-source-freeze"),
        ]
        implicit = []
        planned = [
            ("manifest", "artifact-manifest.json", "release-artifact-manifest"),
            ("out-dir", "artifacts", "release-artifact-directory"),
        ]
    elif tool == _CANDIDATE_VALIDATOR:
        declared = [
            ("record", "candidate-identity.json", "release-candidate-identity"),
            ("predecessor", "predecessor.json", "release-predecessor"),
        ]
        implicit, planned = [], []
        if (
            historical_path("candidate-dir") != historical_root
            or "--no-evaluation-adoption" not in argv
        ):
            raise ReleaseControlError("candidate validator root or evaluation policy differs")
    else:
        kind = (
            "release-source-freeze"
            if tool == "validate_release_source_freeze.py"
            else "release-artifact-manifest"
        )
        declared = [("record", kind.removeprefix("release-") + ".json", kind)]
        implicit, planned = [], []
        if (
            tool == "validate_release_artifact_manifest.py"
            and historical_path("artifacts") != historical_root / "artifacts"
        ):
            raise ReleaseControlError("artifact validator input is outside its canonical run root")
    for flag, name, _ in [*declared, *planned]:
        if historical_path(flag) != historical_root / name:
            raise ReleaseControlError(
                "invocation subject differs from its canonical run path: " + flag
            )
    names = [(name, kind) for _, name, kind in declared] + implicit
    expected_inputs = sorted(
        [
            {
                "path": str(historical_root / name),
                "schema_id": "metriplane." + kind + ".v1",
                "sha256": sha256_bytes(_safe_release_bytes(context.root / name)),
            }
            for name, kind in names
        ],
        key=lambda row: row["path"],
    )
    if context.intent["inputs"] != expected_inputs:
        raise ReleaseControlError("invocation declared input set or captured bytes changed")
    expected_plan = sorted(
        [{"path": name, "schema_id": "metriplane." + kind + ".v1"} for _, name, kind in planned],
        key=lambda row: row["path"],
    )
    if context.intent["planned_outputs"] != expected_plan:
        raise ReleaseControlError("invocation output plan differs from its exact tool contract")
    if outputs is not None:
        root = context.root if output_root is None else output_root
        expected_outputs = []
        if tool == "freeze_release_source.py":
            data = read_json(root / "source-freeze.json")["data"]
            gate_digest = sha256_bytes(_safe_release_bytes(context.root / "gate-input.json"))
            if data["gate_input_digest"] != gate_digest or data["source_sha"] != _command_value(
                argv, "source-sha"
            ):
                raise ReleaseControlError("source output differs from the exact declared inputs")
        elif tool == "build_release_artifacts.py":
            data = read_json(root / "artifact-manifest.json")["data"]
            for key, name in [
                ("source_freeze_digest", "source-freeze.json"),
                ("target_resolution_digest", "target-resolution.json"),
            ]:
                if data[key] != sha256_bytes(_safe_release_bytes(context.root / name)):
                    raise ReleaseControlError(
                        "artifact manifest differs from its declared input: " + key
                    )
        for plan in expected_plan:
            path = root / plan["path"]
            if plan["schema_id"] == "metriplane.release-artifact-directory.v1":
                manifest = read_json(root / "artifact-manifest.json")
                artifacts = _validate_artifact_manifest_payload(
                    manifest["data"], expected_milestone=manifest["data"]["milestone"]
                )
                if sorted(p.name for p in path.iterdir()) != sorted(a["path"] for a in artifacts):
                    raise ReleaseControlError(
                        "invocation artifact directory differs from its exact manifest set"
                    )
                for artifact in artifacts:
                    raw = _safe_release_bytes(path / artifact["path"])
                    if sha256_bytes(raw) != artifact["sha256"] or len(raw) != artifact["size"]:
                        raise ReleaseControlError(
                            "invocation artifact bytes differ from its manifest"
                        )
                    expected_outputs.append(
                        {
                            "path": "artifacts/" + artifact["path"],
                            "schema_id": artifact["media_type"],
                            "sha256": artifact["sha256"],
                        }
                    )
            else:
                expected_outputs.append({**plan, "sha256": sha256_bytes(_safe_release_bytes(path))})
        if outputs != sorted(expected_outputs, key=lambda row: row["path"]):
            raise ReleaseControlError("terminal outputs differ from the declared invocation plan")


def begin_release_invocation(
    tool: str,
    argv: Sequence[str],
    directory: Path,
    *,
    input_paths: Sequence[tuple[Path, str]],
    planned_outputs: Sequence[tuple[Path, str]],
) -> ReleaseInvocation:
    """Exclusively reserve a fixed-stage sequence before worker/canonical effects."""
    if tool == _FINALIZER:
        return _begin_candidate_finalization(tool, argv, directory)
    from metriplane import __version__

    directory = directory.absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)) or ".." in directory.parts:
        raise ReleaseControlError("unsafe invocation directory")
    if (
        re.fullmatch(r"[0-9]{3,}", directory.name) is None
        or int(directory.name) < 1
        or directory.name != f"{int(directory.name):03d}"
    ):
        raise ReleaseControlError("invocation directory needs a canonical positive sequence")
    if (
        directory.parent.name != _invocation_stage(tool)
        or directory.parent.parent.name != "invocations"
    ):
        raise ReleaseControlError("invocation directory has the wrong fixed tool stage")
    root = directory.parents[2]
    outputs = sorted(
        ({"path": _run_relative(root, path), "schema_id": kind} for path, kind in planned_outputs),
        key=lambda row: row["path"],
    )
    existing = _journal_sequences(directory.parent)
    if int(directory.name) != len(existing) + 1:
        raise ReleaseControlError(
            "invocation sequence collides, has gaps or is not the next sequence"
        )
    previous = None
    previous_digest = None
    if existing:
        prior = _validate_intent(existing[-1])
        if (prior.directory / "invocation.json").exists():
            prior_terminal = _validate_terminal(prior)
            previous_digest = sha256_json(prior_terminal)
        previous = {
            "sequence": prior.intent["sequence"],
            "intent_digest": sha256_json(prior.intent),
            "terminal_digest": previous_digest,
            "disposition": "TERMINAL" if previous_digest else "INTERRUPTED_MISSING_TERMINAL",
        }
    inputs = []
    for path, kind in input_paths:
        try:
            raw = _safe_release_bytes(path)
        except ReleaseControlError:
            # The worker diagnoses unavailable inputs; the retained argv still names them.
            continue
        inputs.append(
            {"path": str(path.absolute()), "schema_id": kind, "sha256": sha256_bytes(raw)}
        )
    inputs.sort(key=lambda row: row["path"])
    if len({row["path"] for row in inputs}) != len(inputs):
        raise ReleaseControlError("duplicate invocation input path")
    intent: dict[str, Any] = {
        "schema_version": "metriplane.release-invocation-intent.v1",
        "sequence": int(directory.name),
        "tool": tool,
        "tool_version": __version__,
        "argv": [tool, *argv],
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "inputs": inputs,
        "environment": {
            "working_directory": str(Path.cwd()),
            "python": sys.version.split()[0],
            "fixture_mode": "1"
            if os.environ.get("METRIPLANE_RELEASE_FIXTURE_MODE") == "1"
            else "0",
            "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH", ""),
            "python_hash_seed": os.environ.get("PYTHONHASHSEED", ""),
        },
        "planned_outputs": outputs,
        "previous_invocation_digest": previous_digest,
        "predecessor": previous,
    }
    intent["invocation_id"] = _intent_identity(intent)
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    _durable_json(directory / "intent.json", intent)
    return _validate_intent(directory)


def validate_release_producer_journal(
    record: Mapping[str, Any],
    record_path: Path,
    *,
    producer: str,
) -> None:
    """Resolve exactly one completed producer; locators never confer authority."""
    data = record["data"]
    if data.get("invocation_root_locator") != "invocations":
        raise ReleaseControlError("producer invocation-root locator is missing or unsafe")
    _require_digest(data.get("producer_intent_digest"), "producer intent")
    root = record_path.absolute().parent
    journals = root / "invocations"
    if not journals.is_dir() or journals.is_symlink():
        raise ReleaseControlError("producer invocation root is missing or unsafe")
    matches = []
    for stage in sorted(journals.iterdir()):
        if stage.is_symlink() or not stage.is_dir():
            raise ReleaseControlError("producer invocation stage is unsafe")
        for directory in _journal_sequences(stage):
            context = _validate_intent(directory)
            intent = context.intent
            if intent["tool"] != producer or intent["invocation_id"] != record["invocation_id"]:
                continue
            terminal = _validate_terminal(context)
            if (
                intent["sequence"] != record["sequence"]
                or sha256_json(intent) != data["producer_intent_digest"]
            ):
                raise ReleaseControlError("producer intent/sequence does not bind the output")
            if terminal["status"] != "PASS" or terminal["data"]["exit_code"] != 0:
                raise ReleaseControlError("producer did not complete successfully")
            output_ref = {
                "path": _run_relative(root, record_path),
                "schema_id": "metriplane." + record["record_type"] + ".v1",
                "sha256": sha256_bytes(_safe_release_bytes(record_path)),
            }
            if output_ref not in terminal["data"]["outputs"]:
                raise ReleaseControlError("producer journal does not bind the exact output")
            if producer == "build_release_artifacts.py":
                if data.get("build_invocation_id") != intent["invocation_id"]:
                    raise ReleaseControlError("artifact build invocation identity differs")
                for artifact in data["artifacts"]:
                    artifact_ref = {
                        "path": "artifacts/" + artifact["path"],
                        "schema_id": artifact["media_type"],
                        "sha256": artifact["sha256"],
                    }
                    if artifact_ref not in terminal["data"]["outputs"]:
                        raise ReleaseControlError("producer journal does not bind artifact bytes")
            matches.append(terminal)
    if len(matches) != 1:
        raise ReleaseControlError("expected exactly one completed producer invocation")


def _record_type_from_tool(tool: str) -> str:
    stem = Path(tool).stem
    for prefix in (
        "validate_",
        "capture_",
        "record_",
        "build_",
        "finalize_",
        "prepare_",
        "resolve_",
        "collect_",
        "export_",
        "update_",
        "retain_",
        "execute_",
        "plan_",
        "promote_",
        "freeze_",
        "aggregate_",
        "check_",
    ):
        if stem.startswith(prefix):
            stem = stem.removeprefix(prefix)
            break
    aliases = {
        "release_source": "release-source-freeze",
        "release_delta": "release-capability-delta",
        "release_blocker_attempt": "release-prepublication-blocker-attempt",
        "publication_reconciliation": "release-publication-reconciliation",
        "last_known_good": "release-last-known-good",
        "linear_release_snapshot": "linear-release-snapshot",
        "release_run_statuses": "release-run-status-snapshot",
        "release_task_state_observation": "release-task-state-observation",
        "release_target_observations": "release-target-observations",
        "release_evidence_stores": "release-evidence-store-preflight",
        "release_retention": "release-retention-receipts",
        "release_evidence": "release-retention-receipts",
        "release_artifacts": "release-artifact-manifest",
        "release_attempt_cells": "release-cell-result",
        "release_candidate": "release-promotion",
        "release_qualification": "release-qualification",
    }
    if Path(tool).stem == "plan_release_qualification":
        return "release-qualification-plan"
    return aliases.get(
        stem,
        stem.replace("_", "-")
        if stem.startswith("release_")
        else f"release-{stem.replace('_', '-')}",
    )


@dataclass(frozen=True)
class CommandForm:
    """One allowed section-9B invocation shape."""

    required: frozenset[str]
    equals: tuple[tuple[str, frozenset[str]], ...]


@dataclass(frozen=True)
class ToolContract:
    """Declarative CLI surface for one stable release tool."""

    forms: tuple[CommandForm, ...]
    optional: frozenset[str]
    boolean: frozenset[str]
    repeatable: frozenset[str]
    integer: frozenset[str]
    choices: Mapping[str, tuple[str, ...]]
    output_flag: str | None
    fixture_producer: bool
    record_flag: str | None
    delegated_adapter: bool = False

    @property
    def flags(self) -> frozenset[str]:
        required = frozenset().union(*(form.required for form in self.forms))
        return required | self.optional | self.boolean | self.repeatable | frozenset(self.choices)


def _command_form(specification: str) -> CommandForm:
    required: set[str] = set()
    equals: list[tuple[str, frozenset[str]]] = []
    for token in specification.split():
        name, separator, raw_values = token.partition("=")
        required.add(name)
        if separator:
            equals.append((name, frozenset(raw_values.split(","))))
    return CommandForm(frozenset(required), tuple(equals))


def _tool_contract(
    *forms: str,
    optional: str = "",
    boolean: str = "",
    repeatable: str = "",
    integer: str = "",
    choices: Mapping[str, tuple[str, ...]] | None = None,
    output_flag: str | None = "out",
    fixture_producer: bool = True,
    record_flag: str | None = None,
    delegated_adapter: bool = False,
) -> ToolContract:
    return ToolContract(
        forms=tuple(_command_form(form + " invocation-dir") for form in forms),
        optional=frozenset(optional.split()),
        boolean=frozenset(boolean.split()),
        repeatable=frozenset(repeatable.split()),
        integer=frozenset(integer.split()),
        choices={} if choices is None else choices,
        output_flag=output_flag,
        fixture_producer=fixture_producer,
        record_flag=record_flag,
        delegated_adapter=delegated_adapter,
    )


_MILESTONE_CHOICES: Final[Mapping[str, tuple[str, ...]]] = {"milestone": MILESTONES}
_MANIFEST_PHASES: Final[tuple[str, ...]] = (
    "attempt",
    "index-recovery",
    "pointer-transition",
    "postpublication-conflict",
    "prepublication",
    "prepublication-blocker-attempt",
    "qualified-publication",
    "release-completion",
    "release-completion-task-state",
    "release-finalizing-observation",
    "release-task-finalizing",
    "staging-failure",
    "target-burn",
)
_RETENTION_PHASES: Final[tuple[str, ...]] = (
    "assurance-closure",
    "assurance-deliverable",
    "assurance-packet",
    "attempt",
    "final",
    "index-recovery",
    "pointer-transition",
    "pointer-transition-envelope",
    "postpublication-conflict",
    "prepublication",
    "prepublication-blocker-attempt",
    "release-completion",
    "release-completion-task-state",
    "release-finalizing-observation",
    "release-task-finalizing",
    "staging-failure",
    "target-burn",
)
_STAGING_STAGES: Final[tuple[str, ...]] = (
    "role-resource-resolution",
    "evidence-store-preflight",
    "snapshot",
    "release-metadata",
    "target-observation",
    "burn-lineage",
    "target-resolution",
    "target-burn",
    "gate-input",
    "source-freeze",
    "impact",
    "predecessor",
    "delta",
    "artifact-build",
    "artifact-manifest",
    "candidate-finalization",
    "evaluation-adoption",
    "attempt-index-update",
    "attempt-index-validation",
    "index-recovery",
)
_BLOCKER_STAGES: Final[tuple[str, ...]] = (
    "candidate-identity-validation",
    "gate-main-health",
    "main-health-history",
    "gate-instance",
    "readiness",
    "qualification-plan",
    "attempt",
    "qualification",
    "prepublication-rubric",
    "approval",
    "prepromotion-task-state-observation",
    "prepromotion-task-state-validation",
    "prepromotion-controls",
    "promotion-plan",
    "attempt-index-checkpoint",
    "prepublication-retention",
    "promotion-execution-pre-mutation",
    "promotion-lock-recovery",
    "attempt-index-update",
    "attempt-index-validation",
    "index-recovery",
)
_CONFLICT_STAGES: Final[tuple[str, ...]] = (
    "promotion-execution",
    "promotion-lock-recovery",
    "publication-observations",
    "qualified-publication-manifest",
    "publication-reconciliation",
    "final-retention",
    "final-retention-validation",
    "evidence-chain",
    "evidence-chain-validation",
    "last-known-good",
    "last-known-good-retention",
    "last-known-good-envelope",
    "last-known-good-index",
    "last-known-good-invalidation",
    "release-task-state-observation",
    "release-task-state-validation",
    "release-task-state-evidence-manifest",
    "release-task-state-retention",
    "attempt-index-update",
    "attempt-index-validation",
    "index-recovery",
    "attempt-index-final-checkpoint",
    "release-evidence-history",
    "release-evidence-history-validation",
    "assurance-packet",
    "packet-restore",
    "packet-scan",
    "core-verifier-attestation",
    "core-verifier-attestation-validation",
    "assurance-packet-retention",
    "final-score",
    "final-score-verification",
    "assurance-closure",
    "assurance-closure-retention",
    "assurance-deliverable",
    "assurance-deliverable-restore",
    "assurance-deliverable-scan",
    "deliverable-verifier-attestation",
    "deliverable-verifier-attestation-validation",
    "assurance-deliverable-retention",
    "release-completion",
    "release-completion-retention",
    "release-completion-index",
    "cleanup",
)


TOOL_CONTRACTS: Final[Mapping[str, ToolContract]] = {
    "aggregate_release_attempt.py": _tool_contract("plan coordination attempt-dir out"),
    "build_publication_reconciliation.py": _tool_contract(
        "qualification approval promotion-lock-receipt observations evidence-manifest "
        "retention-receipts out"
    ),
    # This established artifact adapter is direct rather than a tool_main wrapper.
    "build_release_artifacts.py": _tool_contract(
        "target-resolution source-freeze out-dir manifest",
        output_flag="manifest",
        delegated_adapter=True,
    ),
    "build_release_delta_test_map.py": _tool_contract(
        "milestone delta impact-manifest obligations scenarios environments out",
        choices=_MILESTONE_CHOICES,
    ),
    "build_release_evidence_manifest.py": _tool_contract(
        "phase=target-burn,staging-failure,attempt,index-recovery,pointer-transition,"
        "release-task-finalizing,release-finalizing-observation,release-completion-task-state,"
        "release-completion input invocation-root exclude-current-invocation out",
        "phase=prepublication-blocker-attempt candidate-dir blocker invocation-root "
        "exclude-current-invocation out",
        "phase=prepublication candidate-dir round-dir invocation-root "
        "exclude-current-invocation out",
        "phase=qualified-publication staged-manifest retention-receipts "
        "promotion-lock-receipt promotion observations invocation-root "
        "exclude-current-invocation out",
        "phase=postpublication-conflict candidate-dir no-assurance-round input "
        "invocation-root exclude-current-invocation "
        "require-lkg-disposition-and-applicable-invalidation-receipt out",
        optional="additional-invocation-root",
        boolean="exclude-current-invocation no-assurance-round "
        "require-lkg-disposition-and-applicable-invalidation-receipt",
        repeatable="input additional-invocation-root",
        choices={"phase": _MANIFEST_PHASES},
    ),
    "build_release_qualification.py": _tool_contract(
        "plan attempts require-attempt-retention require-attempt-index-receipts out",
        boolean="require-attempt-retention require-attempt-index-receipts",
    ),
    "capture_linear_release_snapshot.py": _tool_contract(
        "project-id registry out",
        optional="provider-auth-from-approved-environment",
        boolean="provider-auth-from-approved-environment",
    ),
    "capture_release_run_statuses.py": _tool_contract(
        "plan attempt-id provider-run-id out always-run", boolean="always-run"
    ),
    "capture_release_target_observations.py": _tool_contract(
        "targets provider-auth-from-approved-environment out",
        boolean="provider-auth-from-approved-environment",
    ),
    "capture_release_task_state_observation.py": _tool_contract(
        "phase=prepromotion project-id task-id require-open-running role-assignments "
        "gate-instance readiness-registry frozen-linear-snapshot out",
        "phase=finalizing project-id task-id require-open-finalizing "
        "protected-transition-event require-transition require-assigned-human-actor "
        "candidate-identity gate-instance readiness-registry frozen-linear-snapshot "
        "reconciliation lkg-index-receipt attempt-index-backend "
        "require-latest-resolved-pointer-state out",
        "phase=finalizing project-id task-id require-open-finalizing "
        "protected-transition-event require-transition require-assigned-human-actor "
        "candidate-identity gate-instance readiness-registry frozen-linear-snapshot "
        "reconciliation chain-receipt lkg-index-receipt core-receipts out",
        "phase=completion project-id task-id require-open-finalizing "
        "protected-transition-event require-transition require-assigned-human-actor "
        "candidate-identity gate-instance readiness-registry frozen-linear-snapshot "
        "completion-input cleanup-plan out",
        boolean="require-open-running require-open-finalizing require-assigned-human-actor "
        "require-latest-resolved-pointer-state",
        choices={
            "phase": ("prepromotion", "finalizing", "completion"),
            "require-transition": ("open_running:open_finalizing",),
        },
    ),
    "check_release_delta.py": _tool_contract(
        "milestone target-resolution predecessor candidate-sha impact-manifest out",
        choices=_MILESTONE_CHOICES,
    ),
    "check_release_readiness.py": _tool_contract(
        "gate-instance candidate-identity predecessor linear-snapshot artifact-manifest "
        "delta delta-test-map out",
        optional="provider-attestation-keyring provider-attestation-keyring-digest",
        fixture_producer=False,
    ),
    "collect_publication_observations.py": _tool_contract(
        "promotion promotion-lock-receipt artifact-manifest targets out"
    ),
    "execute_release_qualification.py": _tool_contract("plan attempt-id cell artifacts out"),
    "export_release_attempt_index.py": _tool_contract(
        "index-backend genesis through-head stores read-back-all out",
        boolean="read-back-all",
    ),
    "export_release_burn_lineage.py": _tool_contract(
        "milestone attempt-index-backend genesis through-head read-back-all out",
        boolean="read-back-all",
        choices=_MILESTONE_CHOICES,
    ),
    "finalize_release_attempt_cells.py": _tool_contract(
        "plan attempt-id hosted-run-statuses attempt-dir out always-run",
        boolean="always-run",
    ),
    "finalize_release_candidate_identity.py": _tool_contract(
        "invocation-dir gate-input source-freeze predecessor artifact-manifest "
        "no-evaluation-adoption work-dir release-root identity-name",
        boolean="no-evaluation-adoption",
        output_flag="identity-name",
    ),
    "finalize_release_gate_instance.py": _tool_contract(
        "gate-input candidate-identity predecessor linear-snapshot obligations scenarios "
        "environments targets evidence-stores task-state-policy repository-protection "
        "main-health main-health-history store-preflight out"
    ),
    "freeze_release_source.py": _tool_contract("gate-input source-sha out"),
    "plan_release_qualification.py": _tool_contract(
        "gate-instance candidate-identity predecessor readiness delta delta-test-map "
        "scenarios candidate-manifest out"
    ),
    "prepare_release_gate_input.py": _tool_contract(
        "milestone target-resolution target-burn target-burn-index-receipt "
        "expected-predecessor-milestone predecessor-policy linear-snapshot "
        "readiness-registry obligations scenarios environments targets evidence-stores "
        "task-state-policy role-assignments out",
        "milestone target-resolution target-burn no-new-burn "
        "expected-predecessor-milestone predecessor-policy linear-snapshot "
        "readiness-registry obligations scenarios environments targets evidence-stores "
        "task-state-policy role-assignments out",
        boolean="no-new-burn",
        choices=_MILESTONE_CHOICES,
    ),
    "prepare_release_impact_manifest.py": _tool_contract(
        "milestone target-resolution base head source-freeze out",
        choices=_MILESTONE_CHOICES,
    ),
    "promote_release_candidate.py": _tool_contract(
        "dry-run gate-instance candidate-identity qualification approval "
        "prepromotion-controls prepromotion-linear-snapshot attempt-index-checkpoint "
        "artifact-manifest targets out",
        "execute invocation-dir plan prepromotion-controls prepromotion-linear-snapshot "
        "readiness-registry frozen-linear-snapshot attempt-index-checkpoint "
        "attempt-index-backend attempt-index-genesis expected-head operation-id "
        "task-state-observation task-state-policy project-id task-id "
        "provider-auth-from-approved-environment require-live-state "
        "require-live-full-release-bom-closed-except-current-decision "
        "require-live-exact-reciprocal-relations require-live-exact-milestone-assignments "
        "full-project-refetch-before-lock-and-before-first-mutation "
        "require-fresh-through-first-mutation bind-live-refetch-in-lock-receipt "
        "retention-receipts lock-receipt-out out",
        "recover-abandoned-lock invocation-dir attempt-index-backend attempt-index-genesis "
        "promotion-operation-id recovery-operation-id expected-active-head "
        "active-lock-record provider-run-termination signed-infrastructure-owner-recovery "
        "prelock-target-observations-from-lock refetch-all-targets targets out",
        boolean="dry-run execute recover-abandoned-lock "
        "provider-auth-from-approved-environment "
        "require-live-full-release-bom-closed-except-current-decision "
        "require-live-exact-reciprocal-relations require-live-exact-milestone-assignments "
        "full-project-refetch-before-lock-and-before-first-mutation "
        "require-fresh-through-first-mutation bind-live-refetch-in-lock-receipt "
        "prelock-target-observations-from-lock refetch-all-targets",
        choices={"require-live-state": ("open_running",)},
    ),
    "record_postpublication_conflict.py": _tool_contract(
        "stage candidate-identity failed-invocation-dir requires-lkg-invalidation "
        "no-assurance-round out",
        "stage candidate-identity failed-invocation-dir no-lkg-invalidation no-assurance-round out",
        optional="stage-record",
        boolean="no-assurance-round",
        choices={"stage": _CONFLICT_STAGES},
    ),
    "record_release_approval.py": _tool_contract(
        "gate-instance qualification no-prepublication-rubric signed-decision out",
        boolean="no-prepublication-rubric",
    ),
    "record_release_blocker_attempt.py": _tool_contract(
        "sequence stage disposition candidate-identity failed-invocation-dir out",
        optional="stage-record",
        integer="sequence",
        choices={"stage": _BLOCKER_STAGES, "disposition": ("recoverable", "terminal")},
    ),
    "record_release_index_recovery.py": _tool_contract(
        "scope-kind=release_staging,evaluation_staging milestone run-id "
        "original-entry-receipt failure-envelope-manifest failure-envelope-receipts "
        "failure-entry-receipt out",
        "scope-kind=release_candidate,evaluation_candidate release-tag candidate-id "
        "original-entry-receipt failure-envelope-manifest failure-envelope-receipts "
        "failure-entry-receipt out",
        "scope-kind=release_completion release-tag candidate-id assurance-round "
        "original-entry-receipt failure-envelope-manifest failure-envelope-receipts "
        "failure-entry-receipt out",
        "scope-kind=release_staging,evaluation_staging milestone run-id "
        "abandon-original-never-committed original-intent-invocation "
        "live-index-absence-proof original-task-state-observation "
        "failed-task-state-validation-invocation task-state-invalidation-reason "
        "task-state-policy project-id task-id provider-auth-from-approved-environment "
        "signed-infrastructure-owner-decision failure-envelope-manifest "
        "failure-envelope-receipts failure-entry-receipt out",
        "scope-kind=release_candidate,evaluation_candidate release-tag candidate-id "
        "abandon-original-never-committed original-intent-invocation "
        "live-index-absence-proof original-task-state-observation "
        "failed-task-state-validation-invocation task-state-invalidation-reason "
        "task-state-policy project-id task-id provider-auth-from-approved-environment "
        "signed-infrastructure-owner-decision failure-envelope-manifest "
        "failure-envelope-receipts failure-entry-receipt out",
        "scope-kind=release_completion release-tag candidate-id assurance-round "
        "abandon-original-never-committed original-intent-invocation "
        "live-index-absence-proof original-task-state-observation "
        "failed-task-state-validation-invocation task-state-invalidation-reason "
        "task-state-policy project-id task-id provider-auth-from-approved-environment "
        "signed-infrastructure-owner-decision failure-envelope-manifest "
        "failure-envelope-receipts failure-entry-receipt out",
        boolean="abandon-original-never-committed provider-auth-from-approved-environment",
        integer="assurance-round",
        choices={
            "scope-kind": (
                "release_staging",
                "release_candidate",
                "evaluation_staging",
                "evaluation_candidate",
                "release_completion",
            ),
            "task-state-invalidation-reason": ("expired", "state_changed"),
        },
    ),
    "record_release_role_assignments.py": _tool_contract(
        "milestone run-id signed-assignments policy out", choices=_MILESTONE_CHOICES
    ),
    "record_release_staging_attempt.py": _tool_contract(
        "work-dir stage failed-invocation-dir out",
        optional="stage-record",
        choices={"stage": _STAGING_STAGES},
    ),
    "record_release_target_burn.py": _tool_contract(
        "target-observations burn-lineage target-resolution out"
    ),
    "resolve_release_predecessor.py": _tool_contract(
        "milestone=v0.4 expected-predecessor-milestone chain-backend chain-genesis "
        "lkg-backend attempt-index-backend attempt-index-genesis stores v0.4-genesis "
        "genesis-only out",
        "milestone=v0.5,v0.6,v0.7,v0.8,v0.9 expected-predecessor-milestone "
        "chain-backend chain-genesis lkg-backend attempt-index-backend "
        "attempt-index-genesis stores v0.4-genesis require-prior-lkg project-id "
        "require-prior-decision-closed out",
        "milestone=v1.0 expected-predecessor-milestone chain-backend chain-genesis "
        "lkg-backend attempt-index-backend attempt-index-genesis stores v0.4-genesis "
        "require-prior-lkg require-prior-completion project-id "
        "require-prior-decision-closed out",
        boolean="genesis-only require-prior-lkg require-prior-completion "
        "require-prior-decision-closed",
        choices=_MILESTONE_CHOICES,
    ),
    "resolve_release_target.py": _tool_contract(
        "milestone initial-package-version initial-release-tag targets "
        "live-target-observations retained-burn-lineage out",
        choices=_MILESTONE_CHOICES,
    ),
    "retain_release_evidence.py": _tool_contract(
        "phase manifest stores out",
        "phase input stores out",
        "phase input manifest invocation-root through-stage exclude-current-invocation stores out",
        boolean="exclude-current-invocation",
        repeatable="input",
        choices={"phase": _RETENTION_PHASES},
    ),
    "update_last_known_good.py": _tool_contract(
        "reconciliation chain-receipt lkg-backend expected-generation "
        "expected-previous-release expected-chain-head operation-id prior-invocation-root "
        "require-prior-stages targets out",
        "invalidate current-receipt conflict signed-invalidation-decision lkg-backend "
        "expected-generation operation-id out",
        "validate-invalidation receipt lkg-backend read-back",
        boolean="invalidate validate-invalidation read-back",
        integer="expected-generation",
    ),
    "update_release_attempt_index.py": _tool_contract(
        "entry-manifest entry-receipts scope-kind=release_staging,evaluation_staging "
        "milestone run-id stage=target-burn,index-recovery sequence "
        "release-tag candidate-id-not-resolved index-backend expected-head operation-id out",
        "entry-manifest entry-receipts scope-kind=release_candidate,evaluation_candidate "
        "release-tag candidate-id stage=qualification-attempt,index-recovery,pointer-transition "
        "sequence "
        "index-backend expected-head operation-id out",
        "entry-manifest entry-receipts scope-kind=release_candidate release-tag candidate-id "
        "stage=release-task-finalizing sequence "
        "index-backend expected-head operation-id task-state-observation task-state-policy "
        "project-id task-id provider-auth-from-approved-environment require-live-state "
        "require-fresh-through-commit bind-live-refetch-in-receipt out",
        "entry-manifest entry-receipts scope-kind=release_completion release-tag candidate-id "
        "assurance-round completion-manifest-digest stage=release-completion sequence "
        "index-backend expected-head operation-id "
        "task-state-observation task-state-policy project-id task-id "
        "provider-auth-from-approved-environment require-live-state "
        "require-fresh-through-commit bind-live-refetch-in-receipt out",
        boolean="candidate-id-not-resolved provider-auth-from-approved-environment "
        "require-fresh-through-commit bind-live-refetch-in-receipt",
        integer="sequence assurance-round",
        choices={
            "scope-kind": (
                "release_staging",
                "release_candidate",
                "evaluation_staging",
                "evaluation_candidate",
                "release_completion",
            ),
            "stage": (
                "target-burn",
                "qualification-attempt",
                "index-recovery",
                "pointer-transition",
                "release-task-finalizing",
                "release-completion",
            ),
            "require-live-state": ("open_finalizing",),
        },
    ),
    "update_release_evidence_chain.py": _tool_contract(
        "reconciliation evidence-manifest final-receipts chain-backend expected-head "
        "operation-id prior-invocation-root require-prior-stages out"
    ),
    "validate_linear_release_snapshot.py": _tool_contract(
        "record registry",
        "record registry frozen-snapshot milestone current-decision "
        "require-full-release-bom-closed-except-current-decision "
        "require-exact-reciprocal-relations require-exact-milestone-assignments "
        "require-current-decision-state",
        boolean="require-full-release-bom-closed-except-current-decision "
        "require-exact-reciprocal-relations require-exact-milestone-assignments",
        choices={
            "milestone": MILESTONES,
            "require-current-decision-state": ("open_running",),
        },
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_publication_reconciliation.py": _tool_contract(
        "record",
        optional=(
            "authority-policy-digest provider-attestation-keyring "
            "provider-attestation-keyring-digest store-readback attempt-store-readback"
        ),
        repeatable="store-readback attempt-store-readback",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_approval.py": _tool_contract(
        "approval-decision gate-instance qualification role-assignments "
        "no-prepublication-rubric record",
        optional=(
            "authority-policy-digest provider-attestation-keyring "
            "provider-attestation-keyring-digest"
        ),
        boolean="no-prepublication-rubric",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_artifact_manifest.py": _tool_contract(
        "record artifacts read-hash",
        optional="provider-attestation-keyring provider-attestation-keyring-digest",
        boolean="read-hash",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_attempt.py": _tool_contract(
        "plan attempt-dir record", output_flag=None, fixture_producer=False, record_flag="record"
    ),
    "validate_release_attempt_index.py": _tool_contract(
        "index-backend genesis through-receipt read-back",
        "record index-backend genesis read-back",
        boolean="read-back",
        output_flag=None,
        fixture_producer=False,
        record_flag=None,
    ),
    "validate_release_candidate_identity.py": _tool_contract(
        "record predecessor no-evaluation-adoption candidate-dir",
        optional="provider-attestation-keyring provider-attestation-keyring-digest",
        boolean="no-evaluation-adoption",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_evidence_chain.py": _tool_contract(
        "chain-backend expected-reconciliation receipt",
        output_flag=None,
        fixture_producer=False,
        record_flag="receipt",
    ),
    "validate_release_evidence_manifest.py": _tool_contract(
        "record",
        optional="require-lkg-disposition-and-applicable-invalidation-receipt",
        boolean="require-lkg-disposition-and-applicable-invalidation-receipt",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_evidence_stores.py": _tool_contract(
        "stores mode=preflight scope require-backends out",
        choices={"mode": ("preflight",)},
    ),
    "validate_release_gate_input.py": _tool_contract(
        "record", output_flag=None, fixture_producer=False, record_flag="record"
    ),
    "validate_release_gate_instance.py": _tool_contract(
        "record candidate-identity predecessor task-state-policy",
        optional="provider-attestation-keyring provider-attestation-keyring-digest",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_predecessor.py": _tool_contract(
        "record milestone=v0.4 validate-genesis-only",
        "record milestone=v0.5,v0.6,v0.7,v0.8,v0.9 read-back-chain read-back-lkg "
        "read-back-pointer-index require-embedded-prior-decision-closed-observation",
        "record milestone=v1.0 read-back-chain read-back-lkg read-back-pointer-index "
        "read-back-required-completion require-embedded-prior-decision-closed-observation",
        boolean="validate-genesis-only read-back-chain read-back-lkg "
        "read-back-pointer-index read-back-required-completion "
        "require-embedded-prior-decision-closed-observation",
        choices=_MILESTONE_CHOICES,
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_prepromotion_controls.py": _tool_contract(
        "gate-instance release-task-state linear-snapshot main-health repository-protection out"
    ),
    "validate_release_qualification.py": _tool_contract(
        "record",
        optional=(
            "provider-attestation-keyring provider-attestation-keyring-digest "
            "attempt-store-readback"
        ),
        repeatable="attempt-store-readback",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_qualification_plan.py": _tool_contract(
        "record gate-instance",
        optional="provider-attestation-keyring provider-attestation-keyring-digest",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_retention.py": _tool_contract(
        "manifest receipts read-back",
        "input receipts read-back",
        "input manifest invocation-root through-stage receipts read-back",
        optional=(
            "provider-attestation-keyring provider-attestation-keyring-digest store-readback"
        ),
        boolean="read-back",
        repeatable="input store-readback",
        output_flag=None,
        fixture_producer=False,
        record_flag=None,
    ),
    "validate_release_role_assignments.py": _tool_contract(
        "record milestone run-id check-conflicts check-freshness",
        optional=(
            "authority-policy-digest provider-attestation-keyring "
            "provider-attestation-keyring-digest"
        ),
        boolean="check-conflicts check-freshness",
        choices=_MILESTONE_CHOICES,
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_source_freeze.py": _tool_contract(
        "record verify-tree-clean",
        boolean="verify-tree-clean",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_target_resolution.py": _tool_contract(
        "record targets read-back-lineage",
        boolean="read-back-lineage",
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
    "validate_release_task_state_observation.py": _tool_contract(
        "phase=prepromotion record task-id gate-instance readiness-registry "
        "frozen-linear-snapshot policy require-open-running require-assigned-authority "
        "check-freshness minimum-validity-seconds",
        "phase=finalizing record task-id gate-instance readiness-registry "
        "frozen-linear-snapshot policy require-open-finalizing "
        "require-no-other-open-required-task check-freshness minimum-validity-seconds",
        "phase=completion record task-id gate-instance readiness-registry "
        "frozen-linear-snapshot policy require-open-finalizing "
        "require-no-other-open-required-task check-freshness minimum-validity-seconds",
        boolean="require-open-running require-assigned-authority require-open-finalizing "
        "require-no-other-open-required-task check-freshness",
        integer="minimum-validity-seconds",
        choices={"phase": ("prepromotion", "finalizing", "completion")},
        output_flag=None,
        fixture_producer=False,
        record_flag="record",
    ),
}


def _argument_destination(flag: str) -> str:
    return flag.replace(".", "_").replace("-", "_")


def _build_tool_parser(name: str, contract: ToolContract) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=name,
        allow_abbrev=False,
        description="Metriplane release qualification interface (contract section 9.B).",
        epilog="Required forms: "
        + " | ".join(
            " ".join(f"--{flag}" for flag in sorted(form.required)) for form in contract.forms
        ),
    )
    common_required = set.intersection(*(set(form.required) for form in contract.forms))
    for flag in sorted(contract.flags):
        kwargs: dict[str, Any] = {
            "dest": _argument_destination(flag),
            "required": flag in common_required,
        }
        if flag in contract.boolean:
            kwargs["action"] = "store_true"
        elif flag in contract.repeatable:
            kwargs["action"] = "append"
        elif flag not in contract.choices:
            kwargs["metavar"] = flag.upper().replace("-", "_").replace(".", "_")
        if flag in contract.integer:
            kwargs["type"] = int
        if flag in contract.choices:
            kwargs["choices"] = contract.choices[flag]
        parser.add_argument(f"--{flag}", **kwargs)
    return parser


def _present_flags(args: argparse.Namespace, contract: ToolContract) -> frozenset[str]:
    present = set()
    for flag in contract.flags:
        value = getattr(args, _argument_destination(flag))
        if value not in (None, False, []):
            present.add(flag)
    return frozenset(present)


def _matches_form(
    args: argparse.Namespace,
    present: frozenset[str],
    form: CommandForm,
    contract: ToolContract,
) -> bool:
    if not form.required <= present or not present <= form.required | contract.optional:
        return False
    for flag, allowed_values in form.equals:
        if getattr(args, _argument_destination(flag)) not in allowed_values:
            return False
    return True


def _normalized_arguments(args: argparse.Namespace, contract: ToolContract) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for flag in sorted(contract.flags):
        value = getattr(args, _argument_destination(flag))
        if value not in (None, False, []):
            result[flag] = value
    return result


def _attestation_verifier_from_args(
    args: argparse.Namespace,
    *,
    live: bool,
) -> ProviderAttestationVerifier | None:
    value = getattr(args, "provider_attestation_keyring", None)
    expected_digest = getattr(args, "provider_attestation_keyring_digest", None)
    if value is None:
        if expected_digest is not None:
            raise ReleaseControlError("provider attestation keyring digest has no keyring")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReleaseControlError("provider attestation keyring path is missing")
    if live and expected_digest is None:
        raise ReleaseControlError("live provider attestation keyring digest is missing")
    if expected_digest is not None and not isinstance(expected_digest, str):
        raise ReleaseControlError("provider attestation keyring digest is invalid")
    return ProviderAttestationVerifier.from_keyring(
        Path(value),
        expected_digest=expected_digest,
    )


def _store_readbacks_from_args(values: object) -> Mapping[str, Path] | None:
    if values in (None, []):
        return None
    if not isinstance(values, list):
        raise ReleaseControlError("store readbacks must be repeatable bindings")
    parsed: dict[str, Path] = {}
    for value in values:
        if not isinstance(value, str) or value.count("=") != 1:
            raise ReleaseControlError("store readback must use STORE_ID=PATH")
        store_id, raw_path = value.split("=", 1)
        if store_id not in {"payload-store-a", "payload-store-b"} or not raw_path:
            raise ReleaseControlError("store readback binding is invalid")
        if store_id in parsed:
            raise ReleaseControlError("store readback binding is duplicated")
        parsed[store_id] = Path(raw_path)
    return parsed


def _attempt_store_readbacks_from_args(
    values: object,
) -> Mapping[str, Mapping[str, Path]] | None:
    if values in (None, []):
        return None
    if not isinstance(values, list):
        raise ReleaseControlError("attempt store readbacks must be repeatable bindings")
    parsed: dict[str, dict[str, Path]] = {}
    for value in values:
        if not isinstance(value, str) or value.count("=") != 1:
            raise ReleaseControlError(
                "attempt store readback must use RETENTION_DIGEST:STORE_ID=PATH"
            )
        identity, raw_path = value.split("=", 1)
        if identity.count(":") != 1 or not raw_path:
            raise ReleaseControlError("attempt store readback binding is invalid")
        retention_digest, store_id = identity.split(":", 1)
        _require_digest(retention_digest, "attempt retention readback")
        if store_id not in {"payload-store-a", "payload-store-b"}:
            raise ReleaseControlError("attempt store readback store id is invalid")
        stores = parsed.setdefault(retention_digest, {})
        if store_id in stores:
            raise ReleaseControlError("attempt store readback binding is duplicated")
        stores[store_id] = Path(raw_path)
    return parsed


def _blocked_result(name: str, reason: str) -> dict[str, Any]:
    return {"reason": reason, "status": "BLOCKED_NOT_READY", "tool": name}


def _legacy_internal_validator(tool: str, argv: Sequence[str]) -> int | None:
    """Keep one pre-contract unit seam; executable wrappers never enter it."""

    if Path(tool).parent != Path(".") or "--input" not in argv or "--mode" not in argv:
        return None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mode", choices=("fixture", "live"), required=True)
    args = parser.parse_args(argv)
    result = read_json(args.input)
    if Path(tool).stem != "validate_release_role_assignments":
        raise ReleaseControlError("legacy internal validation is not available for this tool")
    validate_role_assignments(result, live=args.mode == "live")
    return 0


def _tool_operation(tool: str, argv: Sequence[str], context: ReleaseInvocation) -> int:
    """Run one exact section-9B adapter without inventing live authority."""

    arguments = list(argv) if argv is not None else None
    if arguments is not None:
        try:
            legacy_result = _legacy_internal_validator(tool, arguments)
        except ReleaseControlError as exc:
            raise SystemExit(f"release control failed: {exc}") from exc
        if legacy_result is not None:
            return legacy_result
    name = Path(tool).name
    contract = TOOL_CONTRACTS.get(name)
    if contract is None:
        raise ReleaseControlError(f"unknown release tool contract: {name}")
    if contract.delegated_adapter:
        raise ReleaseControlError(f"{name} owns its parser and must not call tool_main")
    parser = _build_tool_parser(name, contract)
    args = parser.parse_args(arguments)
    present = _present_flags(args, contract)
    for flag in present:
        value = getattr(args, _argument_destination(flag))
        values = value if isinstance(value, list) else [value]
        if any(isinstance(item, str) and not item.strip() for item in values):
            parser.error(f"--{flag} cannot be empty")
    if not any(_matches_form(args, present, form, contract) for form in contract.forms):
        parser.error("arguments do not satisfy any documented section-9B command form")

    if Path(args.invocation_dir).absolute() != context.directory:
        parser.error("invocation directory differs from the reserved intent")
    if contract.output_flag is not None and name != _FINALIZER:
        destination = getattr(args, _argument_destination(contract.output_flag), None)
        if destination is not None:
            relative = _run_relative(context.root, Path(destination))
            if Path(relative).parent != Path("."):
                raise ReleaseControlError(
                    "canonical release record must be directly in its run root"
                )
            setattr(
                args,
                _argument_destination(contract.output_flag),
                str(context.directory / "staged" / relative),
            )

    fixture_mode = os.environ.get("METRIPLANE_RELEASE_FIXTURE_MODE") == "1"
    try:
        attestation_verifier = _attestation_verifier_from_args(args, live=not fixture_mode)
        if name == _FINALIZER:
            if not isinstance(context, CandidateFinalizationInvocation):
                raise ReleaseControlError("finalizer lacks its typed context")
            result = _verify_finalization_source(context)
            _durable_json(context.directory / "staged" / _CANDIDATE_NAME, result)
            return 0
        if name == "freeze_release_source.py":
            if context.intent["sequence"] != 1:
                raise ReleaseControlError("source producer retry requires a new staging run")
            gate_path = Path(args.gate_input).absolute()
            if gate_path != context.root / "gate-input.json":
                raise ReleaseControlError(
                    "source gate input must be gate-input.json in the run root"
                )
            result = build_release_source_freeze_record(
                gate_path,
                args.source_sha,
                frozen_at=context.intent["started_at"],
                invocation_id=context.intent["invocation_id"],
                sequence=context.intent["sequence"],
                producer_intent_digest=sha256_json(context.intent),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            write_immutable_json(Path(args.out), result)
            print(canonical_json(result).decode("utf-8"))
            return 0
        if name == "validate_release_source_freeze.py":
            record_path = Path(args.record).absolute()
            result = read_json(record_path)
            validate_release_source_freeze_record(
                result,
                record_path,
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            print(canonical_json(result).decode("utf-8"))
            return 0
        if name == "check_release_readiness.py":
            readiness_paths = [
                Path(args.gate_instance),
                Path(args.candidate_identity),
                Path(args.predecessor),
                Path(args.linear_snapshot),
                Path(args.artifact_manifest),
                Path(args.delta),
                Path(args.delta_test_map),
            ]
            candidate_root = readiness_paths[0].parent
            if candidate_root.is_symlink() or not candidate_root.is_dir():
                raise ReleaseControlError("release candidate directory is missing or unsafe")
            if any(path.parent != candidate_root for path in readiness_paths[1:]):
                raise ReleaseControlError("readiness inputs do not share one candidate directory")
            gate_input = _release_input(
                candidate_root / "gate-input.json",
                "release-gate-input",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            gate_instance = _release_input(
                readiness_paths[0],
                "release-gate-instance",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            candidate = _release_input(
                readiness_paths[1],
                "release-candidate-identity",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            predecessor = _release_input(
                readiness_paths[2],
                "release-predecessor",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            linear_snapshot = _release_input(
                readiness_paths[3],
                "linear-release-snapshot",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            source_freeze = _release_input(
                candidate_root / "source-freeze.json",
                "release-source-freeze",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            impact_manifest = _release_input(
                candidate_root / "impact-manifest.json",
                "release-impact-manifest",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            artifact_manifest = _release_input(
                readiness_paths[4],
                "release-artifact-manifest",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            delta = _release_input(
                readiness_paths[5],
                "release-capability-delta",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            delta_test_map = _release_input(
                readiness_paths[6],
                "release-delta-test-map",
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
            readiness_registry = read_json(Path("docs/status/release-readiness.json"))
            result = build_release_readiness_record(
                gate_input=gate_input,
                gate_instance=gate_instance,
                candidate_identity_record=candidate,
                predecessor=predecessor,
                linear_snapshot=linear_snapshot,
                source_freeze=source_freeze,
                impact_manifest=impact_manifest,
                artifact_manifest=artifact_manifest,
                delta=delta,
                delta_test_map=delta_test_map,
                readiness_registry=readiness_registry,
            )
            write_immutable_json(Path(args.out), result)
            print(canonical_json(result).decode("utf-8"))
            return 0 if result["data"]["disposition"] == "READY" else 3
        if name == "validate_release_artifact_manifest.py":
            result = read_json(Path(args.record))
            validate_release_artifact_files(
                result,
                Path(args.artifacts),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
                record_path=Path(args.record),
            )
        elif name == "validate_release_retention.py":
            result = read_json(Path(args.receipts))
            raw_inputs = args.input if isinstance(args.input, list) else []
            validate_release_retention_receipts(
                result,
                inputs=[Path(value) for value in raw_inputs],
                manifest=Path(args.manifest) if args.manifest is not None else None,
                invocation_root=(
                    Path(args.invocation_root) if args.invocation_root is not None else None
                ),
                through_stage=args.through_stage,
                live=not fixture_mode,
                readbacks=_store_readbacks_from_args(args.store_readback),
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_qualification.py":
            record_path = Path(args.record)
            result = read_json(record_path)
            validate_release_qualification_record(
                result,
                evidence_root=record_path.parent,
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
                attempt_retention_readbacks=_attempt_store_readbacks_from_args(
                    args.attempt_store_readback
                ),
            )
        elif name == "validate_publication_reconciliation.py":
            record_path = Path(args.record)
            result = read_json(record_path)
            validate_publication_reconciliation_record(
                result,
                evidence_root=record_path.parent,
                live=not fixture_mode,
                expected_authority_policy_digest=args.authority_policy_digest,
                attestation_verifier=attestation_verifier,
                retention_readbacks=_store_readbacks_from_args(args.store_readback),
                attempt_retention_readbacks=_attempt_store_readbacks_from_args(
                    args.attempt_store_readback
                ),
            )
        elif name == "validate_release_gate_instance.py":
            result = read_json(Path(args.record))
            validate_release_gate_instance_record(
                result,
                candidate_identity_record=read_json(Path(args.candidate_identity)),
                predecessor_record=read_json(Path(args.predecessor)),
                task_state_policy=read_json(Path(args.task_state_policy)),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_qualification_plan.py":
            result = read_json(Path(args.record))
            validate_release_qualification_plan_record(
                result,
                gate_instance=read_json(Path(args.gate_instance)),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_approval.py":
            result = read_json(Path(args.record))
            validate_release_approval_record(
                result,
                approval_decision=read_json(Path(args.approval_decision)),
                gate_instance=read_json(Path(args.gate_instance)),
                qualification=read_json(Path(args.qualification)),
                role_assignments=read_json(Path(args.role_assignments)),
                no_prepublication_rubric=bool(args.no_prepublication_rubric),
                live=not fixture_mode,
                expected_authority_policy_digest=args.authority_policy_digest,
                attestation_verifier=attestation_verifier,
            )
        elif name == "validate_release_candidate_identity.py":
            result = read_json(Path(args.record))
            validate_release_candidate_identity_record(
                result,
                predecessor_record=read_json(Path(args.predecessor)),
                candidate_dir=Path(args.candidate_dir),
                no_evaluation_adoption=bool(args.no_evaluation_adoption),
                live=not fixture_mode,
                attestation_verifier=attestation_verifier,
                _active_invocation=context,
            )
        elif contract.fixture_producer:
            result = _blocked_result(
                name,
                "subject-specific operation is not implemented; fixture arguments cannot create PASS evidence",
            )
            print(canonical_json(result).decode("utf-8"))
            return 3
        elif contract.record_flag is not None:
            record_value = getattr(args, _argument_destination(contract.record_flag))
            if not isinstance(record_value, str):
                raise ReleaseControlError("validator record path is missing")
            result = read_json(Path(record_value))
            expected_type = _record_type_from_tool(name)
            if name == "validate_release_role_assignments.py":
                validate_role_assignments(
                    result,
                    live=not fixture_mode,
                    expected_milestone=args.milestone,
                    expected_run_id=args.run_id,
                    expected_authority_policy_digest=args.authority_policy_digest,
                    check_conflicts=bool(args.check_conflicts),
                    check_freshness=bool(args.check_freshness),
                    attestation_verifier=attestation_verifier,
                )
            else:
                _passing_record(result, expected_type, live=not fixture_mode)
                result = _blocked_result(
                    name,
                    "subject-specific dependency and read-back validation is not implemented",
                )
                print(canonical_json(result).decode("utf-8"))
                return 3
        else:
            result = _blocked_result(
                name,
                "subject-specific live read-back validation is not implemented",
            )
            print(canonical_json(result).decode("utf-8"))
            return 3
        print(canonical_json(result).decode("utf-8"))
    except (OSError, ReleaseControlError) as exc:
        result = _blocked_result(name, str(exc))
        print(canonical_json(result).decode("utf-8"))
        return 3
    return 0


def _command_value(argv: Sequence[str], flag: str) -> str | None:
    values = []
    for index, argument in enumerate(argv):
        if argument == "--" + flag:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise ReleaseControlError("missing --" + flag + " value")
            values.append(argv[index + 1])
        elif argument.startswith("--" + flag + "="):
            values.append(argument.split("=", 1)[1])
    if len(values) > 1 or any(not value.strip() for value in values):
        raise ReleaseControlError("duplicate or empty --" + flag)
    return values[0] if values else None


def _collect_staged_outputs(context: ReleaseInvocation) -> list[dict[str, str]]:
    result = []
    staged = context.directory / "staged"
    for planned in context.intent["planned_outputs"]:
        source = _journal_path(staged, planned["path"])
        paths = (
            sorted(source.iterdir())
            if planned["schema_id"] == "metriplane.release-artifact-directory.v1"
            else [source]
        )
        if not paths:
            raise ReleaseControlError("worker produced an empty output set")
        for path in paths:
            raw = _safe_release_bytes(path)
            kind = planned["schema_id"]
            if kind == "metriplane.release-artifact-directory.v1":
                kind = (
                    "application/vnd.pypa.wheel+zip"
                    if path.name.endswith(".whl")
                    else "application/gzip"
                    if path.name.endswith(".tar.gz")
                    else ""
                )
                if not kind:
                    raise ReleaseControlError("worker produced an unknown artifact")
            else:
                record = _source_json(raw, "staged output")
                validate_record(record, kind.removeprefix("metriplane.").removesuffix(".v1"))
                if raw != canonical_json(record):
                    raise ReleaseControlError("worker output record is not canonical")
            result.append(
                {
                    "path": _run_relative(staged, path),
                    "schema_id": kind,
                    "sha256": sha256_bytes(raw),
                }
            )
    return sorted(result, key=lambda row: row["path"])


def _release_worker_main(directory: str) -> int:
    context = _validate_intent(Path(directory))
    _durable_json(context.directory / "worker.pid", {"pid": os.getpid()})
    context.directory.joinpath("staged").mkdir()
    tool = context.intent["tool"]
    if tool == "build_release_artifacts.py":
        from tools import build_release_artifacts as artifact_adapter
    os.chdir(context.intent["environment"]["working_directory"])
    os.environ["METRIPLANE_RELEASE_FIXTURE_MODE"] = context.intent["environment"]["fixture_mode"]
    try:
        _validate_bound_invocation(context)
        if tool == "build_release_artifacts.py":
            args = artifact_adapter._parse_args(context.intent["argv"][1:])
            artifact_adapter._execute(args, context=context)
            code = 0
        else:
            code = _tool_operation(tool, context.intent["argv"][1:], context)
        outputs = _collect_staged_outputs(context) if code == 0 else []
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        outputs = []
    except Exception as exc:
        code = (
            2
            if tool == "build_release_artifacts.py"
            and isinstance(exc, artifact_adapter.ArtifactInputError)
            else 3
        )
        print(
            canonical_json(
                {
                    "tool": tool,
                    "reason": str(exc),
                    "status": "INVALID_INPUT" if code == 2 else "BLOCKED_NOT_READY",
                }
            ).decode(),
            file=sys.stderr,
        )
        outputs = []
    _durable_json(
        context.directory / "worker-result.json",
        {
            "schema_version": "metriplane.release-worker-result.v1",
            "exit_code": code,
            "outputs": outputs,
            "producer_intent_digest": sha256_json(context.intent),
        },
    )
    return code


def _verify_staged_outputs(context: ReleaseInvocation, outputs: list[dict[str, str]]) -> None:
    _validate_bound_invocation(context, outputs=outputs, output_root=context.directory / "staged")
    if outputs != _collect_staged_outputs(context):
        raise ReleaseControlError("worker output inventory or bytes changed")
    tool = context.intent["tool"]
    repository = (
        _source_repository(Path(context.intent["environment"]["working_directory"]))
        if tool in {"freeze_release_source.py", "build_release_artifacts.py"}
        else None
    )
    for row in outputs:
        if not row["schema_id"].startswith("metriplane.release-"):
            continue
        record = read_json(context.directory / "staged" / row["path"])
        if (
            record["invocation_id"] != context.intent["invocation_id"]
            or record["sequence"] != context.intent["sequence"]
        ):
            raise ReleaseControlError("worker output identity differs from pre-effect intent")
        data = record["data"]
        if tool == "freeze_release_source.py":
            assert repository is not None
            actual, _ = _source_freeze_payload(
                context.root / "gate-input.json",
                data["source_sha"],
                repository=repository,
                frozen_at=context.intent["started_at"],
                producer_intent_digest=sha256_json(context.intent),
                live=context.intent["environment"]["fixture_mode"] != "1",
                attestation_verifier=None,
            )
            if actual != data:
                raise ReleaseControlError("supervisor source-freeze revalidation differs")
        if tool == "build_release_artifacts.py":
            artifacts = _validate_artifact_manifest_payload(
                data, expected_milestone=data["milestone"]
            )
            if (
                data["producer_intent_digest"] != sha256_json(context.intent)
                or data["build_invocation_id"] != context.intent["invocation_id"]
            ):
                raise ReleaseControlError("supervisor artifact intent binding differs")
            expected = [
                {
                    "path": "artifacts/" + a["path"],
                    "schema_id": a["media_type"],
                    "sha256": a["sha256"],
                }
                for a in artifacts
            ]
            actual_outputs = [r for r in outputs if not r["schema_id"].startswith("metriplane.")]
            if expected != actual_outputs:
                raise ReleaseControlError("supervisor artifact output set differs from manifest")


def _install_release_outputs(
    context: ReleaseInvocation,
    outputs: list[dict[str, str]],
    *,
    artifact_installer: Callable[[Path, Path], list[tuple[Path, Path]]] | None = None,
) -> None:
    if isinstance(context, CandidateFinalizationInvocation):
        _install_candidate_identity(context, outputs)
        return
    installed: list[tuple[Path, Path]] = []
    created_directories: list[Path] = []
    try:
        for planned in context.intent["planned_outputs"]:
            destination = _journal_path(context.root, planned["path"])
            if destination.exists() or destination.is_symlink():
                raise ReleaseControlError(
                    "refusing to overwrite canonical output: " + str(destination)
                )
            if planned["schema_id"] == "metriplane.release-artifact-directory.v1":
                if artifact_installer is None:
                    raise ReleaseControlError("canonical artifact installer is unavailable")
                installed.extend(
                    artifact_installer(context.directory / "staged" / planned["path"], destination)
                )
                created_directories.append(destination)
        # Install the manifest after its artifact files. No output replacement or EXDEV fallback.
        for row in sorted(
            outputs, key=lambda r: (r["schema_id"].startswith("metriplane."), r["path"])
        ):
            if not row["schema_id"].startswith("metriplane."):
                continue
            source = _journal_path(context.directory / "staged", row["path"])
            destination = _journal_path(context.root, row["path"])
            if sha256_bytes(_safe_release_bytes(source)) != row["sha256"]:
                raise ReleaseControlError("staged bytes changed before installation")
            source.chmod(0o400)
            os.link(source, destination, follow_symlinks=False)
            installed.append((source, destination))
        descriptor = os.open(context.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        for source, destination in reversed(installed):
            try:
                origin, current = source.stat(), destination.stat(follow_symlinks=False)
                if (origin.st_dev, origin.st_ino) == (current.st_dev, current.st_ino):
                    destination.unlink()
            except OSError:
                pass
        for path in reversed(created_directories):
            try:
                path.rmdir()
            except OSError:
                pass
        raise


def _terminal_inputs(context: ReleaseInvocation) -> list[dict[str, str]]:
    paths = [(context.directory / "intent.json", "metriplane.release-invocation-intent.v1")]
    if (context.directory / "partial-files.json").exists():
        raw = _safe_release_bytes(context.directory / "partial-files.json")
        value = _source_json(raw, "partial file inventory")
        if raw != canonical_json(value) or value != _partial_file_projection(context):
            raise ReleaseControlError("retained partial file inventory or bytes changed")
        paths.append(
            (context.directory / "partial-files.json", "metriplane.release-partial-files.v1")
        )
    if isinstance(context, CandidateFinalizationInvocation):
        _check_finalization_observation(context)
        for row in context.intent["finalization"]["history"]:
            previous = context.directory.parent / f"{row['sequence']:03d}"
            for kind, name in [
                ("intent", "intent.json"),
                ("terminal", "invocation.json"),
                ("commit", "terminal-commit.json"),
            ]:
                if row[kind]["state"] == "RAW":
                    paths.append((previous / name, "application/octet-stream"))
        if (context.directory / "classification.json").exists():
            paths.append(
                (
                    context.directory / "classification.json",
                    "metriplane.candidate-finalization-diagnostic.v1",
                )
            )
        for name, kind in [
            ("worker.pid", "application/json"),
            ("worker-result.json", "metriplane.release-worker-result.v1"),
            ("staged/candidate-identity.json", "metriplane.release-candidate-identity.v1"),
        ]:
            path = context.directory / name
            if path.exists() and not path.is_symlink():
                paths.append((path, kind))
        return sorted(
            [
                {
                    "path": _run_relative(context.root, path),
                    "schema_id": kind,
                    "sha256": sha256_bytes(_safe_release_bytes(path)),
                }
                for path, kind in paths
            ],
            key=lambda row: row["path"],
        )
    prior = context.intent["predecessor"]
    if prior is not None:
        previous = context.directory.parent / f"{prior['sequence']:03d}"
        previous_context = _validate_intent(previous)
        if previous_context.intent["tool"] != context.intent["tool"]:
            raise ReleaseControlError("predecessor tool differs from its successor")
        paths.append((previous / "intent.json", "metriplane.release-invocation-intent.v1"))
        if sha256_bytes(_safe_release_bytes(previous / "intent.json")) != prior["intent_digest"]:
            raise ReleaseControlError("predecessor intent changed")
        if prior["terminal_digest"] is not None:
            paths.append((previous / "invocation.json", "metriplane.release-stage-invocation.v1"))
            if (
                sha256_bytes(_safe_release_bytes(previous / "invocation.json"))
                != prior["terminal_digest"]
            ):
                raise ReleaseControlError("predecessor terminal changed")
    return sorted(
        [
            {
                "path": _run_relative(context.root, path),
                "schema_id": kind,
                "sha256": sha256_bytes(_safe_release_bytes(path)),
            }
            for path, kind in paths
        ],
        key=lambda row: row["path"],
    )


def _partial_file_projection(context: ReleaseInvocation) -> dict[str, Any]:
    files = []
    unreadable = []
    roots = []
    for directory in (context.directory / "staged", context.directory / "workspace"):
        root_name = directory.relative_to(context.root).as_posix()
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            roots.append({"path": root_name, "kind": "unsafe"})
            unreadable.append(root_name)
            continue
        if not directory.exists():
            roots.append({"path": root_name, "kind": "absent"})
            continue
        roots.append({"path": root_name, "kind": "directory"})
        for path in sorted(directory.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            name = path.relative_to(context.root).as_posix()
            try:
                raw = _safe_release_bytes(path)
            except ReleaseControlError:
                unreadable.append(name)
            else:
                files.append({"path": name, "sha256": sha256_bytes(raw), "size": len(raw)})
    return {
        "schema_version": "metriplane.release-partial-files.v1",
        "roots": roots,
        "files": files,
        "unreadable": unreadable,
    }


def _retain_partial_files(context: ReleaseInvocation) -> None:
    _durable_json(context.directory / "partial-files.json", _partial_file_projection(context))


def _complete_invocation(
    context: ReleaseInvocation, code: int, outputs: list[dict[str, str]]
) -> None:
    terminal_status = (
        "PASS" if code == 0 else "CANCELLED" if code >= 128 else "BLOCKED" if code == 3 else "FAIL"
    )
    intent = context.intent
    data: dict[str, Any] = {
        "argv": intent["argv"],
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "exit_code": code,
        "inputs": _terminal_inputs(context),
        "outputs": outputs,
        "previous_invocation_digest": intent["previous_invocation_digest"],
        "started_at": intent["started_at"],
        "stderr_digest": sha256_bytes(_safe_release_bytes(context.directory / "stderr")),
        "stdout_digest": sha256_bytes(_safe_release_bytes(context.directory / "stdout")),
        "terminal_status": terminal_status,
        "tool": intent["tool"],
        "tool_version": intent["tool_version"],
    }
    data["invocation_digest"] = sha256_json(data)
    record = make_record(
        "release-stage-invocation",
        data,
        invocation_id=intent["invocation_id"],
        sequence=intent["sequence"],
        synthetic=intent["environment"]["fixture_mode"] == "1",
        status=terminal_status,
    )
    _durable_json(context.directory / "invocation.json", record)
    _validate_terminal(context)
    if isinstance(context, CandidateFinalizationInvocation) and code == 0:
        # Its existence proves the terminal's required fsync returned before creation.
        # A complete-looking terminal left by a failed write/fsync has no receipt.
        _durable_json(
            context.directory / "terminal-commit.json",
            {
                "schema_version": "metriplane.candidate-terminal-commit.v1",
                "intent_sha256": sha256_json(context.intent),
                "terminal_sha256": sha256_json(record),
            },
        )
        _validate_finalization_completion(context)


def _worker_command(context: ReleaseInvocation) -> list[str]:
    return [
        sys.executable,
        "-c",
        "import sys; from metriplane.release_control import _release_worker_main; raise SystemExit(_release_worker_main(sys.argv[1]))",
        str(context.directory),
    ]


def _stop_worker_group(pid: int) -> bool:
    """Stop inherited build children before output/diagnostic hashes are accepted."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            # macOS can report EPERM while a zombie-only group is being reaped.
            # Permission failure is unresolved: only ESRCH proves group absence.
            pass
        time.sleep(0.05)
    return False


def _supervise_release_invocation(
    context: ReleaseInvocation,
    *,
    artifact_installer: Callable[[Path, Path], list[tuple[Path, Path]]] | None = None,
) -> int:
    outputs: list[dict[str, str]] = []
    code = 3
    group_settled = True
    with (
        (context.directory / "stdout").open("xb") as stdout,
        (context.directory / "stderr").open("xb") as stderr,
    ):
        try:
            if (
                isinstance(context, CandidateFinalizationInvocation)
                and context.intent["sequence"] != 1
            ):
                diagnostic = _finalization_diagnostic(context)
                _durable_json(context.directory / "classification.json", diagnostic)
                raise ReleaseControlError(
                    "original candidate finalization is immutable: " + diagnostic["classification"]
                )
            _validate_bound_invocation(context)
            for planned in context.intent["planned_outputs"]:
                destination = _journal_path(
                    context.staging_root
                    if isinstance(context, CandidateFinalizationInvocation)
                    else context.root,
                    planned["path"],
                )
                if destination.exists() or destination.is_symlink():
                    raise ReleaseControlError(
                        "canonical output already exists; a new staging run is required"
                    )
            if (
                context.intent["tool"] in {"freeze_release_source.py", "build_release_artifacts.py"}
                and context.intent["sequence"] != 1
            ):
                raise ReleaseControlError("canonical producer retry requires a new staging run")
            process = subprocess.Popen(
                _worker_command(context),
                cwd=Path(__file__).resolve().parents[1],
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            group_settled = False
            try:
                return_code = process.wait()
            except KeyboardInterrupt:
                process.kill()
                process.wait()
                return_code = -2
            code = 128 - return_code if return_code < 0 else return_code
            group_settled = _stop_worker_group(process.pid)
            if not group_settled:
                raise ReleaseControlError("worker process group has not quiesced")
            if return_code >= 0:
                result = _source_json(
                    _safe_release_bytes(context.directory / "worker-result.json"), "worker result"
                )
                if (
                    set(result)
                    != {"schema_version", "exit_code", "outputs", "producer_intent_digest"}
                    or result["schema_version"] != "metriplane.release-worker-result.v1"
                    or result["exit_code"] != code
                    or result["producer_intent_digest"] != sha256_json(context.intent)
                ):
                    raise ReleaseControlError(
                        "worker verdict does not match the reserved invocation"
                    )
                if code == 0:
                    outputs = result["outputs"]
                    if isinstance(context, CandidateFinalizationInvocation) and stdout.tell() != 0:
                        raise ReleaseControlError(
                            "candidate worker cannot announce finalization success"
                        )
                    _verify_staged_outputs(context, outputs)
                    _install_release_outputs(
                        context, outputs, artifact_installer=artifact_installer
                    )
            if code == 0 and isinstance(context, CandidateFinalizationInvocation):
                stdout.write(_candidate_success_line(_candidate_identity_for_context(context)))
            stdout.flush()
            os.fsync(stdout.fileno())
            stderr.flush()
            os.fsync(stderr.fileno())
        except Exception as exc:
            code, outputs = 3, []
            stderr.write((str(exc) + "\n").encode())
            stderr.flush()
            os.fsync(stderr.fileno())
    if not group_settled:
        raise ReleaseControlError("retained invocation is incomplete: worker group still exists")
    if code != 0:
        _retain_partial_files(context)
    _complete_invocation(context, code, outputs)
    if code == 0 and context.intent["tool"] in {
        "freeze_release_source.py",
        "build_release_artifacts.py",
    }:
        for row in outputs:
            if row["schema_id"].startswith("metriplane."):
                path = _journal_path(context.root, row["path"])
                validate_release_producer_journal(
                    read_json(path), path, producer=context.intent["tool"]
                )
    if code == 0 and isinstance(context, CandidateFinalizationInvocation):
        sys.stdout.write(_safe_release_bytes(context.directory / "stdout").decode("utf-8"))
        return 0
    print(
        canonical_json(
            {
                "tool": context.intent["tool"],
                "status": "PASS" if code == 0 else "BLOCKED_NOT_READY",
                "exit_code": code,
                "invocation": str(context.directory),
            }
        ).decode()
    )
    return code


def run_release_command(
    tool: str,
    argv: Sequence[str],
    *,
    artifact_installer: Callable[[Path, Path], list[tuple[Path, Path]]] | None = None,
) -> int:
    """Run one adapter under the common immutable supervisor journal."""
    try:
        raw = _command_value(argv, "invocation-dir")
        if raw is None:
            raise ReleaseControlError("--invocation-dir is required")
        directory = Path(raw).absolute()
        root = directory.parents[2]
        contract = TOOL_CONTRACTS[tool]
        if tool == _FINALIZER:
            context = begin_release_invocation(
                tool, argv, directory, input_paths=[], planned_outputs=[]
            )
        else:
            inputs = []
            for flag, kind in [
                ("gate-input", "release-gate-input"),
                ("target-resolution", "release-target-resolution"),
                ("source-freeze", "release-source-freeze"),
                ("record", _record_type_from_tool(tool)),
            ]:
                value = _command_value(argv, flag)
                if value is not None:
                    inputs.append((Path(value).absolute(), "metriplane." + kind + ".v1"))
            if tool == _CANDIDATE_VALIDATOR:
                value = _command_value(argv, "predecessor")
                if value is not None:
                    inputs.append((Path(value).absolute(), "metriplane.release-predecessor.v1"))
            if tool == "freeze_release_source.py":
                value = _command_value(argv, "gate-input")
                if value is not None:
                    inputs.append(
                        (
                            Path(value).absolute().parent / "target-resolution.json",
                            "metriplane.release-target-resolution.v1",
                        )
                    )
            outputs = []
            if contract.output_flag is not None:
                value = _command_value(argv, contract.output_flag)
                if value is not None:
                    path = Path(value).absolute()
                    if path.parent != root:
                        raise ReleaseControlError(
                            "canonical record must be directly in its invocation run root"
                        )
                    outputs.append((path, "metriplane." + _record_type_from_tool(tool) + ".v1"))
            if tool == "build_release_artifacts.py":
                value = _command_value(argv, "out-dir")
                if value is not None:
                    if Path(value).absolute() != root / "artifacts":
                        raise ReleaseControlError(
                            "artifact output must be artifacts/ in the invocation run root"
                        )
                    outputs.append(
                        (Path(value).absolute(), "metriplane.release-artifact-directory.v1")
                    )
            context = begin_release_invocation(
                tool, argv, directory, input_paths=inputs, planned_outputs=outputs
            )
    except (OSError, ReleaseControlError, IndexError) as exc:
        print(
            canonical_json({"status": "INVALID_INPUT", "reason": str(exc), "tool": tool}).decode()
        )
        return 2
    try:
        return _supervise_release_invocation(context, artifact_installer=artifact_installer)
    except (OSError, ReleaseControlError) as exc:
        print(
            canonical_json(
                _blocked_result(tool, "incomplete retained invocation: " + str(exc))
            ).decode()
        )
        return 3


def tool_main(tool: str, argv: Sequence[str] | None = None) -> int:
    """Run the exact public adapter; incomplete routes never echo fixture PASS."""
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if argv is not None:
        legacy = _legacy_internal_validator(tool, arguments)
        if legacy is not None:
            return legacy
    name = Path(tool).name
    contract = TOOL_CONTRACTS.get(name)
    if contract is None or contract.delegated_adapter:
        raise ReleaseControlError("unknown or independently parsed release adapter: " + name)
    if "--help" in arguments or "-h" in arguments:
        _build_tool_parser(name, contract).parse_args(arguments)
        return 0
    return run_release_command(name, arguments)


__all__ = [
    "RELEASE_BUILD_RECIPE",
    "RELEASE_BUILD_RECIPE_DIGEST",
    "ReleaseInvocation",
    "begin_release_invocation",
    "build_release_source_freeze_record",
    "run_release_command",
    "validate_release_build_environment",
    "validate_release_producer_journal",
    "validate_release_source_freeze_record",
    "MILESTONES",
    "STAGES",
    "TOOL_CONTRACTS",
    "ReleaseControlError",
    "acquire_promotion_lock",
    "advance_attempt",
    "append_cas_event",
    "audit_release_repository",
    "build_promotion_plan",
    "build_release_readiness_record",
    "candidate_identity",
    "canonical_json",
    "finalize_cells",
    "make_record",
    "new_attempt",
    "read_json",
    "reconcile_publication",
    "record_target_burn",
    "recovery_envelope",
    "require_lock_owner",
    "resolve_burn_with_patch",
    "retain_two_store_evidence",
    "sha256_json",
    "signature_subject_digest",
    "tool_main",
    "validate_approval",
    "validate_cumulative_milestones",
    "validate_lkg_invalidation",
    "validate_predecessor",
    "validate_promotion_plan",
    "validate_publication_reconciliation_record",
    "validate_record",
    "validate_release_approval_record",
    "validate_release_artifact_files",
    "validate_release_candidate_identity_record",
    "validate_release_gate_instance_record",
    "validate_release_qualification_plan_record",
    "validate_release_qualification_record",
    "validate_release_retention_receipts",
    "validate_role_assignments",
    "validate_task_state_observation",
    "write_immutable_json",
]
