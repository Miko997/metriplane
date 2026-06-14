<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# 0.2.0 Phase Matrix

This branch implements the Atlas/Cell Black Box direction as part of the unified
0.2.0 release foundation. Phases that require hardware, external users, or
factory data are represented as honest repo artifacts and claim boundaries.

| Phase | Local status | Primary artifacts |
|---:|---|---|
| 24 | Implemented | README/changelog/docs reframe to Cell Black Box first. |
| 25 | Implemented | `metriplane/atlas/reality_graph.py`, graph export. |
| 26 | Implemented | `metriplane atlas run`, demo replay, run manifest. |
| 27 | Implemented | Process model evaluator and domain pack process contracts. |
| 28 | Implemented | `physical_event_log.jsonl`, event reader/query path. |
| 29 | Implemented | Markdown/HTML Cell Truth Report. |
| 30 | Implemented | Flow metrics JSON/CSV and bottleneck summary. |
| 31 | Implemented | Incident timelines in report and bundle excerpts. |
| 32 | Implemented foundation | Work-order/material/tool fields and traceable pack data. |
| 33 | Scoped module | Guardian remains observe-only; no safety-control claim. |
| 34 | Implemented | Training case generator from incident bundles. |
| 35 | Implemented | Evidence Bundle v3 ZIP/export/verify/checksum path. |
| 36 | Implemented | Generated physical regression YAML and runner. |
| 37 | Implemented | Five checked-in domain packs. |
| 38 | Implemented | Static nontechnical dashboard with report, timeline, incidents, links, and next actions. |
| 39 | Implemented | Deterministic USDA export with zones, asset motion samples, and incident annotations; no latency claim. |
| 40 | Implemented | SQLite local evidence lake, queries, and trend summaries. |
| 41 | Implemented | Event query filters, saved queries, JSON output, and saved-query listing. |
| 42 | Implemented | CSV exports plus read-only REST snapshot, webhook payload, and MQTT topic plan artifacts. |
| 43 | Implemented locally | Edge doctor, resource checks, retention plan, edge bundle, and autostart docs. |
| 44 | Implemented | Multi-cell run index and cross-cell comparison reports by `cell_id`. |
| 45 | Implemented | Video-free privacy report, identity-key scan, retention config, and anonymized proxy export. |
| 46 | Implemented | Rule-based recommendations plus before/after replay comparison with caveats. |
| 47 | Pilot kit implemented | Checklist, questionnaires, success-report template, and reproduction notes; external users still required. |
| 48 | Implemented | `metriplane atlas bench core` covers run/report/bundle/regression summary. |
| 49 | Implemented | JSON Schema export, protocol docs, and compatibility checks. |
| 50 | Implemented locally | Claim audit, release notes, evidence files, tests, manifest/checksum audit path; DOI/external freeze still separate. |

Acceptance command for the local foundation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_atlas_core.py
```
