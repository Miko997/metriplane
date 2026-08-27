# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Test fixtures rely on the active source or installed package profile."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_ISOLATED_ROOT: Path | None = None
_ORIGINAL_ENV: dict[str, str | None] = {}


def pytest_configure() -> None:
    """Keep every test and child process inside an isolated writable home."""
    global _ISOLATED_ROOT
    if _ISOLATED_ROOT is not None:
        return

    temp_base = Path(os.environ.get("TMPDIR", tempfile.gettempdir()))
    original_home = Path(os.environ.get("HOME", temp_base))
    original_cache = Path(os.environ.get("XDG_CACHE_HOME", original_home / ".cache"))
    uv_cache = Path(os.environ.get("UV_CACHE_DIR", original_cache / "uv"))
    _ISOLATED_ROOT = Path(tempfile.mkdtemp(prefix="metriplane-tests-", dir=temp_base))
    values = {
        "HOME": _ISOLATED_ROOT / "home",
        "USERPROFILE": _ISOLATED_ROOT / "windows" / "profile",
        "APPDATA": _ISOLATED_ROOT / "windows" / "roaming",
        "LOCALAPPDATA": _ISOLATED_ROOT / "windows" / "local",
        "XDG_CONFIG_HOME": _ISOLATED_ROOT / "xdg" / "config",
        "XDG_DATA_HOME": _ISOLATED_ROOT / "xdg" / "data",
        "XDG_CACHE_HOME": _ISOLATED_ROOT / "xdg" / "cache",
        "XDG_STATE_HOME": _ISOLATED_ROOT / "xdg" / "state",
        "METRIPLANE_TEST_HOME": _ISOLATED_ROOT,
        # The baseline fixture performs an intentionally offline uv install.
        "UV_CACHE_DIR": uv_cache,
    }
    for name, value in values.items():
        _ORIGINAL_ENV[name] = os.environ.get(name)
        value.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(value)


def pytest_unconfigure() -> None:
    global _ISOLATED_ROOT
    for name, value in _ORIGINAL_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    _ORIGINAL_ENV.clear()
    if _ISOLATED_ROOT is not None:
        shutil.rmtree(_ISOLATED_ROOT, ignore_errors=True)
        _ISOLATED_ROOT = None
