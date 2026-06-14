# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import time
from pathlib import Path

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.atlas.runtime import run_atlas


def bench_core(session_jsonl: str | Path, pack: str | Path, out: str | Path) -> dict:
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)
    run_dir = out_path / "atlas_bench_run"
    started = time.perf_counter()
    manifest = run_atlas(session_jsonl, pack, run_dir, run_id="atlas_bench")
    elapsed = time.perf_counter() - started
    bundle_results = []
    regression_results = []
    bundle_dir = run_dir / "evidence_bundles"
    for bundle in sorted(bundle_dir.glob("*.zip")):
        bundle_results.append(verify_bundle(bundle))
    for spec in sorted((run_dir / "regression_tests").glob("*.yaml")):
        regression_results.append(run_regression(spec))
    result = {
        "schema_version": "metriplane.atlas.bench.v1",
        "run_dir": str(run_dir),
        "elapsed_s": round(elapsed, 6),
        "frame_count": manifest.frame_count,
        "event_count": manifest.event_count,
        "incident_count": manifest.incident_count,
        "bundles_pass": all(item["pass"] for item in bundle_results),
        "regressions_pass": all(item["pass"] for item in regression_results),
    }
    (out_path / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result
