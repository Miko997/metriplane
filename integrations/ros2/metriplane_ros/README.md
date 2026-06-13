# metriplane_ros — ROS 2 Bridge

A ROS 2 package that subscribes to the Metriplane WebSocket stream and republishes each
frame, its alerts, and its incidents as `std_msgs/String` JSON topics. It lives **outside**
the core Python package so installing Metriplane never pulls in ROS dependencies.

## Topics

| Topic | Type | Payload |
|---|---|---|
| `/metriplane/frame_state` | `std_msgs/String` | full frame JSON |
| `/metriplane/alerts` | `std_msgs/String` | one message per alert |
| `/metriplane/incidents` | `std_msgs/String` | one message per incident |

## Parameters

`metriplane_ws_url` (default `ws://localhost:8765`), `reconnect_s` (2.0),
`publish_full_frame`, `publish_alerts`, `publish_incidents`.

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
# 1) start Metriplane producing a WebSocket stream (replay or live)
python -m metriplane.cli --config configs/<replay_config>.yaml
# 2) start the bridge
ros2 launch metriplane_ros bridge.launch.py
# 3) verify
ros2 topic list | grep metriplane
ros2 topic echo /metriplane/frame_state --once
ros2 topic echo /metriplane/alerts
```

## Tests (no ROS required)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  integrations/ros2/metriplane_ros/tests
```

The bridge logic that can be tested without ROS lives in `metriplane_ros/msg_adapters.py`
(pure functions). The node (`bridge_node.py`) imports `rclpy`/`websockets` lazily.

## Limitations (MVP)

- JSON `std_msgs/String` messages first — no custom typed messages yet.
- No TF / MarkerArray publishing yet (planned stretch goals).
- Reconnect is a fixed delay loop.
