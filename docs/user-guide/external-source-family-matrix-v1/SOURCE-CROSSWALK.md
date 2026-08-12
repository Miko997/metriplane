<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Source, version, license, and hash crosswalk

This crosswalk belongs to the candidate `external-source-family-matrix-v1` at
public baseline `5606b956e9309802570cfa46857714722fd70187`. A Git object ID is
reported as a revision identity; SHA-256 values identify downloaded or frozen
files. “Recorded” means an earlier frozen audit captured the value but did not
independently download and rehash the complete body during that audit.

## Source and data identities

| Source family | Decision | Code identity and terms | Dataset identity and terms | File identity and verification boundary |
| --- | --- | --- | --- | --- |
| ManiSkill | **GO** | `mani-skill/ManiSkill`; conversion release 3.0.1 at `a4a4f9272ad64b1564035874b605ceb687b63ed8`, generation package 3.0.0b4 at `652ad9353c0223507a938f0e8d990dd6f1c771ad`; Apache-2.0. Conversion wheel SHA-256 `685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a` | `haosulab/ManiSkill_Demonstrations` revision `d674485bbffdd533914e52d272fdda34c0515608`; dataset card declares Apache-2.0 | PickCube-v1 ZIP `b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8`; HDF5 `03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a`; JSON `16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90`; hashes are frozen proof identities |
| CALVIN | **NO-GO** | `mees/calvin` at `fa03f01f19c65920e18cf37398a9ce859274af76`, root MIT; `mees/calvin_env` at `1431a46bd36bde5903fb6345e68b5ccc30def666`, with unresolved MIT-LICENSE versus GPLv3 package-metadata conflict | Separately hosted `calvin_debug_dataset.zip`; no dataset-specific license or terms found | 1,299,150,917 bytes; published SHA-256 `c66d09147e2c806b244f18ea7d61e388d4dac11f828929779437f728d03e1204`. Only about 1.56 MB of unique ranges were inspected; the complete archive was not independently rehashed |
| robomimic | **GO** | `ARISE-Initiative/robomimic` audit commit `d309eaecc18acf4152a830a895a6984b8ac71b05`, MIT; `ARISE-Initiative/robosuite` v1.5.0 at `1a8701b90c07c6595ace4af9935d7c5ebe1baed3` and v1.5.1 at `51cc01785bab80ffeed20da15e67d7dd4140e76a`, MIT | `robomimic/robomimic_datasets` revision `74fa018461f479cd9fd15b924a16103012096203`; immutable dataset card declares MIT | Raw `v1.5/can/ph/demo_v15.hdf5`, 64,932,974 bytes, SHA-256 `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d`; prepared `v1.5/can/ph/low_dim_v15.hdf5`, 46,889,752 bytes, SHA-256 `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962`; both reacquired and rehashed by workflow run `31619957092` |
| MimicGen | **PARTIALLY SUPPORTED** | `NVlabs/mimicgen` at `72bd767c255545f462e7ccfb2731f2e5d4c1d9bb`; v1.0.0 at `ea0988523f468ccf7570475f1906023f854962e9`; separate NVIDIA source terms with a noncommercial research/evaluation restriction. The completed audit did not freeze an exact formal license identifier or version | `amandlek/mimicgen_datasets` revision `33016f8a62c02334f929f2913af8fdd2a8a129e1`; CC BY 4.0 | Candidate `source/square.hdf5`, 16,451,426 bytes, recorded SHA-256 `c917e99362fd9bd11978d6e2642c1ea88272702fbf55b50367ed471febf550e2`; body not downloaded or locally rehashed. No immutable original-raw/preparation chain was completed |
| RoboCasa / RoboCasa365 | **NOT TESTED** | No repository or revision selected or inspected | No dataset selected or inspected | No path, size, or hash exists in this publication |
| ROS 2 / MCAP + TF2 | **NOT TESTED** | No adapter or tooling set selected or audited | No recording, message schema, calibration sidecar, or payload terms selected or inspected | No artifact, revision, path, or hash exists. Any future work requires separate authorization |

The CALVIN **NO-GO** demonstrates that the rights and timing gates rejected an
otherwise plausible mapping. It is not a compatibility result. MimicGen is
partially audited but unimplemented; favorable dataset terms alone do not
establish a source path.

## Published adapter and derivative treatment

| Source family | Public adapter identity | Derived or normalized material | Rights treatment |
| --- | --- | --- | --- |
| ManiSkill | `95d1134d9fb9273318c552c507952f1c5c26877e`; canonical proof tag `maniskill-pickcube-proof-v1` targets `49c3b37057312c89db030386dd2cc68628d92458` | 75-frame, position-only PickCube trajectory fixture; external source bytes are excluded | Adapter and proof metadata are MIT; modified numeric fixture is treated as Apache-2.0 data with attribution and modification notice; separately licensed assets are excluded |
| CALVIN | None | None | Dataset and derived-state redistribution rights remain unresolved |
| robomimic | `cfc285a3e757fdf742858b1c4cf685c384d01e8b`; adapter subtree tree `94f946232a8139b216512ef796af248bc8e2f366` at both adapter commit and baseline | 118-frame, position-only Can trajectory fixture; raw/prepared HDF5, XML, images, video, simulator code, and assets are excluded | Adapter is MIT; normalized numeric derivative is MIT-treated with immutable attribution and modification notice |
| MimicGen | None | None | No derivative was created; code and dataset terms remain separate |
| RoboCasa / RoboCasa365 | None | None | Not tested; no permission is inferred |
| ROS 2 / MCAP + TF2 | None | None | Not tested; software licenses would not establish recording-payload rights |

The complete structured identities and evidence links are authoritative in
[`matrix.json`](matrix.json).
