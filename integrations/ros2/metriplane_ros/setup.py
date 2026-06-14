# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from setuptools import setup

package_name = "metriplane_ros"

setup(
    name=package_name,
    version="0.2.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/bridge.launch.py"]),
    ],
    install_requires=["setuptools", "websockets"],
    zip_safe=True,
    maintainer="Miko Parkkinen",
    maintainer_email="Miko.parkkinen99@gmail.com",
    description="ROS 2 bridge for Metriplane frames/alerts/incidents.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "metriplane_bridge = metriplane_ros.bridge_node:main",
        ],
    },
)
