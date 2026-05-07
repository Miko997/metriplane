from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Dict, Optional, Tuple

import omni
import omni.kit.commands
from pxr import Gf, UsdGeom

# ---------------------------
# Settings
# ---------------------------
WS_URL = "ws://127.0.0.1:8765"

ROOT = "/World/MetriplaneM6"
PRIM_PREFIX = "id_"  # /World/MetriplaneM6/id_<id>

# Story marker IDs (as STRINGS)
ID_ROBOT = "7"
ID_PALLET_PICKUP = "1"
ID_BOX_PICKUP = "2"
ID_DOCK_DROP_BOX = "3"
ID_PALLET_DROP = "4"

# Distance threshold for "close enough" interactions (meters)
# You requested ~1cm; use slightly higher for stability.
PICKUP_THRESH_M = 0.015

# Fade/delete of disappeared IDs
FADE_START_S = 0.5
DELETE_AFTER_S = 2.5

# Smoothing (0=no smoothing, 0.35 good default)
SMOOTH_ALPHA = 0.35

# Auto-start when imported
AUTO_START = True


_TASK: Optional[asyncio.Task] = None
_STOP = False

_last_pos_units: Dict[str, Tuple[float, float, float]] = {}
_last_seen: Dict[str, float] = {}

# Story state
pallet_state = "none"  # none | on_robot | dropped
box_state = "none"     # none | on_robot | at_dock


# ---------------------------
# Stage helpers
# ---------------------------
def _stage():
    return omni.usd.get_context().get_stage()


def _meters_per_unit() -> float:
    st = _stage()
    try:
        mpu = float(st.GetMetersPerUnit())
        if mpu > 0:
            return mpu
    except Exception:
        pass
    # common default is centimeters
    return 0.01


def _m_to_units(v_m: float) -> float:
    return float(v_m) / _meters_per_unit()


def _xyz_m_to_units(x: float, y: float, z: float) -> Tuple[float, float, float]:
    s = 1.0 / _meters_per_unit()
    return (float(x) * s, float(y) * s, float(z) * s)


def _ensure_xform(path: str):
    st = _stage()
    prim = st.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return prim
    return UsdGeom.Xform.Define(st, path).GetPrim()


def _ensure_cube(path: str):
    st = _stage()
    prim = st.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return prim
    return UsdGeom.Cube.Define(st, path).GetPrim()


def _set_translate(path: str, x: float, y: float, z: float) -> None:
    st = _stage()
    prim = st.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    api = UsdGeom.XformCommonAPI(prim)
    api.SetTranslate(Gf.Vec3d(float(x), float(y), float(z)))


def _set_cube_size(path: str, size_units: float) -> None:
    st = _stage()
    prim = st.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    cube = UsdGeom.Cube(prim)
    try:
        cube.CreateSizeAttr(float(size_units))
    except Exception:
        # already exists
        cube.GetSizeAttr().Set(float(size_units))


def _set_opacity(path: str, opacity01: float) -> None:
    st = _stage()
    prim = st.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    g = UsdGeom.Gprim(prim)
    if not g:
        return
    attr = g.GetDisplayOpacityAttr()
    if not attr:
        attr = g.CreateDisplayOpacityAttr()
    attr.Set([float(max(0.0, min(1.0, opacity01)))])


def _delete_prim(path: str) -> None:
    st = _stage()
    prim = st.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    try:
        omni.kit.commands.execute("DeletePrims", paths=[path])
    except Exception:
        # fallback: set invisible if delete fails
        _set_opacity(path, 0.0)


# ---------------------------
# Motion helpers
# ---------------------------
def _smooth(key: str, x: float, y: float, z: float) -> Tuple[float, float, float]:
    prev = _last_pos_units.get(key)
    if prev is None or SMOOTH_ALPHA <= 0:
        _last_pos_units[key] = (x, y, z)
        return (x, y, z)
    a = float(SMOOTH_ALPHA)
    sx = a * x + (1 - a) * prev[0]
    sy = a * y + (1 - a) * prev[1]
    sz = a * z + (1 - a) * prev[2]
    _last_pos_units[key] = (sx, sy, sz)
    return (sx, sy, sz)


