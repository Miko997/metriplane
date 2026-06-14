# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from metriplane.atlas import models
from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.domain_packs import validate_domain_pack


MODEL_TYPES: list[type[BaseModel]] = [
    models.AssetRegistryModel,
    models.WorkspaceModel,
    models.ProcessModel,
    models.WorkOrderModel,
    models.AtlasEvent,
    models.AtlasDeviation,
    models.AtlasIncident,
    models.RealityGraphExport,
    models.BundleManifest,
    models.RegressionSpec,
    models.TrainingCase,
    models.ImprovementAction,
    models.AtlasRunManifest,
]


def export_protocol(out_dir: str | Path) -> dict:
    out = Path(out_dir)
    schemas = out / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    written = []
    for model_type in MODEL_TYPES:
        path = schemas / f"{model_type.__name__}.schema.json"
        path.write_text(json.dumps(model_type.model_json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path))
    index = {
        "schema_version": "metriplane.atlas.protocol_export.v1",
        "protocol": "Open Atlas Protocol v1",
        "schema_files": written,
        "limitations": ["Local JSON Schema export from Pydantic models; not a standards-body specification."],
    }
    (out / "open_atlas_protocol_index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return index


def compat_check(pack_dir: str | Path | None = None, bundle: str | Path | None = None) -> dict:
    errors: list[str] = []
    if pack_dir:
        errors.extend(f"pack: {error}" for error in validate_domain_pack(pack_dir))
    if bundle:
        result = verify_bundle(bundle)
        if not result["pass"]:
            errors.extend(f"bundle: {error}" for error in result["errors"])
    return {
        "schema_version": "metriplane.atlas.protocol_compat_check.v1",
        "pass": not errors,
        "errors": errors,
    }
