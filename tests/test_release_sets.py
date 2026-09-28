from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.check_release_sets import ReleaseSetError, validate

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/status/release-sets.json"
SCHEMA = ROOT / "schemas/metriplane.release-sets.v1.schema.json"


def test_release_set_registry_is_current() -> None:
    validate(ROOT, REGISTRY, SCHEMA)


def _copy(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    checkout = tmp_path / "checkout"
    shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    registry_path = checkout / "docs/status/release-sets.json"
    value = json.loads(registry_path.read_text(encoding="utf-8"))
    return checkout, registry_path, value


@pytest.mark.parametrize(
    "mutation", ["top-level-contract", "duplicate-project", "set-semantics", "unexpected-field"]
)
def test_release_set_registry_rejects_incomplete_or_ambiguous_boms(
    tmp_path: Path, mutation: str
) -> None:
    checkout, registry_path, value = _copy(tmp_path)
    sets = value["sets"]
    if mutation == "top-level-contract":
        del value["owner"]
        value["schema_version"] = "metriplane.release-sets.v2"
    elif mutation == "duplicate-project":
        value["projects"]["ros2-mcap"] = value["projects"]["source-adapter-sdk"]
    elif mutation == "set-semantics":
        sets["analytics"]["root_extras"] = []
        sets["research"]["extends"] = ["core"]
    else:
        sets["review"]["unexpected"] = True
    registry_path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    with pytest.raises(ReleaseSetError):
        validate(checkout, registry_path, checkout / SCHEMA.relative_to(ROOT))


def test_release_set_registry_rejects_project_lock_or_schema_drift(tmp_path: Path) -> None:
    checkout, registry_path, _ = _copy(tmp_path)
    lock_path = checkout / "adapters/source_adapter_sdk/uv.lock"
    lock_bytes = lock_path.read_bytes()
    lock_path.unlink()
    with pytest.raises(ReleaseSetError, match="lacks metadata or lock"):
        validate(checkout, registry_path, checkout / SCHEMA.relative_to(ROOT))
    lock_path.write_bytes(lock_bytes)
    schema_path = checkout / SCHEMA.relative_to(ROOT)
    schema_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseSetError, match="schema bytes are not canonical"):
        validate(checkout, registry_path, schema_path)
