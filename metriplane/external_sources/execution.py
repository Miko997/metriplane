# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate and execute portable external fixtures through the Atlas engine."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from metriplane import __version__
from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.atlas.runtime import run_atlas
from metriplane.external_sources.contract import (
    AdapterDeclaration,
    ConversionReproducibility,
    DomainPackFiles,
    EntityMappingReference,
    ExternalSourceManifestV1,
    FileReference,
    NormalizationDeclaration,
    RightsDeclarations,
    SessionReference,
    SourceArtifact,
    SourceProject,
    SourceSelection,
    ValidatedExternalFixture,
    conversion_inputs_sha256,
    evaluation_inputs_sha256,
    validate_external_fixture_bundle,
)
from metriplane.provenance.run_provenance import sha256_file
from metriplane.schema import frame_time_s

VALIDATION_SUMMARY_SCHEMA_VERSION: Final = "metriplane.external_validation_summary.v1"
RUN_SUMMARY_SCHEMA_VERSION: Final = "metriplane.external_run_summary.v1"
EXTERNAL_PROVENANCE_SCHEMA_VERSION: Final = "metriplane.external_source_provenance.v1"

_EXPECTED_INPUT_ERRORS = (ValueError, OSError, UnicodeError)
_SAFE_OPERATIONAL_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class _ExecutionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        populate_by_name=True,
    )


class ValidationCheck(_ExecutionModel):
    check_id: str
    passed: bool = Field(
        validation_alias=AliasChoices("passed", "pass"),
        serialization_alias="pass",
    )
    detail: str


class SourceRevisionSummary(_ExecutionModel):
    kind: str
    value: str


class SourceIdentitySummary(_ExecutionModel):
    artifact_id: str
    role: str
    presence: str
    sha256: str | None = None
    immutable_identifier: str | None = None
    path: str | None = None
    uri: str | None = None


class AdapterIdentitySummary(_ExecutionModel):
    adapter_id: str
    name: str
    version: str
    commit: str
    parameters_sha256: str
    environment: str


