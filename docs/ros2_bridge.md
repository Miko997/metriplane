<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ROS 2 Bridge

Metriplane ships an official ROS 2 bridge (`integrations/ros2/metriplane_ros`) that
republishes the Metriplane WebSocket stream onto ROS 2 topics, so robotics systems can
consume object state, alerts, and incidents.

It is packaged **separately** from the core Python package: installing Metriplane does not
require ROS, and the core test suite passes without ROS installed.

## Prerequisites

- ROS 2 (tested target: Jazzy on Ubuntu 24.04)
- `python3-websockets`
- A running Metriplane instance producing a WebSocket stream

## Topics

```
/metriplane/frame_state   std_msgs/String   # full frame JSON
/metriplane/alerts        std_msgs/String   # one message per alert
/metriplane/incidents     std_msgs/String   # one message per incident
```

## Build

```bash
mkdir -p ~/metriplane_ros_ws/src
cp -r integrations/ros2/metriplane_ros ~/metriplane_ros_ws/src/
cd ~/metriplane_ros_ws
colcon build
source install/setup.bash
```

## Run

```bash
ros2 launch metriplane_ros bridge.launch.py
```

## Smoke test

```bash
ros2 topic list | grep metriplane
ros2 topic echo /metriplane/frame_state --once
ros2 topic echo /metriplane/alerts
```

## Testing without ROS

The message adapters are pure functions and are covered by the core suite
(`tests/test_ros2_msg_adapters.py`) and the package tests
(`integrations/ros2/metriplane_ros/tests/test_msg_adapters.py`).

## Limitations

- JSON `std_msgs/String` messages first; no custom typed messages yet.
- No TF or `visualization_msgs/MarkerArray` in the MVP.
- ROS end-to-end smoke is a manual/hardware step; CI covers the adapters only.
