<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Rights matrix

This record separates container and tooling terms from recording payload and
normalized-derivative rights. A repository license is evidence. It is not
silently expanded into a recording-specific grant when the payload's provenance
or derivative treatment remains unclear.

| Material | Identified terms | Decision for this work |
| --- | --- | --- |
| Omega Prime ROS repository code | [MIT license](https://github.com/ika-rwth-aachen/omega-prime-ros/blob/cd39f9aeec98a003115acf1077a12f6bd2163efe/LICENSE), blob `6699e708e0cde50ef8ee2a3bdde73485029b748e` | Code terms recorded. No code copied. |
| Omega Prime ROS example recording | Stored in the MIT-licensed repository; README calls it a simulation example | Recording authorship, generator identity, and normalized-derivative publication treatment are not stated at artifact level. Rejected. Source bytes not redistributed. |
| TUM repository code | [GPL-3.0 license](https://github.com/TUMFTM/3DVehicleDynamicsStateEstimation/blob/14ba6285d1cb8d0cd847a69af4e1981015d48b8e/LICENSE), blob `f288702d2fa16d3cdf0035b15a9fcbc552cd88e7` | Code terms recorded. No code copied. |
| TUM Las Vegas recording | Repository README identifies a TUM Autonomous Motorsports recording | No artifact-level recording and normalized-derivative rights statement was found. Rejected independently on technical gates. Source bytes not redistributed. |
| AIT repository code | [Apache-2.0 license](https://github.com/AIT-Assistive-Autonomous-Systems/postgis_ros_bridge_demo_workspace/blob/8c17a9830f88154f52f26ab96d93e462c8796827/LICENSE), blob `261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64` | Code terms recorded. No code copied. |
| AIT GNSS/IMU recording | Git LFS recording in the repository | No artifact-level recording and normalized-derivative rights statement was found. Rejected independently on technical gates. Source bytes not redistributed. |
| MCAP format and Python library | MCAP project MIT terms | Used only in the isolated adapter environment. It grants no rights to an MCAP payload. |
| `std_msgs`, `builtin_interfaces`, and `geometry_msgs` definitions | Apache-2.0 ROS 2 interface texts embedded in the synthetic recording and isolated adapter | Included only for the narrow synthetic profile with their upstream terms. A future external source must identify every consumed schema and its terms. |
| `tf2_msgs/msg/TFMessage` definition | BSD-3-Clause; ROS 2 `geometry2` commit `f6053126926a38ffad5e81588054d793d87fc662`, schema blob `fda1e4d0985406667d26b7b36cbbedc9bb497074`, license blob `d79557eefaf84816a7ce5f6201fa32fac60a69b5` | The exact `Copyright (c) 2008, Willow Garage, Inc. All rights reserved.` notice and complete BSD terms are retained in the adapter's packaged `THIRD_PARTY_NOTICES.md`, source sidecar, generated rights record, and REUSE metadata. |
| TF2 semantics | Technical behavior is implemented independently for the bounded static-transform subset | No ROS or TF2 source code is copied into Metriplane core. |
| Synthetic recording | Metriplane-authored, MIT | May be generated and used for format engineering. It is not external evidence. |
| Synthetic normalized fixture | Metriplane-authored, MIT | May be distributed after exact freeze and inventory validation. |
| Adapter and capability SDK | Independently authored, MIT | Isolated repository packages, excluded from the ordinary Metriplane wheel. |
| Operator rules and reports | Metriplane-authored, MIT | Separate from source facts and source outcome labels. |

No raw candidate recording is included in the repository. No source project,
container library, ROS package, or repository license is presented as endorsing
Metriplane or validating its result.
