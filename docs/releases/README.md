<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Release records

This directory contains finalized historical release records and
owner-reviewable release preparation material.

- [v0.4.0.post2 migration and behavior changes](v0.4.0-migration.md)
- [v0.4.0.post2 GitHub release notes](v0.4.0-release-notes.md)
- [v0.4.0.post2 launch materials and finalization record](v0.4.0-launch-materials.md)

The v0.3.0 files below are finalized historical release records:

- [v0.3.0 migration and behavior changes](v0.3.0-migration.md)
- [v0.3.0 GitHub release notes](v0.3.0-release-notes.md)
- [v0.3.0 launch materials and finalization checklist](v0.3.0-launch-materials.md)

The finalized v0.4.0.post2 records are bound to the approved release commit,
retained build-once artifacts, production registry readback, and subsequent
controlled broker reconciliation. The frozen v0.2.0 DOI is not attributed to a
newer release.

The immutable `v0.4.0` tag is retained as history of the failed publication
attempt. Its qualification stopped before registry publication, so no 0.4.0
package or GitHub Release exists. The immutable `v0.4.0.post1` candidate passed
locked qualification and TestPyPI staging, but production stopped before lease
creation or upload; the required protected-main broker repair retired it
unpublished. Its retained artifacts remain historical and do not qualify
post2.

The exact v0.4.0.post2 bytes were published and independently read back from
PyPI, then attached unchanged to the GitHub Release. The original production
workflow's final reconciliation job failed closed after publication; its exact
lease quarantine was later resolved through the documented controlled broker
recovery. No additional upload or release identity was created.