def _dist_xy_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _pos_world_m(obj: dict) -> Optional[Tuple[float, float, float]]:
    pw = obj.get("pos_world")
    if isinstance(pw, (list, tuple)) and len(pw) >= 3:
        try:
            return (float(pw[0]), float(pw[1]), float(pw[2]))
        except Exception:
            return None
    return None


def _id_path(oid: str) -> str:
    return f"{ROOT}/{PRIM_PREFIX}{oid}"


def _payload_path(name: str) -> str:
    return f"{ROOT}/payload_{name}"


def _marker_base_size_m() -> float:
    # printed marker is 9.5cm; you wanted "40% smaller" => 60%
    return 0.095 * 0.60  # 5.7cm


def _ensure_scene_root():
    _ensure_xform(ROOT)


def _ensure_marker_cube(oid: str) -> str:
    path = _id_path(oid)
    _ensure_cube(path)

    base_m = _marker_base_size_m()
    # make robot slightly larger
    size_m = base_m * 1.2 if oid == ID_ROBOT else base_m
    _set_cube_size(path, _m_to_units(size_m))
    return path


def _ensure_payload_cube(name: str, size_m: float) -> str:
    path = _payload_path(name)
    _ensure_cube(path)
    _set_cube_size(path, _m_to_units(size_m))
    return path


# ---------------------------
# Story logic
# ---------------------------
def _update_story(pos_m: Dict[str, Tuple[float, float, float]]) -> None:
    global pallet_state, box_state

    r = pos_m.get(ID_ROBOT)
    if r is None:
        return

    robot_xy = (r[0], r[1])

    p1 = pos_m.get(ID_PALLET_PICKUP)
    p2 = pos_m.get(ID_BOX_PICKUP)
    p3 = pos_m.get(ID_DOCK_DROP_BOX)
    p4 = pos_m.get(ID_PALLET_DROP)

    pallet_size_m = _marker_base_size_m() * 1.1
    box_size_m = _marker_base_size_m() * 0.7

    robot_size_m = _marker_base_size_m() * 1.2
    pallet_z_m = (robot_size_m / 2.0) + (pallet_size_m / 2.0)
    box_z_m = pallet_z_m + (pallet_size_m / 2.0) + (box_size_m / 2.0)

    # (1) Pick up pallet near marker 1
    if pallet_state == "none" and p1 is not None:
        if _dist_xy_m(robot_xy, (p1[0], p1[1])) <= PICKUP_THRESH_M:
            pallet_state = "on_robot"
            print("[M6 story] pallet PICKED UP at marker 1")

    # (2) Pick up box near marker 2 (requires pallet on robot)
    if pallet_state == "on_robot" and box_state == "none" and p2 is not None:
        if _dist_xy_m(robot_xy, (p2[0], p2[1])) <= PICKUP_THRESH_M:
            box_state = "on_robot"
            print("[M6 story] box PICKED UP at marker 2")

    # (3) Drop box at dock marker 3
    if box_state == "on_robot" and p3 is not None:
        if _dist_xy_m(robot_xy, (p3[0], p3[1])) <= PICKUP_THRESH_M:
            box_state = "at_dock"
            print("[M6 story] box DROPPED at marker 3 (dock)")

    # (4) Drop pallet at marker 4 after box delivered
    if pallet_state == "on_robot" and box_state == "at_dock" and p4 is not None:
        if _dist_xy_m(robot_xy, (p4[0], p4[1])) <= PICKUP_THRESH_M:
            pallet_state = "dropped"
            print("[M6 story] pallet DROPPED at marker 4")

    # Apply payload transforms
    pallet_path = _ensure_payload_cube("pallet", pallet_size_m)
    if pallet_state == "on_robot":
        x_u, y_u, _ = _xyz_m_to_units(r[0], r[1], r[2])
        _set_translate(pallet_path, x_u, y_u, _m_to_units(pallet_z_m))
        _set_opacity(pallet_path, 1.0)
    elif pallet_state == "dropped" and p4 is not None:
        x_u, y_u, _ = _xyz_m_to_units(p4[0], p4[1], p4[2])
        _set_translate(pallet_path, x_u, y_u, _m_to_units(pallet_size_m / 2.0))
        _set_opacity(pallet_path, 1.0)
    else:
        _set_opacity(pallet_path, 0.0)

    box_path = _ensure_payload_cube("box", box_size_m)
    if box_state == "on_robot":
        x_u, y_u, _ = _xyz_m_to_units(r[0], r[1], r[2])
        _set_translate(box_path, x_u, y_u, _m_to_units(box_z_m))
        _set_opacity(box_path, 1.0)
    elif box_state == "at_dock" and p3 is not None:
        x_u, y_u, _ = _xyz_m_to_units(p3[0], p3[1], p3[2])
        _set_translate(box_path, x_u, y_u, _m_to_units(box_size_m / 2.0))
        _set_opacity(box_path, 1.0)
    else:
        _set_opacity(box_path, 0.0)


