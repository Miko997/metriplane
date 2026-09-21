# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path


from metriplane.strict_parsing import load_yaml_path

from metriplane.testing.models import PhysicalRegressionExpected


def load_expected(path: str | Path) -> PhysicalRegressionExpected:
    """Load expected.yaml.

    Accepts either a top-level mapping or one nested under an `expected:` key.
    """
    data = load_yaml_path(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected file must be a mapping")
    inner = data.get("expected", data)
    if "schema_version" in data and "schema_version" not in inner:
        inner = {**inner, "schema_version": data["schema_version"]}
    return PhysicalRegressionExpected.model_validate(inner)
