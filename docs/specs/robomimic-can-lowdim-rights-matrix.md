<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# robomimic Can low-dimensional rights and redistribution matrix

Status: **rights gate GO and fixture/adapter licensing treatment implemented
for the exact MIT-declared dataset revision and modified normalized numeric
fixture; scoped REUSE and local fixture/output path-leak checks pass.**

This is a research-software licensing and provenance record, not legal advice.
It separates source code, dataset bytes, embedded model material, normalized
data, adapter code, rules, and documentation. A public download is not treated
as a license, and the software license is not used as a substitute for the
dataset declaration.

## 1. Frozen rights identities

| Boundary | Primary identity | Declared terms | Decision |
| --- | --- | --- | --- |
| robomimic source code | [`ARISE-Initiative/robomimic`](https://github.com/ARISE-Initiative/robomimic/tree/d309eaecc18acf4152a830a895a6984b8ac71b05) at `d309eaecc18acf4152a830a895a6984b8ac71b05` | [MIT](https://github.com/ARISE-Initiative/robomimic/blob/d309eaecc18acf4152a830a895a6984b8ac71b05/LICENSE) | Inspect as primary evidence. Do not copy upstream implementation into the independently authored adapter. |
| robosuite source code | [`ARISE-Initiative/robosuite`](https://github.com/ARISE-Initiative/robosuite/tree/51cc01785bab80ffeed20da15e67d7dd4140e76a) at prepared boundary `v1.5.1` / `51cc01785bab80ffeed20da15e67d7dd4140e76a`; raw metadata also records `v1.5.0` / `1a8701b90c07c6595ace4af9935d7c5ebe1baed3` | MIT | Inspect field and preparation semantics. Do not package or redistribute robosuite source through this fixture. |
| Official dataset repository | [`robomimic/robomimic_datasets`](https://huggingface.co/datasets/robomimic/robomimic_datasets/tree/74fa018461f479cd9fd15b924a16103012096203) at `74fa018461f479cd9fd15b924a16103012096203` | Immutable dataset card declares `license: mit`; repository is public and ungated; no path-specific override was found | Covers the exact raw and prepared bodies at this revision. Retain MIT notice, source attribution, immutable identity, and modified-data notice for normalized publication. |
| Independently authored Metriplane adapter | `adapters/robomimic_lowdim/` at Git-bound commit `cfc285a3e757fdf742858b1c4cf685c384d01e8b` | MIT through SPDX headers and path-scoped REUSE metadata | Publish as isolated source-specific code. Production conversion/finalization requires its running tracked bytes to equal that commit's adapter tree. No upstream source was copied into it. |

The audited robomimic code commit is an audit identity, not the asserted
generator of the prepared dataset. This generation-provenance limitation does
not alter the separate dataset license declaration or the independently bound
Metriplane adapter identity.

## 2. Material-by-material treatment

| Material | Rights basis / classification | Public repository treatment | Attribution or notice |
| --- | --- | --- | --- |
| Raw HDF5 `v1.5/can/ph/demo_v15.hdf5` | MIT-declared dataset artifact at the immutable revision; 64,932,974 bytes; SHA-256 `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` | **Referenced only.** Do not commit, package, release, or embed it. | Record repository, revision, path, size, hash, license, and acquisition command. |
| Prepared HDF5 `v1.5/can/ph/low_dim_v15.hdf5` | MIT-declared dataset artifact at the same revision; 46,889,752 bytes; SHA-256 `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` | **Referenced only.** Do not commit, package, release, or embed it. | Same immutable attribution; explicitly call `obs` prepared/simulator-derived. |
| Per-demo embedded `model_file` XML | Bytes are embedded within the MIT-declared raw/prepared dataset and used as a provenance witness | **Do not redistribute.** Do not extract it into the fixture, wheel, docs, test data, or release. | Manifest says the XML was an external conversion/audit input only. |
| robomimic / robosuite / MuJoCo source or binaries | Separately licensed upstream software; not needed by the direct-HDF5 adapter | **Excluded.** No source-framework package, source file, simulator binary, or copied implementation in the ordinary wheel or fixture. | Cite exact audit commits in documentation only. |
| Simulator model assets, meshes, textures, robot assets | Potentially separate asset terms; not needed for the portable normalized fixture | **Excluded by project decision.** Do not acquire for this fixture or redistribute. | Source-manifest absence inventory; no claim that dataset MIT relicenses separately distributed upstream assets. |
| Images, rendered video, screenshots | Not needed and may reproduce separately protected visual assets | **Excluded.** | State that the fixture is low-dimensional and image-free. |
| Raw states/actions, rewards, dones, masks, metadata | Dataset fields; most are provenance-only or excluded from conversion | **Do not publish source arrays.** Raw numeric state, actions, outcomes, filters, and model metadata remain outside the fixture. | Manifest inventories what was compared and what was excluded. |
| Normalized Can/TCP numeric session | Modified/derived numeric values from the exact MIT-declared prepared dataset, tied to independent raw witnesses | **GO under MIT** for the narrowly transformed fixture, with source attribution and a conspicuous modified-data notice. | Preserve upstream MIT notice; identify both source artifacts; say coordinates were selected, projected to world XY, given normalized Z=0, renamed, and assigned operator-authored zones. |
| Entity map and normalization report | Independently authored provenance structure containing source identifiers and transformation facts; may include derived audit values | **GO under MIT**, scoped to the fixture. | Cite exact source and mark any copied/derived numeric facts. |
| Operator-authored polygon, waits, domain pack, and work order | Layer-C Metriplane-authored compatibility-test rules | **GO under MIT**. | Prominently distinguish them from source geometry, source timing rules, and official Can success. |
| Expected-outcome record, Atlas reports, evidence, regression | Metriplane-authored test/result material derived from the normalized fixture | **GO under MIT; generated and verified for the frozen scenario.** | State that the expected-outcome record is not Atlas input and the result is not an upstream success/safety decision. The no-incident control has no evidence bundle or regression. |
| Adapter code | Independently authored source-specific code with no copied upstream source | **GO under MIT; implemented and reviewed at `cfc285a3e757fdf742858b1c4cf685c384d01e8b`.** Keep its dependency lock isolated. | SPDX headers and path-scoped REUSE metadata; dependency licenses remain their own. |
| Adapter dependency lock and environment record | Factual dependency identities and independently authored environment description | **GO under MIT** for the record itself; dependencies are not relicensed | Preserve names, versions, hashes, and their upstream licenses. |
| These audit documents | Independently authored factual documentation with primary-source citations | **MIT**, following the repository documentation treatment | SPDX header; no endorsement or legal-advice claim. |

## 3. Required modified-data and attribution notice

The shared fixture README and each incident/control durable source manifest make
the following facts readily visible:

1. the source dataset is `robomimic/robomimic_datasets` at immutable revision
   `74fa018461f479cd9fd15b924a16103012096203`;
2. the exact raw and prepared paths, sizes, and SHA-256 values are those in this
   matrix;
3. the dataset card at that revision declares MIT;
4. Metriplane publishes modified/normalized numeric data, not either HDF5 body;
5. modifications select `demo_0` prepared `obs` world-position fields, retain
   X/Y in metres, set normalized Z to zero, discard orientation and source Z,
   rename entities, and assign zones using an operator-authored polygon;
6. raw state and model XML were used only as independent provenance witnesses;
7. source outcomes, actions, `next_obs`, images, and simulator assets are not
   included or used as incident truth;
8. the operator polygon and waits are not official robomimic or robosuite task
   definitions; and
9. neither the source projects nor their maintainers endorse Metriplane.

The fixture retains the repository MIT license text and immutable upstream
references. Calling it simply “Metriplane MIT data” without source attribution
and a modified-data notice would be insufficient even though both the source
grant and implemented fixture treatment use MIT.

## 4. REUSE treatment

New files must receive truthful, narrow REUSE metadata without changing the
license of pre-existing material:

- independently authored adapter source, tests, configuration, and docs:
  `SPDX-License-Identifier: MIT` with the appropriate Metriplane copyright;
- the complete normalized fixture subtree: path-scoped MIT treatment that also
  preserves upstream attribution and the modified-data notice;
- raw HDF5, prepared HDF5, extracted model XML, simulator assets, and upstream
  source: absent, so no repository license stanza is created for them; and
- dependency locks: annotate the record itself without claiming that listed
  packages are MIT or Metriplane-authored.

If inline SPDX comments are incompatible with a deterministic JSON, JSONL,
YAML, or CSV artifact, use a narrow `.reuse/dep5` stanza for the exact path.
Do not use a blanket repository stanza and do not claim that adding a license
file relicenses another project's work.

The implemented `.reuse/dep5` stanzas cover
`adapters/robomimic_lowdim/*` as Metriplane-authored MIT material and
`examples/external_sources/robomimic_lowdim/*` as MIT-treated modified data with
`NOASSERTION` copyright plus the exact source-boundary comment. The fixture
README supplies immutable attribution and a conspicuous modification notice;
`LICENSES/MIT.txt` supplies the repository license text. `reuse 5.0.2
lint-file` passed for the adapter, fixture, and these four MET-18 documents on
2026-08-12. Recursive fixture, installed-run, and ZIP path scans also passed.
The full repository retains pre-existing REUSE debt outside MET-18;
path-scoped success is not a claim of repository-wide compliance.

## 5. Redistribution decision

- Source code: **referenced/inspected, not copied**.
- Raw and prepared HDF5: **referenced, never included**.
- Embedded XML and source/simulator assets: **never included**.
- Normalized numeric fixture: **GO under MIT with attribution and modified-data
  notice**.
- Operator-authored rule pack: **GO under MIT**, explicitly Layer C.
- Independently authored adapter: **GO under MIT**, implemented at Git-bound
  commit `cfc285a3e757fdf742858b1c4cf685c384d01e8b` after copied-code and notice
  review.
- Public claim: one exact transformed trajectory only; no general compatibility,
  official-success, physical-accuracy, safety, endorsement, or independent
  adoption claim.

If the immutable dataset card or path-specific terms change, that does not
alter the frozen revision's recorded identity, but publication must stop until
the exact revision and grant can again be verified. If a later review finds a
path-specific restriction or an obligation that the fixture cannot satisfy,
remove the source-derived fixture bytes and retain acquisition/conversion
documentation only.
