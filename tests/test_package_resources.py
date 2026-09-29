# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from importlib import resources

from metriplane.demo import BUNDLED_DEMO_RESOURCES
from metriplane.resources import RUNTIME_RESOURCES, resource


def test_bundled_demo_resource_inventory_is_complete_and_nonempty() -> None:
    package = resources.files("metriplane.demo")

    assert len(BUNDLED_DEMO_RESOURCES) == 6
    for relative_path in BUNDLED_DEMO_RESOURCES:
        resource = package.joinpath(relative_path)
        assert resource.is_file(), relative_path
        assert resource.read_bytes(), relative_path


def test_bundled_runtime_resource_inventory_is_complete_and_nonempty() -> None:
    assert len(RUNTIME_RESOURCES) == 42
    for relative_path in RUNTIME_RESOURCES:
        installed = resource(relative_path)
        assert installed.is_file(), relative_path
        assert installed.read_bytes(), relative_path
