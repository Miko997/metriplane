#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Run the ROS 2 adapter checks without loading host ROS pytest plugins."""

from __future__ import annotations

import os


def main() -> int:
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    import pytest

    return int(
        pytest.main(
            [
                "-q",
                "tests/test_ros2_msg_adapters.py",
                "tests/test_ros2_packaging.py",
                "integrations/ros2/metriplane_ros/tests/test_msg_adapters.py",
            ]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
