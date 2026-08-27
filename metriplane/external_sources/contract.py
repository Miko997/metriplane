# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""External Source Contract v1 models and portable-bundle validation.

This module validates an opt-in profile around the existing FrameStateModel 1.0
and Atlas domain-pack boundary. It deliberately does not import or understand any
upstream robotics framework and does not change Atlas execution.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote_plus, urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from metriplane.atlas.domain_packs import (
    DomainPack,
    load_domain_pack,
    validate_domain_pack,
)
from metriplane.provenance.run_provenance import (
    canonical_json_dumps,
    sha256_file,
    sha256_text,
)
from metriplane.schema import FrameStateModel, ObjectStateModel
from metriplane.zones import point_in_polygon

CONTRACT_SCHEMA_VERSION = "metriplane.external_source_contract.v1"
CONTRACT_PROFILE = "metriplane.atlas.complete_snapshot.v1"
ENTITY_MAPPING_SCHEMA_VERSION = "metriplane.external_entity_mapping.v1"
NORMALIZATION_REPORT_SCHEMA_VERSION = "metriplane.external_normalization_report.v1"
EXPECTED_OUTCOME_SCHEMA_VERSION = "metriplane.external_expected_outcome.v1"

_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_EXTENSION_NAMESPACE = (
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?){2,}$"
)
_RESERVED_EXTENSION_KEYS = {
    "atlas_events",
    "atlas_incidents",
    "core_semantics",
    "domain_pack",
    "domain_pack_override",
    "events",
    "expected_incidents",
    "expected_outcome",
    "incident",
    "incident_id",
    "incident_truth",
    "incidents",
    "process_events",
    "process_rules",
    "used_as_incident_truth",
    "validation_override",
}
_RESERVED_EXTENSION_KEYS_COMPACT = {
    re.sub(r"[^a-z0-9]", "", key.lower()) for key in _RESERVED_EXTENSION_KEYS
}
_PROHIBITED_SESSION_ANNOTATIONS = {
    "failure",
    "failure_label",
    "incident",
    "incident_id",
    "reward",
    "source_incident_id",
    "success",
    "success_label",
    "terminated",
    "truncated",
}
_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_DIGEST = re.compile(r"^(?:[^@\s]+@)?sha256:[0-9a-f]{64}$")
_METRIPLANE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?$")


def validate_safe_relative_path(value: str) -> str:
    """Validate a portable slash-separated path without normalizing ambiguity."""
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ValueError(f"unsafe bundle path: {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe bundle path: {value!r}")
    return value


def _validate_uri(value: str) -> str:
    if any(character.isspace() for character in value):
        raise ValueError("URI must not contain whitespace")
    if not _URI_SCHEME.match(value):
        raise ValueError("URI must include an absolute scheme")
    if not value.split(":", 1)[1]:
        raise ValueError("URI must include a value after its absolute scheme")
    parsed = urlsplit(value)
    if parsed.scheme.lower() in {"http", "https"} and not parsed.netloc:
        raise ValueError("HTTP(S) URI must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URI must not contain embedded credentials")
    credential_names = {
        "access_token",
        "api_key",
        "apikey",
        "credential",
        "password",
        "secret",
        "signature",
        "token",
    }
    compact_credential_names = {re.sub(r"[^a-z0-9]", "", name) for name in credential_names}

    def _is_credential_name(name: str) -> bool:
        compact = re.sub(r"[^a-z0-9]", "", unquote_plus(name).lower())
        return compact in compact_credential_names or compact.endswith(
            (
                "accesstoken",
                "apikey",
                "credential",
                "password",
                "secret",
                "signature",
                "token",
            )
        )

    query_or_fragment_names = {
        item.split("=", 1)[0]
        for component in (parsed.query, parsed.fragment)
        for item in component.split("&")
        if "=" in item
    }
    if any(_is_credential_name(name) for name in query_or_fragment_names):
        raise ValueError("URI must not contain credential-like query parameters")
    return value


def _nonempty_identifier(value: str, *, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value


def _validate_nonblank(value: str) -> str:
    return _nonempty_identifier(value, label="value")


def _require_known_semantic(value: str, *, label: str) -> None:
    if value.strip().lower() in {"n/a", "na", "unknown", "unspecified"}:
        raise ValueError(f"{label} must be explicitly known")


def _unique(values: Sequence[str], *, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


def _reject_reserved_extension_keys(value: JsonValue, *, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.strip().lower())
            if normalized in _RESERVED_EXTENSION_KEYS_COMPACT:
                raise ValueError(
                    f"{path}.{key} attempts to alter reserved Atlas or incident semantics"
                )
            _reject_reserved_extension_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_reserved_extension_keys(item, path=f"{path}[{index}]")


def _resolve_json_pointer(document: JsonValue, pointer: str) -> JsonValue:
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with '/'")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
            continue
        raise ValueError(f"JSON pointer does not resolve: {pointer}")
    return current


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SafeRelativePath = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(validate_safe_relative_path),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "pattern": (
                "^(?!.*[\\x00-\\x1f\\x7f])(?!/)(?![A-Za-z]:)(?!.*\\\\)"
                r"(?!.*(?:^|/)\.\.?($|/))"
                r"(?!.*//)(?!.*\/$).+$"
            ),
        },
        mode="validation",
    ),
]
AbsoluteUri = Annotated[
    str,
    StringConstraints(min_length=3),
    AfterValidator(_validate_uri),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 3,
            "pattern": r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$",
        },
        mode="validation",
    ),
]
NamespacedKey = Annotated[str, StringConstraints(pattern=_EXTENSION_NAMESPACE)]
NonBlankString = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_validate_nonblank),
    WithJsonSchema(
        {"type": "string", "minLength": 1, "pattern": r".*\S.*"},
        mode="validation",
    ),
]
CommitSha = Annotated[str, StringConstraints(pattern=_COMMIT_SHA.pattern)]


