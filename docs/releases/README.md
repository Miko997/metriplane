<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Release drafts

This directory contains owner-reviewable release material. A file marked
**DRAFT — UNPUBLISHED** is preparation, not a statement that a version, date,
artifact hash, DOI, or registry publication exists.

- [v0.3.0 migration and behavior changes](v0.3.0-migration.md)
- [v0.3.0 GitHub release notes](v0.3.0-release-notes.md)
- [v0.3.0 launch materials and finalization checklist](v0.3.0-launch-materials.md)
- [cumulative v0.4 through v1.0 qualification runbook](qualification-runbook.md)
- [`v0.3.0` observed predecessor genesis](v0.3.0-genesis.json)
- [release evidence-chain genesis](release-evidence-chain-genesis.json)
- [release attempt-index genesis](release-attempt-index-genesis.json)

Fill placeholders only from the approved final commit and successful release
workflow. The frozen v0.2.0 DOI is never a placeholder for a newer release.

The cumulative release framework is owned by `MP2-007`. Publication consumes
its retained qualification, role, approval, and retention records; the
publication workflow, a tag, and synthetic fixtures cannot create release
authority. Live v0.4 qualification remains blocked until MP2-018 supplies the
external non-author approval, two-store read-back, CAS, hosted-protection, and
real merge-path evidence named by the runbook.

The repository-protection validators bound by the MP2-007 work order were
observed at the dependency-complete base with these exact SHA-256 digests:

| Path | SHA-256 |
| --- | --- |
| `tools/capture_repository_protection.py` | `81ce55adcb6ce3591fa5bf63ce5901df5020ae8ed316fd018d8fa7a636f382ab` |
| `tools/check_repository_protection.py` | `b034b515a138d97c5cd446a5370d5797a04cb4ce2e11fd8985a74a2b83a09532` |
