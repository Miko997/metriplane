#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Runner-safe cleanup check for the localhost Settings page."""

from __future__ import annotations

import os

from metriplane.launcher import (
    _METRIPLANE_KNOWN_PORTS,
    _find_port_owner,
    _get_pgid,
    _is_port_in_use,
    _load_state,
    _stop_pg,
    _wait_for_port_free,
)


def _active_pids_from_state() -> set[int]:
    state = _load_state()
    pids: set[int] = set()
    for key in ("runner", "dashboard", "fusion"):
        pid = (state.get(key) or {}).get("pid")
        if pid:
            pids.add(int(pid))
    return pids


def main() -> int:
    current_pid = os.getpid()
    parent_pid = os.getppid()
    protected_pids = _active_pids_from_state() | {current_pid, parent_pid}
    protected_pgids = {pg for pid in protected_pids if (pg := _get_pgid(pid))}

    print("=== Runner-safe MetriPlane cleanup check ===")
    print("This UI action will not kill the active runner or dashboard.")
    print("For a full restart, use: metriplane restart")

    killed_any = False
    found_any = False
    for port in _METRIPLANE_KNOWN_PORTS:
        if port in (9000, 8088):
            owner = _find_port_owner(port)
            if owner:
                found_any = True
                print(f"port {port}: active UI service pid={owner['pid']} - kept")
            else:
                print(f"port {port}: free")
            continue

        if not _is_port_in_use("127.0.0.1", port):
            print(f"port {port}: free")
            continue

        found_any = True
        owner = _find_port_owner(port)
        if owner is None:
            print(f"port {port}: occupied, owner unknown - skipped")
            continue

        pid = int(owner["pid"])
        pgid = _get_pgid(pid) or pid
        cmd = owner["cmdline"][:120]
        if pid in protected_pids or pgid in protected_pgids:
            print(f"port {port}: active MetriPlane service pid={pid} - kept")
            continue
        if not owner["safe_to_kill"]:
            print(f"port {port}: non-MetriPlane process pid={pid} - skipped")
            print(f"  cmd: {cmd}")
            continue

        print(f"port {port}: stale MetriPlane process pid={pid} - stopping")
        print(f"  cmd: {cmd}")
        _stop_pg(pgid, pid, name=f"port-{port}")
        if _wait_for_port_free(port, timeout=5.0):
            print(f"  released port {port}")
            killed_any = True
        else:
            print(f"  port {port} still occupied after cleanup attempt")

    if killed_any:
        print("\nCleanup complete. Active runner/dashboard were kept online.")
    elif found_any:
        print("\nNo stale process was removed. Active services were kept online.")
    else:
        print("\nNo occupied MetriPlane ports found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
