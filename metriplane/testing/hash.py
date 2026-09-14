# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(obj: Any) -> str:
    """Deterministic sha256 over a JSON-serializable object (sorted keys)."""
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def incidents_fingerprint(incidents: list[Any]) -> str:
    """Hash the observable shape of incidents, ignoring volatile IDs."""
    shape = [
        {
            "rule_id": inc.rule_id,
            "severity": inc.severity,
            "objects": sorted(inc.object_ids),
            "zones": sorted(inc.zones),
            "duration_s": inc.duration_s,
        }
        for inc in sorted(incidents, key=lambda i: (i.opened_ts, i.rule_id))
    ]
    return stable_hash(shape)
