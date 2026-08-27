# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import pytest

from metriplane.release_control import (
    ProviderAttestationVerifier,
    canonical_json,
    make_record,
    release_authority_policy_digest,
    signature_subject_digest,
    validate_record,
    validate_role_assignments,
)

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ModuleNotFoundError:  # The frozen project environment does not own this dependency yet.
    Draft202012Validator = None  # type: ignore[assignment,misc]
    FormatChecker = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
STATUS = ROOT / "docs/status"
SCHEMA_PATHS = tuple(
    sorted(
        {
            *SCHEMAS.glob("metriplane.release-*.v1.schema.json"),
            SCHEMAS / "metriplane.linear-release-snapshot.v1.schema.json",
            SCHEMAS / "metriplane.provider-run-termination.v1.schema.json",
        }
    )
)
SIGNATURE_REQUIRED = {
    "release-approval-decision",
    "release-approval",
    "release-protected-input",
    "release-role-assignments",
    "release-task-state-observation",
}
BACKEND_IDS = (
    "payload-store-a",
    "payload-store-b",
    "attempt-index",
    "success-chain",
    "last-known-good",
    "main-health-state",
    "main-health-summary",
)
WORKFLOW_STATES = {
    "open_running": {
        "id": "6326ecac-afa9-4bdd-a9d2-2826db1e03b5",
        "name": "In Progress",
        "type": "started",
    },
    "open_finalizing": {
        "id": "7ba29f42-2854-4d0e-bf55-c04550be46eb",
        "name": "In Review",
        "type": "started",
    },
    "closed": {
        "id": "a37b0586-c805-4225-94c3-c690abb56d5a",
        "name": "Done",
        "type": "completed",
    },
}
BASE_SEMANTIC_CHECKS = {
    "payload_digest == sha256(canonical_json(data))",
    "record_id == sha256(canonical_json(record_without_record_id))",
    "signature.subject_digest == sha256(canonical_json(decision_envelope))",
    "all referenced digests resolve to the exact retained subject bytes",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _resolve(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    assert isinstance(reference, str) and reference.startswith("#/$defs/")
    name = reference.removeprefix("#/$defs/")
    resolved = root["$defs"][name]
    assert isinstance(resolved, dict)
    return resolved


def _is_type(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise AssertionError(f"unsupported test-validator type: {expected}")


def _local_errors(
    value: object,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str = "$",
) -> Iterator[str]:
    schema = _resolve(schema, root)

    if "const" in schema and value != schema["const"]:
        yield f"{path}: not const"
    if "enum" in schema and value not in schema["enum"]:
        yield f"{path}: not enum member"

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        matches = sum(not list(_local_errors(value, branch, root, path)) for branch in one_of)
        if matches != 1:
            yield f"{path}: matched {matches} oneOf branches"

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for branch in all_of:
            yield from _local_errors(value, branch, root, path)

    condition = schema.get("if")
    if isinstance(condition, dict):
        branch_name = "then" if not list(_local_errors(value, condition, root, path)) else "else"
        branch = schema.get(branch_name)
        if isinstance(branch, dict):
            yield from _local_errors(value, branch, root, path)

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _is_type(value, expected_type):
        yield f"{path}: expected {expected_type}"
        return

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                yield f"{path}: missing {key}"
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child in properties.items():
                if key in value:
                    yield from _local_errors(value[key], child, root, f"{path}.{key}")
            if schema.get("additionalProperties") is False:
                for key in value.keys() - properties.keys():
                    yield f"{path}: unexpected {key}"

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            yield f"{path}: too few items"
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(value) > maximum:
            yield f"{path}: too many items"
        if schema.get("uniqueItems") is True:
            rendered = [_canonical(item) for item in value]
            if len(rendered) != len(set(rendered)):
                yield f"{path}: duplicate items"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                yield from _local_errors(item, item_schema, root, f"{path}[{index}]")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            yield f"{path}: too short"
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            yield f"{path}: too long"
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            yield f"{path}: pattern mismatch"
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value)
            except ValueError:
                yield f"{path}: invalid date-time"
        if schema.get("format") == "uri":
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                yield f"{path}: invalid URI"

    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            yield f"{path}: below minimum"
        maximum = schema.get("maximum")
        if isinstance(maximum, int) and value > maximum:
            yield f"{path}: above maximum"


def _errors(value: object, schema: Mapping[str, Any]) -> list[str]:
    if Draft202012Validator is not None:
        checker = FormatChecker()
        validator = Draft202012Validator(schema, format_checker=checker)
        return [error.message for error in validator.iter_errors(value)]
    return list(_local_errors(value, schema, schema))


def _sample_string(schema: Mapping[str, Any], seed: int) -> str:
    pattern = schema.get("pattern")
    if pattern == "^[0-9a-f]{64}$":
        return "abcdef"[seed % 6] * 64
    if pattern == "^[0-9a-f]{40}$":
        return "abcdef"[seed % 6] * 40
    if pattern == "^v(?:0\\.[3-9]|1\\.0)\\.[0-9]+$":
        return f"v0.4.{seed}"
    if pattern == "^[A-Z][A-Z0-9]*-[1-9][0-9]*$":
        return f"MET-{seed + 1}"
    if pattern == "^[A-Za-z0-9._-]*[Ll]inear[A-Za-z0-9._-]*$":
        return "fake-linear"
    if pattern == "^[A-Za-z0-9._-]*(?:[Pp]rovider|[Gg]it[Hh]ub)[A-Za-z0-9._-]*$":
        return "fake-provider"
    if schema.get("format") == "date-time":
        return f"2026-08-27T00:00:{seed % 60:02d}Z"
    if schema.get("format") == "uri":
        return f"https://example.invalid/value-{seed}"
    if pattern and "[0-9a-f]{8}-" in pattern:
        return f"00000000-0000-0000-0000-{seed:012d}"
    minimum = max(1, int(schema.get("minLength", 1)))
    return (f"value-{seed}" + "x" * minimum)[: max(minimum, len(f"value-{seed}"))]


def _sample(schema: Mapping[str, Any], root: Mapping[str, Any], seed: int = 0) -> Any:
    schema = _resolve(schema, root)
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    enum = schema.get("enum")
    if isinstance(enum, list):
        return copy.deepcopy(enum[seed % len(enum)])
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        return _sample(one_of[seed % len(one_of)], root, seed)
    expected_type = schema.get("type")
    if expected_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        return {
            key: _sample(properties[key], root, seed + index)
            for index, key in enumerate(schema.get("required", []))
        }
    if expected_type == "array":
        count = int(schema.get("minItems", 0))
        return [_sample(schema["items"], root, seed + index) for index in range(count)]
    if expected_type == "string":
        return _sample_string(schema, seed)
    if expected_type == "integer":
        return int(schema.get("minimum", 0))
    if expected_type == "boolean":
        return False
    if expected_type == "null":
        return None
    raise AssertionError(f"cannot synthesize schema node: {schema}")


def _set_synthetic_signature(signature: dict[str, Any], subject_digest: str) -> None:
    signature.update(
        {
            "actor_id": "fixture-actor",
            "algorithm": "test-sha256-v1",
            "provider": "test-fixture",
            "signature": "f" * 64,
            "subject_digest": subject_digest,
            "synthetic": True,
        }
    )


def _set_live_signature(signature: dict[str, Any], subject_digest: str) -> None:
    signature.update(
        {
            "actor_id": "provider-actor",
            "algorithm": "provider-attestation-v1",
            "provider": "linear",
            "signature": "f" * 64,
            "subject_digest": subject_digest,
            "synthetic": False,
        }
    )


def _rebind_record(record: dict[str, Any], *, synthetic: bool) -> None:
    record["synthetic"] = synthetic
    record["payload_digest"] = hashlib.sha256(canonical_json(record["data"])).hexdigest()
    subject_digest = signature_subject_digest(record)
    for signature in record["signatures"]:
        if synthetic:
            _set_synthetic_signature(signature, subject_digest)
        else:
            _set_live_signature(signature, subject_digest)
    unsigned = dict(record)
    unsigned.pop("record_id", None)
    record["record_id"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()


def _sample_record(schema: Mapping[str, Any]) -> dict[str, Any]:
    record = _sample(schema, schema)
    assert isinstance(record, dict)
    if record["record_type"] == "release-last-known-good":
        record["data"].update({"invalidation_decision_digest": None, "state": "LKG"})
    if record["record_type"] == "release-target-burn":
        record["data"].update(
            {"burn_id": "a" * 64, "disposition": "new_burn", "indexing_required": True}
        )
    _rebind_record(record, synthetic=True)
    return record


def _first_digest_path(value: object, path: tuple[object, ...] = ()) -> tuple[object, ...] | None:
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return path
    if isinstance(value, dict):
        for key, child in value.items():
            found = _first_digest_path(child, (*path, key))
            if found is not None:
                return found
    if isinstance(value, list):
        for index, child in enumerate(value):
            found = _first_digest_path(child, (*path, index))
            if found is not None:
                return found
    return None


def _replace_path(value: object, path: tuple[object, ...], replacement: object) -> None:
    cursor = value
    for part in path[:-1]:
        cursor = cursor[part]  # type: ignore[index]
    cursor[path[-1]] = replacement  # type: ignore[index]


def _validate_evidence_stores(value: Mapping[str, Any]) -> None:
    if set(value) != {
        "attempt_index",
        "backends",
        "live_status",
        "owner",
        "schema_version",
        "secrets_embedded",
        "stores",
    }:
        raise ValueError("registry shape")
    if value["live_status"] != "BLOCKED_NOT_READY" or value["secrets_embedded"] is not False:
        raise ValueError("live/readiness claim")
    if value["attempt_index"] != {
        "backend": None,
        "backend_id": "attempt-index",
        "cas_required": True,
        "read_back_required": True,
    }:
        raise ValueError("attempt-index projection")
    backends = value["backends"]
    if (
        not isinstance(backends, list)
        or tuple(item["backend_id"] for item in backends) != BACKEND_IDS
    ):
        raise ValueError("backend identities")
    if len({item["backend_id"] for item in backends}) != 7:
        raise ValueError("backend collision")
    payload = backends[:2]
    if {item["backend_kind"] for item in payload} != {"immutable_payload"}:
        raise ValueError("payload type")
    if len({item["independence_group"] for item in payload}) != 2:
        raise ValueError("payload independence")
    stores = value["stores"]
    if [item["backend_id"] for item in stores] != [item["backend_id"] for item in payload]:
        raise ValueError("payload projection")
    if any(item["live_binding"] is not None for item in stores):
        raise ValueError("payload projection binding")
    if [item["independence_group"] for item in stores] != [
        item["independence_group"] for item in payload
    ]:
        raise ValueError("payload projection independence")
    if len({_canonical(item["credential_reference"]) for item in backends}) != 7:
        raise ValueError("credential separation")
    for backend in backends:
        if backend["live_binding"] is not None or backend["binding_status"] != "UNRESOLVED":
            raise ValueError("unproved provider binding")
        if set(backend["namespaces"]) != {"production", "preflight", "test"}:
            raise ValueError("namespace set")
        if len(set(backend["namespaces"].values())) != 3:
            raise ValueError("namespace overlap")
        if backend["retention"] != {
            "deletion": "forbidden",
            "hold": "governance_hold_required",
            "minimum_days": None,
            "mode": "retain_indefinitely",
        }:
            raise ValueError("retention policy")
        capabilities = set(backend["required_capabilities"])
        if backend["backend_kind"] == "immutable_payload":
            required = {"immutable_put", "read", "sha256_read_back", "hold"}
        else:
            required = {"read", "compare_and_swap", "stale_conflict"}
        if not required <= capabilities:
            raise ValueError("backend capability")
        if backend["backend_id"] in {"artifact", "state", "store"}:
            raise ValueError("ambiguous backend")


def _validate_task_state_policy(value: Mapping[str, Any]) -> None:
    if value["workflow_states"] != WORKFLOW_STATES:
        raise ValueError("workflow states")
    expected_edges = [("open_running", "open_finalizing"), ("open_finalizing", "closed")]
    edges = [(item["from"], item["to"]) for item in value["allowed_transitions"]]
    if edges != expected_edges:
        raise ValueError("transition graph")
    if any(item["authorized_role"] != "release_operator" for item in value["allowed_transitions"]):
        raise ValueError("transition role")
    if any(item["provider_event_required"] is not True for item in value["allowed_transitions"]):
        raise ValueError("provider event")
    if value["freshness_windows_seconds"] != {"prepromotion": 300, "terminal_commit": 120}:
        raise ValueError("freshness windows")
    if value["server_clock_skew_budget_seconds"] != {"capture": 30, "terminal_commit": 30}:
        raise ValueError("clock skew")
    if value["cross_system_atomicity"] != "not_claimed":
        raise ValueError("atomicity claim")
    if value["authority_status"] != "POLICY_ONLY_NO_LIVE_PROVIDER_RECEIPT":
        raise ValueError("provider evidence claim")


def test_all_registry_schemas_are_distinct_draft_2020_12_contracts() -> None:
    assert len(SCHEMA_PATHS) == 49
    fingerprints: dict[str, Path] = {}
    for path in SCHEMA_PATHS:
        schema = _load(path)
        if Draft202012Validator is not None:
            Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(path.name)
        assert schema["properties"]["data"]["additionalProperties"] is False
        assert schema["properties"]["data"]["required"]
        assert BASE_SEMANTIC_CHECKS <= set(schema["x-metriplane-semantic-checks"])
        fingerprint = hashlib.sha256(
            _canonical(schema["properties"]["data"]).encode("utf-8")
        ).hexdigest()
        assert fingerprint not in fingerprints, (
            f"{path.name} duplicates the subject contract in {fingerprints[fingerprint].name}"
        )
        fingerprints[fingerprint] = path
    assert len(fingerprints) == 49


@pytest.mark.parametrize(
    "path",
    tuple(
        path
        for path in sorted((ROOT / "tests/fixtures/release/valid").glob("*.json"))
        if SCHEMAS / f"metriplane.{_load(path)['record_type']}.v1.schema.json" in SCHEMA_PATHS
    ),
    ids=lambda path: path.stem,
)
def test_checked_in_registry_fixtures_validate_against_subject_contracts(path: Path) -> None:
    record = _load(path)
    schema = _load(SCHEMAS / f"metriplane.{record['record_type']}.v1.schema.json")
    assert _errors(record, schema) == []


@pytest.mark.parametrize(
    ("kind", "generic_data"),
    [
        (
            "linear-release-snapshot",
            {"state": "In Progress", "task_id": "generic", "tool": "generic"},
        ),
        ("provider-run-termination", {"state": "success", "tool": "generic"}),
    ],
)
def test_snapshot_and_termination_contracts_reject_empty_and_generic_data(
    kind: str, generic_data: dict[str, str]
) -> None:
    schema = _load(SCHEMAS / f"metriplane.{kind}.v1.schema.json")
    assert _errors({}, schema["properties"]["data"])
    assert _errors(generic_data, schema["properties"]["data"])


@pytest.mark.parametrize("path", SCHEMA_PATHS, ids=lambda path: path.stem)
def test_subject_contracts_reject_required_field_digest_and_shape_mutations(path: Path) -> None:
    schema = _load(path)
    record = _sample_record(schema)
    assert _errors(record, schema) == []
    validate_record(record, record["record_type"])

    for required in schema["properties"]["data"]["required"]:
        mutated = copy.deepcopy(record)
        del mutated["data"][required]
        _rebind_record(mutated, synthetic=True)
        assert _errors(mutated, schema), required

    unknown = copy.deepcopy(record)
    unknown["data"]["unexpected_subject_field"] = True
    _rebind_record(unknown, synthetic=True)
    assert _errors(unknown, schema)

    malformed_envelope = copy.deepcopy(record)
    malformed_envelope["payload_digest"] = "not-a-digest"
    assert _errors(malformed_envelope, schema)

    digest_path = _first_digest_path(record["data"])
    if digest_path is not None:
        malformed_subject = copy.deepcopy(record)
        _replace_path(malformed_subject["data"], digest_path, "not-a-digest")
        _rebind_record(malformed_subject, synthetic=True)
        assert _errors(malformed_subject, schema), digest_path

    if record["record_type"] in SIGNATURE_REQUIRED:
        unsigned = copy.deepcopy(record)
        unsigned["signatures"] = []
        _rebind_record(unsigned, synthetic=True)
        assert _errors(unsigned, schema)


@pytest.mark.parametrize(
    "path",
    tuple(path for path in SCHEMA_PATHS if "x-metriplane-live-required" in _load(path)),
    ids=lambda path: path.stem,
)
def test_live_records_require_authority_and_provenance_fields(path: Path) -> None:
    schema = _load(path)
    live = _sample_record(schema)
    for index, field in enumerate(schema["x-metriplane-live-required"], start=100):
        live["data"][field] = _sample(
            schema["properties"]["data"]["properties"][field], schema, index
        )
    _rebind_record(live, synthetic=False)
    assert _errors(live, schema) == []

    for field in schema["x-metriplane-live-required"]:
        mutated = copy.deepcopy(live)
        del mutated["data"][field]
        _rebind_record(mutated, synthetic=False)
        assert _errors(mutated, schema), field


def test_live_role_assignment_passes_schema_and_semantic_validator() -> None:
    keyring_digest = "a" * 64

    def binding(role: str, actor: str, backup: str, provenance: str) -> dict[str, object]:
        return {
            "actor_id": actor,
            "backup_actor_id": backup,
            "conflict_free": True,
            "provenance_digest": provenance * 64,
            "provider": "github",
            "role": role,
        }

    data = {
        "author_id": "author",
        "author_provider": "github",
        "authority_policy_digest": release_authority_policy_digest(keyring_digest),
        "authorized_executor_id": "executor",
        "independent_assurance": {"applicability": "not_applicable"},
        "infrastructure_owner": binding(
            "infrastructure_owner", "infrastructure", "infrastructure-backup", "b"
        ),
        "milestone": "v0.4",
        "non_author_reviewer": binding("non_author_reviewer", "reviewer", "reviewer-backup", "c"),
        "non_author_reviewer_id": "reviewer",
        "operator": binding("release_operator", "executor", "executor-backup", "d"),
        "provider_attestation_keyring_digest": keyring_digest,
        "publisher": binding("publisher", "publisher", "publisher-backup", "e"),
        "publisher_id": "publisher",
        "run_id": "111",
        "signing_method": "provider-attestation-v1",
        "task_id": "MP2-007",
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_until": "2099-01-01T00:00:00Z",
    }
    unsigned = make_record(
        "release-role-assignments",
        data,
        invocation_id="live-role-schema-runtime",
        sequence=1,
        synthetic=False,
    )
    subject_digest = signature_subject_digest(unsigned)
    record = make_record(
        "release-role-assignments",
        data,
        invocation_id="live-role-schema-runtime",
        sequence=1,
        synthetic=False,
        signatures=[
            {
                "actor_id": "executor",
                "algorithm": "provider-attestation-v1",
                "provider": "github",
                "signature": "0" * 128,
                "subject_digest": subject_digest,
                "synthetic": False,
            }
        ],
    )
    schema = _load(SCHEMAS / "metriplane.release-role-assignments.v1.schema.json")
    assert _errors(record, schema) == []

    class AcceptingVerifier:
        @staticmethod
        def verify(_signature: Mapping[str, Any], *, subject_digest: str) -> bool:
            return bool(subject_digest)

    verifier = AcceptingVerifier()
    verifier.keyring_digest = keyring_digest

    validate_role_assignments(
        record,
        live=True,
        expected_milestone="v0.4",
        expected_run_id="111",
        expected_authority_policy_digest=data["authority_policy_digest"],
        check_conflicts=True,
        check_freshness=True,
        attestation_verifier=cast(ProviderAttestationVerifier, verifier),
    )


def test_digest_relationships_remain_runtime_enforced() -> None:
    schema = _load(SCHEMAS / "metriplane.release-promotion-lock.v1.schema.json")
    record = _sample_record(schema)
    record["data"]["epoch"] += 1
    assert _errors(record, schema) == []
    with pytest.raises(ValueError, match="payload digest mismatch"):
        validate_record(record, "release-promotion-lock")


def test_task_state_record_schema_rejects_crossed_edges_ids_and_time_budgets() -> None:
    schema = _load(SCHEMAS / "metriplane.release-task-state-policy.v1.schema.json")
    record = _sample_record(schema)
    assert _errors(record, schema) == []

    mutations: list[dict[str, Any]] = []
    crossed = copy.deepcopy(record)
    crossed["data"]["allowed_transitions"][0].update({"from": "open_running", "to": "closed"})
    mutations.append(crossed)
    wrong_id = copy.deepcopy(record)
    wrong_id["data"]["states"][0]["id"] = "0" * 36
    mutations.append(wrong_id)
    stale = copy.deepcopy(record)
    stale["data"]["prepromotion_freshness_seconds"] = 301
    mutations.append(stale)
    skew = copy.deepcopy(record)
    skew["data"]["terminal_commit_clock_skew_seconds"] = 31
    mutations.append(skew)

    for mutation in mutations:
        _rebind_record(mutation, synthetic=True)
        assert _errors(mutation, schema)


@pytest.mark.parametrize(
    ("kind", "mutator"),
    [
        (
            "release-target-burn",
            lambda data: data.update(
                {"burn_id": None, "disposition": "new_burn", "indexing_required": False}
            ),
        ),
        (
            "release-last-known-good",
            lambda data: data.update(
                {"invalidation_decision_digest": None, "state": "INVALIDATED"}
            ),
        ),
        (
            "release-readiness",
            lambda data: data.update(
                {"disposition": "READY", "unresolved_blockers": ["unresolved"]}
            ),
        ),
    ],
)
def test_subject_conditionals_reject_internally_conflicting_records(
    kind: str, mutator: Any
) -> None:
    schema = _load(SCHEMAS / f"metriplane.{kind}.v1.schema.json")
    record = _sample_record(schema)
    mutator(record["data"])
    _rebind_record(record, synthetic=True)
    assert _errors(record, schema)


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("release-evidence-store-preflight", "independence_verified"),
        ("release-prepromotion-controls", "all_valid"),
        ("release-publication-observations", "all_targets_observed"),
        ("release-retention-receipts", "all_content_equal"),
    ],
)
def test_failure_and_partial_records_remain_schema_representable(kind: str, field: str) -> None:
    schema = _load(SCHEMAS / f"metriplane.{kind}.v1.schema.json")
    record = _sample_record(schema)
    record["data"][field] = False
    _rebind_record(record, synthetic=True)
    assert _errors(record, schema) == []


def test_evidence_store_registry_is_exact_and_mutation_closed() -> None:
    registry = _load(STATUS / "release-evidence-stores.json")
    _validate_evidence_stores(registry)

    mutations: list[dict[str, Any]] = []
    missing = copy.deepcopy(registry)
    missing["backends"].pop()
    mutations.append(missing)
    coupled = copy.deepcopy(registry)
    coupled["backends"][1]["independence_group"] = coupled["backends"][0]["independence_group"]
    mutations.append(coupled)
    generic = copy.deepcopy(registry)
    generic["backends"][2]["backend_id"] = "state"
    mutations.append(generic)
    weak = copy.deepcopy(registry)
    weak["backends"][3]["required_capabilities"].remove("compare_and_swap")
    mutations.append(weak)
    shared_credential = copy.deepcopy(registry)
    shared_credential["backends"][1]["credential_reference"] = shared_credential["backends"][0][
        "credential_reference"
    ]
    mutations.append(shared_credential)
    false_ready = copy.deepcopy(registry)
    false_ready["live_status"] = "READY"
    mutations.append(false_ready)

    for mutation in mutations:
        with pytest.raises(ValueError):
            _validate_evidence_stores(mutation)


def test_task_state_policy_binds_exact_ids_graph_role_and_time_budgets() -> None:
    policy = _load(STATUS / "release-task-state-policy.json")
    _validate_task_state_policy(policy)

    mutations: list[dict[str, Any]] = []
    wrong_id = copy.deepcopy(policy)
    wrong_id["workflow_states"]["open_finalizing"]["id"] = "0" * 36
    mutations.append(wrong_id)
    missing_edge = copy.deepcopy(policy)
    missing_edge["allowed_transitions"].pop()
    mutations.append(missing_edge)
    wrong_role = copy.deepcopy(policy)
    wrong_role["allowed_transitions"][0]["authorized_role"] = "implementation_agent"
    mutations.append(wrong_role)
    stale = copy.deepcopy(policy)
    stale["freshness_windows_seconds"]["prepromotion"] = 0
    mutations.append(stale)
    excess_skew = copy.deepcopy(policy)
    excess_skew["server_clock_skew_budget_seconds"]["terminal_commit"] = 31
    mutations.append(excess_skew)
    false_atomicity = copy.deepcopy(policy)
    false_atomicity["cross_system_atomicity"] = "atomic"
    mutations.append(false_atomicity)

    for mutation in mutations:
        with pytest.raises(ValueError):
            _validate_task_state_policy(mutation)
