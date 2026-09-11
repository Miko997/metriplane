# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_work_order_catalog.py"
CATALOG = ROOT / "docs/status/task-work-orders.json"
SCHEMA = ROOT / "schemas/metriplane.mp2-work-order-set.v1.schema.json"

spec = importlib.util.spec_from_file_location("work_order_catalog", TOOL)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def test_exact_authoritative_catalog_is_valid() -> None:
    result = tool.validate_catalog(CATALOG, schema_path=SCHEMA)
    assert result["verdict"] == "PASS"
    assert result["task_count"] == 93
    assert result["criterion_count"] == 280


def test_check_is_read_only() -> None:
    before = CATALOG.read_bytes()
    assert tool.main(["check", "--catalog", str(CATALOG), "--schema", str(SCHEMA)]) == 0
    assert CATALOG.read_bytes() == before


def test_transcription_requires_exact_packet_and_explicit_out(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    assert (
        tool.main(
            ["transcribe", "--source", str(CATALOG), "--out", str(out), "--schema", str(SCHEMA)]
        )
        == 0
    )
    assert out.read_bytes() == CATALOG.read_bytes()


def test_substituted_catalog_is_rejected(tmp_path: Path) -> None:
    value = json.loads(CATALOG.read_bytes())
    value["tasks"][0]["first_required_release"] = "v0.5"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(tool.CatalogError, match="source digest"):
        tool.validate_catalog(changed, schema_path=SCHEMA)
