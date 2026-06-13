# Incident Evidence Bundles — Phase 06 Evidence

- phase: 06
- feature: evidence_bundles
- module: metriplane/sentinel/bundles.py
- bundle_contents: incident.json, alerts.jsonl, session_excerpt.jsonl, trace.csv, objects.yaml, rules.yaml, (zones.yaml, config.yaml when supplied), report.md, report.html, replay.sh, CHECKSUMS.sha256
- command: `metriplane incidents bundle <incident_id> --session <session.jsonl> --rules configs/rules.example.yaml --objects configs/objects.example.yaml --out evidence/bundles/<id>`
- reproduce: `./replay.sh` inside the bundle re-runs detection on the excerpt and verifies the incident reproduces and all checksums match
- verify command: `metriplane incidents verify-bundle <bundle_dir>`
- expected output:
  - `PASS: checksum verified`
  - `PASS: incident reproduced`
- self-contained: bundle replays without source-tree context (only the `metriplane` CLI is required)
- tests: tests/test_evidence_bundles.py (7 tests: file presence, executable replay.sh, verify OK, tamper detection on report and trace, excerpt window, per-incident alert filtering)
- limitations:
  - Session excerpt keeps a +/- 2.0s pad around the incident window
  - Reproduction match is on rule_id + object set (not exact timestamp equality)
