# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Structural, semantic, and evidence validation for capability records."""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import artifact_sha256, canonical_sha256, load_json

SCHEMA_VERSION = "metriplane.source_adapter_capability.v1"
CONTRACT_VERSION = "metriplane.external_source_contract.v1"
CONTRACT_PROFILE = "metriplane.atlas.complete_snapshot.v1"
FRAME_STATE_MODEL_VERSION = "1.0"


class CapabilityValidationError(ValueError):
    """Raised when a capability record fails closed."""


@dataclass(frozen=True)
class CapabilityAssessment:
    """Permission result after structural and semantic validation."""

    technically_permitted: bool
    external_source_permitted: bool
    reasons: tuple[str, ...]


def schema_path() -> Path:
    """Return the installed capability schema path."""

    return Path(
        str(
            files("metriplane_source_adapter_sdk").joinpath(
                "schemas", f"{SCHEMA_VERSION}.schema.json"
            )
        )
    )


def record_path(name: str) -> Path:
    """Return an installed post-hoc record path by stable short name."""

    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) is None:
        raise ValueError("record name must be lowercase ASCII with '-' or '_'")
    return Path(str(files("metriplane_source_adapter_sdk").joinpath("records", f"{name}.json")))


def _fail(path: str, message: str) -> None:
    raise CapabilityValidationError(f"{path}: {message}")


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise RuntimeError(f"schema uses unsupported type {expected!r}")


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise RuntimeError("only local JSON Schema references are supported")
    node: Any = root
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[token]
    if not isinstance(node, dict):
        raise RuntimeError("schema reference does not resolve to an object")
    return node


