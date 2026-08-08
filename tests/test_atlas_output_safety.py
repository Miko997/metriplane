# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from metriplane.atlas.runtime import _safe_generated_out_dir, run_atlas


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_PACK = ROOT / "configs" / "domain_packs" / "assembly_cell"
ASSEMBLY_SESSION = ROOT / "datasets" / "demo" / "atlas" / "assembly_cell_missing_tool.jsonl"


def test_existing_system_temp_output_requires_explicit_overwrite() -> None:
    with TemporaryDirectory(dir="/tmp", prefix="metriplane-atlas-safety-") as temp_dir:
        out_dir = Path(temp_dir)
        sentinel = out_dir / "unrelated-user-data.txt"
        sentinel.write_text("keep", encoding="utf-8")

        assert _safe_generated_out_dir(out_dir) is False
        with pytest.raises(ValueError, match="without --overwrite"):
            run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, out_dir)
        assert sentinel.read_text(encoding="utf-8") == "keep"

        manifest = run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, out_dir, overwrite=True)
        assert manifest.event_count == 6
        assert not sentinel.exists()
