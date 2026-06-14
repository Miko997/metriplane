<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane v0.1.3 Proof Check Signoff

Release name: MetriPlane v0.1.3 — Paper B Provenance-Synchronized Evidence Release

Paper title: **Benchmarking Camera-First Planar Digital Twins: A Reproducible Protocol and MetriPlane Evaluation**

## Clean Checkout

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
git fetch --tags
git checkout v0.1.3
```

## Release Identity

| Field | Value |
|---|---|
| Release tag | `v0.1.3` |
| Prior canonical evidence release | `v0.1.2` |
| Initial public release | `v0.1.0` |
| Commit | resolved by the v0.1.3 tag target (`git rev-parse v0.1.3^{commit}`) |
| Release date | `2026-05-18` |
| Archival DOI | Not claimed; pending |

## Verification Commands

```bash
sha256sum -c evidence/CHECKSUMS.sha256
python scripts/audit_evidence.py
```

## Verification Results

| Check | Result |
|---|---|
| SHA256 verification | PASS on local release-tree validation with `sha256sum -c evidence/CHECKSUMS.sha256`. |
| Manifest verification | PASS on local release-tree validation with `python scripts/audit_evidence.py`; manifest paths, release tag, checksums, and file coverage are checked. |
| CSV metric verification | PASS on local release-tree validation with `python scripts/audit_evidence.py`; canonical manifest metrics are recomputed from the CSV artifacts. |

## Known Limitations

- Planar XY tracking only; world `Z=0`.
- ArUco/fiducial markers are required.
- Marker continuity is not marker-free recognition or general re-identification.
- Live evaluation uses a small workspace and the primary marker set IDs 4, 7, and 12.
- Fusion jitter is stability evidence only; absolute fused accuracy is not measured by `fusion_jitter_001.csv`.
- GPU benchmark scope is fusion compute only for tested N=1-1000 workloads.
- Zone dwell and transitions are applied analytics, not a manually annotated ground-truth zone benchmark.
- Large raw JSONL sessions may be archived outside Git and should be checked against recorded hashes when present.
- No peer-reviewed publication, accepted paper, archival DOI, or ACM artifact badge is claimed for this release.

The patch from v0.1.2 to v0.1.3 corrects stale documentation, manifest values, title metadata, citation metadata, and provenance hygiene. It does not introduce new benchmark measurements.
