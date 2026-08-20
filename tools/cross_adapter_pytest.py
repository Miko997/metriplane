# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Pytest bridge for adapter tests that deliberately invoke a root runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_TEST_PYTHON_ENV = "CROSS_ADAPTER_ROOT_TEST_PYTHON"


def pytest_configure() -> None:
    """Point deliberate root-runtime subprocesses at the gate's locked Python."""

    value = os.environ.get(ROOT_TEST_PYTHON_ENV)
    if value is None:
        raise RuntimeError(f"{ROOT_TEST_PYTHON_ENV} is required by this gate-only plugin")
    executable = Path(value)
    if (
        not executable.is_absolute()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
    ):
        raise RuntimeError(f"{ROOT_TEST_PYTHON_ENV} must name an absolute executable file")
    sys._base_executable = str(executable)  # type: ignore[attr-defined]
