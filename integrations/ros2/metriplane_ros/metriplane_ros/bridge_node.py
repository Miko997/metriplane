"""Metriplane → ROS 2 bridge node.

Connects to the Metriplane WebSocket stream, and re-publishes each frame (and its alerts /
incidents) onto ROS 2 topics as std_msgs/String JSON payloads. rclpy and websockets are
imported lazily so this module can be imported (and its adapters tested) without ROS 2.

Topics:
    /metriplane/frame_state   std_msgs/String  (full frame JSON)
    /metriplane/alerts        std_msgs/String  (one msg per alert)
    /metriplane/incidents     std_msgs/String  (one msg per incident)
"""
from __future__ import annotations

import asyncio
import json
import threading

from metriplane_ros.msg_adapters import (
    extract_alert_json_strings,
    extract_frame_json,
    extract_incident_json_strings,
)


def _build_node():  # pragma: no cover - requires rclpy
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    class MetriplaneBridge(Node):
        def __init__(self) -> None:
            super().__init__("metriplane_bridge")
            self.ws_url = self.declare_parameter(
                "metriplane_ws_url", "ws://localhost:8765").value
            self.reconnect_s = float(
                self.declare_parameter("reconnect_s", 2.0).value)
            self.publish_full_frame = bool(
                self.declare_parameter("publish_full_frame", True).value)
            self.publish_alerts = bool(
                self.declare_parameter("publish_alerts", True).value)
            self.publish_incidents = bool(
                self.declare_parameter("publish_incidents", True).value)

            self.frame_pub = self.create_publisher(String, "/metriplane/frame_state", 10)
            self.alert_pub = self.create_publisher(String, "/metriplane/alerts", 10)
            self.incident_pub = self.create_publisher(
                String, "/metriplane/incidents", 10)

            self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
            self._thread.start()

        def _run_async_loop(self) -> None:
            asyncio.run(self._connect_loop())

        async def _connect_loop(self) -> None:
            import websockets  # lazy
            while rclpy.ok():
                try:
                    async with websockets.connect(self.ws_url) as ws:
                        self.get_logger().info(f"connected to {self.ws_url}")
                        async for raw in ws:
                            self._handle_frame(raw)
                except Exception as exc:
                    self.get_logger().warning(f"WebSocket reconnect after error: {exc}")
                    await asyncio.sleep(self.reconnect_s)

        def _handle_frame(self, raw: str) -> None:
            try:
                data = json.loads(raw)
            except Exception:
                return
            if self.publish_full_frame:
                m = String()
                m.data = extract_frame_json(data)
                self.frame_pub.publish(m)
            if self.publish_alerts:
                for s in extract_alert_json_strings(data):
                    a = String()
                    a.data = s
                    self.alert_pub.publish(a)
            if self.publish_incidents:
                for s in extract_incident_json_strings(data):
                    i = String()
                    i.data = s
                    self.incident_pub.publish(i)

    return MetriplaneBridge()


def main(args=None) -> None:  # pragma: no cover - requires rclpy
    import rclpy
    rclpy.init(args=args)
    node = _build_node()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
