<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Review Questions

Use these prompts when reviewing the v0.2.0 evidence package.

- Can a reviewer reproduce the deterministic replay result from checked-in data?
- Does the assembly-cell case generate the listed report, dashboard, graph, trace, bundle, and regression artifacts?
- Does `INC-0001.zip` verify cleanly and include the expected manifest, state segment, event timeline, and report?
- Does the generated regression test pass against the replay/domain-pack evidence?
- Are paper claims limited to evidence listed in `docs/paper/claim_evidence_table.md`?
- Are integration statements bounded to observe-only adapter behavior unless runtime evidence exists?
- Is v0.1.4 described only as the historical DOI baseline?
- Are any Docker, Isaac Sim, safety, robot-control, machine-control, or marker-free tracking claims introduced without evidence?
