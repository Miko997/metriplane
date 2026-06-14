# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Root conftest.py — prepends repo root to sys.path so the local
metriplane package shadows any older system-installed copy.

Required because the ROS2 launch_testing plugin fires
pytest_pycollect_makemodule before per-directory conftest.py files run.
"""
import importlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

# Prepend repo root so the local metriplane/ (with runner/) wins over any
# installed version that may lack the runner sub-package.
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Flush FileFinder path-importer caches so that sub-packages whose
# __init__.py was created after the editable install (e.g. metriplane/config/)
# are discovered correctly rather than being served from a stale namespace.
importlib.invalidate_caches()

# Pre-import core metriplane sub-packages so pytest's test-module collection
# phase always finds them with correct __file__ (not as stale namespaces).
# Python caches the first successful import in sys.modules, so subsequent
# "from metriplane.X import Y" calls in test modules re-use the cached object.
import metriplane.config  # noqa: F401 – ensures Config, load_config etc. are cached
import metriplane.mapping  # noqa: F401
import metriplane.recording  # noqa: F401
