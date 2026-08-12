# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DATA = Path(__file__).resolve().parent / "data"
DEFAULT_CONFIG = (
    PACKAGE_DATA / "frozen-config.json"
    if (PACKAGE_DATA / "frozen-config.json").is_file()
    else PACKAGE_ROOT / "config" / "frozen-config.json"
)
DEFAULT_LOCK = (
    PACKAGE_DATA / "uv.lock" if (PACKAGE_DATA / "uv.lock").is_file() else PACKAGE_ROOT / "uv.lock"
)

DATASET_REPOSITORY = "robomimic/robomimic_datasets"
DATASET_REVISION = "74fa018461f479cd9fd15b924a16103012096203"
RAW_REPOSITORY_PATH = "v1.5/can/ph/demo_v15.hdf5"
PREPARED_REPOSITORY_PATH = "v1.5/can/ph/low_dim_v15.hdf5"
RAW_SIZE = 64_932_974
RAW_SHA256 = "86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d"
PREPARED_SIZE = 46_889_752
PREPARED_SHA256 = "3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962"

PROJECT_COMMIT = "d309eaecc18acf4152a830a895a6984b8ac71b05"
RAW_ROBOSUITE_COMMIT = "1a8701b90c07c6595ace4af9935d7c5ebe1baed3"
PREPARED_ROBOSUITE_COMMIT = "51cc01785bab80ffeed20da15e67d7dd4140e76a"
DEMO_ID = "demo_0"
FRAME_COUNT = 118
CONTROL_PERIOD_NS = 50_000_000
CONTROL_FREQUENCY_HZ = 20
SOURCE_BACKEND = "external:robomimic_lowdim_prepared_obs"

# Filled from the canonical, pretty-printed config bytes above. Conversion rejects any drift.
FROZEN_CONFIG_SHA256 = "3cfa88b1512215d8545c1404bcc80e18bf780d1dfc899553ccc69c2517c623c5"

EXPECTED_PREPARED_OBS_KEYS = {
    "object",
    "robot0_eef_pos",
    "robot0_eef_quat",
    "robot0_eef_quat_site",
    "robot0_gripper_qpos",
    "robot0_gripper_qvel",
    "robot0_joint_pos",
    "robot0_joint_pos_cos",
    "robot0_joint_pos_sin",
    "robot0_joint_vel",
}
