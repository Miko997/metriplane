<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Evidence: ROS 2 manual runtime smoke - 2026-06-14

## Result

PASS

## Test type

Manual runtime smoke test.

## Environment

- OS: Linux miko-21796-2252-20700 6.17.0-35-generic x86_64 GNU/Linux
- Python: Python 3.12.3
- MetriPlane commit: 1ca27a1
- ROS 2 distro: Jazzy
- GPU: NVIDIA GeForce RTX 5070 Ti
- Driver: 580.159.03
- CUDA, if relevant: not measured in this smoke
- Shell: /bin/bash
- Working directory: /home/miko/projects/metriplane-public

## Commands run

```bash
mkdir -p /tmp/metriplane_ros_ws/src
cp -R integrations/ros2/metriplane_ros /tmp/metriplane_ros_ws/src/
source /opt/ros/jazzy/setup.bash
cd /tmp/metriplane_ros_ws
colcon build --event-handlers console_direct+
source /tmp/metriplane_ros_ws/install/setup.bash
ros2 pkg list | grep -E "^(metriplane_ros|rclpy|std_msgs|rosbag2|rosbag2_py)$"
ros2 run metriplane_ros metriplane_bridge --help
python3 <inline websocket frame source on ws://127.0.0.1:8765>
ros2 launch metriplane_ros bridge.launch.py ws_url:=ws://127.0.0.1:8765
ros2 topic list
timeout 12s ros2 topic echo /metriplane/frame_state --once
timeout 12s ros2 topic echo /metriplane/alerts --once
timeout 12s ros2 topic echo /metriplane/incidents --once
timeout 6s ros2 bag record -o /tmp/metriplane_ros2_manual_bag_2026_06_14 \
  /metriplane/frame_state /metriplane/alerts /metriplane/incidents
ros2 bag info /tmp/metriplane_ros2_manual_bag_2026_06_14
```

## Artifacts

- `evidence/experiments/manual_ros2_2026-06-14/environment.txt`
- `evidence/experiments/manual_ros2_2026-06-14/colcon_build_output.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_pkg_list.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_run_output.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ws_frame_source.log`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_launch_output.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_topic_list.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_topic_echo_frame_state.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_topic_echo_alerts.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_topic_echo_incidents.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_bag_record.txt`
- `evidence/experiments/manual_ros2_2026-06-14/ros2_bag_info.txt`
- `evidence/experiments/manual_ros2_2026-06-14/checksums.sha256`
- Temporary rosbag database: `/tmp/metriplane_ros2_manual_bag_2026_06_14` (not tracked)

No screenshot captured.

## Expected behavior

The checked-in ROS 2 bridge package should build, launch, connect to the local
MetriPlane WebSocket frame source, publish `/metriplane/frame_state`,
`/metriplane/alerts`, and `/metriplane/incidents`, and allow `ros2 topic echo`
and `ros2 bag record` to observe messages.

## Observed behavior

The package built and appeared in `ros2 pkg list`. `setup.cfg` installed the
`metriplane_bridge` console script into the ROS 2 libexec path:

```text
Installing metriplane_bridge script to /tmp/metriplane_ros_ws/install/metriplane_ros/lib/metriplane_ros
```

`ros2 run metriplane_ros metriplane_bridge --help` returned:

```text
usage: metriplane_bridge [--ros-args -p ws_url:=ws://127.0.0.1:8765 -p frame_topic:=/metriplane/frame_state -p alerts_topic:=/metriplane/alerts -p incidents_topic:=/metriplane/incidents]
```

The local WebSocket frame source started, `ros2 launch` started the bridge node,
and the bridge connected to `ws://127.0.0.1:8765`. `ros2 topic list` showed:

```text
/metriplane/alerts
/metriplane/frame_state
/metriplane/incidents
/parameter_events
/rosout
```

`ros2 topic echo /metriplane/frame_state --once` received a
`std_msgs/msg/String` JSON frame. The alerts and incidents topics also each
returned one JSON string message. `ros2 bag info` reported `Messages: 112`,
including 56 `/metriplane/frame_state` messages, 28 `/metriplane/alerts`
messages, and 28 `/metriplane/incidents` messages.

## Pass criteria

- ROS 2 package visible: PASS
- `ros2 run metriplane_ros metriplane_bridge --help` works: PASS
- ROS 2 bridge launches: PASS
- `/metriplane/frame_state` topic visible: PASS
- ROS 2 message received: PASS
- ros2 bag recorded expected topics/messages: PASS

## Limitations

- Manual test only.
- One maintainer environment.
- No latency measurement.
- No production runtime guarantee.
- No robot-control claim.
- No safety certification.
- No collision-avoidance claim.
- No simulator physics-correctness claim.
- No full 3D claim.
