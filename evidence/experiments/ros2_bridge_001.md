# ROS 2 Bridge — Phase 08 Evidence

- phase: 08
- feature: ros2_bridge
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: integrations/ros2/metriplane_ros/ (separate from core; no ROS dep in core install)

## Commands run

```bash
# ROS-free adapter tests (core suite + package tests)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_ros2_msg_adapters.py \
  tests/test_ros2_packaging.py \
  integrations/ros2/metriplane_ros/tests/test_msg_adapters.py
```

Result: 18 passed.

## What was built

- `metriplane_ros/msg_adapters.py` — pure functions: `extract_frame_json`,
  `extract_alert_json_strings` (top-level and Sentinel `metrics.sentinel.alerts`),
  `extract_incident_json_strings`, `extract_object_summary`.
- `metriplane_ros/bridge_node.py` — `MetriplaneBridge(Node)` connecting to the Metriplane
  WebSocket, publishing `/metriplane/frame_state`, `/metriplane/alerts`,
  `/metriplane/incidents`; background asyncio loop with reconnect; rclpy/websockets
  imported lazily.
- `package.xml`, `setup.py`, `setup.cfg`, `resource/metriplane_ros`,
  `launch/bridge.launch.py`.

## Topics

```
/metriplane/frame_state   std_msgs/String
/metriplane/alerts        std_msgs/String
/metriplane/incidents     std_msgs/String
```

## Limitations / pending

- ROS end-to-end smoke (`colcon build` + `ros2 topic echo`) is a manual step on a ROS 2
  host; **this evidence covers the ROS-free adapter logic and package structure**, not a
  live `ros2 topic echo` capture.
- MVP uses JSON `std_msgs/String`; custom messages and TF are future work.
