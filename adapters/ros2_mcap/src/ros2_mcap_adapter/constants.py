# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Frozen profile constants."""

from __future__ import annotations

from pathlib import Path

from .schemas import SCHEMA_SHA256

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "frozen-config.json"
DEFAULT_LOCK = PACKAGE_ROOT / "uv.lock"

ADAPTER_ID = "org.metriplane.ros2_mcap_recorded_state"
ADAPTER_VERSION = "1.0.0"
PROFILE_ID = "metriplane.ros2_mcap_recorded_state.v1"
SOURCE_CLASSIFICATION = "FORMAT-ENGINEERING ONLY / SYNTHETIC / NOT EXTERNAL-SOURCE EVIDENCE"
SOURCE_ARTIFACT_ID = "metriplane_synthetic_ros2_mcap_v1"
SOURCE_FILENAME = "metriplane-synthetic-recorded-state-v1.mcap"
DEFAULT_SOURCE = PACKAGE_ROOT / "source" / SOURCE_FILENAME

FRAME_COUNT = 60
FIRST_TIMESTAMP_NS = 1_000_000_000
PERIOD_NS = 100_000_000
PUBLISH_TIME_OFFSET_NS = 1_000_000
LOG_TIME_OFFSET_NS = 2_000_000

TF_TOPIC = "/tf_static"
MATERIAL_TOPIC = "/metriplane/material_pose"
TOOL_TOPIC = "/metriplane/tool_pose"
OUTCOME_TOPIC = "/metriplane/source_outcome"

POSE_SCHEMA_NAME = "geometry_msgs/msg/PoseStamped"
TF_SCHEMA_NAME = "tf2_msgs/msg/TFMessage"
OUTCOME_SCHEMA_NAME = "metriplane_msgs/msg/SourceOutcome"
SCHEMA_ENCODING = "ros2msg"
MESSAGE_ENCODING = "cdr"

EXPECTED_SCHEMA_SHA256 = {
    POSE_SCHEMA_NAME: SCHEMA_SHA256[POSE_SCHEMA_NAME],
    TF_SCHEMA_NAME: SCHEMA_SHA256[TF_SCHEMA_NAME],
    OUTCOME_SCHEMA_NAME: SCHEMA_SHA256[OUTCOME_SCHEMA_NAME],
}

# These values bind conversion to the deterministic source produced by
# generator.py. They are updated only when the frozen source construction changes.
SOURCE_SIZE = 28_735
SOURCE_SHA256 = "c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99"
FROZEN_CONFIG_SHA256 = "a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962"
FROZEN_LOCK_SHA256 = "864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6"

__all__ = [
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "DEFAULT_CONFIG",
    "DEFAULT_LOCK",
    "DEFAULT_SOURCE",
    "EXPECTED_SCHEMA_SHA256",
    "FIRST_TIMESTAMP_NS",
    "FRAME_COUNT",
    "FROZEN_CONFIG_SHA256",
    "FROZEN_LOCK_SHA256",
    "LOG_TIME_OFFSET_NS",
    "MATERIAL_TOPIC",
    "MESSAGE_ENCODING",
    "OUTCOME_SCHEMA_NAME",
    "OUTCOME_TOPIC",
    "PACKAGE_ROOT",
    "PERIOD_NS",
    "POSE_SCHEMA_NAME",
    "PROFILE_ID",
    "PUBLISH_TIME_OFFSET_NS",
    "SCHEMA_ENCODING",
    "SOURCE_ARTIFACT_ID",
    "SOURCE_CLASSIFICATION",
    "SOURCE_FILENAME",
    "SOURCE_SHA256",
    "SOURCE_SIZE",
    "TF_SCHEMA_NAME",
    "TF_TOPIC",
    "TOOL_TOPIC",
]