class ContractModel(BaseModel):
    """Strict base for all contract-owned structures."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        validate_default=True,
    )


class FileReference(ContractModel):
    path: SafeRelativePath
    sha256: Sha256
    media_type: NonBlankString | None = None


class FixtureIdentity(ContractModel):
    fixture_id: str
    title: str
    description: str
    bounded_recording: Literal[True]
    distribution: Literal[
        "public",
        "reference_only",
        "derived_only",
        "proprietary",
        "private",
    ]

    @field_validator("fixture_id", "title", "description")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _nonempty_identifier(value, label="fixture identity field")


class SourceRevision(ContractModel):
    kind: Literal[
        "git_commit",
        "content_digest",
        "dataset_revision",
        "doi_version",
        "immutable_build_id",
    ]
    value: NonBlankString

    @model_validator(mode="after")
    def _value_is_immutable(self) -> SourceRevision:
        if self.value.strip().lower() in {
            "current",
            "head",
            "latest",
            "main",
            "master",
            "tip",
            "unknown",
        }:
            raise ValueError("source revision must be immutable, not a moving label")
        if self.kind == "git_commit" and _COMMIT_SHA.fullmatch(self.value) is None:
            raise ValueError("git_commit source revision must be a full 40- or 64-hex commit")
        if self.kind == "content_digest" and _CONTENT_DIGEST.fullmatch(self.value) is None:
            raise ValueError("content_digest source revision must use sha256:<64 lowercase hex>")
        return self


class SourceProject(ContractModel):
    name: NonBlankString
    canonical_uri: AbsoluteUri
    version: NonBlankString | None = None
    revision: SourceRevision


class SourceArtifact(ContractModel):
    artifact_id: NonBlankString
    role: NonBlankString
    media_type: NonBlankString
    rights_id: NonBlankString
    presence: Literal["included", "referenced", "withheld"]
    path: SafeRelativePath | None = None
    uri: AbsoluteUri | None = None
    sha256: Sha256 | None = None
    immutable_identifier: NonBlankString | None = None
    description: NonBlankString

    @model_validator(mode="after")
    def _identity_is_complete(self) -> SourceArtifact:
        if self.immutable_identifier is not None and self.immutable_identifier.strip().lower() in {
            "current",
            "head",
            "latest",
            "main",
            "master",
            "tip",
            "unknown",
        }:
            raise ValueError("immutable_identifier must not be a moving label")
        if self.presence == "included":
            if self.path is None:
                raise ValueError("included source artifact requires path")
            if self.sha256 is None:
                raise ValueError("included source artifact requires sha256")
        else:
            if self.path is not None:
                raise ValueError(f"{self.presence} source artifact must not set path")
            if self.uri is None:
                raise ValueError(f"{self.presence} source artifact requires uri")
            if self.sha256 is None and not self.immutable_identifier:
                raise ValueError(
                    f"{self.presence} source artifact requires sha256 or immutable_identifier"
                )
        return self


class SourceSelection(ContractModel):
    artifact_ids: list[NonBlankString] = Field(min_length=1)
    method: Literal[
        "entire_artifact",
        "episode",
        "group",
        "index_range",
        "time_range",
        "external_selector",
    ]
    episode_id: NonBlankString | None = None
    group_path: NonBlankString | None = None
    start_index: int | None = Field(default=None, ge=0)
    end_index_exclusive: int | None = Field(default=None, gt=0)
    start_time: float | None = None
    end_time: float | None = None
    selector: FileReference | None = None
    rationale: NonBlankString

    @model_validator(mode="after")
    def _selector_matches_method(self) -> SourceSelection:
        _unique(self.artifact_ids, label="selected source artifact id")
        populated = {
            "episode_id": self.episode_id,
            "group_path": self.group_path,
            "start_index": self.start_index,
            "end_index_exclusive": self.end_index_exclusive,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "selector": self.selector,
        }
        allowed = {
            "entire_artifact": set(),
            "episode": {"episode_id"},
            "group": {"group_path"},
            "index_range": {"start_index", "end_index_exclusive"},
            "time_range": {"start_time", "end_time"},
            "external_selector": {"selector"},
        }[self.method]
        contradictory = sorted(
            name for name, value in populated.items() if value is not None and name not in allowed
        )
        if contradictory:
            raise ValueError(f"{self.method} selection cannot declare: {', '.join(contradictory)}")
        if self.method == "episode" and not self.episode_id:
            raise ValueError("episode selection requires episode_id")
        if self.method == "group" and not self.group_path:
            raise ValueError("group selection requires group_path")
        if self.method == "index_range":
            if self.start_index is None or self.end_index_exclusive is None:
                raise ValueError(
                    "index_range selection requires start_index and end_index_exclusive"
                )
            if self.end_index_exclusive <= self.start_index:
                raise ValueError("end_index_exclusive must be greater than start_index")
        if self.method == "time_range":
            if self.start_time is None or self.end_time is None:
                raise ValueError("time_range selection requires start_time and end_time")
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be greater than start_time")
        if self.method == "external_selector" and self.selector is None:
            raise ValueError("external_selector selection requires selector")
        return self


class LicenseDeclaration(ContractModel):
    status: Literal["declared", "proprietary", "unknown"]
    identifier: NonBlankString | None = None
    uri: AbsoluteUri | None = None

    @model_validator(mode="after")
    def _declared_license_has_identity(self) -> LicenseDeclaration:
        if self.status in ("declared", "proprietary") and not self.identifier:
            raise ValueError(f"{self.status} license requires identifier")
        if self.status == "unknown" and (self.identifier is not None or self.uri is not None):
            raise ValueError("unknown license cannot claim an identifier or URI")
        return self


class CitationRecord(ContractModel):
    text: NonBlankString
    uri: AbsoluteUri | None = None


class SourceRightsDeclaration(ContractModel):
    rights_id: NonBlankString
    source_access: Literal["public", "restricted", "proprietary", "private"]
    license: LicenseDeclaration
    citation: list[CitationRecord] = Field(min_length=1)
    source_use_permission: Literal["verified", "not_required", "unresolved"]
    redistribution: Literal[
        "allowed",
        "prohibited",
        "derived_only",
        "permission_required",
        "private",
    ]
    redistribution_permission: Literal["verified", "not_required", "unresolved"]
    permission_basis: NonBlankString

    @model_validator(mode="after")
    def _permission_states_are_coherent(self) -> SourceRightsDeclaration:
        if (
            self.source_access in ("proprietary", "private")
            and self.source_use_permission == "not_required"
        ):
            raise ValueError(
                f"{self.source_access} source access cannot claim source_use_permission=not_required"
            )
        if (
            self.redistribution == "permission_required"
            and self.redistribution_permission == "not_required"
        ):
            raise ValueError(
                "permission_required redistribution cannot claim redistribution_permission=not_required"
            )
        if self.redistribution == "allowed" and self.redistribution_permission == "unresolved":
            raise ValueError("allowed redistribution requires resolved redistribution permission")
        return self


class FixtureRightsDeclaration(ContractModel):
    access: Literal["public", "restricted", "proprietary", "private"]
    license: LicenseDeclaration
    citation: list[CitationRecord] = Field(min_length=1)
    redistribution: Literal["allowed", "prohibited", "permission_required", "private"]
    redistribution_permission: Literal["verified", "not_required", "unresolved"]
    permission_basis: NonBlankString

    @model_validator(mode="after")
    def _distribution_is_coherent(self) -> FixtureRightsDeclaration:
        if self.redistribution == "allowed" and self.redistribution_permission == "unresolved":
            raise ValueError("allowed fixture redistribution requires resolved permission")
        if (
            self.redistribution == "permission_required"
            and self.redistribution_permission == "not_required"
        ):
            raise ValueError(
                "permission_required fixture redistribution cannot claim permission=not_required"
            )
        return self


class RightsDeclarations(ContractModel):
    source_artifacts: list[SourceRightsDeclaration] = Field(min_length=1)
    fixture: FixtureRightsDeclaration

    @model_validator(mode="after")
    def _source_rights_ids_are_unique(self) -> RightsDeclarations:
        _unique(
            [declaration.rights_id for declaration in self.source_artifacts],
            label="source rights id",
        )
        return self


class AdapterParameters(ContractModel):
    inline: dict[str, JsonValue] | None = None
    reference: FileReference | None = None
    sha256: Sha256

    @model_validator(mode="after")
    def _one_parameter_representation(self) -> AdapterParameters:
        if (self.inline is None) == (self.reference is None):
            raise ValueError("adapter parameters require exactly one of inline or reference")
        if self.inline is not None:
            _reject_reserved_extension_keys(self.inline, path="adapter.parameters.inline")
            actual = sha256_text(canonical_json_dumps(self.inline))
            if actual != self.sha256:
                raise ValueError(
                    f"adapter parameter sha256 mismatch: declared {self.sha256}, computed {actual}"
                )
        elif self.reference is not None and self.reference.sha256 != self.sha256:
            raise ValueError("adapter parameter sha256 must match referenced parameter file")
        return self


class AdapterEnvironment(ContractModel):
    runtime: NonBlankString
    runtime_version: NonBlankString
    operating_system: NonBlankString
    architecture: NonBlankString
    dependency_lock: FileReference | None = None
    container_image_digest: NonBlankString | None = None
    description: NonBlankString

    @model_validator(mode="after")
    def _reproducible_identity(self) -> AdapterEnvironment:
        if self.dependency_lock is None and not self.container_image_digest:
            raise ValueError(
                "adapter environment requires dependency_lock or container_image_digest"
            )
        if (
            self.container_image_digest is not None
            and _CONTAINER_DIGEST.fullmatch(self.container_image_digest) is None
        ):
            raise ValueError(
                "container_image_digest must be sha256:<64 lowercase hex>, optionally "
                "prefixed by an image name and @"
            )
        return self


class AdapterDeclaration(ContractModel):
    adapter_id: NamespacedKey
    name: NonBlankString
    version: NonBlankString
    repository_uri: AbsoluteUri
    commit: CommitSha
    entrypoint: NonBlankString
    environment: AdapterEnvironment
    parameters: AdapterParameters


class ClockMapping(ContractModel):
    source_clock: NonBlankString
    source_field: NonBlankString
    source_unit: Literal["seconds", "milliseconds", "microseconds", "nanoseconds", "ticks", "index"]
    evaluation_field: Literal["ts", "ts_sim_ns"]
    mapping_method: Literal["identity_seconds", "fixed_step", "affine", "lookup_table"]
    fixed_step_ns: int | None = Field(default=None, gt=0)
    fixed_step_origin_ns: int | None = Field(default=None, ge=0)
    scale: float | None = Field(default=None, gt=0)
    offset: float | None = None
    lookup: FileReference | None = None
    description: NonBlankString

    @model_validator(mode="after")
    def _mapping_parameters_are_declared(self) -> ClockMapping:
        _require_known_semantic(self.source_clock, label="source_clock")
        _require_known_semantic(self.source_field, label="source_field")
        _require_known_semantic(self.description, label="clock mapping description")
        if self.mapping_method == "identity_seconds":
            if self.source_unit != "seconds" or self.evaluation_field != "ts":
                raise ValueError("identity_seconds requires seconds -> ts")
            if any(
                value is not None
                for value in (
                    self.fixed_step_ns,
                    self.fixed_step_origin_ns,
                    self.scale,
                    self.offset,
                    self.lookup,
                )
            ):
                raise ValueError(
                    "identity_seconds cannot declare fixed-step, affine, or lookup fields"
                )
        elif self.mapping_method == "fixed_step":
            if (
                self.fixed_step_ns is None
                or self.fixed_step_origin_ns is None
                or self.evaluation_field != "ts_sim_ns"
            ):
                raise ValueError(
                    "fixed_step requires fixed_step_ns, fixed_step_origin_ns, and "
                    "evaluation_field ts_sim_ns"
                )
            if any(value is not None for value in (self.scale, self.offset, self.lookup)):
                raise ValueError("fixed_step cannot declare affine or lookup fields")
        elif self.mapping_method == "affine":
            if self.scale is None or self.offset is None:
                raise ValueError("affine clock mapping requires scale and offset")
            if any(
                value is not None
                for value in (self.fixed_step_ns, self.fixed_step_origin_ns, self.lookup)
            ):
                raise ValueError("affine clock mapping cannot declare fixed-step or lookup fields")
        elif self.mapping_method == "lookup_table":
            if self.lookup is None:
                raise ValueError("lookup_table clock mapping requires lookup")
            if any(
                value is not None
                for value in (
                    self.fixed_step_ns,
                    self.fixed_step_origin_ns,
                    self.scale,
                    self.offset,
                )
            ):
                raise ValueError(
                    "lookup_table clock mapping cannot declare fixed-step or affine fields"
                )
        return self


class TransformDeclaration(ContractModel):
    method: Literal["identity", "rigid_matrix", "affine_matrix", "homography", "custom"]
    parameters: FileReference | None = None
    implementation: NonBlankString

    @model_validator(mode="after")
    def _nonidentity_is_parameterized(self) -> TransformDeclaration:
        _require_known_semantic(self.implementation, label="transform implementation")
        if self.method == "identity" and self.parameters is not None:
            raise ValueError("identity transform cannot declare parameters")
        if self.method != "identity" and self.parameters is None:
            raise ValueError(f"transform method {self.method} requires parameters")
        return self


class InformationLossDeclaration(ContractModel):
    operation: NonBlankString
    lost_information: list[NonBlankString] = Field(min_length=1)
    impact: NonBlankString


class ProjectionDeclaration(ContractModel):
    method: Literal["identity_3d", "planar_xy", "homography", "custom"]
    dropped_axes: list[NonBlankString] = Field(default_factory=list)
    output_z_policy: Literal["preserve", "zero", "not_applicable"]
    parameters: FileReference | None = None
    implementation: NonBlankString

    @model_validator(mode="after")
    def _projection_is_explicit(self) -> ProjectionDeclaration:
        _require_known_semantic(self.implementation, label="projection implementation")
        if self.method == "identity_3d":
            if (
                self.dropped_axes
                or self.output_z_policy != "preserve"
                or self.parameters is not None
            ):
                raise ValueError(
                    "identity_3d cannot drop axes or declare parameters and must preserve z"
                )
        elif self.method == "planar_xy":
            if self.dropped_axes != ["z"] or self.output_z_policy != "zero":
                raise ValueError("planar_xy requires dropped_axes=['z'] and output_z_policy=zero")
            if self.parameters is not None:
                raise ValueError("planar_xy cannot declare projection parameters")
        elif self.parameters is None:
            raise ValueError(f"projection method {self.method} requires parameters")
        return self


class CoordinateMapping(ContractModel):
    source_frame: NonBlankString
    target_frame: NonBlankString
    source_units: NonBlankString
    target_units: NonBlankString
    transform: TransformDeclaration
    projection: ProjectionDeclaration
    information_loss: list[InformationLossDeclaration]

    @model_validator(mode="after")
    def _coordinate_operations_match(self) -> CoordinateMapping:
        for label, value in (
            ("source_frame", self.source_frame),
            ("target_frame", self.target_frame),
            ("source_units", self.source_units),
            ("target_units", self.target_units),
        ):
            _require_known_semantic(value, label=label)
        if self.transform.method == "identity" and (
            self.source_frame != self.target_frame or self.source_units != self.target_units
        ):
            raise ValueError("identity transform requires identical source/target frames and units")
        if self.source_units != self.target_units and self.transform.method not in (
            "affine_matrix",
            "custom",
        ):
            raise ValueError("unit conversion requires an affine_matrix or custom transform")
        if self.projection.method == "identity_3d" and self.information_loss:
            raise ValueError("identity_3d projection cannot declare information loss")
        if self.projection.method != "identity_3d" and not self.information_loss:
            raise ValueError("non-identity projection requires information_loss declaration")
        return self


class EntityMappingReference(FileReference):
    schema_version: Literal["metriplane.external_entity_mapping.v1"]


NormalizedField = Literal[
    "schema_version",
    "source_backend",
    "ts",
    "ts_sim_ns",
    "frame_id",
    "objects[*].id",
    "objects[*].pos_world",
    "objects[*].vel_world",
    "objects[*].zone",
    "objects[*].confidence",
    "fused[*].id",
    "fused[*].pos_world",
    "fused[*].vel_world",
    "fused[*].zone",
    "fused[*].confidence",
]

ObservationField = Literal[
    "objects[*].pos_world",
    "objects[*].vel_world",
    "objects[*].zone",
    "objects[*].confidence",
    "fused[*].pos_world",
    "fused[*].vel_world",
    "fused[*].zone",
    "fused[*].confidence",
]


class FieldProvenance(ContractModel):
    normalized_field: NormalizedField
    layer: Literal["source_fact", "adapter_derived_fact"]
    source_artifact_ids: list[NonBlankString] = Field(min_length=1)
    source_fields: list[NonBlankString] = Field(default_factory=list)
    derivation: NonBlankString | None = None
    parameter_references: list[FileReference] = Field(default_factory=list)
    confidence_origin: Literal["source_value", "documented_algorithm"] | None = None

    @model_validator(mode="after")
    def _layer_is_explained(self) -> FieldProvenance:
        _unique(self.source_artifact_ids, label="field-provenance source artifact id")
        _unique(self.source_fields, label="field-provenance source field")
        _unique(
            [reference.path for reference in self.parameter_references],
            label="field-provenance parameter path",
        )
        if self.layer == "source_fact" and not self.source_fields:
            raise ValueError(f"source fact {self.normalized_field} requires source_fields")
        if self.layer == "source_fact" and (
            self.derivation is not None or self.parameter_references
        ):
            raise ValueError(
                f"source fact {self.normalized_field} cannot declare derivation parameters"
            )
        if self.layer == "adapter_derived_fact" and not self.derivation:
            raise ValueError(f"adapter-derived field {self.normalized_field} requires derivation")
        if (
            self.layer == "adapter_derived_fact"
            and self.normalized_field not in ("schema_version", "source_backend")
            and not self.source_fields
        ):
            raise ValueError(
                f"adapter-derived field {self.normalized_field} requires source_fields; "
                "free-text derivation cannot conceal a source annotation or other input"
            )
        if self.normalized_field.endswith(".confidence") and self.confidence_origin is None:
            raise ValueError("confidence provenance requires source_value or documented_algorithm")
        if not self.normalized_field.endswith(".confidence") and self.confidence_origin is not None:
            raise ValueError("confidence_origin is valid only for a confidence field")
        return self


class ZoneAssignment(ContractModel):
    method: Literal["source_label", "polygon", "lookup_table", "documented_algorithm"]
    definitions: FileReference
    parameters: FileReference | None = None
    boundary_policy: Literal["inclusive", "exclusive", "half_open", "not_applicable"]
    overlap_policy: Literal["reject", "priority_order", "not_applicable"]
    zone_priority: list[NonBlankString] = Field(default_factory=list)
    outside_workspace_policy: Literal["explicit_label", "reject"]
    outside_zone_label: NonBlankString | None = None
    implementation: NonBlankString

    @model_validator(mode="after")
    def _outside_policy_is_explicit(self) -> ZoneAssignment:
        _require_known_semantic(self.implementation, label="zone-assignment implementation")
        if self.outside_workspace_policy == "explicit_label" and not self.outside_zone_label:
            raise ValueError("explicit_label outside policy requires outside_zone_label")
        if self.outside_workspace_policy == "reject" and self.outside_zone_label is not None:
            raise ValueError("reject outside policy cannot declare outside_zone_label")
        if self.method == "source_label":
            if self.parameters is not None:
                raise ValueError("source_label zone assignment cannot declare parameters")
            if self.boundary_policy != "not_applicable" or self.overlap_policy != "not_applicable":
                raise ValueError(
                    "source_label zone assignment requires not_applicable boundary/overlap policies"
                )
        elif self.method == "polygon":
            if self.parameters is not None:
                raise ValueError(
                    "polygon zone assignment uses workspace definitions, not parameters"
                )
            if self.boundary_policy not in ("inclusive", "exclusive"):
                raise ValueError(
                    "polygon zone assignment requires inclusive or exclusive boundary_policy"
                )
            if self.overlap_policy == "not_applicable":
                raise ValueError("polygon zone assignment requires an overlap policy")
        elif self.method == "lookup_table":
            if self.parameters is None:
                raise ValueError("lookup_table zone assignment requires parameters")
            if self.boundary_policy != "not_applicable" or self.overlap_policy != "not_applicable":
                raise ValueError(
                    "lookup_table zone assignment requires not_applicable boundary/overlap policies"
                )
        elif self.parameters is None:
            raise ValueError("documented_algorithm zone assignment requires parameters")
        if self.overlap_policy == "priority_order" and not self.zone_priority:
            raise ValueError("priority_order overlap policy requires zone_priority")
        if self.overlap_policy != "priority_order" and self.zone_priority:
            raise ValueError("zone_priority is valid only with priority_order overlap policy")
        _unique(self.zone_priority, label="zone priority")
        return self


class CarryForwardPolicy(ContractModel):
    method: Literal["none", "bounded_last_observation"]
    fields: list[ObservationField] = Field(default_factory=list)
    max_gap_ns: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _bounded_policy_has_limit(self) -> CarryForwardPolicy:
        _unique(self.fields, label="carry-forward field")
        if self.method == "bounded_last_observation" and (
            not self.fields or self.max_gap_ns is None
        ):
            raise ValueError("bounded carry-forward requires fields and max_gap_ns")
        if self.method == "none" and (self.fields or self.max_gap_ns is not None):
            raise ValueError("carry-forward method none cannot declare fields or max_gap_ns")
        return self


class InterpolationPolicy(ContractModel):
    method: Literal["none", "linear", "nearest_neighbor", "zero_order_hold"]
    fields: list[ObservationField] = Field(default_factory=list)
    max_gap_ns: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _declared_interpolation_is_bounded(self) -> InterpolationPolicy:
        _unique(self.fields, label="interpolation field")
        if self.method == "linear" and any(field.endswith(".zone") for field in self.fields):
            raise ValueError("linear interpolation cannot be applied to categorical zone fields")
        if self.method != "none" and (not self.fields or self.max_gap_ns is None):
            raise ValueError("interpolation requires fields and max_gap_ns")
        if self.method == "none" and (self.fields or self.max_gap_ns is not None):
            raise ValueError("interpolation method none cannot declare fields or max_gap_ns")
        return self


class ResamplingPolicy(ContractModel):
    method: Literal["none", "fixed_rate", "selected_source_frames"]
    fields: list[NormalizedField] = Field(default_factory=list)
    output_period_ns: int | None = Field(default=None, gt=0)
    max_gap_ns: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _declared_resampling_is_bounded(self) -> ResamplingPolicy:
        _unique(self.fields, label="resampling field")
        if self.method == "fixed_rate" and (
            not self.fields or self.output_period_ns is None or self.max_gap_ns is None
        ):
            raise ValueError(
                "fixed_rate resampling requires fields, output_period_ns, and max_gap_ns"
            )
        if (
            self.method == "fixed_rate"
            and self.output_period_ns is not None
            and self.max_gap_ns is not None
            and self.max_gap_ns < self.output_period_ns
        ):
            raise ValueError("fixed_rate max_gap_ns must be at least one output period")
        if self.method == "selected_source_frames" and (
            not self.fields or self.output_period_ns is not None or self.max_gap_ns is None
        ):
            raise ValueError(
                "selected_source_frames resampling requires fields, max_gap_ns, and no "
                "output_period_ns"
            )
        if self.method == "none" and (
            self.fields or self.output_period_ns is not None or self.max_gap_ns is not None
        ):
            raise ValueError("resampling method none cannot declare fields, period, or max_gap_ns")
        return self


class SynchronizationPolicy(ContractModel):
    method: Literal["not_applicable", "exact_timestamp", "nearest_neighbor", "windowed"]
    fields: list[ObservationField] = Field(default_factory=list)
    reference_stream: NonBlankString | None = None
    max_skew_ns: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _declared_synchronization_is_bounded(self) -> SynchronizationPolicy:
        _unique(self.fields, label="synchronization field")
        if self.method in ("nearest_neighbor", "windowed") and (
            not self.fields or not self.reference_stream or self.max_skew_ns is None
        ):
            raise ValueError(
                f"{self.method} synchronization requires reference_stream and max_skew_ns"
            )
        if self.method == "exact_timestamp" and (
            not self.fields or not self.reference_stream or self.max_skew_ns != 0
        ):
            raise ValueError(
                "exact_timestamp synchronization requires reference_stream and max_skew_ns=0"
            )
        if self.method == "not_applicable" and (
            self.fields or self.reference_stream is not None or self.max_skew_ns is not None
        ):
            raise ValueError(
                "not_applicable synchronization cannot declare fields or alignment parameters"
            )
        return self


class TemporalAlignment(ContractModel):
    interpolation: InterpolationPolicy
    resampling: ResamplingPolicy
    synchronization: SynchronizationPolicy


class PartialUpdateMaterialization(ContractModel):
    method: Literal[
        "bounded_last_observation",
        "state_restoration",
        "source_snapshot_join",
        "documented_algorithm",
    ]
    fields: list[ObservationField] = Field(min_length=1)
    implementation: NonBlankString
    parameters: FileReference
    carry_forward_dependency: Literal["none", "declared_bounded_policy"]

    @field_validator("fields")
    @classmethod
    def _unique_fields(cls, value: list[ObservationField]) -> list[ObservationField]:
        _unique(value, label="partial-update materialization field")
        return value

    @model_validator(mode="after")
    def _carry_forward_use_is_structured(self) -> PartialUpdateMaterialization:
        if (
            self.method == "bounded_last_observation"
            and self.carry_forward_dependency != "declared_bounded_policy"
        ):
            raise ValueError(
                "bounded_last_observation materialization requires "
                "carry_forward_dependency=declared_bounded_policy"
            )
        if self.method != "bounded_last_observation" and self.carry_forward_dependency != "none":
            raise ValueError(
                f"{self.method} materialization cannot conceal carry-forward behavior; "
                "use bounded_last_observation with a bounded carry_forward policy"
            )
        return self


class CompletenessPolicy(ContractModel):
    source_stream_semantics: Literal["complete_snapshot", "partial_update"]
    frame_semantics: Literal["complete_snapshot"]
    partial_updates_materialized: bool
    materialization: PartialUpdateMaterialization | None = None
    omission_policy: Literal["reject_omission"]
    unknown_state_policy: Literal["reject_fixture"]
    process_relevant_entity_policy: Literal["known_in_every_frame"]
    carry_forward: CarryForwardPolicy

    @model_validator(mode="after")
    def _partial_updates_are_resolved(self) -> CompletenessPolicy:
        if self.source_stream_semantics == "partial_update":
            if not self.partial_updates_materialized or self.materialization is None:
                raise ValueError(
                    "partial-update source must be materialized into complete snapshots "
                    "with a declared materialization operation"
                )
            if self.materialization.method == "bounded_last_observation":
                if self.carry_forward.method != "bounded_last_observation":
                    raise ValueError(
                        "bounded_last_observation materialization requires a bounded "
                        "carry_forward policy"
                    )
                if set(self.materialization.fields) != set(self.carry_forward.fields):
                    raise ValueError(
                        "partial-update materialization fields must match bounded "
                        "carry_forward fields"
                    )
            elif self.carry_forward.method != "none":
                raise ValueError(
                    "carry_forward must be none unless it is the declared partial-update "
                    "materialization method"
                )
        elif self.partial_updates_materialized or self.materialization is not None:
            raise ValueError(
                "complete-snapshot source must not declare partial-update materialization"
            )
        return self


class ConfidencePolicy(ContractModel):
    mode: Literal["absent", "source", "documented_algorithm"]
    source_field: NonBlankString | None = None
    algorithm: NonBlankString | None = None
    implementation: FileReference | None = None
    input_fields: list[NonBlankString] = Field(default_factory=list)
    parameters: FileReference | None = None
    output_semantics: NonBlankString | None = None
    placeholder_or_invented_values: Literal[False] | None = None

    @model_validator(mode="after")
    def _confidence_has_origin(self) -> ConfidencePolicy:
        if self.mode == "absent" and any(
            value is not None
            for value in (
                self.source_field,
                self.algorithm,
                self.implementation,
                self.parameters,
                self.output_semantics,
                self.placeholder_or_invented_values,
            )
        ):
            raise ValueError("absent confidence cannot declare an origin")
        if self.mode == "absent" and self.input_fields:
            raise ValueError("absent confidence cannot declare input_fields")
        if self.mode == "source":
            if not self.source_field:
                raise ValueError("source confidence requires source_field")
            if (
                any(
                    value is not None
                    for value in (
                        self.algorithm,
                        self.implementation,
                        self.parameters,
                        self.output_semantics,
                        self.placeholder_or_invented_values,
                    )
                )
                or self.input_fields
            ):
                raise ValueError("source confidence cannot declare algorithm fields")
        if self.mode == "documented_algorithm" and (
            not self.algorithm
            or self.implementation is None
            or not self.input_fields
            or self.parameters is None
            or not self.output_semantics
            or self.placeholder_or_invented_values is not False
        ):
            raise ValueError(
                "algorithm confidence requires algorithm, implementation, input_fields, "
                "parameters, output_semantics, and placeholder_or_invented_values=false"
            )
        if self.mode == "documented_algorithm" and self.source_field is not None:
            raise ValueError("algorithm confidence cannot declare source_field")
        _unique(self.input_fields, label="confidence algorithm input field")
        return self


class SourceAnnotation(ContractModel):
    name: NonBlankString
    source_field: NonBlankString
    treatment: Literal["provenance_only", "source_selection_only", "excluded"]
    retained_in: Literal[
        "source_artifact",
        "manifest_extension",
        "not_retained",
    ]
    retained_reference: NonBlankString | None = None
    source_artifact_ids: list[NonBlankString] = Field(min_length=1)

    @model_validator(mode="after")
    def _retention_is_explicit(self) -> SourceAnnotation:
        _unique(self.source_artifact_ids, label="annotation source artifact id")
        if self.treatment == "excluded" and self.retained_in != "not_retained":
            raise ValueError("excluded source annotation must use retained_in=not_retained")
        if self.treatment != "excluded" and self.retained_in == "not_retained":
            raise ValueError("retained source annotation must identify its retention location")
        if self.retained_in == "manifest_extension":
            if self.retained_reference is None:
                raise ValueError("manifest_extension requires retained_reference")
            if not self.retained_reference.startswith("/extensions/"):
                raise ValueError(
                    "manifest_extension retained_reference must be a JSON pointer under "
                    "/extensions/"
                )
        elif self.retained_reference is not None:
            raise ValueError("retained_reference is valid only for manifest/report retention")
        return self


class SourceAnnotationPolicy(ContractModel):
    annotations: list[SourceAnnotation]
    inventory_complete: Literal[True]
    used_as_incident_truth: Literal[False]
    used_as_process_events: Literal[False]
    source_incident_ids_in_normalized_input: Literal[False]
    frame_state_events_policy: Literal["empty"]


class NormalizationDeclaration(ContractModel):
    frame_state_model_version: Literal["1.0"]
    source_backend: NonBlankString
    authoritative_object_collection: Literal["objects", "fused"]
    clock: ClockMapping
    coordinates: CoordinateMapping
    entity_mapping: EntityMappingReference
    atlas_asset_mapping: FileReference
    field_provenance: list[FieldProvenance] = Field(min_length=1)
    zone_assignment: ZoneAssignment
    completeness: CompletenessPolicy
    temporal_alignment: TemporalAlignment
    confidence: ConfidencePolicy
    source_annotations: SourceAnnotationPolicy

    @model_validator(mode="after")
    def _field_declarations_are_unique(self) -> NormalizationDeclaration:
        _require_known_semantic(self.source_backend, label="source_backend")
        _unique(
            [item.normalized_field for item in self.field_provenance],
            label="normalized field provenance declaration",
        )
        prefix = "objects[*]." if self.authoritative_object_collection == "objects" else "fused[*]."
        wrong_collection = sorted(
            item.normalized_field
            for item in self.field_provenance
            if (
                item.normalized_field.startswith("objects[*].")
                or item.normalized_field.startswith("fused[*].")
            )
            and not item.normalized_field.startswith(prefix)
        )
        if wrong_collection:
            raise ValueError(
                "field provenance targets the non-authoritative object collection: "
                + ", ".join(wrong_collection)
            )
        provenance: dict[str, FieldProvenance] = {
            item.normalized_field: item for item in self.field_provenance
        }
        for required_derived_field in ("schema_version", "source_backend", f"{prefix}id"):
            declaration = provenance.get(required_derived_field)
            if declaration is None or declaration.layer != "adapter_derived_fact":
                raise ValueError(
                    f"{required_derived_field} requires adapter_derived_fact provenance"
                )
        evaluation_clock = provenance.get(self.clock.evaluation_field)
        if self.clock.mapping_method != "identity_seconds" and (
            evaluation_clock is None or evaluation_clock.layer != "adapter_derived_fact"
        ):
            raise ValueError(
                f"{self.clock.mapping_method} clock output requires adapter-derived provenance"
            )
        if (
            self.coordinates.transform.method != "identity"
            or self.coordinates.projection.method != "identity_3d"
        ):
            for state_field in (f"{prefix}pos_world", f"{prefix}vel_world"):
                state_declaration = provenance.get(state_field)
                if (
                    state_declaration is not None
                    and state_declaration.layer != "adapter_derived_fact"
                ):
                    raise ValueError(
                        f"transformed or projected {state_field} requires "
                        "adapter_derived_fact provenance"
                    )
            if provenance.get(f"{prefix}pos_world") is None:
                raise ValueError("transformed or projected state requires pos_world provenance")
        zone = provenance.get(f"{prefix}zone")
        expected_zone_layer = (
            "source_fact"
            if self.zone_assignment.method == "source_label"
            else "adapter_derived_fact"
        )
        if zone is None or zone.layer != expected_zone_layer:
            raise ValueError(
                f"{self.zone_assignment.method} zone assignment requires "
                f"{expected_zone_layer} provenance"
            )
        confidence = provenance.get(f"{prefix}confidence")
        if self.confidence.mode == "absent":
            if confidence is not None:
                raise ValueError("absent confidence policy cannot declare confidence provenance")
        elif self.confidence.mode == "source":
            if (
                confidence is None
                or confidence.layer != "source_fact"
                or confidence.confidence_origin != "source_value"
                or self.confidence.source_field not in confidence.source_fields
            ):
                raise ValueError(
                    "source confidence requires matching source_fact/source_value provenance"
                )
        elif (
            confidence is None
            or confidence.layer != "adapter_derived_fact"
            or confidence.confidence_origin != "documented_algorithm"
        ):
            raise ValueError("algorithm confidence requires matching adapter-derived provenance")
        if self.confidence.mode == "documented_algorithm":
            assert self.confidence.implementation is not None
            assert self.confidence.parameters is not None
            assert confidence is not None
            declared_parameter_paths = {
                reference.path for reference in confidence.parameter_references
            }
            required_parameter_paths = {
                self.confidence.implementation.path,
                self.confidence.parameters.path,
            }
            if not required_parameter_paths.issubset(declared_parameter_paths):
                raise ValueError(
                    "algorithm confidence provenance must reference its hashed implementation "
                    "and parameters"
                )
            if not set(self.confidence.input_fields).issubset(confidence.source_fields):
                raise ValueError(
                    "algorithm confidence provenance must list every declared source input field"
                )
        temporal_derived_fields: set[str] = set()
        temporal_derived_fields.update(self.completeness.carry_forward.fields)
        if self.completeness.materialization is not None:
            temporal_derived_fields.update(self.completeness.materialization.fields)
        temporal_derived_fields.update(self.temporal_alignment.interpolation.fields)
        temporal_derived_fields.update(self.temporal_alignment.resampling.fields)
        temporal_derived_fields.update(self.temporal_alignment.synchronization.fields)
        resampling = self.temporal_alignment.resampling
        if resampling.method != "none" and "frame_id" not in resampling.fields:
            raise ValueError("resampling must declare frame_id as an adapter-derived field")
        if (
            resampling.method == "fixed_rate"
            and self.clock.evaluation_field not in resampling.fields
        ):
            raise ValueError(
                "fixed_rate resampling must declare the evaluation clock as adapter-derived"
            )
        for field in sorted(temporal_derived_fields):
            declaration = provenance.get(field)
            if declaration is None or declaration.layer != "adapter_derived_fact":
                raise ValueError(
                    f"temporal operation on {field} requires adapter_derived_fact provenance"
                )
        annotation_keys = [
            f"{item.name}:{item.source_field}" for item in self.source_annotations.annotations
        ]
        _unique(annotation_keys, label="source annotation inventory entry")
        annotation_sources = {
            (artifact_id, annotation.source_field)
            for annotation in self.source_annotations.annotations
            for artifact_id in annotation.source_artifact_ids
        }
        semantic_sources = {
            (artifact_id, source_field)
            for declaration in self.field_provenance
            for artifact_id in declaration.source_artifact_ids
            for source_field in declaration.source_fields
        }
        prohibited_overlap = sorted(annotation_sources & semantic_sources)
        if prohibited_overlap:
            formatted = ", ".join(
                f"{artifact_id}:{source_field}" for artifact_id, source_field in prohibited_overlap
            )
            raise ValueError(
                "source annotations cannot feed normalized Atlas semantic fields: " + formatted
            )
        return self


class DomainPackFiles(ContractModel):
    domain_pack_id: NonBlankString
    rationale: NonBlankString
    rule_origin: Literal["operator_configured_rules"]
    source_annotations_used: Literal[False]
    assets: FileReference
    workspace: FileReference
    process: FileReference
    contracts: FileReference
    work_orders: FileReference


class SessionReference(FileReference):
    frame_count: int = Field(gt=0)
    frame_state_model_version: Literal["1.0"]


class ExpectedOutcomeReference(FileReference):
    role: Literal["test_metadata_only"]
    atlas_input: Literal[False]


class NormalizedArtifacts(ContractModel):
    session: SessionReference
    normalization_report: FileReference
    expected_outcome: ExpectedOutcomeReference
    checksums_path: SafeRelativePath


class EvaluationDeclaration(ContractModel):
    engine: Literal["atlas"]
    metriplane_version: NonBlankString
    domain_pack_id: NonBlankString
    provenance_layer: Literal["metriplane_derived_results"]
    expected_outcome_is_input: Literal[False]

    @field_validator("metriplane_version")
    @classmethod
    def _exact_version(cls, value: str) -> str:
        if _METRIPLANE_VERSION.fullmatch(value) is None:
            raise ValueError("metriplane_version must be an exact semantic version")
        return value


class TrustLayerPolicy(ContractModel):
    source_facts: Literal["source.artifacts_and_field_provenance"]
    adapter_derived_facts: Literal["adapter_and_normalization"]
    operator_configured_rules: Literal["domain_pack_only"]
    metriplane_derived_results: Literal["atlas_outputs_only"]
    source_annotations_can_drive_incidents: Literal[False]
    expected_outcome_is_atlas_input: Literal[False]


class ExternalSourceManifestV1(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        validate_default=True,
        title="Metriplane External Source Contract v1",
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": (
                "https://www.metriplane.com/schemas/"
                "metriplane.external_source_contract.v1.schema.json"
            ),
        },
    )

    schema_version: Literal["metriplane.external_source_contract.v1"]
    contract_profile: Literal["metriplane.atlas.complete_snapshot.v1"]
    fixture: FixtureIdentity
    source_project: SourceProject
    source_artifacts: list[SourceArtifact] = Field(min_length=1)
    selection: SourceSelection
    rights: RightsDeclarations
    adapter: AdapterDeclaration
    normalization: NormalizationDeclaration
    domain_pack: DomainPackFiles
    normalized_artifacts: NormalizedArtifacts
    evaluation: EvaluationDeclaration
    trust_layers: TrustLayerPolicy
    limitations: list[NonBlankString] = Field(min_length=1)
    extensions: dict[NamespacedKey, JsonValue] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": False},
    )

    @model_validator(mode="after")
    def _cross_references_are_safe(self) -> ExternalSourceManifestV1:
        artifact_ids = [artifact.artifact_id for artifact in self.source_artifacts]
        _unique(artifact_ids, label="source artifact id")
        known_artifacts = set(artifact_ids)
        selected_artifacts = set(self.selection.artifact_ids)
        for artifact_id in self.selection.artifact_ids:
            if artifact_id not in known_artifacts:
                raise ValueError(f"selection references unknown source artifact: {artifact_id}")
        for declaration in self.normalization.field_provenance:
            for artifact_id in declaration.source_artifact_ids:
                if artifact_id not in known_artifacts:
                    raise ValueError(
                        f"field provenance references unknown source artifact: {artifact_id}"
                    )
                if artifact_id not in selected_artifacts:
                    raise ValueError(
                        f"field provenance references unselected source artifact: {artifact_id}"
                    )
        for annotation in self.normalization.source_annotations.annotations:
            for artifact_id in annotation.source_artifact_ids:
                if artifact_id not in known_artifacts:
                    raise ValueError(
                        f"source annotation references unknown source artifact: {artifact_id}"
                    )
                if artifact_id not in selected_artifacts:
                    raise ValueError(
                        f"source annotation references unselected source artifact: {artifact_id}"
                    )
            if annotation.retained_in == "manifest_extension":
                assert annotation.retained_reference is not None
                try:
                    _resolve_json_pointer(
                        {"extensions": self.extensions},
                        annotation.retained_reference,
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"source annotation {annotation.name!r} has unresolved "
                        f"retained_reference: {exc}"
                    ) from exc

        source_rights = {
            rights_declaration.rights_id: rights_declaration
            for rights_declaration in self.rights.source_artifacts
        }
        referenced_rights: set[str] = set()
        for artifact in self.source_artifacts:
            rights_declaration = source_rights.get(artifact.rights_id)
            if rights_declaration is None:
                raise ValueError(
                    f"source artifact {artifact.artifact_id} references unknown rights_id: "
                    f"{artifact.rights_id}"
                )
            referenced_rights.add(artifact.rights_id)
            if artifact.presence == "included":
                if self.fixture.distribution in ("reference_only", "derived_only"):
                    raise ValueError(
                        f"{self.fixture.distribution} fixture must not include source artifact "
                        f"{artifact.artifact_id}"
                    )
                if rights_declaration.source_use_permission == "unresolved":
                    raise ValueError(
                        f"included source artifact {artifact.artifact_id} requires resolved "
                        "source-use permission"
                    )
                allowed_publicly = rights_declaration.redistribution == "allowed"
                allowed_with_permission = (
                    rights_declaration.redistribution == "permission_required"
                    and rights_declaration.redistribution_permission == "verified"
                )
                allowed_privately = (
                    rights_declaration.redistribution == "private"
                    and self.fixture.distribution == "private"
                    and self.rights.fixture.access == "private"
                    and rights_declaration.source_use_permission == "verified"
                    and rights_declaration.redistribution_permission == "verified"
                )
                if not (allowed_publicly or allowed_with_permission or allowed_privately):
                    raise ValueError(
                        f"included source artifact {artifact.artifact_id} lacks an explicit "
                        "redistribution permission compatible with this fixture"
                    )
        unused_rights = sorted(set(source_rights) - referenced_rights)
        if unused_rights:
            raise ValueError(
                "source rights declarations are not referenced by an artifact: "
                + ", ".join(unused_rights)
            )
        if self.fixture.distribution == "public":
            fixture_rights = self.rights.fixture
            if fixture_rights.access != "public":
                raise ValueError("public fixture requires fixture rights access=public")
            if fixture_rights.license.status == "unknown":
                raise ValueError("public fixture requires a resolved fixture license")
            if fixture_rights.redistribution != "allowed":
                raise ValueError("public fixture requires allowed fixture redistribution")
            for rights_declaration in source_rights.values():
                if rights_declaration.license.status == "unknown":
                    raise ValueError(
                        "public fixture requires resolved source license: "
                        f"{rights_declaration.rights_id}"
                    )
                if rights_declaration.source_use_permission == "unresolved":
                    raise ValueError(
                        "public fixture requires resolved source-use permission: "
                        f"{rights_declaration.rights_id}"
                    )
        if self.fixture.distribution == "private":
            if self.rights.fixture.access != "private":
                raise ValueError("private fixture requires fixture rights access=private")
            if self.rights.fixture.redistribution != "private":
                raise ValueError("private fixture requires fixture redistribution=private")
        if (
            self.fixture.distribution == "proprietary"
            and self.rights.fixture.access != "proprietary"
        ):
            raise ValueError("proprietary fixture requires fixture rights access=proprietary")

        if self.normalization.atlas_asset_mapping != self.domain_pack.assets:
            raise ValueError(
                "normalized-object to Atlas-asset mapping must reference domain_pack.assets"
            )
        if self.normalization.zone_assignment.definitions != self.domain_pack.workspace:
            raise ValueError("zone assignment definitions must reference domain_pack.workspace")
        if self.evaluation.domain_pack_id != self.domain_pack.domain_pack_id:
            raise ValueError("evaluation domain_pack_id must match domain_pack.domain_pack_id")
        if self.normalized_artifacts.checksums_path != "CHECKSUMS.sha256":
            raise ValueError("v1 bundle checksum inventory must be CHECKSUMS.sha256")
        included_source_paths = {
            artifact.path
            for artifact in self.source_artifacts
            if artifact.presence == "included" and artifact.path is not None
        }
        operator_or_mapping_paths = {
            self.domain_pack.assets.path,
            self.domain_pack.workspace.path,
            self.domain_pack.process.path,
            self.domain_pack.contracts.path,
            self.domain_pack.work_orders.path,
            self.normalization.entity_mapping.path,
        }
        collapsed_trust_paths = sorted(included_source_paths & operator_or_mapping_paths)
        if collapsed_trust_paths:
            raise ValueError(
                "included source facts cannot reuse operator-rule or entity-mapping paths: "
                + ", ".join(collapsed_trust_paths)
            )
        protected_outputs = {
            self.normalized_artifacts.session.path: "normalized session",
            self.normalized_artifacts.normalization_report.path: "normalization report",
            self.normalized_artifacts.expected_outcome.path: "expected outcome",
        }
        if len(protected_outputs) != 3:
            raise ValueError(
                "normalized session, normalization report, and expected outcome paths "
                "must be distinct"
            )
        roles_by_path: dict[str, list[str]] = {}
        for label, reference in _manifest_file_references(self):
            roles_by_path.setdefault(reference.path, []).append(label)
        for path, permitted_label in protected_outputs.items():
            conflicting_roles = sorted(
                label for label in roles_by_path.get(path, []) if label != permitted_label
            )
            if conflicting_roles:
                raise ValueError(
                    f"{permitted_label} path {path!r} cannot also serve as conversion/input "
                    f"roles: {', '.join(conflicting_roles)}"
                )
        mapping_path = self.normalization.entity_mapping.path
        permitted_mapping_roles = {
            "entity mapping",
            (
                "field provenance parameters for "
                f"{self.normalization.authoritative_object_collection}[*].id"
            ),
        }
        conflicting_mapping_roles = sorted(
            label
            for label in roles_by_path.get(mapping_path, [])
            if label not in permitted_mapping_roles
        )
        if conflicting_mapping_roles:
            raise ValueError(
                f"generated entity-mapping path {mapping_path!r} cannot also serve as a "
                "Stage 1 input role: " + ", ".join(conflicting_mapping_roles)
            )
        for namespace, value in self.extensions.items():
            if namespace.startswith("metriplane."):
                raise ValueError("extensions must not use the reserved metriplane namespace")
            _reject_reserved_extension_keys(value, path=f"extensions.{namespace}")
        return self


class SourceEntityReference(ContractModel):
    source_artifact_id: NonBlankString
    source_entity_id: NonBlankString


class EntityFusionDeclaration(ContractModel):
    method: Literal["exact_identity", "priority", "weighted", "documented_algorithm"]
    implementation: NonBlankString
    parameters: FileReference


class EntityMappingEntry(ContractModel):
    source_entities: list[SourceEntityReference] = Field(min_length=1)
    normalized_object_id: NonBlankString
    atlas_asset_id: NonBlankString
    process_relevant: bool
    description: NonBlankString
    fusion: EntityFusionDeclaration | None = None

    @model_validator(mode="after")
    def _fusion_is_explicit(self) -> EntityMappingEntry:
        source_keys = [
            f"{source.source_artifact_id}\0{source.source_entity_id}"
            for source in self.source_entities
        ]
        _unique(source_keys, label="source entity identity within mapping")
        if len(self.source_entities) > 1 and self.fusion is None:
            raise ValueError("many-to-one entity mapping requires a fusion declaration")
        if len(self.source_entities) == 1 and self.fusion is not None:
            raise ValueError("single-source entity mapping cannot declare fusion")
        return self


class EntityMappingDocument(ContractModel):
    schema_version: Literal["metriplane.external_entity_mapping.v1"]
    mappings: list[EntityMappingEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _mappings_are_one_to_one(self) -> EntityMappingDocument:
        source_keys = [
            f"{source.source_artifact_id}\0{source.source_entity_id}"
            for item in self.mappings
            for source in item.source_entities
        ]
        _unique(
            source_keys,
            label="source artifact/entity identity",
        )
        _unique(
            [item.normalized_object_id for item in self.mappings],
            label="normalized object id",
        )
        _unique([item.atlas_asset_id for item in self.mappings], label="Atlas asset id")
        return self


class ConversionRunResult(ContractModel):
    run_id: NonBlankString
    artifacts: dict[SafeRelativePath, Sha256] = Field(min_length=1)


class ConversionReproducibility(ContractModel):
    input_fingerprint_sha256: Sha256
    comparison_policy: Literal["sha256_byte_identity"]
    status: Literal["demonstrated", "not_demonstrated"]
    equivalent: bool
    runs: list[ConversionRunResult] = Field(min_length=1)

    @model_validator(mode="after")
    def _demonstrated_requires_two_runs(self) -> ConversionReproducibility:
        _unique([run.run_id for run in self.runs], label="conversion run id")
        run_artifacts = [run.artifacts for run in self.runs]
        actual_equivalence = len(run_artifacts) >= 2 and all(
            result == run_artifacts[0] for result in run_artifacts[1:]
        )
        if self.equivalent != actual_equivalence:
            raise ValueError("conversion equivalent flag does not match per-run artifact hashes")
        if self.status == "demonstrated" and (len(self.runs) < 2 or not self.equivalent):
            raise ValueError(
                "demonstrated conversion reproducibility requires at least two equivalent runs"
            )
        if self.status == "not_demonstrated" and self.equivalent:
            raise ValueError("not_demonstrated conversion reproducibility cannot claim equivalence")
        return self


class NormalizationOperation(ContractModel):
    operation_id: NonBlankString
    kind: Literal[
        "time_mapping",
        "entity_mapping",
        "coordinate_transform",
        "projection",
        "zone_assignment",
        "partial_update_materialization",
        "synchronization",
        "resampling",
        "interpolation",
        "carry_forward",
    ]
    applied: bool
    declaration_path: NonBlankString
    summary: NonBlankString


class NormalizationReport(ContractModel):
    schema_version: Literal["metriplane.external_normalization_report.v1"]
    fixture_id: NonBlankString
    contract_schema_version: Literal["metriplane.external_source_contract.v1"]
    result: Literal["pass"]
    source_record_count: int = Field(ge=0)
    normalized_frame_count: int = Field(gt=0)
    process_relevant_entity_count: int = Field(gt=0)
    omitted_process_relevant_observations: Literal[0]
    unknown_process_relevant_observations: Literal[0]
    operations: list[NormalizationOperation] = Field(min_length=1)
    conversion_reproducibility: ConversionReproducibility
    warnings: list[NonBlankString]
    limitations: list[NonBlankString] = Field(min_length=1)

    @model_validator(mode="after")
    def _operation_inventory_is_unique(self) -> NormalizationReport:
        _unique(
            [operation.operation_id for operation in self.operations],
            label="normalization operation id",
        )
        _unique(
            [operation.kind for operation in self.operations],
            label="normalization operation kind",
        )
        return self


class ExpectedOutcome(ContractModel):
    schema_version: Literal["metriplane.external_expected_outcome.v1"]
    role: Literal["test_metadata_only"]
    atlas_input: Literal[False]
    fixture_id: NonBlankString
    frame_count: int = Field(gt=0)
    event_count: int = Field(ge=0)
    deviation_count: int = Field(ge=0)
    incident_count: int = Field(ge=0)
    event_types: list[NonBlankString]
    incident_types: list[NonBlankString]
    evidence_bundle_verified: bool
    regression_passed: bool

    @model_validator(mode="after")
    def _type_inventory_matches_counts(self) -> ExpectedOutcome:
        if len(self.event_types) != self.event_count:
            raise ValueError("event_types length must equal event_count")
        if len(self.incident_types) != self.incident_count:
            raise ValueError("incident_types length must equal incident_count")
        return self


@dataclass(frozen=True)
class ValidatedExternalFixture:
    """Validated portable inputs ready for the unchanged Atlas engine."""

    root: Path
    manifest: ExternalSourceManifestV1
    frames: tuple[FrameStateModel, ...]
    domain_pack: DomainPack
    entity_mapping: EntityMappingDocument
    normalization_report: NormalizationReport
    expected_outcome: ExpectedOutcome


def render_external_source_contract_schema() -> str:
    """Render the deterministic checked-in JSON Schema representation."""
    schema = ExternalSourceManifestV1.model_json_schema(
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number is prohibited: {value}")


def _load_json(path: Path, *, label: str) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except Exception as exc:
        raise ValueError(f"invalid {label} at {path}: {exc}") from exc


def load_external_source_manifest(path: str | Path) -> ExternalSourceManifestV1:
    """Load a strict v1 manifest without performing bundle filesystem validation."""
    manifest_path = Path(path)
    try:
        return ExternalSourceManifestV1.model_validate(
            _load_json(manifest_path, label="external source manifest")
        )
    except Exception as exc:
        raise ValueError(f"invalid external source manifest {manifest_path}: {exc}") from exc


def conversion_inputs_sha256(manifest: ExternalSourceManifestV1) -> str:
    """Fingerprint Stage 1 inputs; equality does not itself prove equivalent output."""
    normalization = manifest.normalization.model_dump(mode="json")
    mapping_path = manifest.normalization.entity_mapping.path
    normalization["entity_mapping"].pop("sha256")
    for declaration in normalization["field_provenance"]:
        for reference in declaration["parameter_references"]:
            if reference["path"] == mapping_path:
                reference.pop("sha256")
    payload = {
        "schema_version": manifest.schema_version,
        "contract_profile": manifest.contract_profile,
        "source_project": manifest.source_project.model_dump(mode="json"),
        "source_artifacts": [item.model_dump(mode="json") for item in manifest.source_artifacts],
        "selection": manifest.selection.model_dump(mode="json"),
        "rights": manifest.rights.model_dump(mode="json"),
        "adapter": manifest.adapter.model_dump(mode="json"),
        "normalization": normalization,
    }
    return sha256_text(canonical_json_dumps(payload))


def evaluation_inputs_sha256(manifest: ExternalSourceManifestV1) -> str:
    """Fingerprint Stage 2 inputs separately from source conversion inputs."""
    payload = {
        "contract_profile": manifest.contract_profile,
        "session": manifest.normalized_artifacts.session.model_dump(mode="json"),
        "domain_pack": manifest.domain_pack.model_dump(mode="json"),
        "evaluation": manifest.evaluation.model_dump(mode="json"),
    }
    return sha256_text(canonical_json_dumps(payload))


def _bundle_file(root: Path, relative_path: str, *, label: str) -> Path:
    validate_safe_relative_path(relative_path)
    path = root / relative_path
    current = root
    for part in relative_path.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not be a symlink: {relative_path}")
    if not path.is_file():
        raise ValueError(f"missing {label}: {relative_path}")
    return path


def _verify_checksum_inventory(root: Path, checksum_relative_path: str) -> None:
    checksum_path = _bundle_file(
        root,
        checksum_relative_path,
        label="checksum inventory",
    )
    recorded: dict[str, str] = {}
    order: list[str] = []
    for line_number, line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        match = _CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"malformed checksum entry on line {line_number}")
        digest, relative_path = match.groups()
        validate_safe_relative_path(relative_path)
        if relative_path == checksum_relative_path:
            raise ValueError("CHECKSUMS.sha256 must not checksum itself")
        if relative_path in recorded:
            raise ValueError(f"duplicate checksum entry: {relative_path}")
        recorded[relative_path] = digest
        order.append(relative_path)
    if order != sorted(order):
        raise ValueError("checksum entries must be sorted by path")

    inventory: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"bundle symlink is not allowed: {relative_path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"bundle entry is not a regular file or directory: {relative_path}")
        if relative_path != checksum_relative_path:
            inventory.add(relative_path)
    for relative_path in sorted(inventory - set(recorded)):
        raise ValueError(f"file missing checksum entry: {relative_path}")
    for relative_path in sorted(set(recorded) - inventory):
        raise ValueError(f"checksum references missing file: {relative_path}")
    for relative_path, expected in recorded.items():
        actual = sha256_file(root / relative_path)
        if actual != expected:
            raise ValueError(
                f"checksum mismatch for {relative_path}: expected {expected}, computed {actual}"
            )


def _manifest_file_references(
    manifest: ExternalSourceManifestV1,
) -> list[tuple[str, FileReference]]:
    references: list[tuple[str, FileReference]] = []
    for artifact in manifest.source_artifacts:
        if artifact.presence == "included":
            assert artifact.path is not None and artifact.sha256 is not None
            references.append(
                (
                    f"source artifact {artifact.artifact_id}",
                    FileReference(
                        path=artifact.path,
                        sha256=artifact.sha256,
                        media_type=artifact.media_type,
                    ),
                )
            )
    if manifest.selection.selector is not None:
        references.append(("source selection", manifest.selection.selector))
    if manifest.adapter.parameters.reference is not None:
        references.append(("adapter parameters", manifest.adapter.parameters.reference))
    if manifest.adapter.environment.dependency_lock is not None:
        references.append(("adapter dependency lock", manifest.adapter.environment.dependency_lock))

    normalization = manifest.normalization
    optional_references = (
        ("clock lookup", normalization.clock.lookup),
        ("transform parameters", normalization.coordinates.transform.parameters),
        ("projection parameters", normalization.coordinates.projection.parameters),
        ("zone parameters", normalization.zone_assignment.parameters),
        (
            "partial-update materialization parameters",
            (
                normalization.completeness.materialization.parameters
                if normalization.completeness.materialization is not None
                else None
            ),
        ),
        ("confidence implementation", normalization.confidence.implementation),
        ("confidence parameters", normalization.confidence.parameters),
    )
    references.extend((label, ref) for label, ref in optional_references if ref is not None)
    for declaration in normalization.field_provenance:
        references.extend(
            (
                f"field provenance parameters for {declaration.normalized_field}",
                reference,
            )
            for reference in declaration.parameter_references
        )
    references.extend(
        [
            ("entity mapping", normalization.entity_mapping),
            ("Atlas asset mapping", normalization.atlas_asset_mapping),
            ("zone definitions", normalization.zone_assignment.definitions),
            ("domain-pack assets", manifest.domain_pack.assets),
            ("domain-pack workspace", manifest.domain_pack.workspace),
            ("domain-pack process", manifest.domain_pack.process),
            ("domain-pack contracts", manifest.domain_pack.contracts),
            ("domain-pack work orders", manifest.domain_pack.work_orders),
            ("normalized session", manifest.normalized_artifacts.session),
            ("normalization report", manifest.normalized_artifacts.normalization_report),
            ("expected outcome", manifest.normalized_artifacts.expected_outcome),
        ]
    )
    return references


def _verify_manifest_file_references(root: Path, manifest: ExternalSourceManifestV1) -> None:
    for label, reference in _manifest_file_references(manifest):
        path = _bundle_file(root, reference.path, label=label)
        actual = sha256_file(path)
        if actual != reference.sha256:
            raise ValueError(
                f"{label} sha256 mismatch for {reference.path}: "
                f"expected {reference.sha256}, computed {actual}"
            )


def _strict_object_keys(raw: Any, *, line_number: int, collection: str) -> None:
    if not isinstance(raw, list):
        raise ValueError(  # noqa: TRY004 - invalid fixture content, not API misuse
            f"session line {line_number} {collection} must be a list"
        )
    allowed = set(ObjectStateModel.model_fields)
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(  # noqa: TRY004 - invalid fixture content
                f"session line {line_number} {collection}[{index}] must be an object"
            )
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(
                f"session line {line_number} {collection}[{index}] contains unknown "
                f"ObjectStateModel fields: {', '.join(sorted(unknown))}"
            )
        if item.get("extra") is not None:
            raise ValueError(
                f"session line {line_number} {collection}[{index}].extra is prohibited; "
                "source metadata belongs in namespaced manifest extensions"
            )


def _session_field_paths(raw: dict[str, Any], authoritative: str) -> set[str]:
    paths = {"schema_version", "source_backend", "ts", "frame_id"}
    if raw.get("ts_sim_ns") is not None:
        paths.add("ts_sim_ns")
    prefix = "objects[*]" if authoritative == "objects" else "fused[*]"
    collection = raw.get(authoritative) or []
    for item in collection:
        for field in ("id", "pos_world", "vel_world", "zone", "confidence"):
            if field in item and item[field] is not None:
                paths.add(f"{prefix}.{field}")
    return paths


def _point_on_segment(
    x: float,
    y: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    *,
    tolerance: float = 1e-9,
) -> bool:
    cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
    if abs(cross) > tolerance:
        return False
    dot = (x - ax) * (bx - ax) + (y - ay) * (by - ay)
    if dot < -tolerance:
        return False
    squared_length = (bx - ax) ** 2 + (by - ay) ** 2
    return dot <= squared_length + tolerance


def _point_on_polygon_boundary(
    x: float,
    y: float,
    polygon: list[list[float]],
) -> bool:
    points = [(float(point[0]), float(point[1])) for point in polygon]
    return any(
        _point_on_segment(x, y, ax, ay, bx, by)
        for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1], strict=True)
    )


def _expected_polygon_zone(
    x: float,
    y: float,
    *,
    pack: DomainPack,
    assignment: ZoneAssignment,
) -> str:
    matches: list[str] = []
    for zone in pack.workspace.zones:
        if len(zone.polygon) < 3 or any(
            len(point) != 2 or not all(math.isfinite(float(coordinate)) for coordinate in point)
            for point in zone.polygon
        ):
            raise ValueError(
                "polygon zone assignment requires at least three two-dimensional points "
                f"for {zone.zone_id!r}"
            )
        polygon = [(float(point[0]), float(point[1])) for point in zone.polygon]
        inside = point_in_polygon(x, y, polygon)
        if inside and assignment.boundary_policy == "exclusive":
            inside = not _point_on_polygon_boundary(x, y, zone.polygon)
        if inside:
            matches.append(zone.zone_id)

    if not matches:
        if assignment.outside_workspace_policy == "explicit_label":
            assert assignment.outside_zone_label is not None
            return assignment.outside_zone_label
        raise ValueError(f"position ({x}, {y}) is outside every workspace polygon")
    if len(matches) == 1:
        return matches[0]
    if assignment.overlap_policy == "reject":
        raise ValueError(
            f"position ({x}, {y}) matches overlapping zones: {', '.join(sorted(matches))}"
        )
    for zone_id in assignment.zone_priority:
        if zone_id in matches:
            return zone_id
    raise ValueError(
        "zone priority does not resolve overlapping matches: " + ", ".join(sorted(matches))
    )


def _load_and_validate_session(
    path: Path,
    manifest: ExternalSourceManifestV1,
    mapping: EntityMappingDocument,
    pack: DomainPack,
) -> tuple[FrameStateModel, ...]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    frames: list[FrameStateModel] = []
    declared_fields = {item.normalized_field for item in manifest.normalization.field_provenance}
    observed_fields: set[str] = set()
    previous_time: float | None = None
    authoritative_name = manifest.normalization.authoritative_object_collection
    relevant_ids = {item.normalized_object_id for item in mapping.mappings if item.process_relevant}
    mapped_ids = {item.normalized_object_id for item in mapping.mappings}
    observed_object_ids: set[str] = set()
    workspace_zones = {zone.zone_id for zone in pack.workspace.zones}
    outside_label = manifest.normalization.zone_assignment.outside_zone_label
    assignment = manifest.normalization.zone_assignment
    if outside_label in workspace_zones:
        raise ValueError("outside_zone_label must not collide with a declared workspace zone")
    if (
        assignment.overlap_policy == "priority_order"
        and set(assignment.zone_priority) != workspace_zones
    ):
        raise ValueError("zone_priority must list every workspace zone exactly once")
    confidence_values: list[float] = []
    authoritative_observation_count = 0

    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_nonfinite_json_constant,
            )
        except Exception as exc:
            raise ValueError(f"invalid session JSON on line {line_number}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(  # noqa: TRY004 - invalid fixture content
                f"session line {line_number} must be a JSON object"
            )
        if raw.get("type") == "run_header":
            raise ValueError(
                f"session line {line_number} run header is prohibited; conversion provenance "
                "belongs in source-manifest.json"
            )
        unknown_fields = set(raw) - set(FrameStateModel.model_fields)
        prohibited = unknown_fields & _PROHIBITED_SESSION_ANNOTATIONS
        if prohibited:
            raise ValueError(
                f"session line {line_number} contains prohibited source incident/annotation "
                f"fields: {', '.join(sorted(prohibited))}"
            )
        if unknown_fields:
            raise ValueError(
                f"session line {line_number} contains unknown FrameStateModel fields: "
                f"{', '.join(sorted(unknown_fields))}"
            )
        if raw.get("schema_version") != "1.0":
            raise ValueError(
                f"session line {line_number} must explicitly declare schema_version 1.0"
            )
        if any(raw.get(field) is not None for field in ("run_id", "config_hash", "git_commit")):
            raise ValueError(
                f"session line {line_number} embeds Metriplane evaluation provenance; "
                "conversion and evaluation provenance must remain separate"
            )
        if raw.get("metrics") is not None or raw.get("raw_per_camera") is not None:
            raise ValueError(
                f"session line {line_number} contains profile-external metadata; "
                "use namespaced manifest extensions"
            )
        if raw.get("events", []) != []:
            raise ValueError(
                f"session line {line_number} events must be empty for {CONTRACT_PROFILE}"
            )
        _strict_object_keys(raw.get("objects"), line_number=line_number, collection="objects")
        if raw.get("fused") is not None:
            _strict_object_keys(raw.get("fused"), line_number=line_number, collection="fused")

        if authoritative_name == "objects" and raw.get("fused") is not None:
            raise ValueError(
                f"session line {line_number} declares objects authoritative but also supplies fused"
            )
        if authoritative_name == "fused":
            if raw.get("fused") is None:
                raise ValueError(f"session line {line_number} is missing authoritative fused state")
            if raw.get("objects") != []:
                raise ValueError(
                    f"session line {line_number} must keep non-authoritative objects empty "
                    "when fused is authoritative"
                )

        try:
            frame = FrameStateModel.model_validate(raw)
        except Exception as exc:
            raise ValueError(
                f"invalid FrameStateModel on session line {line_number}: {exc}"
            ) from exc
        if frame.source_backend != manifest.normalization.source_backend:
            raise ValueError(
                f"session line {line_number} source_backend {frame.source_backend!r} does not "
                f"match manifest value {manifest.normalization.source_backend!r}"
            )
        expected_frame_id = len(frames)
        if frame.frame_id != expected_frame_id:
            raise ValueError(
                f"session line {line_number} frame_id must be deterministic and ordered: "
                f"expected {expected_frame_id}, got {frame.frame_id}"
            )
        if manifest.normalization.clock.evaluation_field == "ts_sim_ns":
            if frame.ts_sim_ns is None:
                raise ValueError(
                    f"session line {line_number} is missing declared evaluation clock ts_sim_ns"
                )
            evaluation_time = frame.ts_sim_ns / 1_000_000_000.0
        else:
            if frame.ts_sim_ns is not None:
                raise ValueError(
                    f"session line {line_number} supplies undeclared ts_sim_ns evaluation clock"
                )
            evaluation_time = float(frame.ts)
        if not math.isfinite(evaluation_time) or evaluation_time < 0:
            raise ValueError(f"session line {line_number} has invalid evaluation time")
        if previous_time is not None and evaluation_time <= previous_time:
            raise ValueError(
                f"session line {line_number} evaluation time must be strictly monotonic: "
                f"{evaluation_time} follows {previous_time}"
            )
        clock = manifest.normalization.clock
        if clock.mapping_method == "fixed_step":
            assert clock.fixed_step_ns is not None
            assert clock.fixed_step_origin_ns is not None
            assert frame.ts_sim_ns is not None
            expected_ns = clock.fixed_step_origin_ns + frame.frame_id * clock.fixed_step_ns
            if frame.ts_sim_ns != expected_ns:
                raise ValueError(
                    f"session line {line_number} ts_sim_ns violates fixed_step mapping: "
                    f"expected {expected_ns}, got {frame.ts_sim_ns}"
                )
        if previous_time is not None:
            delta_ns = round((evaluation_time - previous_time) * 1_000_000_000)
            resampling = manifest.normalization.temporal_alignment.resampling
            if resampling.method == "fixed_rate" and delta_ns != resampling.output_period_ns:
                raise ValueError(
                    f"session line {line_number} interval {delta_ns}ns violates fixed-rate "
                    f"period {resampling.output_period_ns}ns"
                )
            if (
                resampling.method == "selected_source_frames"
                and resampling.max_gap_ns is not None
                and delta_ns > resampling.max_gap_ns
            ):
                raise ValueError(
                    f"session line {line_number} interval {delta_ns}ns exceeds selected-frame "
                    f"max_gap_ns {resampling.max_gap_ns}"
                )
        previous_time = evaluation_time

        authoritative = frame.objects if authoritative_name == "objects" else frame.fused
        assert authoritative is not None
        by_id = {item.id: item for item in authoritative}
        unmapped = sorted(set(by_id) - mapped_ids)
        if unmapped:
            raise ValueError(
                f"session line {line_number} contains authoritative objects absent from "
                f"entity-mapping.json: {', '.join(unmapped)}"
            )
        observed_object_ids.update(by_id)
        missing = sorted(relevant_ids - set(by_id))
        if missing:
            raise ValueError(
                f"session line {line_number} omits process-relevant entities under "
                f"complete_snapshot: {', '.join(missing)}"
            )
        for object_id, item in by_id.items():
            if item.pos_world is None or item.zone is None:
                raise ValueError(
                    f"session line {line_number} object {object_id!r} has unknown position or "
                    "zone; unknown state cannot be treated as absence"
                )
            if item.zone not in workspace_zones and item.zone != outside_label:
                raise ValueError(
                    f"session line {line_number} object {object_id!r} references undeclared "
                    f"zone {item.zone!r}"
                )
            assert item.pos_world is not None
            if (
                manifest.normalization.coordinates.projection.output_z_policy == "zero"
                and item.pos_world[2] != 0.0
            ):
                raise ValueError(
                    f"session line {line_number} object {object_id!r} violates projection "
                    "output_z_policy=zero"
                )
            if assignment.method == "polygon":
                expected_zone = _expected_polygon_zone(
                    item.pos_world[0],
                    item.pos_world[1],
                    pack=pack,
                    assignment=assignment,
                )
                if item.zone != expected_zone:
                    raise ValueError(
                        f"session line {line_number} object {object_id!r} zone {item.zone!r} "
                        f"contradicts polygon assignment {expected_zone!r}"
                    )
            authoritative_observation_count += 1
            if item.confidence is not None:
                confidence_values.append(item.confidence)
        observed_fields.update(_session_field_paths(raw, authoritative_name))
        frames.append(frame)

    if not frames:
        raise ValueError(f"no frame records found in normalized session: {path}")
    if len(frames) != manifest.normalized_artifacts.session.frame_count:
        raise ValueError(
            "normalized session frame_count mismatch: manifest declares "
            f"{manifest.normalized_artifacts.session.frame_count}, found {len(frames)}"
        )
    unobserved_mappings = sorted(mapped_ids - observed_object_ids)
    if unobserved_mappings:
        raise ValueError(
            "entity mappings are not observed in the bounded normalized session: "
            + ", ".join(unobserved_mappings)
        )
    undeclared = sorted(observed_fields - declared_fields)
    if undeclared:
        raise ValueError(
            "normalized fields have no source-versus-derived provenance declaration: "
            + ", ".join(undeclared)
        )
    unused_declarations = sorted(declared_fields - observed_fields)
    if unused_declarations:
        raise ValueError(
            "field provenance declarations are not present in the normalized session: "
            + ", ".join(unused_declarations)
        )

    confidence_mode = manifest.normalization.confidence.mode
    if confidence_values and confidence_mode == "absent":
        raise ValueError("normalized confidence is present but confidence policy is absent")
    if confidence_mode != "absent" and len(confidence_values) != authoritative_observation_count:
        raise ValueError(
            f"confidence policy {confidence_mode} requires confidence on every authoritative object"
        )
    return tuple(frames)


def _validate_mapping(
    mapping: EntityMappingDocument,
    manifest: ExternalSourceManifestV1,
    pack: DomainPack,
) -> None:
    artifact_ids = {artifact.artifact_id for artifact in manifest.source_artifacts}
    assets_by_id = pack.assets.by_asset_id()
    process_relevant_assets: set[str] = set()
    expected_types: set[str] = set()
    for step in pack.process.steps:
        process_relevant_assets.update(step.required_assets)
        expected_types.update(step.expected_asset_types)
    process_relevant_assets.update(
        asset.asset_id for asset in pack.assets.assets if asset.asset_type in expected_types
    )

    mapped_relevant: set[str] = set()
    for entry in mapping.mappings:
        for source in entry.source_entities:
            if source.source_artifact_id not in artifact_ids:
                raise ValueError(
                    "entity mapping references unknown source artifact: "
                    f"{source.source_artifact_id}"
                )
            if source.source_artifact_id not in set(manifest.selection.artifact_ids):
                raise ValueError(
                    "entity mapping references unselected source artifact: "
                    f"{source.source_artifact_id}"
                )
        asset = assets_by_id.get(entry.atlas_asset_id)
        if asset is None:
            raise ValueError(
                f"entity mapping references unknown Atlas asset: {entry.atlas_asset_id}"
            )
        if asset.object_id != entry.normalized_object_id:
            source_label = ", ".join(
                f"{source.source_artifact_id}:{source.source_entity_id}"
                for source in entry.source_entities
            )
            raise ValueError(
                f"entity mapping for {source_label!r} maps normalized object "
                f"{entry.normalized_object_id!r}, but assets.yaml maps asset "
                f"{entry.atlas_asset_id!r} from object {asset.object_id!r}"
            )
        if entry.process_relevant:
            mapped_relevant.add(entry.atlas_asset_id)
    missing = sorted(process_relevant_assets - mapped_relevant)
    if missing:
        raise ValueError(
            "process-relevant Atlas assets must have process_relevant entity mappings: "
            + ", ".join(missing)
        )


def _verify_mapping_file_references(
    root: Path,
    mapping: EntityMappingDocument,
    manifest: ExternalSourceManifestV1,
) -> None:
    identity_field = f"{manifest.normalization.authoritative_object_collection}[*].id"
    identity_provenance = next(
        (
            declaration
            for declaration in manifest.normalization.field_provenance
            if declaration.normalized_field == identity_field
        ),
        None,
    )
    declared_identity_parameters = {
        (reference.path, reference.sha256)
        for reference in (
            identity_provenance.parameter_references if identity_provenance is not None else []
        )
    }
    for entry in mapping.mappings:
        if entry.fusion is None:
            continue
        reference = entry.fusion.parameters
        if reference.path == manifest.normalization.entity_mapping.path:
            raise ValueError(
                "entity-fusion parameters cannot reuse the generated entity-mapping output"
            )
        if (reference.path, reference.sha256) not in declared_identity_parameters:
            raise ValueError(
                "entity-fusion parameters must be repeated as a hashed parameter reference "
                f"for {identity_field} so they are included in Stage 1 provenance: "
                f"{reference.path}"
            )
        path = _bundle_file(root, reference.path, label="entity-fusion parameters")
        actual = sha256_file(path)
        if actual != reference.sha256:
            raise ValueError(
                f"entity-fusion parameters sha256 mismatch for {reference.path}: "
                f"expected {reference.sha256}, computed {actual}"
            )


def validate_external_fixture_bundle(root: str | Path) -> ValidatedExternalFixture:
    """Validate one portable bundle without running or modifying Atlas."""
    bundle_root = Path(root)
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise ValueError(f"external fixture root must be a regular directory: {bundle_root}")
    manifest_path = _bundle_file(
        bundle_root,
        "source-manifest.json",
        label="source manifest",
    )
    manifest = load_external_source_manifest(manifest_path)
    _verify_checksum_inventory(bundle_root, manifest.normalized_artifacts.checksums_path)
    _verify_manifest_file_references(bundle_root, manifest)

    pack_roles = {
        "assets": (manifest.domain_pack.assets.path, "assets.yaml"),
        "workspace": (manifest.domain_pack.workspace.path, "workspace.yaml"),
        "process": (manifest.domain_pack.process.path, "process.yaml"),
        "contracts": (manifest.domain_pack.contracts.path, "contracts.yaml"),
        "work_orders": (manifest.domain_pack.work_orders.path, "work_orders.csv"),
    }
    for role, (path, expected_name) in pack_roles.items():
        if Path(path).name != expected_name:
            raise ValueError(
                f"domain_pack.{role}.path must end in Atlas canonical filename "
                f"{expected_name!r}; got {path!r}"
            )
    pack_paths = [path for path, _expected_name in pack_roles.values()]
    pack_parents = {str(Path(path).parent) for path in pack_paths}
    if len(pack_parents) != 1:
        raise ValueError("all domain-pack files must share one directory")
    pack_root = bundle_root / Path(pack_paths[0]).parent
    pack_errors = validate_domain_pack(pack_root)
    if pack_errors:
        raise ValueError("invalid external fixture domain pack:\n- " + "\n- ".join(pack_errors))
    pack = load_domain_pack(pack_root)
    if pack.workspace.units != manifest.normalization.coordinates.target_units:
        raise ValueError(
            "coordinate target_units must match domain-pack workspace units: "
            f"{manifest.normalization.coordinates.target_units!r} != {pack.workspace.units!r}"
        )

    mapping_path = _bundle_file(
        bundle_root,
        manifest.normalization.entity_mapping.path,
        label="entity mapping",
    )
    try:
        mapping = EntityMappingDocument.model_validate(
            _load_json(mapping_path, label="entity mapping")
        )
    except Exception as exc:
        raise ValueError(f"invalid entity mapping {mapping_path}: {exc}") from exc
    _verify_mapping_file_references(bundle_root, mapping, manifest)
    _validate_mapping(mapping, manifest, pack)

    session_path = _bundle_file(
        bundle_root,
        manifest.normalized_artifacts.session.path,
        label="normalized session",
    )
    frames = _load_and_validate_session(session_path, manifest, mapping, pack)

    report_path = _bundle_file(
        bundle_root,
        manifest.normalized_artifacts.normalization_report.path,
        label="normalization report",
    )
    try:
        report = NormalizationReport.model_validate(
            _load_json(report_path, label="normalization report")
        )
    except Exception as exc:
        raise ValueError(f"invalid normalization report {report_path}: {exc}") from exc
    if report.fixture_id != manifest.fixture.fixture_id:
        raise ValueError("normalization report fixture_id does not match manifest")
    if report.normalized_frame_count != len(frames):
        raise ValueError("normalization report normalized_frame_count does not match session")
    relevant_count = sum(item.process_relevant for item in mapping.mappings)
    if report.process_relevant_entity_count != relevant_count:
        raise ValueError(
            "normalization report process_relevant_entity_count does not match entity mapping"
        )
    expected_conversion_fingerprint = conversion_inputs_sha256(manifest)
    if (
        report.conversion_reproducibility.input_fingerprint_sha256
        != expected_conversion_fingerprint
    ):
        raise ValueError(
            "normalization report conversion input fingerprint does not match manifest"
        )
    expected_operation_state: dict[str, tuple[str, bool]] = {
        "time_mapping": ("normalization.clock", True),
        "entity_mapping": ("normalization.entity_mapping", True),
        "coordinate_transform": (
            "normalization.coordinates.transform",
            manifest.normalization.coordinates.transform.method != "identity",
        ),
        "projection": (
            "normalization.coordinates.projection",
            manifest.normalization.coordinates.projection.method != "identity_3d",
        ),
        "zone_assignment": ("normalization.zone_assignment", True),
        "synchronization": (
            "normalization.temporal_alignment.synchronization",
            manifest.normalization.temporal_alignment.synchronization.method != "not_applicable",
        ),
        "resampling": (
            "normalization.temporal_alignment.resampling",
            manifest.normalization.temporal_alignment.resampling.method != "none",
        ),
        "interpolation": (
            "normalization.temporal_alignment.interpolation",
            manifest.normalization.temporal_alignment.interpolation.method != "none",
        ),
        "carry_forward": (
            "normalization.completeness.carry_forward",
            manifest.normalization.completeness.carry_forward.method != "none",
        ),
    }
    if manifest.normalization.completeness.materialization is not None:
        expected_operation_state["partial_update_materialization"] = (
            "normalization.completeness.materialization",
            True,
        )
    operations_by_kind: dict[str, NormalizationOperation] = {
        operation.kind: operation for operation in report.operations
    }
    if set(operations_by_kind) != set(expected_operation_state):
        missing = sorted(set(expected_operation_state) - set(operations_by_kind))
        extra = sorted(set(operations_by_kind) - set(expected_operation_state))
        raise ValueError(
            f"normalization report operation coverage mismatch; missing={missing}, extra={extra}"
        )
    for kind, (expected_declaration_path, expected_applied) in expected_operation_state.items():
        operation = operations_by_kind[kind]
        if operation.declaration_path != expected_declaration_path:
            raise ValueError(
                f"normalization operation {kind} must reference {expected_declaration_path!r}"
            )
        if operation.applied is not expected_applied:
            raise ValueError(
                f"normalization operation {kind} applied={operation.applied} contradicts "
                f"the manifest policy (expected {expected_applied})"
            )

    session_output = manifest.normalized_artifacts.session
    mapping_output = manifest.normalization.entity_mapping
    required_conversion_outputs = {session_output.path, mapping_output.path}
    for conversion_run in report.conversion_reproducibility.runs:
        declared_conversion_outputs = set(conversion_run.artifacts)
        if declared_conversion_outputs != required_conversion_outputs:
            missing = sorted(required_conversion_outputs - declared_conversion_outputs)
            extra = sorted(declared_conversion_outputs - required_conversion_outputs)
            raise ValueError(
                f"conversion run {conversion_run.run_id} must contain exactly the Stage 1 "
                f"session and entity-mapping outputs; missing={missing}, extra={extra}"
            )
        if conversion_run.artifacts.get(session_output.path) != session_output.sha256:
            raise ValueError(
                f"conversion run {conversion_run.run_id} omits normalized session hash: "
                f"{session_output.path}"
            )
        if conversion_run.artifacts.get(mapping_output.path) != mapping_output.sha256:
            raise ValueError(
                f"conversion run {conversion_run.run_id} omits entity-mapping hash: "
                f"{mapping_output.path}"
            )
        for path, digest in conversion_run.artifacts.items():
            artifact_path = _bundle_file(
                bundle_root,
                path,
                label=f"conversion run {conversion_run.run_id} output",
            )
            actual = sha256_file(artifact_path)
            if actual != digest:
                raise ValueError(
                    f"conversion run {conversion_run.run_id} output hash mismatch for {path}: "
                    f"expected {digest}, computed {actual}"
                )

    expected_outcome_path = _bundle_file(
        bundle_root,
        manifest.normalized_artifacts.expected_outcome.path,
        label="expected outcome test metadata",
    )
    try:
        expected = ExpectedOutcome.model_validate(
            _load_json(expected_outcome_path, label="expected outcome test metadata")
        )
    except Exception as exc:
        raise ValueError(f"invalid expected outcome {expected_outcome_path}: {exc}") from exc
    if expected.fixture_id != manifest.fixture.fixture_id:
        raise ValueError("expected outcome fixture_id does not match manifest")
    if expected.frame_count != len(frames):
        raise ValueError("expected outcome frame_count does not match normalized session")

    return ValidatedExternalFixture(
        root=bundle_root,
        manifest=manifest,
        frames=frames,
        domain_pack=pack,
        entity_mapping=mapping,
        normalization_report=report,
        expected_outcome=expected,
    )