def _fade_and_cleanup(now: float) -> None:
    to_delete = []
    for oid, last in list(_last_seen.items()):
        age = now - last
        path = _id_path(oid)

        if age <= FADE_START_S:
            continue

        if age >= DELETE_AFTER_S:
            to_delete.append((oid, path))
            continue

        t = (age - FADE_START_S) / max(DELETE_AFTER_S - FADE_START_S, 1e-6)
        op = 1.0 - max(0.0, min(1.0, t))
        _set_opacity(path, op)

    for oid, path in to_delete:
        _delete_prim(path)
        _last_seen.pop(oid, None)
        _last_pos_units.pop(oid, None)


# ---------------------------
# Websocket loop
# ---------------------------
async def ws_loop() -> None:
    global _STOP

    _ensure_scene_root()

    try:
        import websockets  # type: ignore
    except Exception as e:
        print("[M6 story] ERROR: websockets not available in Kit:", e)
        print("[M6 story] Enable omni.kit.pipapi and install websockets, or use a Kit build with websockets.")
        return

    print(f"[M6 story] Connecting to {WS_URL} ...")
    while not _STOP:
        try:
            async with websockets.connect(WS_URL, ping_interval=None) as ws:
                print("[M6 story] Connected.")
                async for msg in ws:
                    if _STOP:
                        break

                    try:
                        frame = json.loads(msg)
                    except Exception:
                        continue

                    objs = frame.get("objects", [])
                    if not isinstance(objs, list):
                        continue

                    now = time.time()
                    pos_m: Dict[str, Tuple[float, float, float]] = {}

                    for obj in objs:
                        if not isinstance(obj, dict):
                            continue
                        oid = str(obj.get("id"))
                        pw = _pos_world_m(obj)
                        if pw is None:
                            continue

                        pos_m[oid] = pw
                        _last_seen[oid] = now

                        path = _ensure_marker_cube(oid)
                        x_u, y_u, z_u = _xyz_m_to_units(pw[0], pw[1], pw[2])
                        sx, sy, sz = _smooth(oid, x_u, y_u, z_u)
                        _set_translate(path, sx, sy, sz)
                        _set_opacity(path, 1.0)

                    _update_story(pos_m)
                    _fade_and_cleanup(now)

                    await omni.kit.app.get_app().next_update_async()

        except Exception as e:
            print("[M6 story] Disconnected / retrying:", e)
            await asyncio.sleep(0.5)


def start() -> None:
    global _TASK, _STOP
    _STOP = False
    if _TASK is not None and not _TASK.done():
        print("[M6 story] already running")
        return
    _TASK = asyncio.ensure_future(ws_loop())
    print("[M6 story] started")


def stop() -> None:
    global _STOP, _TASK
    _STOP = True
    if _TASK is not None and not _TASK.done():
        _TASK.cancel()
    _TASK = None
    print("[M6 story] stopped")


if AUTO_START:
    start()
