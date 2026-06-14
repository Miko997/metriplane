# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from metriplane.sentinel.config import SentinelConfig


def test_disabled_by_default():
    cfg = SentinelConfig()
    assert cfg.enabled is False
    assert cfg.control_enabled is False


def test_from_none_is_disabled():
    cfg = SentinelConfig.from_dict(None)
    assert cfg.enabled is False


def test_parses_from_dict():
    cfg = SentinelConfig.from_dict({
        "enabled": True,
        "mode": "shadow_auditor",
        "contracts_file": "c.yaml",
        "objects_file": "o.yaml",
    })
    assert cfg.enabled is True
    assert cfg.contracts_file == "c.yaml"
    assert cfg.objects_file == "o.yaml"


def test_invalid_mode_rejected():
    with pytest.raises(ValueError, match="invalid sentinel mode"):
        SentinelConfig.from_dict({"enabled": True, "mode": "controller"})


def test_control_enabled_cannot_be_true():
    with pytest.raises(ValueError, match="control_enabled cannot be true"):
        SentinelConfig.from_dict({"enabled": True, "control_enabled": True})


def test_control_enabled_always_false_property():
    cfg = SentinelConfig.from_dict({"enabled": True})
    assert cfg.control_enabled is False
