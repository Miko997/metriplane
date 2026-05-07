#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

CFG="${1:-config.m8_fusion_live.yaml}"

# 1) Start fusion (THIS is the only process that touches cameras)
python tools/run_fusion_yaml.py "$CFG" &
PID_FUSION=$!

# give WS server time
sleep 1.2

# 2) Start WS viewer (topdown + cam diagnostics)
python tools/ws_viewer_multi.py --url ws://127.0.0.1:8765 --bounds="-0.05,1.15,-0.05,0.45" &
PID_VIEW=$!

# 3) Start ROS2 bridge
# IMPORTANT: run in a shell that has ROS sourced.
(
  source /opt/ros/jazzy/setup.bash
  source ~/src/metriplane/ros2_ws/install/setup.bash
  ros2 launch metriplane_ros2_bridge metriplane_bridge.launch.py
) &
PID_ROS=$!

echo
echo "== RUNNING =="
echo "Fusion PID:  $PID_FUSION"
echo "Viewer PID:  $PID_VIEW"
echo "ROS2 PID:    $PID_ROS"
echo
echo "Now open Omniverse and run:"
echo "  metriplane-omniverse-ext/tools/live_ws_playback.py"
echo "or your story script."
echo
echo "Press Ctrl+C here to stop everything."

cleanup() {
  echo "[demo] stopping..."
  kill -INT "$PID_VIEW" "$PID_ROS" "$PID_FUSION" 2>/dev/null || true
  wait "$PID_VIEW" 2>/dev/null || true
  wait "$PID_ROS" 2>/dev/null || true
  wait "$PID_FUSION" 2>/dev/null || true
}
trap cleanup INT TERM

wait "$PID_VIEW"
cleanup
