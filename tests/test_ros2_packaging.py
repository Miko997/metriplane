# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""ROS-free checks for the standalone metriplane_ros package layout."""

from __future__ import annotations

import ast
import configparser
import importlib
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ROS_PACKAGE = ROOT / "integrations" / "ros2" / "metriplane_ros"


def _setup_call_keywords() -> dict[str, ast.AST]:
    tree = ast.parse((ROS_PACKAGE / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    raise AssertionError("setup.py does not call setup()")


def test_setup_py_installs_metriplane_bridge_console_script():
    kwargs = _setup_call_keywords()
    package_expr = ast.unparse(kwargs["packages"])
    entry_points = ast.literal_eval(kwargs["entry_points"])

    assert package_expr == "[package_name]"
    assert (
        "metriplane_bridge = metriplane_ros.bridge_node:main"
        in entry_points["console_scripts"]
    )


def test_setup_cfg_installs_console_scripts_into_ros_libexec_path():
    cfg = configparser.ConfigParser()
    cfg.read(ROS_PACKAGE / "setup.cfg")

    assert cfg["develop"]["script_dir"] == "$base/lib/metriplane_ros"
    assert cfg["install"]["install_scripts"] == "$base/lib/metriplane_ros"


def test_package_xml_declares_ament_python_and_runtime_dependencies():
    package = ET.parse(ROS_PACKAGE / "package.xml").getroot()
    build_tools = {node.text for node in package.findall("buildtool_depend")}
    exec_deps = {node.text for node in package.findall("exec_depend")}
    build_type = package.findtext("export/build_type")

    assert "ament_python" in build_tools
    assert "rclpy" in exec_deps
    assert "std_msgs" in exec_deps
    assert "launch_ros" in exec_deps
    assert build_type == "ament_python"


def test_launch_file_uses_metriplane_bridge_executable_and_expected_parameters():
    text = (ROS_PACKAGE / "launch" / "bridge.launch.py").read_text(encoding="utf-8")

    assert 'executable="metriplane_bridge"' in text
    for name in ("ws_url", "frame_topic", "alerts_topic", "incidents_topic"):
        assert f'DeclareLaunchArgument("{name}"' in text
        assert f'"{name}": LaunchConfiguration("{name}")' in text


def test_bridge_module_exposes_main_without_importing_ros():
    sys.path.insert(0, str(ROS_PACKAGE))
    try:
        bridge_node = importlib.import_module("metriplane_ros.bridge_node")
    finally:
        sys.path.remove(str(ROS_PACKAGE))

    assert callable(bridge_node.main)
