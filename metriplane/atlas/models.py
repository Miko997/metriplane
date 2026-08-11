# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ASSET_REGISTRY_SCHEMA = "metriplane.atlas.asset_registry.v1"
WORKSPACE_SCHEMA = "metriplane.atlas.workspace.v1"
PROCESS_MODEL_SCHEMA = "metriplane.atlas.process_model.v1"
WORK_ORDER_SCHEMA = "metriplane.atlas.work_order.v1"
EVENT_SCHEMA = "metriplane.atlas.event.v1"
DEVIATION_SCHEMA = "metriplane.atlas.deviation.v1"
INCIDENT_SCHEMA = "metriplane.atlas.incident.v1"
REALITY_GRAPH_SCHEMA = "metriplane.atlas.reality_graph.v1"
EVIDENCE_BUNDLE_SCHEMA = "metriplane.atlas.evidence_bundle.v1"
REGRESSION_TEST_SCHEMA = "metriplane.atlas.regression_test.v1"
TRAINING_CASE_SCHEMA = "metriplane.atlas.training_case.v1"
IMPROVEMENT_ACTION_SCHEMA = "metriplane.atlas.improvement_action.v1"
RUN_MANIFEST_SCHEMA = "metriplane.atlas.run_manifest.v1"
EXTERNAL_SOURCE_PROVENANCE_REFERENCE_SCHEMA: Final = (
    "metriplane.atlas.external_source_provenance_reference.v1"
)
EXTERNAL_SOURCE_PROVENANCE_SCHEMA: Final = "metriplane.external_source_provenance.v1"
EXTERNAL_SOURCE_PROVENANCE_RUN_PATH: Final = "external_source_provenance.json"
EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH: Final = (
    "provenance/external_source_provenance.json"
)

ATLAS_LIMITATIONS = [
    "planar_xy_state",
    "tracked_or_tagged_assets_required",
    "not_certified_safety_or_quality_decision_system",
]


class AssetModel(BaseModel):
    object_id: str
    asset_id: str
    asset_type: str
    label: str
    work_order_id: str | None = None
    material_id: str | None = None
    tool_id: str | None = None
    expected_zones: list[str] = Field(default_factory=list)
    expected_stations: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class AssetRegistryModel(BaseModel):
    schema_version: Literal["metriplane.atlas.asset_registry.v1"] = ASSET_REGISTRY_SCHEMA
    assets: list[AssetModel]

    def by_object_id(self) -> dict[str, AssetModel]:
        return {asset.object_id: asset for asset in self.assets}

    def by_asset_id(self) -> dict[str, AssetModel]:
        return {asset.asset_id: asset for asset in self.assets}


class ZoneModel(BaseModel):
    zone_id: str
    zone_type: str
    polygon: list[list[float]] = Field(default_factory=list)
    label: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class StationModel(BaseModel):
    station_id: str
    zone_id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class WorkspaceModel(BaseModel):
    schema_version: Literal["metriplane.atlas.workspace.v1"] = WORKSPACE_SCHEMA
    cell_id: str
    units: str = "meters"
    zones: list[ZoneModel] = Field(default_factory=list)
    stations: list[StationModel] = Field(default_factory=list)

    def station_by_zone(self) -> dict[str, StationModel]:
        return {station.zone_id: station for station in self.stations}


class ProcessStepModel(BaseModel):
    step_id: str
    label: str
    expected_asset_types: list[str] = Field(default_factory=list)
    required_assets: list[str] = Field(default_factory=list)
    required_zone: str | None = None
    required_station: str | None = None
    max_wait_s: float | None = None
    quality_requires_material_ids: list[str] = Field(default_factory=list)


class ProcessModel(BaseModel):
    schema_version: Literal["metriplane.atlas.process_model.v1"] = PROCESS_MODEL_SCHEMA
    process_id: str
    work_order_type: str = "demo"
    steps: list[ProcessStepModel]


class WorkOrderModel(BaseModel):
    schema_version: Literal["metriplane.atlas.work_order.v1"] = WORK_ORDER_SCHEMA
    work_order_id: str
    process_id: str
    product: str | None = None
    planned_start: str | None = None
    planned_end: str | None = None
    priority: str | None = None


