# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from metriplane.atlas.domain_packs import validate_domain_pack


def validate_pack_or_raise(path: str | Path) -> None:
    errors = validate_domain_pack(path)
    if errors:
        raise ValueError("; ".join(errors))
