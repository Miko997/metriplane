<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Release drafts

This directory contains owner-reviewable release material. A file marked
**DRAFT — UNPUBLISHED** is preparation, not a statement that a version, date,
artifact hash, DOI, or registry publication exists.

- [v0.4.0.post2 migration and behavior changes](v0.4.0-migration.md)
- [v0.4.0.post2 draft GitHub release notes](v0.4.0-release-notes.md)
- [v0.4.0.post2 draft launch materials and finalization checklist](v0.4.0-launch-materials.md)

The v0.3.0 files below are finalized historical release records:

- [v0.3.0 migration and behavior changes](v0.3.0-migration.md)
- [v0.3.0 GitHub release notes](v0.3.0-release-notes.md)
- [v0.3.0 launch materials and finalization checklist](v0.3.0-launch-materials.md)

Fill v0.4.0.post2 placeholders only from the approved final commit, retained
build-once artifacts, successful workflows, and production registry readback.
The frozen v0.2.0 DOI is never a placeholder for a newer release.

The immutable `v0.4.0` tag is retained as history of the failed publication
attempt. Its qualification stopped before registry publication, so no 0.4.0
package or GitHub Release exists. The immutable `v0.4.0.post1` candidate passed
locked qualification and TestPyPI staging, but production stopped before lease
creation or upload; the required protected-main broker repair retired it
unpublished. Its retained artifacts remain historical and do not qualify
post2.
