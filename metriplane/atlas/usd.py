# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.atlas.domain_packs import load_domain_pack


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _iter_frames(path: Path) -> list[dict]:
    frames = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("type") == "run_header":
            continue
        frames.append(data)
    return frames


def _object_rows(frames: list[dict]) -> list[tuple[float, str, tuple[float, float, float], str | None]]:
    rows = []
    for frame in frames:
        objects = frame.get("fused") or frame.get("objects") or []
        for obj in objects:
            pos = obj.get("pos_world") or [0.0, 0.0, 0.0]
            rows.append((float(frame.get("ts", 0.0)), str(obj.get("id")), (float(pos[0]), float(pos[1]), float(pos[2])), obj.get("zone")))
    return rows


def export_usda(run_dir: str | Path, out_path: str | Path | None = None) -> Path:
    run = Path(run_dir)
    manifest = json.loads((run / "atlas_manifest.json").read_text(encoding="utf-8"))
    pack = load_domain_pack(run / "configs")
    source_session = Path(manifest["source_session_jsonl"])
    frames = _iter_frames(source_session)
    rows = _object_rows(frames)
    incidents = [
        json.loads(line)
        for line in (run / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out = Path(out_path) if out_path else run / "twinverify_replay.usda"
    out.parent.mkdir(parents=True, exist_ok=True)
    asset_by_object = pack.assets.by_object_id()
    lines = [
        "#usda 1.0",
        "(",
        '    metersPerUnit = 1',
        '    upAxis = "Z"',
        ")",
        "",
        'def Xform "MetriPlaneAtlasReplay"',
        "{",
        f'    custom string schema_version = "metriplane.atlas.twinverify_usda.v1"',
        f'    custom string run_id = "{_q(str(manifest.get("run_id", "")))}"',
        f'    custom string cell_id = "{_q(str(manifest.get("cell_id", "")))}"',
        '    custom string limitation = "Replay-derived planar state; no Isaac latency or safety claim."',
    ]
    lines.extend([
        '    def Xform "Zones"',
        "    {",
    ])
    for zone in pack.workspace.zones:
        points = ", ".join(f"({float(x):.3f}, {float(y):.3f}, 0)" for x, y in zone.polygon)
        lines.extend([
            f'        def Xform "{_q(zone.zone_id)}"',
            "        {",
            f'            custom string zone_type = "{_q(zone.zone_type)}"',
            f"            custom point3f[] polygon = [{points}]",
            "        }",
        ])
    lines.extend(["    }", '    def Xform "Assets"', "    {"])
    seen_assets = sorted({object_id for _, object_id, _, _ in rows})
    for object_id in seen_assets:
        asset = asset_by_object.get(object_id)
        asset_id = asset.asset_id if asset else f"object_{object_id}"
        asset_type = asset.asset_type if asset else "unknown"
        samples = [(ts, pos, zone) for ts, oid, pos, zone in rows if oid == object_id]
        sample_text = ", ".join(f"{ts:.3f}: ({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f})" for ts, pos, _ in samples)
        zone_text = ", ".join(f"{ts:.3f}:{zone or '-'}" for ts, _, zone in samples)
        first = samples[0][1] if samples else (0.0, 0.0, 0.0)
        lines.extend([
            f'        def Xform "{_q(asset_id)}"',
            "        {",
            f'            custom string asset_type = "{_q(asset_type)}"',
            f'            custom string motion_samples = "{_q(sample_text)}"',
            f'            custom string zone_samples = "{_q(zone_text)}"',
            f"            double3 xformOp:translate = ({first[0]:.3f}, {first[1]:.3f}, {first[2]:.3f})",
            '            uniform token[] xformOpOrder = ["xformOp:translate"]',
            "        }",
        ])
    lines.extend(["    }", '    def Xform "Incidents"', "    {"])
    for incident in incidents:
        lines.extend([
            f'        def Xform "{_q(str(incident.get("incident_id", "incident")))}"',
            "        {",
            f'            custom string incident_type = "{_q(str(incident.get("incident_type", "")))}"',
            f'            custom string title = "{_q(str(incident.get("title", "")))}"',
            f'            custom string event_ids = "{_q(", ".join(incident.get("event_ids", [])))}"',
            "        }",
        ])
    lines.extend(["    }", "}"])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
