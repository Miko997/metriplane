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

ARCHIVE_SIZE = 36_590_010
ARCHIVE_SHA256 = "b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8"
HDF5_SIZE = 29_349_195
HDF5_SHA256 = "03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a"
JSON_SIZE = 228_218
JSON_SHA256 = "16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90"

DATASET_REPOSITORY = "haosulab/ManiSkill_Demonstrations"
DATASET_REVISION = "d674485bbffdd533914e52d272fdda34c0515608"
ARCHIVE_REPOSITORY_PATH = "demos/PickCube-v1.zip"
DATASET_GENERATION_COMMIT = "652ad9353c0223507a938f0e8d990dd6f1c771ad"
CONVERSION_COMMIT = "a4a4f9272ad64b1564035874b605ceb687b63ed8"
CONVERSION_WHEEL_SHA256 = "685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a"

EPISODE_ID = 0
GROUP_NAME = "traj_0"
TRANSITION_COUNT = 74
STATE_COUNT = 75
CONTROL_PERIOD_NS = 50_000_000
CONTROL_FREQUENCY_HZ = 20
SOURCE_BACKEND = "external:maniskill_pickcube_state_restore"
POSE_STREAM_SHA256 = "1c2fe261f0bb2190683900e5b751c9416a18f13b6a6485c45969809bd48860d2"
FROZEN_CONFIG_SHA256 = "2062eb44090276b7933e15600d286f532c15f3399746dbe15738bb0411d5e202"

EXPECTED_DATASETS = {
    "actions": ((74, 8), "float32"),
    "env_states/actors/cube": ((75, 13), "float32"),
    "env_states/actors/goal_site": ((75, 13), "float32"),
    "env_states/actors/table-workspace": ((75, 13), "float32"),
    "env_states/articulations/panda": ((75, 31), "float32"),
    "rewards": ((74,), "float32"),
    "success": ((74,), "bool"),
    "terminated": ((74,), "bool"),
    "truncated": ((74,), "bool"),
}