def _validate_schema_node(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
) -> None:
    if "$ref" in schema:
        _validate_schema_node(value, _resolve_ref(root, schema["$ref"]), root, path)
        return
    if "anyOf" in schema:
        errors: list[str] = []
        for option in schema["anyOf"]:
            try:
                _validate_schema_node(value, option, root, path)
                return
            except CapabilityValidationError as exc:
                errors.append(str(exc))
        _fail(path, "does not match any permitted schema alternative")
    if "const" in schema and value != schema["const"]:
        _fail(path, f"must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        _fail(path, f"must be one of {schema['enum']!r}")
    expected_type = schema.get("type")
    if expected_type is not None and not _is_type(value, expected_type):
        _fail(path, f"must be {expected_type}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            _fail(path, "is too short")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            _fail(path, f"does not match {pattern!r}")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        _fail(path, f"must be at least {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            _fail(path, "has too few items")
        if schema.get("uniqueItems"):
            fingerprints = [canonical_sha256(item) for item in value]
            if len(fingerprints) != len(set(fingerprints)):
                _fail(path, "contains duplicate items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate_schema_node(item, item_schema, root, f"{path}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = sorted(set(required) - set(value))
        if missing:
            _fail(path, f"missing required fields {missing}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                _fail(path, f"unknown fields {unknown}")
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                _validate_schema_node(child, child_schema, root, f"{path}.{key}")


def _require_evidence_references(record: dict[str, Any]) -> None:
    evidence = record["evidence"]
    identifiers = [item["evidence_id"] for item in evidence]
    if len(identifiers) != len(set(identifiers)):
        _fail("$.evidence", "evidence_id values must be unique")
    known = set(identifiers)
    for name, capability in record["capabilities"].items():
        references = capability["evidence_ids"]
        if not references:
            _fail(f"$.capabilities.{name}.evidence_ids", "must not be empty")
        unknown = sorted(set(references) - known)
        if unknown:
            _fail(f"$.capabilities.{name}.evidence_ids", f"unknown evidence IDs {unknown}")


def _validate_semantics(record: dict[str, Any]) -> None:
    if record["schema_version"] != SCHEMA_VERSION:
        _fail("$.schema_version", "unsupported capability schema")
    contract = record["contract"]
    if (
        contract["version"] != CONTRACT_VERSION
        or contract["profile"] != CONTRACT_PROFILE
        or contract["frame_state_model_version"] != FRAME_STATE_MODEL_VERSION
    ):
        _fail("$.contract", "capability records cannot change the frozen contract boundary")

    artifacts = record["source"]["artifacts"]
    artifact_ids = [item["artifact_id"] for item in artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        _fail("$.source.artifacts", "artifact_id values must be unique")
    if record["capabilities"]["artifact_identity"]["all_required_artifacts_hashed"] is not True:
        _fail("$.capabilities.artifact_identity", "all required artifacts must be hashed")
    rights = record["source"]["rights"]
    source_rights = rights["source_records"]
    rights_ids = [item["rights_id"] for item in source_rights]
    if len(rights_ids) != len(set(rights_ids)):
        _fail("$.source.rights.source_records", "rights_id values must be unique")
    if rights["derived_fixture"]["rights_id"] in set(rights_ids):
        _fail(
            "$.source.rights.derived_fixture.rights_id",
            "must identify a separate rights subject",
        )
    rights_by_id = {item["rights_id"]: item for item in source_rights}
    bound_subjects: list[str] = []
    for rights_record in source_rights:
        unknown_subjects = sorted(set(rights_record["subject_artifact_ids"]) - set(artifact_ids))
        if unknown_subjects:
            _fail(
                "$.source.rights.source_records",
                f"rights record binds unknown artifacts {unknown_subjects}",
            )
        bound_subjects.extend(rights_record["subject_artifact_ids"])
    if sorted(bound_subjects) != sorted(artifact_ids) or len(bound_subjects) != len(
        set(bound_subjects)
    ):
        _fail(
            "$.source.rights.source_records", "source rights must bind each artifact exactly once"
        )
    for index, artifact in enumerate(artifacts):
        rights_record = rights_by_id.get(artifact["rights_id"])
        if (
            rights_record is None
            or artifact["artifact_id"] not in rights_record["subject_artifact_ids"]
        ):
            _fail(
                f"$.source.artifacts[{index}].rights_id",
                "artifact rights_id does not bind this source artifact",
            )
    if rights["source_bytes_in_fixture"] != any(
        artifact["presence"] == "included" for artifact in artifacts
    ):
        _fail("$.source.rights.source_bytes_in_fixture", "must match included source artifacts")
    if record["capabilities"]["rights"]["status"] == "verified" and (
        any(item["source_use"] != "verified" for item in source_rights)
        or rights["derived_fixture"]["redistribution"] != "verified"
    ):
        _fail(
            "$.capabilities.rights", "verified rights require bound source use and fixture rights"
        )
    for index, artifact in enumerate(artifacts):
        if (
            artifact["presence"] == "included"
            and rights_by_id[artifact["rights_id"]]["source_redistribution"] != "allowed"
        ):
            _fail(
                f"$.source.artifacts[{index}].presence",
                "included source bytes require allowed source redistribution",
            )

    clock = record["capabilities"]["clock"]
    if clock["order_only"]:
        _fail("$.capabilities.clock.order_only", "order-only clocks are prohibited")
    if not clock["authoritative"]:
        _fail("$.capabilities.clock.authoritative", "the evaluation clock must be authoritative")

    coordinates = record["capabilities"]["coordinates"]
    loss = record["capabilities"]["information_loss"]
    if loss["status"] == "verified" and (not loss["declared"] or not loss["items"]):
        _fail(
            "$.capabilities.information_loss",
            "verified information loss requires a declaration and nonempty items",
        )
    if loss["declared"] and not loss["items"]:
        _fail(
            "$.capabilities.information_loss.items",
            "declared information loss requires nonempty items",
        )
    if not loss["declared"] and (loss["items"] or loss["status"] == "verified"):
        _fail(
            "$.capabilities.information_loss",
            "undeclared information loss requires empty items and cannot be verified",
        )
    if coordinates["projection_method"] != "identity" and (
        not loss["declared"] or not loss["items"]
    ):
        _fail("$.capabilities.information_loss", "nonidentity projection requires declared loss")

    identity = record["capabilities"]["entity_identity"]
    if not identity["stable"] or not identity["explicit_mapping"]:
        _fail("$.capabilities.entity_identity", "entity identity must be stable and explicit")
    normalized_ids = [item["normalized_id"] for item in identity["normalized_entities"]]
    if len(normalized_ids) != len(set(normalized_ids)):
        _fail("$.capabilities.entity_identity.normalized_entities", "normalized IDs must be unique")
    process_relevant = {
        item["normalized_id"]
        for item in identity["normalized_entities"]
        if item["process_relevant"]
    }
    if set(identity["required_entities"]) != process_relevant:
        _fail(
            "$.capabilities.entity_identity.required_entities",
            "must exactly match process-relevant normalized IDs",
        )

    provenance = record["capabilities"]["field_provenance"]
    if not provenance["complete"] or not provenance["trust_layers_separated"]:
        _fail("$.capabilities.field_provenance", "field provenance must be complete and layered")

    completeness = record["capabilities"]["completeness"]
    if completeness["frame_semantics"] != "complete_snapshot":
        _fail(
            "$.capabilities.completeness.frame_semantics", "only complete snapshots are permitted"
        )
    if completeness["unknown_state_policy"] != "reject_fixture":
        _fail("$.capabilities.completeness.unknown_state_policy", "unknown state must reject")
    if completeness["omission_policy"] != "reject_omission":
        _fail("$.capabilities.completeness.omission_policy", "omission must reject")
    carry = completeness["carry_forward"]
    if completeness["interpolation"] != "none" or completeness["resampling"] != "none":
        _fail(
            "$.capabilities.completeness",
            "interpolation and resampling are unsupported",
        )
    if completeness["source_stream_semantics"] == "complete_snapshot" and (
        completeness["partial_updates_materialized"]
        or completeness["materialization_method"] != "none"
        or completeness["synchronization_tolerance_ns"] != 0
        or carry["method"] != "none"
        or completeness["synchronization"] != "not_applicable"
    ):
        _fail(
            "$.capabilities.completeness",
            "complete source snapshots require no materialization, zero tolerance, and no carry-forward",
        )
    if (
        completeness["source_stream_semantics"] == "partial_updates"
        and not completeness["partial_updates_materialized"]
    ):
        _fail(
            "$.capabilities.completeness",
            "partial updates require explicit materialization",
        )
    if completeness["materialization_method"] == "exact_snapshot_join" and (
        completeness["source_stream_semantics"] != "partial_updates"
        or not completeness["partial_updates_materialized"]
        or completeness["synchronization_tolerance_ns"] != 0
        or carry["method"] != "none"
        or completeness["synchronization"] != "exact_timestamp"
    ):
        _fail(
            "$.capabilities.completeness",
            "exact snapshot join requires partial updates, exact timestamps, zero tolerance, and no carry-forward",
        )
    if completeness["materialization_method"] == "bounded_last_observation" and (
        completeness["source_stream_semantics"] != "partial_updates"
        or not completeness["partial_updates_materialized"]
        or carry["method"] != "bounded_last_observation"
    ):
        _fail(
            "$.capabilities.completeness",
            "bounded materialization requires partial updates and bounded carry-forward",
        )
    if completeness["source_stream_semantics"] == "partial_updates" and completeness[
        "materialization_method"
    ] not in {"exact_snapshot_join", "bounded_last_observation"}:
        _fail(
            "$.capabilities.completeness.materialization_method",
            "partial updates require exact join or bounded last-observation materialization",
        )
    if carry["method"] == "none" and (carry["fields"] or carry["max_gap_ns"] is not None):
        _fail("$.capabilities.completeness.carry_forward", "none cannot carry fields or a gap")
    if carry["method"] == "bounded_last_observation" and (
        not carry["fields"] or carry["max_gap_ns"] is None
    ):
        _fail(
            "$.capabilities.completeness.carry_forward",
            "bounded carry-forward needs fields and a gap",
        )

    anti_taint = record["capabilities"]["anti_taint"]
    if not anti_taint["inventory_complete"]:
        _fail(
            "$.capabilities.anti_taint.inventory_complete", "annotation inventory must be complete"
        )
    if anti_taint["used_as_incident_truth"] or anti_taint["used_as_process_events"]:
        _fail("$.capabilities.anti_taint", "source outcomes cannot drive Atlas")
    if anti_taint["frame_state_events_policy"] != "empty":
        _fail("$.capabilities.anti_taint.frame_state_events_policy", "source events are prohibited")

    deterministic = record["capabilities"]["deterministic_conversion"]
    if deterministic["status"] == "verified" and (
        deterministic["clean_run_count"] < 3
        or deterministic["compared_output_count"] < 1
        or deterministic["comparison_policy"] not in {"byte_identity", "canonical_identity"}
        or deterministic["equivalent"] is not True
    ):
        _fail(
            "$.capabilities.deterministic_conversion",
            "verified conversion needs three equivalent clean runs and compared outputs",
        )

    portable = record["capabilities"]["portable_evaluation"]
    if portable["status"] == "verified" and (
        portable["source_dependencies_required"] or not portable["environments"]
    ):
        _fail(
            "$.capabilities.portable_evaluation",
            "portable evaluation must exclude source dependencies",
        )
    platform_keys = [
        (item["operating_system"], item["python_version"]) for item in portable["environments"]
    ]
    if len(platform_keys) != len(set(platform_keys)):
        _fail("$.capabilities.portable_evaluation.environments", "platform rows must be unique")
    expected_platforms = {
        ("Ubuntu", "3.12"),
        ("Ubuntu", "3.13"),
        ("macOS", "3.12"),
        ("macOS", "3.13"),
    }
    if set(platform_keys) != expected_platforms:
        _fail(
            "$.capabilities.portable_evaluation.environments",
            "must declare exactly Ubuntu and macOS on Python 3.12 and 3.13",
        )
    classifications = record["record"]
    statuses = {item["status"] for item in portable["environments"]}
    if classifications["classification"] == "post_hoc" and statuses != {"pass"}:
        _fail(
            "$.capabilities.portable_evaluation.environments",
            "post-hoc successful adapters require four passing portable rows",
        )
    if portable["status"] == "verified" and statuses != {"pass"}:
        _fail(
            "$.capabilities.portable_evaluation",
            "verified portability requires every declared row to pass",
        )
    if portable["status"] != "verified" and "pass" in statuses:
        _fail(
            "$.capabilities.portable_evaluation",
            "unverified portability cannot contain passing rows",
        )
    if classifications["evidence_classification"] == "synthetic_format_engineering" and (
        "pass" in statuses or not statuses <= {"required", "pending"}
    ):
        _fail(
            "$.capabilities.portable_evaluation.environments",
            "native synthetic records cannot predeclare portable rows as passed",
        )

    semantics = record["capabilities"]["semantics"]
    overlap = {item.casefold() for item in semantics["supported"]} & {
        item.casefold() for item in semantics["prohibited"]
    }
    if overlap:
        _fail("$.capabilities.semantics", "supported and prohibited semantics overlap")
    _require_evidence_references(record)


def validate_capability(record: Any) -> dict[str, Any]:
    """Validate one capability record and return it unchanged."""

    schema = load_json(schema_path())
    if not isinstance(schema, dict):
        raise CapabilityValidationError("capability schema is not a JSON object")
    try:
        _validate_schema_node(record, schema, schema, "$")
    except KeyError as exc:
        raise RuntimeError(f"invalid bundled capability schema: missing {exc}") from exc
    if not isinstance(record, dict):
        raise CapabilityValidationError("$: must be object")
    _validate_semantics(record)
    return record


def load_capability(path: str | Path) -> dict[str, Any]:
    """Load and validate one capability record."""

    value = load_json(path)
    return validate_capability(value)


def capability_fingerprint(record: Any) -> str:
    """Validate and fingerprint a record using the canonical JSON form."""

    return canonical_sha256(validate_capability(record))


def assess_capability(record: Any) -> CapabilityAssessment:
    """Assess technical gates separately from external-source evidence status."""

    validated = validate_capability(record)
    reasons: list[str] = []
    if validated["contract"]["fit"] != "verified":
        reasons.append("External Source Contract v1 fit is not verified")
    required = (
        "artifact_identity",
        "rights",
        "clock",
        "coordinates",
        "entity_identity",
        "field_provenance",
        "completeness",
        "information_loss",
        "anti_taint",
        "deterministic_conversion",
        "portable_evaluation",
        "semantics",
    )
    for name in required:
        if validated["capabilities"][name]["status"] != "verified":
            reasons.append(f"{name} is not verified")
    technical = not reasons
    external = technical and validated["record"]["evidence_classification"] == "external_source"
    if technical and not external:
        reasons.append("record is format-engineering evidence, not external-source evidence")
    return CapabilityAssessment(technical, external, tuple(reasons))


def _safe_repository_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise CapabilityValidationError("repository evidence path contains backslash")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise CapabilityValidationError("repository evidence path is unsafe")
    return path


def verify_repository_evidence(record: Any, repository_root: str | Path) -> dict[str, str]:
    """Verify every repository-file evidence hash without following symlinks."""

    validated = validate_capability(record)
    root = Path(repository_root).resolve()
    verified: dict[str, str] = {}
    for evidence in validated["evidence"]:
        if evidence["kind"] != "repository_file":
            continue
        relative = _safe_repository_path(evidence["path"])
        candidate = root
        for part in relative.parts[:-1]:
            candidate /= part
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise CapabilityValidationError(
                    f"repository evidence parent is unavailable: {candidate}"
                ) from exc
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise CapabilityValidationError(
                    f"repository evidence parent is not a real directory: {candidate}"
                )
        candidate /= relative.parts[-1]
        actual = artifact_sha256(candidate)
        if actual != evidence["sha256"]:
            _fail(f"$.evidence[{evidence['evidence_id']}]", "repository evidence hash mismatch")
        verified[evidence["evidence_id"]] = actual
    return verified