class ExternalValidationSummary(_ExecutionModel):
    """Stable machine-readable result for external fixture preflight."""

    schema_version: Literal["metriplane.external_validation_summary.v1"] = (
        VALIDATION_SUMMARY_SCHEMA_VERSION
    )
    passed: bool = Field(
        validation_alias=AliasChoices("passed", "pass"),
        serialization_alias="pass",
    )
    fixture_root: str
    fixture_id: str | None = None
    contract_schema_version: str | None = None
    contract_profile: str | None = None
    manifest_sha256: str | None = None
    session_sha256: str | None = None
    domain_pack_file_hashes: dict[str, str] = Field(default_factory=dict)
    entity_mapping_sha256: str | None = None
    normalization_report_sha256: str | None = None
    source_identities: list[SourceIdentitySummary] = Field(default_factory=list)
    source_revision: SourceRevisionSummary | None = None
    adapter_identity: AdapterIdentitySummary | None = None
    metriplane_version: str
    declared_metriplane_version: str | None = None
    frame_state_model_version: str | None = None
    frame_count: int | None = None
    normalized_object_count: int | None = None
    source_entity_count: int | None = None
    first_authoritative_timestamp: float | None = None
    last_authoritative_timestamp: float | None = None
    checks: list[ValidationCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ProvenanceFileReference(_ExecutionModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExternalProvenanceArtifacts(_ExecutionModel):
    manifest: ProvenanceFileReference
    normalized_session: SessionReference
    entity_mapping: EntityMappingReference
    normalization_report: FileReference
    domain_pack: DomainPackFiles


class ExternalReproducibilityProvenance(_ExecutionModel):
    conversion_inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conversion: ConversionReproducibility


class ExternalEvaluationProvenance(_ExecutionModel):
    declared_metriplane_version: str
    actual_metriplane_version: str
    frame_state_model_version: Literal["1.0"]
    run_id: str
    command: list[str]


class ExternalSourceProvenanceV1(_ExecutionModel):
    """Compact contract-derived provenance stored with an external Atlas run."""

    schema_version: Literal["metriplane.external_source_provenance.v1"] = (
        EXTERNAL_PROVENANCE_SCHEMA_VERSION
    )
    fixture_id: str
    contract_schema_version: str
    contract_profile: str
    fixture_distribution: str
    source_project: SourceProject
    source_artifacts: list[SourceArtifact]
    selection: SourceSelection
    rights: RightsDeclarations
    adapter: AdapterDeclaration
    normalization: NormalizationDeclaration
    artifacts: ExternalProvenanceArtifacts
    reproducibility: ExternalReproducibilityProvenance
    evaluation: ExternalEvaluationProvenance
    limitations: list[str]


class EvidenceBundleResult(_ExecutionModel):
    path: str
    verified: bool
    errors: list[str] = Field(default_factory=list)


class RegressionResult(_ExecutionModel):
    path: str
    passed: bool
    errors: list[str] = Field(default_factory=list)


class ExternalRunSummary(_ExecutionModel):
    """Stable machine-readable result for one external fixture evaluation."""

    schema_version: Literal["metriplane.external_run_summary.v1"] = (
        RUN_SUMMARY_SCHEMA_VERSION
    )
    passed: bool = Field(
        validation_alias=AliasChoices("passed", "pass"),
        serialization_alias="pass",
    )
    fixture_id: str | None = None
    validation: ExternalValidationSummary
    run_id: str | None = None
    output_directory: str
    metriplane_version: str
    source_project: str | None = None
    source_revision: SourceRevisionSummary | None = None
    adapter_identity: AdapterIdentitySummary | None = None
    frame_count: int | None = None
    event_count: int | None = None
    deviation_count: int | None = None
    incident_count: int | None = None
    report_path: str | None = None
    evidence_bundles: list[EvidenceBundleResult] = Field(default_factory=list)
    generated_regressions: list[RegressionResult] = Field(default_factory=list)
    provenance: ProvenanceFileReference | None = None
    limitations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _PreflightResult:
    summary: ExternalValidationSummary
    fixture: ValidatedExternalFixture | None


def _source_identities(manifest: ExternalSourceManifestV1) -> list[SourceIdentitySummary]:
    return [
        SourceIdentitySummary(
            artifact_id=artifact.artifact_id,
            role=artifact.role,
            presence=artifact.presence,
            sha256=artifact.sha256,
            immutable_identifier=artifact.immutable_identifier,
            path=artifact.path,
            uri=artifact.uri,
        )
        for artifact in manifest.source_artifacts
    ]


def _source_revision(manifest: ExternalSourceManifestV1) -> SourceRevisionSummary:
    return SourceRevisionSummary(
        kind=manifest.source_project.revision.kind,
        value=manifest.source_project.revision.value,
    )


def _adapter_identity(manifest: ExternalSourceManifestV1) -> AdapterIdentitySummary:
    environment = manifest.adapter.environment
    environment_identity = (
        environment.container_image_digest
        or (
            environment.dependency_lock.sha256
            if environment.dependency_lock is not None
            else ""
        )
    )
    return AdapterIdentitySummary(
        adapter_id=manifest.adapter.adapter_id,
        name=manifest.adapter.name,
        version=manifest.adapter.version,
        commit=manifest.adapter.commit,
        parameters_sha256=manifest.adapter.parameters.sha256,
        environment=environment_identity,
    )


def _domain_pack_hashes(manifest: ExternalSourceManifestV1) -> dict[str, str]:
    return {
        "assets": manifest.domain_pack.assets.sha256,
        "workspace": manifest.domain_pack.workspace.sha256,
        "process": manifest.domain_pack.process.sha256,
        "contracts": manifest.domain_pack.contracts.sha256,
        "work_orders": manifest.domain_pack.work_orders.sha256,
    }


def _validated_summary(
    root: Path,
    fixture: ValidatedExternalFixture,
) -> ExternalValidationSummary:
    manifest = fixture.manifest
    frames = fixture.frames
    return ExternalValidationSummary(
        passed=True,
        fixture_root=str(root),
        fixture_id=manifest.fixture.fixture_id,
        contract_schema_version=manifest.schema_version,
        contract_profile=manifest.contract_profile,
        manifest_sha256=sha256_file(root / "source-manifest.json"),
        session_sha256=manifest.normalized_artifacts.session.sha256,
        domain_pack_file_hashes=_domain_pack_hashes(manifest),
        entity_mapping_sha256=manifest.normalization.entity_mapping.sha256,
        normalization_report_sha256=(
            manifest.normalized_artifacts.normalization_report.sha256
        ),
        source_identities=_source_identities(manifest),
        source_revision=_source_revision(manifest),
        adapter_identity=_adapter_identity(manifest),
        metriplane_version=__version__,
        declared_metriplane_version=manifest.evaluation.metriplane_version,
        frame_state_model_version=manifest.normalization.frame_state_model_version,
        frame_count=len(frames),
        normalized_object_count=len(fixture.entity_mapping.mappings),
        source_entity_count=sum(
            len(mapping.source_entities) for mapping in fixture.entity_mapping.mappings
        ),
        first_authoritative_timestamp=frame_time_s(frames[0]),
        last_authoritative_timestamp=frame_time_s(frames[-1]),
        checks=[
            ValidationCheck(
                check_id="manifest_contract",
                passed=True,
                detail="Strict External Source Contract v1 manifest validated.",
            ),
            ValidationCheck(
                check_id="local_bundle_integrity",
                passed=True,
                detail="Local paths, symlinks, inventory, and declared hashes validated.",
            ),
            ValidationCheck(
                check_id="normalized_session",
                passed=True,
                detail="FrameStateModel 1.0 session and complete snapshots validated.",
            ),
            ValidationCheck(
                check_id="domain_pack",
                passed=True,
                detail="Existing Atlas domain-pack validation passed.",
            ),
            ValidationCheck(
                check_id="cross_artifact_agreement",
                passed=True,
                detail="Manifest, mapping, session, report, and process rules agree.",
            ),
        ],
        warnings=list(fixture.normalization_report.warnings),
        errors=[],
        limitations=list(
            dict.fromkeys(
                [*manifest.limitations, *fixture.normalization_report.limitations]
            )
        ),
    )


def _failed_validation_summary(root: Path, error: Exception) -> ExternalValidationSummary:
    message = str(error).strip() or type(error).__name__
    return ExternalValidationSummary(
        passed=False,
        fixture_root=str(root),
        metriplane_version=__version__,
        checks=[
            ValidationCheck(
                check_id="external_fixture_preflight",
                passed=False,
                detail=message,
            )
        ],
        errors=[message],
    )


def _preflight_external_fixture(root: str | Path) -> _PreflightResult:
    supplied_root = Path(root)
    display_root = supplied_root.absolute()
    try:
        if supplied_root.is_symlink():
            raise ValueError(f"external fixture root must not be a symlink: {supplied_root}")
        try:
            resolved_root = supplied_root.resolve(strict=True)
        except RuntimeError as exc:
            raise ValueError(
                f"cannot resolve external fixture root {supplied_root}: {exc}"
            ) from exc
        if not resolved_root.is_dir():
            raise ValueError(
                f"external fixture root must be a regular directory: {supplied_root}"
            )
        fixture = validate_external_fixture_bundle(resolved_root)
        summary = _validated_summary(resolved_root, fixture)
        declared_version = fixture.manifest.evaluation.metriplane_version
        if declared_version != __version__:
            message = (
                "fixture evaluation.metriplane_version does not match the installed "
                f"Metriplane version: {declared_version!r} != {__version__!r}"
            )
            summary = summary.model_copy(
                update={
                    "passed": False,
                    "checks": [
                        *summary.checks,
                        ValidationCheck(
                            check_id="evaluation_runtime_version",
                            passed=False,
                            detail=message,
                        ),
                    ],
                    "errors": [message],
                }
            )
            return _PreflightResult(summary=summary, fixture=None)
        summary = summary.model_copy(
            update={
                "checks": [
                    *summary.checks,
                    ValidationCheck(
                        check_id="evaluation_runtime_version",
                        passed=True,
                        detail=f"Installed Metriplane version matches {declared_version}.",
                    ),
                ]
            }
        )
        return _PreflightResult(summary=summary, fixture=fixture)
    except _EXPECTED_INPUT_ERRORS as exc:
        return _PreflightResult(
            summary=_failed_validation_summary(display_root, exc),
            fixture=None,
        )


def validate_external_fixture(root: str | Path) -> ExternalValidationSummary:
    """Validate an external fixture without invoking Atlas or modifying inputs."""
    return _preflight_external_fixture(root).summary


def _domain_pack_root(root: Path, manifest: ExternalSourceManifestV1) -> Path:
    return root / Path(manifest.domain_pack.assets.path).parent


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _resolve_output_path(path: str | Path) -> Path:
    supplied = Path(path)
    try:
        return supplied.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve external run output path {supplied}: {exc}") from exc


def _select_operational_run_id(fixture_id: str, explicit_run_id: str | None) -> str:
    if explicit_run_id is not None:
        if _SAFE_OPERATIONAL_RUN_ID.fullmatch(explicit_run_id) is None:
            raise ValueError(
                "external run --run-id must be 1-128 ASCII letters, digits, dots, "
                "underscores, or hyphens, and must start with a letter or digit"
            )
        return explicit_run_id

    candidate = f"external_{fixture_id}"
    if _SAFE_OPERATIONAL_RUN_ID.fullmatch(candidate) is not None:
        return candidate

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", fixture_id).strip("._-")
    slug = slug[:72].rstrip("._-") or "fixture"
    digest = hashlib.sha256(
        fixture_id.encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:12]
    return f"external_{slug}_{digest}"


def _external_provenance(
    fixture: ValidatedExternalFixture,
    *,
    run_id: str,
    output_directory: Path,
    overwrite: bool,
) -> ExternalSourceProvenanceV1:
    manifest = fixture.manifest
    command = [
        "metriplane",
        "external",
        "run",
        str(fixture.root),
        "--out",
        str(output_directory),
        "--run-id",
        run_id,
    ]
    if overwrite:
        command.append("--overwrite")
    return ExternalSourceProvenanceV1(
        fixture_id=manifest.fixture.fixture_id,
        contract_schema_version=manifest.schema_version,
        contract_profile=manifest.contract_profile,
        fixture_distribution=manifest.fixture.distribution,
        source_project=manifest.source_project,
        source_artifacts=manifest.source_artifacts,
        selection=manifest.selection,
        rights=manifest.rights,
        adapter=manifest.adapter,
        normalization=manifest.normalization,
        artifacts=ExternalProvenanceArtifacts(
            manifest=ProvenanceFileReference(
                path="source-manifest.json",
                sha256=sha256_file(fixture.root / "source-manifest.json"),
            ),
            normalized_session=manifest.normalized_artifacts.session,
            entity_mapping=manifest.normalization.entity_mapping,
            normalization_report=manifest.normalized_artifacts.normalization_report,
            domain_pack=manifest.domain_pack,
        ),
        reproducibility=ExternalReproducibilityProvenance(
            conversion_inputs_sha256=conversion_inputs_sha256(manifest),
            evaluation_inputs_sha256=evaluation_inputs_sha256(manifest),
            conversion=fixture.normalization_report.conversion_reproducibility,
        ),
        evaluation=ExternalEvaluationProvenance(
            declared_metriplane_version=manifest.evaluation.metriplane_version,
            actual_metriplane_version=__version__,
            frame_state_model_version=manifest.normalization.frame_state_model_version,
            run_id=run_id,
            command=command,
        ),
        limitations=list(
            dict.fromkeys(
                [*manifest.limitations, *fixture.normalization_report.limitations]
            )
        ),
    )


def _failed_run_summary(
    validation: ExternalValidationSummary,
    output: Path,
    errors: list[str],
    *,
    run_id: str | None = None,
) -> ExternalRunSummary:
    return ExternalRunSummary(
        passed=False,
        fixture_id=validation.fixture_id,
        validation=validation,
        run_id=run_id,
        output_directory=str(output),
        metriplane_version=__version__,
        source_revision=validation.source_revision,
        adapter_identity=validation.adapter_identity,
        limitations=list(validation.limitations),
        errors=errors,
    )


def run_external_fixture(
    root: str | Path,
    out_dir: str | Path,
    *,
    run_id: str | None = None,
    overwrite: bool = False,
) -> ExternalRunSummary:
    """Validate a fixture, run unchanged Atlas, and verify generated artifacts."""
    preflight = _preflight_external_fixture(root)
    output = Path(out_dir).absolute()
    if preflight.fixture is None:
        return _failed_run_summary(
            preflight.summary,
            output,
            list(preflight.summary.errors),
            run_id=run_id,
        )

    fixture = preflight.fixture
    manifest = fixture.manifest
    try:
        resolved_output = _resolve_output_path(out_dir)
    except ValueError as exc:
        return _failed_run_summary(
            preflight.summary,
            output,
            [str(exc)],
            run_id=run_id,
        )
    if _paths_overlap(fixture.root.resolve(), resolved_output):
        message = (
            "external run output must not equal, contain, or be contained by the "
            f"fixture root: output={resolved_output}, fixture={fixture.root}"
        )
        return _failed_run_summary(
            preflight.summary,
            resolved_output,
            [message],
            run_id=run_id,
        )

    try:
        selected_run_id = _select_operational_run_id(
            manifest.fixture.fixture_id,
            run_id,
        )
    except ValueError as exc:
        return _failed_run_summary(
            preflight.summary,
            resolved_output,
            [str(exc)],
            run_id=run_id,
        )
    provenance = _external_provenance(
        fixture,
        run_id=selected_run_id,
        output_directory=resolved_output,
        overwrite=overwrite,
    )
    session_path = fixture.root / manifest.normalized_artifacts.session.path
    pack_root = _domain_pack_root(fixture.root, manifest)
    try:
        atlas_manifest = run_atlas(
            session_path,
            pack_root,
            resolved_output,
            run_id=selected_run_id,
            overwrite=overwrite,
            external_source_provenance=provenance.model_dump(mode="json"),
        )
    except _EXPECTED_INPUT_ERRORS as exc:
        message = str(exc).strip() or type(exc).__name__
        return _failed_run_summary(
            preflight.summary,
            resolved_output,
            [message],
            run_id=selected_run_id,
        )

    errors: list[str] = []
    evidence_results: list[EvidenceBundleResult] = []
    for bundle_path in sorted((resolved_output / "evidence_bundles").glob("*.zip")):
        result = verify_bundle(bundle_path)
        verified = bool(result.get("pass"))
        result_errors = [str(item) for item in result.get("errors", [])]
        evidence_results.append(
            EvidenceBundleResult(
                path=str(bundle_path),
                verified=verified,
                errors=result_errors,
            )
        )
        if not verified:
            if result_errors:
                errors.extend(
                    f"evidence bundle {bundle_path.name}: {item}"
                    for item in result_errors
                )
            else:
                errors.append(
                    f"evidence bundle {bundle_path.name}: verification failed without details"
                )

    regression_results: list[RegressionResult] = []
    for regression_path in sorted((resolved_output / "regression_tests").glob("*.yaml")):
        result = run_regression(regression_path)
        passed = bool(result.get("pass"))
        result_errors = [str(item) for item in result.get("errors", [])]
        regression_results.append(
            RegressionResult(
                path=str(regression_path),
                passed=passed,
                errors=result_errors,
            )
        )
        if not passed:
            if result_errors:
                errors.extend(
                    f"regression {regression_path.name}: {item}"
                    for item in result_errors
                )
            else:
                errors.append(
                    f"regression {regression_path.name}: replay failed without details"
                )

    if len(evidence_results) != atlas_manifest.incident_count:
        errors.append(
            "generated evidence bundle count does not match Atlas incident count: "
            f"{len(evidence_results)} != {atlas_manifest.incident_count}"
        )
    if len(regression_results) != atlas_manifest.incident_count:
        errors.append(
            "generated regression count does not match Atlas incident count: "
            f"{len(regression_results)} != {atlas_manifest.incident_count}"
        )

    provenance_path = resolved_output / "external_source_provenance.json"
    provenance_reference: ProvenanceFileReference | None = None
    atlas_reference = atlas_manifest.external_source_provenance
    if atlas_reference is None:
        errors.append("Atlas manifest is missing external source provenance reference")
    elif not provenance_path.is_file():
        errors.append("external source provenance artifact is missing from the run")
    else:
        actual_sha256 = sha256_file(provenance_path)
        if atlas_reference.path != "external_source_provenance.json":
            errors.append("Atlas manifest external provenance path is not canonical")
        if atlas_reference.sha256 != actual_sha256:
            errors.append("Atlas manifest external provenance hash does not match the artifact")
        provenance_reference = ProvenanceFileReference(
            path=str(provenance_path),
            sha256=actual_sha256,
        )

    report_path = resolved_output / atlas_manifest.artifacts["cell_truth_report_html"]
    if not report_path.is_file():
        errors.append(f"Atlas report is missing: {report_path}")

    return ExternalRunSummary(
        passed=not errors,
        fixture_id=manifest.fixture.fixture_id,
        validation=preflight.summary,
        run_id=atlas_manifest.run_id,
        output_directory=str(resolved_output),
        metriplane_version=__version__,
        source_project=manifest.source_project.name,
        source_revision=_source_revision(manifest),
        adapter_identity=_adapter_identity(manifest),
        frame_count=atlas_manifest.frame_count,
        event_count=atlas_manifest.event_count,
        deviation_count=atlas_manifest.deviation_count,
        incident_count=atlas_manifest.incident_count,
        report_path=str(report_path),
        evidence_bundles=evidence_results,
        generated_regressions=regression_results,
        provenance=provenance_reference,
        limitations=list(preflight.summary.limitations),
        errors=errors,
    )


def summary_json(summary: ExternalValidationSummary | ExternalRunSummary) -> str:
    """Serialize a summary with stable aliases for CLI and CI consumers."""
    import json

    return json.dumps(
        summary.model_dump(mode="json", by_alias=True, exclude_none=True),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
