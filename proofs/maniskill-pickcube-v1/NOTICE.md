<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# Notice and artifact boundary

This proof combines references, modified/derived fixture data, independently
authored software, proof documentation, and generated Metriplane results. They
do not all have the same origin or licensing treatment. This notice describes
those boundaries; it does not replace the licenses or provenance records.

## Upstream source references

The source demonstration was not created by Metriplane or Miko Parkkinen. It is
identified as one official ManiSkill Demonstrations `PickCube-v1`
motion-planning episode from dataset revision
`d674485bbffdd533914e52d272fdda34c0515608`:

- ManiSkill project, conversion source release `v3.0.1`, commit
  `a4a4f9272ad64b1564035874b605ceb687b63ed8`;
- ManiSkill Demonstrations dataset,
  <https://huggingface.co/datasets/haosulab/ManiSkill_Demonstrations/tree/d674485bbffdd533914e52d272fdda34c0515608>;
- dataset-generation package ManiSkill `3.0.0b4`, commit
  `652ad9353c0223507a938f0e8d990dd6f1c771ad`.

The dataset card at the pinned revision declares `apache-2.0`. No standalone
dataset `LICENSE` file was found at that revision. The exact source URI,
identity, byte size, SHA-256, permission basis, and citation are retained in
the fixture manifests. `proof-record.json` retains the proof-facing source
identities and rights summary.

The following source material is referenced but **not included** in this proof
or its fixture trees:

- the 36,590,010-byte `PickCube-v1.zip` archive;
- the 29,349,195-byte source HDF5 trajectory;
- the 228,218-byte source JSON metadata;
- Panda robot, table, environment, URDF, GLB, or other simulator assets;
- simulator packages and checkpoints;
- source actions and raw source payloads;
- screenshots, videos, rendered images, and camera data.

Anyone performing the optional Level-B conversion obtains the upstream
materials separately and remains responsible for their upstream terms.

## Modified/derived portable fixtures

The canonical incident and control fixture trees are:

- `examples/external_sources/maniskill_pickcube/incident`
- `examples/external_sources/maniskill_pickcube/control`

Their normalized coordinates are modified/derived data. The adapter restores
named source state, selects the cube and Panda TCP, copies source-world X/Y,
sets normalized Z to `0.0`, discards orientation and other excluded fields,
assigns zones against an operator-authored polygon, and emits a fixed
state-index clock. The goal pose is inert provenance and operator rationale,
not a normalized process object.

These fixtures are treated separately under Apache-2.0 attribution and
modified-data notice through repository REUSE metadata. That fixture-scoped
treatment does not change the Metriplane repository or proof documentation as
a whole to Apache-2.0 and does not imply that the upstream project authored or
approved the normalization or Metriplane rules.

## Adapter software

`adapters/maniskill_pickcube/` is independently authored source-specific
adapter software under the MIT License. Its frozen public implementation is
identified by commit `95d1134d9fb9273318c552c507952f1c5c26877e`.
It does not copy upstream ManiSkill implementation into Metriplane. Its pinned
dependencies retain their own notices and terms.

The adapter is conversion tooling, not a Metriplane runtime dependency. The
portable Level-A proof does not install or require ManiSkill, SAPIEN, Torch,
h5py, Vulkan, or the adapter.

## Proof documentation and generated artifacts

This proof documentation, schema, standard-library reproduction wrapper, and
proof-building/validation tooling are independently authored and use the
repository's MIT licensing where recorded by SPDX metadata. Generated
validation summaries, run summaries, checksums, environment records, incident
evidence, and regression results retain their path-specific license
classification in `proof-record.json`.

An incident evidence archive and generated incident regression are included
only because the recorded incident occurred. No control evidence archive,
regression, empty placeholder, or substitute artifact is created: the control
produced no incident.

## Claim and attribution boundary

The target polygon and relative waits `0.20 s` and `0.30 s` are
Metriplane-authored operator rules. They are not upstream source truth or an
official ManiSkill task-success definition. Source reward, success,
termination, truncation, actions, and horizon metadata do not drive normalized
state or Atlas incidents.

This proof is classified as an owner-generated public technical proof. It is
not ManiSkill validation or endorsement and is not an independent external
reproduction. Refer to `CLAIMS.md` before describing its result.

Metriplane has resource identifier `RRID:SCR_028813`. That RRID refers to the
Metriplane resource, not specifically to this proof package. This proof has no
DOI. Its proposed Git tag `maniskill-pickcube-proof-v1` is pending merge,
explicit owner approval, and final verification; no stable-tag claim is made
while this remains a candidate. The exact final proof commit is recorded in
`proof-record.json`; CFF 1.2 has no dedicated Git-commit field, so no
unsupported field is invented in `CITATION.cff`.
