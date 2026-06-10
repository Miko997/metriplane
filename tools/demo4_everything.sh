#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-board_55x40_warehouse_story_v1_fusion}"
CFG="${2:-configs/examples/config.m8_fusion_55x40_live.yaml}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
METRIPLANE_TOP="$(cd "$ROOT/.." && pwd)"
ROS_WS="${METRIPLANE_TOP}/ros2_ws"
RVIZ_CFG="${ROS_WS}/install/metriplane_ros2_bridge/share/metriplane_ros2_bridge/config/metriplane.rviz"

# bounds in meters: xmin,xmax,ymin,ymax
BOUNDS="${BOUNDS:-"-0.05,0.60,-0.05,0.45"}"

export METRIPLANE_SHOW_PREVIEW="${METRIPLANE_SHOW_PREVIEW:-1}"
export METRIPLANE_PREVIEW_SCALE="${METRIPLANE_PREVIEW_SCALE:-1.0}"
export METRIPLANE_TOPDOWN_BOUNDS="${METRIPLANE_TOPDOWN_BOUNDS:-$BOUNDS}"

echo "======================================"
echo "Metriplane Demo 4: EVERYTHING AT ONCE"
echo "======================================"
echo "profile=$PROFILE"
echo "cfg=$CFG"
echo "bounds=$METRIPLANE_TOPDOWN_BOUNDS"
echo "Omniverse: connect to ws://127.0.0.1:8765"
echo

# Ensure the profile is active for apply_profile_defaults()
mkdir -p "$ROOT/calib"
printf "profile: %s\n" "$PROFILE" > "$ROOT/calib/active_profile.yaml"

# free cameras if stuck
fuser -k /dev/video0 /dev/video2 >/dev/null 2>&1 || true

echo "[demo4] starting fusion (WS server + camera capture + preview windows)..."
(
  cd "$ROOT"
  python tools/run_fusion_yaml.py "$CFG"
) &
FUSION_PID=$!

# wait until WS is up
for _ in $(seq 1 80); do
  if ss -lntp 2>/dev/null | grep -q "127.0.0.1:8765"; then break; fi
  sleep 0.1
done

if ! ss -lntp 2>/dev/null | grep -q "127.0.0.1:8765"; then
  echo "[demo4] ERROR: fusion did not start WS server on 127.0.0.1:8765 (fusion likely crashed)."
  kill "$FUSION_PID" >/dev/null 2>&1 || true
  exit 1
fi

# ROS2 bridge + RViz (avoid set -u crash from trace vars)
export COLCON_TRACE="${COLCON_TRACE:-0}"
export AMENT_TRACE_SETUP_FILES="${AMENT_TRACE_SETUP_FILES:-0}"

echo "[demo4] starting ROS2 bridge..."
(
  set +u
  source /opt/ros/jazzy/setup.bash
  source "$ROS_WS/install/setup.bash"
  set -u
  ros2 launch metriplane_ros2_bridge metriplane_bridge.launch.py ws_url:=ws://127.0.0.1:8765
) &
ROS_PID=$!

echo "[demo4] starting RViz..."
(
  set +u
  source /opt/ros/jazzy/setup.bash
  set -u
  rviz2 -d "$RVIZ_CFG"
) &
RVIZ_PID=$!

cleanup() {
  set +e
  kill "$RVIZ_PID" "$ROS_PID" "$FUSION_PID" >/dev/null 2>&1 || true
  fuser -k /dev/video0 /dev/video2 >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo
echo "RUNNING:"
echo "  - Preview windows: Metriplane cam0 + cam1 + Metriplane topdown"
echo "  - Fusion WS: ws://127.0.0.1:8765"
echo "  - RViz should be visible"
echo "Stop: Ctrl+C here"
wait
