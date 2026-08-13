# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from metriplane_source_adapter_sdk import load_capability, record_path


@pytest.fixture
def maniskill_record() -> dict:
    return copy.deepcopy(load_capability(record_path("maniskill-pickcube")))


@pytest.fixture
def robomimic_record() -> dict:
    return copy.deepcopy(load_capability(record_path("robomimic-lowdim")))


@pytest.fixture
def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]
