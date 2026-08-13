# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-FileCopyrightText: ROS 2 interface definition contributors
# SPDX-License-Identifier: MIT AND Apache-2.0 AND BSD-3-Clause

"""Exact embedded ROS 2 schema identities supported by the profile."""

from __future__ import annotations

from .canonical import sha256_bytes

POSE_STAMPED_SCHEMA = b"""std_msgs/Header header
geometry_msgs/Pose pose
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
================================================================================
MSG: geometry_msgs/Pose
geometry_msgs/Point position
geometry_msgs/Quaternion orientation
================================================================================
MSG: geometry_msgs/Point
float64 x
float64 y
float64 z
================================================================================
MSG: geometry_msgs/Quaternion
float64 x
float64 y
float64 z
float64 w
"""

TF_MESSAGE_SCHEMA = b"""geometry_msgs/TransformStamped[] transforms
================================================================================
MSG: geometry_msgs/TransformStamped
std_msgs/Header header
string child_frame_id
geometry_msgs/Transform transform
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
================================================================================
MSG: geometry_msgs/Transform
geometry_msgs/Vector3 translation
geometry_msgs/Quaternion rotation
================================================================================
MSG: geometry_msgs/Vector3
float64 x
float64 y
float64 z
================================================================================
MSG: geometry_msgs/Quaternion
float64 x
float64 y
float64 z
float64 w
"""

OUTCOME_SCHEMA = b"""std_msgs/Header header
bool success
string result
string alarm
string action
string annotation
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
"""

SCHEMAS = {
    "geometry_msgs/msg/PoseStamped": POSE_STAMPED_SCHEMA,
    "tf2_msgs/msg/TFMessage": TF_MESSAGE_SCHEMA,
    "metriplane_msgs/msg/SourceOutcome": OUTCOME_SCHEMA,
}

SCHEMA_SHA256 = {name: sha256_bytes(data) for name, data in SCHEMAS.items()}

__all__ = ["OUTCOME_SCHEMA", "POSE_STAMPED_SCHEMA", "SCHEMAS", "SCHEMA_SHA256", "TF_MESSAGE_SCHEMA"]
