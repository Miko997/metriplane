# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("ws_url", default_value="ws://127.0.0.1:8765"),
            DeclareLaunchArgument("frame_topic", default_value="/metriplane/frame_state"),
            DeclareLaunchArgument("alerts_topic", default_value="/metriplane/alerts"),
            DeclareLaunchArgument("incidents_topic", default_value="/metriplane/incidents"),
            Node(
                package="metriplane_ros",
                executable="metriplane_bridge",
                name="metriplane_bridge",
                parameters=[
                    {
                        "ws_url": LaunchConfiguration("ws_url"),
                        "frame_topic": LaunchConfiguration("frame_topic"),
                        "alerts_topic": LaunchConfiguration("alerts_topic"),
                        "incidents_topic": LaunchConfiguration("incidents_topic"),
                        "reconnect_s": 2.0,
                        "publish_full_frame": True,
                        "publish_alerts": True,
                        "publish_incidents": True,
                    }
                ],
            ),
        ]
    )
