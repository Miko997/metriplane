<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# External recording candidate comparison

## Method

The bounded search inspected exactly three official public repositories.
Metadata, repository trees, immutable commits, license files, and recording
objects were checked before any candidate adoption. A candidate had to establish
immutable bytes, recording rights, explicit process-relevant state, stable
identity, one authoritative clock and domain, an exact frame path, authoritative
units, deterministic complete snapshots, portable derivation, and no core
change.

No candidate passed all gates. No candidate recording was converted. The search
stopped after the third rejection as predeclared.

## Decision table

| Priority | Official repository and immutable revision | Recording identity | Metadata facts | Decision | Hard-gate result |
| --- | --- | --- | --- | --- | --- |
| 1 | [`ika-rwth-aachen/omega-prime-ros`](https://github.com/ika-rwth-aachen/omega-prime-ros/tree/cd39f9aeec98a003115acf1077a12f6bd2163efe) at `cd39f9aeec98a003115acf1077a12f6bd2163efe` | [`example/rosbag2/rosbag2_2026_02_27-10_31_09_0.mcap`](https://github.com/ika-rwth-aachen/omega-prime-ros/blob/cd39f9aeec98a003115acf1077a12f6bd2163efe/example/rosbag2/rosbag2_2026_02_27-10_31_09_0.mcap); 19,838,626 bytes; Git blob `55f0dcd01e14cc6b83a0904d22f87a3222edf4c6`; SHA-256 `f9e7edc28012e41635472b12660491170949ef9b950767dcdd29528ee2835733` | rosbag2 v9, MCAP, Jazzy, CDR, 13.273378718 s, 1,166 messages; 145 `EgoData`, 145 `ObjectList`, 869 `/tf`, 7 `/tf_static` | Rejected | Official files do not establish the message-header clock domain or the simulator/input generation identity. The repository MIT license does not state a recording-specific payload and normalized-derivative boundary. |
| 2 | [`TUMFTM/3DVehicleDynamicsStateEstimation`](https://github.com/TUMFTM/3DVehicleDynamicsStateEstimation/tree/14ba6285d1cb8d0cd847a69af4e1981015d48b8e) at `14ba6285d1cb8d0cd847a69af4e1981015d48b8e` | [`vegas24_pub/vegas24_pub.mcap`](https://github.com/TUMFTM/3DVehicleDynamicsStateEstimation/blob/14ba6285d1cb8d0cd847a69af4e1981015d48b8e/vegas24_pub/vegas24_pub.mcap); 95,351,438 bytes; Git blob `481a208c7b44376e4587b1c06f04bb1efd0983bd`; SHA-256 `bfbf93ee7e0eeebb66cebf89bee39a37772ea273b61f18bfd909c39ba817c266` | rosbag2 v5, MCAP, CDR, 86.558537056 s, 200,884 messages; odometry, IMU, wheel, steering, brake, drivetrain, and status streams; no `/tf` or `/tf_static` | Rejected | No TF2 path exists for the proposed profile, no bounded multi-entity workcell snapshot is documented, the header clock domain is not declared, and recording-specific derived-state rights are not explicit. |
| 3 | [`AIT-Assistive-Autonomous-Systems/postgis_ros_bridge_demo_workspace`](https://github.com/AIT-Assistive-Autonomous-Systems/postgis_ros_bridge_demo_workspace/tree/8c17a9830f88154f52f26ab96d93e462c8796827) at `8c17a9830f88154f52f26ab96d93e462c8796827` | [`roscon_demo_gnss_imu_0.mcap`](https://github.com/AIT-Assistive-Autonomous-Systems/postgis_ros_bridge_demo_workspace/blob/8c17a9830f88154f52f26ab96d93e462c8796827/src/postgis_ros_bridge_demo/data/roscon_demo_gnss_imu/roscon_demo_gnss_imu_0.mcap); Git LFS OID and SHA-256 `798011d1b0235d113dd1c00b76a826553fbba7e3639d7b35ee648eaaec0269cc`; 36,484,419 bytes; pointer blob `89d1a4f866e3be2225719f83b66cde74f3978a8d` | rosbag2 v5, MCAP, CDR, 459.726300223 s, 96,548 messages; 4,597 `NavSatFix` and 91,951 `Imu`; no pose, object-state, `/tf`, or `/tf_static` stream | Rejected | It contains sensor measurements, not explicit process-relevant object state. No TF path, stable workcell entity mapping, or complete snapshot path exists. The clock domain and recording-specific derivative rights are not declared. |

## Official metadata identities

| Candidate | Metadata path | Git blob |
| --- | --- | --- |
| Omega Prime ROS | [`example/rosbag2/metadata.yaml`](https://github.com/ika-rwth-aachen/omega-prime-ros/blob/cd39f9aeec98a003115acf1077a12f6bd2163efe/example/rosbag2/metadata.yaml) | `45f9e03bb4900e837ce15125a8c09f6f19b6f520` |
| TUM vehicle-dynamics recording | [`vegas24_pub/metadata.yaml`](https://github.com/TUMFTM/3DVehicleDynamicsStateEstimation/blob/14ba6285d1cb8d0cd847a69af4e1981015d48b8e/vegas24_pub/metadata.yaml) | `1a9c1ba57929d4784bb46f5125c85a56b21b5091` |
| AIT GNSS/IMU demo | [`metadata.yaml`](https://github.com/AIT-Assistive-Autonomous-Systems/postgis_ros_bridge_demo_workspace/blob/8c17a9830f88154f52f26ab96d93e462c8796827/src/postgis_ros_bridge_demo/data/roscon_demo_gnss_imu/metadata.yaml) | `2b14971aa2fbb71d10460c732ae3e2f7a3c37b04` |

Container timestamps and message rates were not promoted to evaluation clocks.
Repository license files were recorded as evidence but were not silently treated
as recording-specific grants for publishing normalized derivatives.

## Download accounting

Candidate screening was metadata-first. The Omega Prime ROS and TUM payloads
were materialized as immutable Git objects in the bounded audit cache so their
full payload SHA-256 values could be recomputed. Their combined materialized
size was 115,190,064 bytes. The AIT payload was not downloaded; its size and
SHA-256 came from its Git LFS pointer. The total remained below the 2 GB audit
budget. No candidate payload was used for adapter development or conversion.