class AtlasEvent(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    schema_version: Literal["metriplane.atlas.event.v1"] = EVENT_SCHEMA
    event_id: str
    run_id: str
    ts: float
    frame_id: int = Field(strict=True, ge=0)
    event_type: str
    severity: Literal["info", "warning", "critical"] = "info"
    message: str
    asset_id: str | None = None
    asset_type: str | None = None
    work_order_id: str | None = None
    process_step_id: str | None = None
    zone_id: str | None = None
    station_id: str | None = None
    value: float | str | None = None
    threshold: float | str | None = None
    evidence: list[str] = Field(default_factory=list)


class AtlasDeviation(BaseModel):
    schema_version: Literal["metriplane.atlas.deviation.v1"] = DEVIATION_SCHEMA
    deviation_id: str
    type: str
    severity: Literal["info", "warning", "critical"] = "warning"
    work_order_id: str | None = None
    process_step_id: str | None = None
    asset_id: str | None = None
    duration_s: float | None = None
    event_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=lambda: list(ATLAS_LIMITATIONS))


class AtlasIncident(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    schema_version: Literal["metriplane.atlas.incident.v1"] = INCIDENT_SCHEMA
    incident_id: str
    incident_type: str
    severity: Literal["info", "warning", "critical"] = "warning"
    title: str
    start_ts: float
    end_ts: float
    asset_ids: list[str] = Field(default_factory=list)
    work_order_id: str | None = None
    event_ids: list[str] = Field(default_factory=list)
    summary: str
    limitations: list[str] = Field(default_factory=lambda: list(ATLAS_LIMITATIONS))

    @model_validator(mode="after")
    def _ordered_times(self):
        if self.end_ts < self.start_ts:
            raise ValueError("incident end_ts must be greater than or equal to start_ts")
        return self


class Entity(BaseModel):
    id: str
    type: str
    label: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    type: str
    source_id: str
    target_id: str
    ts_start: float | None = None
    ts_end: float | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class RealityGraphExport(BaseModel):
    schema_version: Literal["metriplane.atlas.reality_graph.v1"] = REALITY_GRAPH_SCHEMA
    graph_id: str
    run_id: str
    entities: list[Entity]
    edges: list[Edge]
    limitations: list[str] = Field(default_factory=lambda: list(ATLAS_LIMITATIONS))


class FlowMetrics(BaseModel):
    schema_version: str = "metriplane.atlas.flow_metrics.v1"
    run_id: str
    observed_duration_s: float
    event_count: int
    incident_count: int
    station_occupancy_s: dict[str, float] = Field(default_factory=dict)
    wait_time_s: dict[str, float] = Field(default_factory=dict)
    bottlenecks: list[str] = Field(default_factory=list)


class ImprovementAction(BaseModel):
    schema_version: Literal["metriplane.atlas.improvement_action.v1"] = IMPROVEMENT_ACTION_SCHEMA
    action_id: str
    action_type: str
    title: str
    rationale: str
    cited_event_ids: list[str] = Field(default_factory=list)
    cited_incident_ids: list[str] = Field(default_factory=list)
    caveat: str = (
        "Recommendation is derived from replay evidence and is not a guaranteed causal fix "
        "without before/after validation."
    )


class ExternalSourceProvenanceReference(BaseModel):
    """Compact reference to the full external-source provenance artifact."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        strict=True,
        validate_default=True,
    )

    schema_version: Literal[
        "metriplane.atlas.external_source_provenance_reference.v1"
    ] = EXTERNAL_SOURCE_PROVENANCE_REFERENCE_SCHEMA
    path: Literal[
        "external_source_provenance.json",
        "provenance/external_source_provenance.json",
    ]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_id: str
    contract_schema_version: str
    contract_profile: str
    source_project: str
    source_revision: str
    adapter_id: str
    adapter_version: str
    adapter_commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

    @field_validator(
        "fixture_id",
        "contract_schema_version",
        "contract_profile",
        "source_project",
        "source_revision",
        "adapter_id",
        "adapter_version",
    )
    @classmethod
    def _identity_is_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("external source provenance identity must not be blank")
        return value


def _required_provenance_mapping(
    value: object,
    *,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004 - invalid persisted content
            f"external source provenance {field} must be an object"
        )
    return value


def _required_provenance_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"external source provenance {field} must be a nonblank string"
        )
    return value


def external_source_provenance_reference(
    provenance: dict[str, Any],
    *,
    path: Literal[
        "external_source_provenance.json",
        "provenance/external_source_provenance.json",
    ],
    sha256: str,
) -> ExternalSourceProvenanceReference:
    """Build the compact Atlas reference from a validated provenance document."""

    provenance_schema_version = _required_provenance_string(
        provenance.get("schema_version"),
        field="schema_version",
    )
    if provenance_schema_version != EXTERNAL_SOURCE_PROVENANCE_SCHEMA:
        raise ValueError(
            "unsupported external source provenance schema_version: "
            f"{provenance_schema_version!r}"
        )
    source_project = _required_provenance_mapping(
        provenance.get("source_project"),
        field="source_project",
    )
    revision = source_project.get("revision")
    if isinstance(revision, dict):
        revision_value = _required_provenance_string(
            revision.get("value"),
            field="source_project.revision.value",
        )
        revision_kind = revision.get("kind")
        if revision_kind is None:
            source_revision = revision_value
        else:
            source_revision = (
                f"{_required_provenance_string(revision_kind, field='source_project.revision.kind')}:"
                f"{revision_value}"
            )
    else:
        source_revision = _required_provenance_string(
            revision,
            field="source_project.revision",
        )

    adapter = _required_provenance_mapping(
        provenance.get("adapter"),
        field="adapter",
    )
    return ExternalSourceProvenanceReference(
        path=path,
        sha256=sha256,
        fixture_id=_required_provenance_string(
            provenance.get("fixture_id"),
            field="fixture_id",
        ),
        contract_schema_version=_required_provenance_string(
            provenance.get("contract_schema_version"),
            field="contract_schema_version",
        ),
        contract_profile=_required_provenance_string(
            provenance.get("contract_profile"),
            field="contract_profile",
        ),
        source_project=_required_provenance_string(
            source_project.get("name"),
            field="source_project.name",
        ),
        source_revision=source_revision,
        adapter_id=_required_provenance_string(
            adapter.get("adapter_id"),
            field="adapter.adapter_id",
        ),
        adapter_version=_required_provenance_string(
            adapter.get("version"),
            field="adapter.version",
        ),
        adapter_commit=_required_provenance_string(
            adapter.get("commit"),
            field="adapter.commit",
        ),
    )


class BundleManifest(BaseModel):
    schema_version: Literal["metriplane.atlas.evidence_bundle.v1"] = EVIDENCE_BUNDLE_SCHEMA
    bundle_id: str
    incident_id: str
    run_id: str
    required_files: list[str]
    limitations: list[str] = Field(default_factory=lambda: list(ATLAS_LIMITATIONS))
    external_source_provenance: ExternalSourceProvenanceReference | None = None


class RegressionSpec(BaseModel):
    schema_version: Literal["metriplane.atlas.regression_test.v1"] = REGRESSION_TEST_SCHEMA
    test_id: str
    source_bundle: str
    expected_events: list[dict[str, Any]] = Field(default_factory=list)
    expected_incidents: list[dict[str, Any]] = Field(default_factory=list)
    tolerances: dict[str, float] = Field(default_factory=lambda: {
        "event_time_s": 0.5,
        "duration_s": 1.0,
    })


class TrainingCase(BaseModel):
    schema_version: Literal["metriplane.atlas.training_case.v1"] = TRAINING_CASE_SCHEMA
    training_case_id: str
    title: str
    what_happened: str
    why_it_matters: str
    evidence_links: list[str]
    what_to_do_next: list[str]
    quiz_questions: list[dict[str, str]]
    limitations: list[str] = Field(default_factory=lambda: list(ATLAS_LIMITATIONS))


class AtlasRunManifest(BaseModel):
    schema_version: Literal["metriplane.atlas.run_manifest.v1"] = RUN_MANIFEST_SCHEMA
    run_id: str
    source_session_jsonl: str
    domain_pack: str
    cell_id: str
    frame_count: int
    event_count: int
    deviation_count: int
    incident_count: int
    artifacts: dict[str, str]
    limitations: list[str] = Field(default_factory=lambda: list(ATLAS_LIMITATIONS))
    external_source_provenance: ExternalSourceProvenanceReference | None = None
