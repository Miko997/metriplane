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
    assert tool.main(["check", "--catalog", str(changed), "--schema", str(SCHEMA)]) == 2


def test_transcription_never_overwrites_an_existing_output(tmp_path: Path) -> None:
    out = tmp_path / "catalog.json"
    out.write_text("retained", encoding="utf-8")
    assert (
        tool.main(
            ["transcribe", "--source", str(CATALOG), "--out", str(out), "--schema", str(SCHEMA)]
        )
        == 2
    )
    assert out.read_text(encoding="utf-8") == "retained"


def test_v050_rows_apply_owner_scoped_human_review_policy_only() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    tasks = {row["task_id"]: row for row in catalog["tasks"]}

    trust_action = tasks["MP2-030"]["manual_external_irreversible_actions"]
    assert len(trust_action) == 1
    assert trust_action[0]["required_role"] == "security_release_architecture_owner"
    assert "non-author approver" not in json.dumps(trust_action)
    assert "automated execution evidence" in trust_action[0]["requirement"]

    release_actions = tasks["MP2-049"]["manual_external_irreversible_actions"]
    human_review = next(
        row for row in release_actions if row["kind"] == "independent_human_release_approval"
    )
    assert human_review["status"] == "NOT_APPLICABLE"
    assert human_review["required_role"] == "none"
    assert "must never be represented as PASS" in human_review["requirement"]
    backups = next(row for row in release_actions if row["kind"] == "backup_role_assignments")
    assert backups["required_role"] == (
        "backup_operator plus backup_infrastructure_owner plus backup_publisher"
    )
    assert "backup_non_author_reviewer" not in backups["required_role"]
    assert {row["required_role"] for row in release_actions} >= {
        "publisher",
        "operator",
        "infrastructure_owner",
    }

    later_expected_roles = {
        "MP2-207": "independent_assurance_verifier",
        "MP2-210": "non_author_reviewer",
        "MP2-223": "independent_non_maintainer_rerunner",
        "MP2-225": "non_author_reviewer",
    }
    for task_id, required_role in later_expected_roles.items():
        roles = {
            row["required_role"] for row in tasks[task_id]["manual_external_irreversible_actions"]
        }
        assert required_role in roles
