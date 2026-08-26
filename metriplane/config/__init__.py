# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
metriplane.config package.

``metriplane/config/`` (this directory) and ``metriplane/config.py`` (a sibling
file) share the same dotted name. Python packages always win over same-named
modules, so this ``__init__.py`` must manually load the sibling ``config.py``
and re-export its public API so that callers can continue to write:

    from metriplane.config import Config, load_config, resolve_profile
"""

from __future__ import annotations

import importlib.util as _util
import sys as _sys
from pathlib import Path as _Path

# ---------------------------------------------------------------------------
# Load the sibling metriplane/config.py by file path and expose its symbols.
# We register it under a private name to avoid infinite recursion.
# ---------------------------------------------------------------------------
_config_py = _Path(__file__).parent.parent / "config.py"  # metriplane/config.py
_PRIVATE_NAME = "metriplane._config_flat"

if _PRIVATE_NAME not in _sys.modules:
    _spec = _util.spec_from_file_location(_PRIVATE_NAME, _config_py)
    assert _spec and _spec.loader, f"Cannot load {_config_py}"
    _flat = _util.module_from_spec(_spec)
    _sys.modules[_PRIVATE_NAME] = _flat
    _spec.loader.exec_module(_flat)  # type: ignore[union-attr]
else:
    _flat = _sys.modules[_PRIVATE_NAME]

# Re-export every public symbol into this package's namespace
for _name in [_n for _n in dir(_flat) if not _n.startswith("_")]:
    globals()[_name] = getattr(_flat, _name)

del _name, _config_py, _PRIVATE_NAME, _spec, _flat
