from __future__ import annotations

import pytest

from metriplane.contracts.load import ContractLoadError, load_spatial_contract

VALID = """\
schema_version: "1.0"
contract_id: demo
subjects:
  movable:
    object_types: [cart]
rules:
  - id: r1
    type: forbidden_zone
    subject: movable
    zones: [exit_lane]
"""


def test_load_valid(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(VALID)
    pkg = load_spatial_contract(p)
    assert pkg.contract_id == "demo"
    assert len(pkg.rules) == 1


def test_missing_file_raises(tmp_path):
    with pytest.raises(ContractLoadError, match="not found"):
        load_spatial_contract(tmp_path / "nope.yaml")


def test_empty_file_raises(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    with pytest.raises(ContractLoadError, match="empty"):
        load_spatial_contract(p)


def test_non_dict_top_level_raises(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ContractLoadError, match="must be a mapping"):
        load_spatial_contract(p)


def test_error_message_includes_filename(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("contract_id: x\nrules:\n  - id: r\n    type: minimum_distance\n")
    with pytest.raises(ContractLoadError) as exc:
        load_spatial_contract(p)
    assert "bad.yaml" in str(exc.value)


def test_demo_contract_loads():
    pkg = load_spatial_contract("configs/contracts/sentinel_demo.yaml")
    assert pkg.contract_id == "sentinel_demo_warehouse"
    assert len(pkg.rules) == 4
