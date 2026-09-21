# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import yaml

from metriplane.strict_parsing import load_yaml_path

from metriplane.contracts.models import SpatialContractPackage


class ContractLoadError(ValueError):
    """Raised when a contract file cannot be loaded or is structurally invalid."""


def load_spatial_contract(path: str | Path) -> SpatialContractPackage:
    p = Path(path)
    if not p.exists():
        raise ContractLoadError(f"contract file not found: {p}")
    try:
        raw = load_yaml_path(p)
    except yaml.YAMLError as e:
        raise ContractLoadError(f"{p}: invalid YAML: {e}") from e
    if raw is None:
        raise ContractLoadError(f"{p}: contract file is empty")
    if not isinstance(raw, dict):
        raise ContractLoadError(f"{p}: top-level contract must be a mapping")
    try:
        return SpatialContractPackage.model_validate(raw)
    except Exception as e:
        raise ContractLoadError(f"{p}: {e}") from e
