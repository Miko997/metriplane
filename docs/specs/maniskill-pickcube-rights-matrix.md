# ManiSkill PickCube source and redistribution matrix

Status: **preflight decision; no raw source bytes or normalized fixture have
been committed.**

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
