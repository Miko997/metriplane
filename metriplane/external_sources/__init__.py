# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Source-neutral contracts for portable, recorded external fixtures."""

from metriplane.external_sources.contract import (
    CONTRACT_PROFILE,
    CONTRACT_SCHEMA_VERSION,
    ExternalSourceManifestV1,
    ValidatedExternalFixture,
    conversion_inputs_sha256,
    evaluation_inputs_sha256,
    load_external_source_manifest,
    render_external_source_contract_schema,
    validate_external_fixture_bundle,
)
from metriplane.external_sources.execution import (
    EXTERNAL_PROVENANCE_SCHEMA_VERSION,
    RUN_SUMMARY_SCHEMA_VERSION,
    VALIDATION_SUMMARY_SCHEMA_VERSION,
    ExternalRunSummary,
    ExternalSourceProvenanceV1,
    ExternalValidationSummary,
    run_external_fixture,
    validate_external_fixture,
)

__all__ = [
    "CONTRACT_PROFILE",
    "CONTRACT_SCHEMA_VERSION",
    "EXTERNAL_PROVENANCE_SCHEMA_VERSION",
    "RUN_SUMMARY_SCHEMA_VERSION",
    "VALIDATION_SUMMARY_SCHEMA_VERSION",
    "ExternalRunSummary",
    "ExternalSourceManifestV1",
    "ExternalSourceProvenanceV1",
    "ExternalValidationSummary",
    "ValidatedExternalFixture",
    "conversion_inputs_sha256",
    "evaluation_inputs_sha256",
    "load_external_source_manifest",
    "render_external_source_contract_schema",
    "run_external_fixture",
    "validate_external_fixture",
    "validate_external_fixture_bundle",
]
