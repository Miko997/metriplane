from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="metriplane_ros",
            executable="metriplane_bridge",
            name="metriplane_bridge",
            parameters=[{
                "metriplane_ws_url": "ws://localhost:8765",
                "reconnect_s": 2.0,
                "publish_full_frame": True,
                "publish_alerts": True,
                "publish_incidents": True,
            }],
        )
    ])
