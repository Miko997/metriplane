<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill PickCube source and redistribution matrix

Status: **GO — raw source bytes remain referenced and excluded; the implemented
portable fixtures have separate Apache-2.0 treatment.**

Historical preflight status, preserved as decision history: **preflight
decision; no raw source bytes or normalized fixture have been committed.**

This is a research-software provenance decision, not legal advice. It keeps
source data licensing separate from Metriplane's software license.

| Material | Primary-source basis | Public treatment |
| --- | --- | --- |
| ManiSkill source code | Repository root [Apache-2.0 license](https://github.com/mani-skill/ManiSkill/blob/a4a4f9272ad64b1564035874b605ceb687b63ed8/LICENSE) | May be used in an isolated conversion environment with attribution and license obligations. Do not copy upstream implementation into the adapter unnecessarily. |
| PickCube environment code | Part of the same tagged source tree | Inspect and invoke through the pinned package; do not present it as Metriplane-authored code. |
| Quaternion conversion utility | Upstream third-party notice includes PyTorch3D BSD terms in [`LICENSE-3RD-PARTY`](https://github.com/mani-skill/ManiSkill/blob/a4a4f9272ad64b1564035874b605ceb687b63ed8/LICENSE-3RD-PARTY) | Invoke the installed utility; preserve applicable upstream notices in the adapter environment record. |
| Demonstration HDF5 | Pinned dataset card declares [`license: apache-2.0`](https://huggingface.co/datasets/haosulab/ManiSkill_Demonstrations/blob/d674485bbffdd533914e52d272fdda34c0515608/README.md); no separate dataset `LICENSE` file was found | Reference by immutable repository revision, path, size, and hash. Do not commit, package, or release the raw HDF5. |
| Demonstration JSON | Same dataset declaration | Reference by immutable repository revision, path, size, and hash. Do not commit, package, or release the raw JSON. |
| Panda robot assets | ManiSkill's [license statement](https://github.com/mani-skill/ManiSkill/blob/a4a4f9272ad64b1564035874b605ceb687b63ed8/README.md#license) says assets are CC BY-NC 4.0 | Conversion environment only. Do not redistribute in Git, wheels, releases, or fixture bundles. |
| Table/environment assets | Same upstream asset statement where applicable | Conversion environment only; do not redistribute. |
| Videos and screenshots | Can reproduce protected or non-commercially licensed visual assets | Do not generate or redistribute for this fixture. |
| Checkpoints and motion-planning support assets | Separate asset/data rights may apply | Do not redistribute. They are not needed after stored-state conversion. |
| Derived cube, goal, and TCP coordinates | Derived from the pinned Apache-declared dataset through a documented transformation | Conditional public redistribution is supportable only with source attribution, exact source hashes, an Apache-2.0 reference, and a clear modified/normalized-data notice. Do not imply MIT-only licensing. |
| Portable normalized fixture | Mix of independently authored rules and source-derived coordinate data | Keep data rights separate from the Metriplane code license. Include only contract-declared normalized artifacts after the architecture PAUSE is resolved. |
| Adapter code | Independently authored source-specific code | May use the repository's software license if it contains no copied upstream code and retains notices for invoked dependencies. |
| Audit and evaluator documentation | Independently authored factual description with citations | May be published with primary-source citations and claim limitations. |

## Decision

- Raw HDF5 and JSON classification: **referenced**, never included.
- Raw asset, mesh, image, video, and checkpoint redistribution: **prohibited by
  this project decision**, regardless of whether a narrower permission might
  later be demonstrated.
- Normalized coordinate redistribution: **conditional GO** under separate
  source attribution and modified-data notice, but only after the architecture
  preflight reaches GO.
- Adapter source redistribution: **GO** after implementation, dependency-notice
  review, and verification that no upstream source or assets were copied.
- Package policy: no source data, source assets, ManiSkill, SAPIEN, Torch, h5py,
  or Vulkan package enters the ordinary Metriplane wheel or runtime dependencies.

The absence of a dataset-level `LICENSE` file is disclosed rather than silently
equated with absence of a license declaration. If project counsel or policy
requires a standalone license file for derived-data redistribution, retain the
fixture as acquisition-and-conversion instructions only.

## Implemented treatment — 2026-08-12

The architecture PAUSE was resolved and the conditional treatment above was
implemented without changing the source-rights facts in the matrix.

| Implemented material | Repository treatment |
| --- | --- |
| `adapters/maniskill_pickcube/*` | Independently authored adapter code, tests, configuration, and documentation under MIT; frozen adapter commit `8a0c878be9670423d1610c5d89fb090bcd1d5735` |
| `examples/external_sources/maniskill_pickcube/*` | Public modified/derived fixture subtree under Apache-2.0, with REUSE copyright value `NOASSERTION`, source citation, and modified-data notice |
| `LICENSES/MIT.txt` | Canonical MIT license text for MIT-tagged repository material |
| `LICENSES/Apache-2.0.txt` | Canonical Apache License 2.0 text for the fixture subtree |
| `.reuse/dep5` | Narrow path-based distinction between the MIT adapter and Apache-2.0 fixture; no blanket repository relicensing |

Both fixtures reference, but do not contain, the ZIP, HDF5, JSON, Panda URDF,
table asset, video, screenshot, checkpoint, or source-framework package. Their
normalized coordinates are prominently described as modified/derived data from
the pinned ManiSkill Demonstrations dataset. The operator-authored rules and
metadata are distributed with the fixture under the same fixture-scoped
Apache-2.0 treatment. This does not imply that Metriplane created the source
dataset or that the Metriplane repository as a whole is Apache-2.0.

The frozen fixture identities tying this treatment to the published bytes are:

- frozen configuration SHA-256:
  `2062eb44090276b7933e15600d286f532c15f3399746dbe15738bb0411d5e202`;
- shared session SHA-256:
  `7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`;
- incident fixture fingerprint:
  `b45b71495d50686bcffa3f4e230d0b8325ef1fd0ffdfc2775e53c1f041ad8a04`;
- control fixture fingerprint:
  `cb5c157aec19381affcceb025b375caa6bef1b6179df58ce6faa290312881f68`.

The adapter/fixture REUSE gate is intentionally scoped. The audited global
baseline was already noncompliant with REUSE 3.3 before this implementation:
of 1,068 files, 642 had copyright information and 641 had licensing
information. Much of the missing metadata belongs to pre-existing or frozen
material whose rights cannot truthfully be repaired with a blanket MIT stanza.
The new path-specific metadata does not alter those bytes, and no clean global
`reuse lint` result is claimed. Repository-wide REUSE cleanup remains a
separate rights-inventory task.
