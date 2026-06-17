<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Key Generated Paper Artifacts

| Artifact | Path | Summary |
|---|---|---|
| Cell Truth Report | `atlas_run/cell_truth_report.md`, `atlas_run/cell_truth_report.html` | Nontechnical report for the missing-tool delay incident. |
| Atlas dashboard | `atlas_run/atlas_dashboard.html` | Static dashboard with run timeline, incident, evidence links, and action summary. |
| Evidence bundle | `atlas_run/evidence_bundles/INC-0001.zip` | Portable incident bundle; listing and checksum captured under `artifacts/`. |
| Regression spec | `atlas_run/regression_tests/INC-0001.yaml` | Generated regression test for `missing_tool_caused_delay_INC-0001`. |
| Physical event log | `atlas_run/physical_event_log.jsonl` | Six replay-derived physical events. |
| Reality graph | `atlas_run/reality_graph.json` | Asset, zone, station, process, event, and incident graph. |
| Process trace | `atlas_run/process_trace.json` | Completed steps and active process state for the run. |
| Bundle verification | `logs/bundle_verify.txt` | Verifier result with `"pass": true`. |
| Regression output | `logs/regression_test.json` | Regression result with `"pass": true`. |

The generated artifacts are replay-derived and planar/tagged-asset scoped.
