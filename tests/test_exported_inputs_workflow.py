# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.cli import main as metriplane_main


def test_exported_inputs_complete_own_data_command_path(tmp_path: Path, capsys) -> None:
    inputs = tmp_path / "my-inputs"
    run_dir = tmp_path / "my-run"
    session = inputs / "session.jsonl"
    pack = inputs / "domain-pack"
    bundle = run_dir / "evidence_bundles" / "INC-0001.zip"
    regression = run_dir / "regression_tests" / "INC-0001.yaml"

    assert metriplane_main(["demo", "--export-inputs", str(inputs)]) == 0
    assert metriplane_main(["atlas", "validate-pack", str(pack)]) == 0
    assert (
        metriplane_main(
            [
                "atlas",
                "run",
                "--session-jsonl",
                str(session),
                "--pack",
                str(pack),
                "--out",
                str(run_dir),
            ]
        )
        == 0
    )
    assert metriplane_main(["atlas", "report", "--run-dir", str(run_dir)]) == 0
    assert metriplane_main(["atlas", "bundle", "verify", str(bundle)]) == 0
    assert metriplane_main(["atlas", "test", str(regression), "--json"]) == 0

    manifest = json.loads((run_dir / "atlas_manifest.json").read_text(encoding="utf-8"))
    assert manifest["event_count"] == 6
    assert manifest["incident_count"] == 1
    assert (run_dir / "cell_truth_report.html").is_file()
    assert bundle.is_file()
    assert regression.is_file()

    output = capsys.readouterr().out
    assert "events=6 incidents=1" in output
    assert str(run_dir / "cell_truth_report.html") in output
    assert output.count('"pass": true') == 2
