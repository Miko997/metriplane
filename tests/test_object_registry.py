from __future__ import annotations

import pytest

from metriplane.sentinel.cli_registry import main_objects
from metriplane.sentinel.registry import (
    ObjectRegistryConfig,
    load_registry,
    validate_registry,
)

VALID_YAML = """\
objects:
  - object_id: cart_01
    marker_id: 7
    type: cart
    display_name: Cart 01
    dimensions_m: [0.40, 0.30]
    tags: [mobile]
  - object_id: pallet_01
    marker_id: 12
    type: pallet
    display_name: Pallet 01
  - object_id: human_proxy_01
    marker_id: 3
    type: human_proxy
    display_name: Human Proxy 01
"""


@pytest.fixture
def registry_file(tmp_path):
    p = tmp_path / "objects.yaml"
    p.write_text(VALID_YAML)
    return p


def test_load_valid(registry_file):
    cfg = load_registry(registry_file)
    assert len(cfg.objects) == 3


def test_by_marker_id_found(registry_file):
    cfg = load_registry(registry_file)
    entry = cfg.by_marker_id(7)
    assert entry is not None
    assert entry.object_id == "cart_01"


def test_by_marker_id_not_found(registry_file):
    cfg = load_registry(registry_file)
    assert cfg.by_marker_id(99) is None


def test_by_object_id(registry_file):
    cfg = load_registry(registry_file)
    entry = cfg.by_object_id("pallet_01")
    assert entry is not None
    assert entry.marker_id == 12


def test_resolve_id_registered(registry_file):
    cfg = load_registry(registry_file)
    assert cfg.resolve_id("7") == "cart_01"


def test_resolve_id_fallback(registry_file):
    cfg = load_registry(registry_file)
    assert cfg.resolve_id("99") == "marker_99"


def test_validate_ok(registry_file):
    errors = validate_registry(registry_file)
    assert errors == []


def test_validate_duplicate_marker(tmp_path):
    bad = """\
objects:
  - object_id: cart_01
    marker_id: 7
    type: cart
    display_name: Cart 01
  - object_id: cart_02
    marker_id: 7
    type: cart
    display_name: Cart 02
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    errors = validate_registry(p)
    assert any("duplicate marker_id" in e for e in errors)


def test_validate_duplicate_object_id(tmp_path):
    bad = """\
objects:
  - object_id: cart_01
    marker_id: 7
    type: cart
    display_name: Cart 01
  - object_id: cart_01
    marker_id: 12
    type: cart
    display_name: Cart 01b
"""
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    errors = validate_registry(p)
    assert any("duplicate object_id" in e for e in errors)


def test_cli_validate_pass(registry_file):
    rc = main_objects(["validate", str(registry_file)])
    assert rc == 0


def test_cli_validate_fail(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: valid: yaml: [[[")
    rc = main_objects(["validate", str(bad)])
    assert rc == 1


def test_cli_list(registry_file, capsys):
    rc = main_objects(["list", "--config", str(registry_file)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cart_01" in out
    assert "pallet_01" in out
