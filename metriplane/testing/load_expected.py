from __future__ import annotations

from pathlib import Path

import yaml

from metriplane.testing.models import PhysicalRegressionExpected


def load_expected(path: str | Path) -> PhysicalRegressionExpected:
    """Load expected.yaml.

    Accepts either a top-level mapping or one nested under an `expected:` key.
    """
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected file must be a mapping")
    inner = data.get("expected", data)
    if "schema_version" in data and "schema_version" not in inner:
        inner = {**inner, "schema_version": data["schema_version"]}
    return PhysicalRegressionExpected.model_validate(inner)
