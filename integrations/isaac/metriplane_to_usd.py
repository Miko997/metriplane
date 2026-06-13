#!/usr/bin/env python3
"""Export Metriplane traces + incidents into a USD (.usda) replay scene.

Pure Python, no NVIDIA software required. The output `.usda` is a 2D floor replay that can
be opened in Omniverse / Isaac Sim, or inspected as text.

Coordinate mapping (documented): USD X = Metriplane X, USD Y = Metriplane Y, USD Z = 0.
This is a flat floor-plane replay.

Example:
    python integrations/isaac/metriplane_to_usd.py \\
        --run-dir evidence/incidents/INC-0001 \\
        --out /tmp/metriplane_replay.usda
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

# type -> display color (RGB 0..1)
_TYPE_COLOR = {
    "cart": (0.2, 0.5, 0.9),
    "pallet": (0.95, 0.6, 0.1),
    "human_proxy": (0.9, 0.2, 0.2),
    "robot": (0.2, 0.8, 0.3),
    "robot_proxy": (0.2, 0.8, 0.3),
}
_DEFAULT_COLOR = (0.6, 0.6, 0.6)


def _find(run_dir: Path, names: list[str]) -> Path | None:
    for n in names:
        p = run_dir / n
        if p.exists():
            return p
    return None


def _registry_map(run_dir: Path) -> dict[int, dict]:
    p = _find(run_dir, ["objects.yaml", "object_registry.yaml"])
    if p is None:
        return {}
    try:
        import yaml
        data = yaml.safe_load(p.read_text())
        return {int(e["marker_id"]): e for e in data.get("objects", [])}
    except Exception:
        return {}


@dataclass
class ObjectTrack:
    object_id: str
    type: str
    samples: list[tuple[int, float, float]] = field(default_factory=list)  # (frame, x, y)


def load_traces(run_dir: str | Path) -> tuple[list[ObjectTrack], str | None]:
    """Build per-object position time-series from a session JSONL in run_dir."""
    from metriplane.sentinel.engine import iter_frames

    run = Path(run_dir)
    session = _find(run, ["session_excerpt.jsonl", "session.jsonl",
                          "traces/object_traces.jsonl"])
    if session is None:
        raise FileNotFoundError(f"no session JSONL found under {run}")
    reg = _registry_map(run)

    tracks: dict[str, ObjectTrack] = {}
    run_id: str | None = None
    for idx, frame in enumerate(iter_frames(session)):
        if frame.run_id:
            run_id = frame.run_id
        observed = frame.fused if frame.fused else frame.objects
        for o in observed:
            if o.pos_world is None:
                continue
            try:
                mid = int(o.id)
            except (TypeError, ValueError):
                mid = None
            entry = reg.get(mid) if mid is not None else None
            oid = entry["object_id"] if entry else f"marker_{o.id}"
            otype = entry["type"] if entry else "unknown"
            tr = tracks.get(oid)
            if tr is None:
                tr = ObjectTrack(object_id=oid, type=otype)
                tracks[oid] = tr
            tr.samples.append((idx, o.pos_world[0], o.pos_world[1]))
    return [tracks[k] for k in sorted(tracks)], run_id


def load_incidents(run_dir: str | Path) -> list[dict]:
    run = Path(run_dir)
    p = _find(run, ["incident.json", "incidents/incidents.json", "incidents.json"])
    if p is None:
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _usd_name(s: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s) or "obj"


def _sanitize(s: str) -> str:
    return s.replace("\\", "/").replace('"', "'")


def write_usda_replay(*, run_dir: str | Path, output_path: str | Path,
                      scale: float = 1.0, fps: float = 30.0) -> dict:
    run = Path(run_dir)
    tracks, run_id = load_traces(run)
    incidents = load_incidents(run)

    n_frames = max((t.samples[-1][0] for t in tracks if t.samples), default=0)

    lines: list[str] = []
    lines.append("#usda 1.0")
    lines.append("(")
    lines.append('    defaultPrim = "World"')
    lines.append('    upAxis = "Z"')
    lines.append(f"    timeCodesPerSecond = {fps}")
    lines.append("    startTimeCode = 0")
    lines.append(f"    endTimeCode = {n_frames}")
    lines.append("    customLayerData = {")
    lines.append(f'        string metriplane_run_id = "{_sanitize(run_id or "unknown")}"')
    lines.append(f'        string metriplane_source = "{_sanitize(str(run))}"')
    lines.append('        string metriplane_coordinate_mapping = "USD_X=X, USD_Y=Y, USD_Z=0 (2D floor)"')
    lines.append("    }")
    lines.append(")")
    lines.append("")
    lines.append('def Xform "World"')
    lines.append("{")

    # Floor
    lines.append('    def Cube "Floor"')
    lines.append("    {")
    lines.append("        double size = 1")
    lines.append("        float3 xformOp:scale = (20, 20, 0.01)")
    lines.append('        uniform token[] xformOpOrder = ["xformOp:scale"]')
    lines.append("        color3f[] primvars:displayColor = [(0.15, 0.15, 0.18)]")
    lines.append("    }")
    lines.append("")

    # Objects
    lines.append('    def Xform "Objects"')
    lines.append("    {")
    for tr in tracks:
        color = _TYPE_COLOR.get(tr.type, _DEFAULT_COLOR)
        name = _usd_name(tr.object_id)
        lines.append(f'        def Sphere "{name}"')
        lines.append("        {")
        lines.append("            double radius = 0.2")
        lines.append(f'            custom string metriplane:object_id = "{_sanitize(tr.object_id)}"')
        lines.append(f'            custom string metriplane:type = "{_sanitize(tr.type)}"')
        lines.append(f"            color3f[] primvars:displayColor = [{color}]")
        lines.append("            double3 xformOp:translate.timeSamples = {")
        for frame_idx, x, y in tr.samples:
            lines.append(f"                {frame_idx}: ({x * scale}, {y * scale}, 0),")
        lines.append("            }")
        lines.append('            uniform token[] xformOpOrder = ["xformOp:translate"]')
        lines.append("        }")
    lines.append("    }")
    lines.append("")

    # Incidents
    lines.append('    def Xform "Incidents"')
    lines.append("    {")
    for inc in incidents:
        iid = inc.get("incident_id", "incident")
        name = _usd_name(iid)
        # place marker at first object's first sample, else origin
        mx, my = 0.0, 0.0
        inc_objs = set(inc.get("object_ids", []))
        for tr in tracks:
            if tr.object_id in inc_objs and tr.samples:
                mx, my = tr.samples[0][1], tr.samples[0][2]
                break
        summary = _sanitize(str(inc.get("summary", "")))
        lines.append(f'        def Cube "{name}"')
        lines.append("        {")
        lines.append("            double size = 0.4")
        lines.append("            color3f[] primvars:displayColor = [(1, 0, 0)]")
        lines.append(f'            custom string metriplane:incident_id = "{_sanitize(iid)}"')
        lines.append(f'            custom string metriplane:summary = "{summary}"')
        lines.append(f"            float3 xformOp:translate = ({mx * scale}, {my * scale}, 0.5)")
        lines.append('            uniform token[] xformOpOrder = ["xformOp:translate"]')
        lines.append("        }")
    lines.append("    }")
    lines.append("}")
    lines.append("")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))

    manifest = {
        "run_id": run_id,
        "source": str(run),
        "output": str(out),
        "fps": fps,
        "scale": scale,
        "frames": n_frames + 1,
        "coordinate_mapping": "USD_X=X, USD_Y=Y, USD_Z=0 (2D floor)",
        "object_ids": [t.object_id for t in tracks],
        "incident_ids": [i.get("incident_id") for i in incidents],
    }
    manifest_path = out.with_name("metriplane_replay_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("metriplane_to_usd")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--fps", type=float, default=30.0)
    args = p.parse_args(argv)

    out = args.out or str(Path(args.run_dir) / "isaac" / "metriplane_replay.usda")
    manifest = write_usda_replay(run_dir=args.run_dir, output_path=out,
                                 scale=args.scale, fps=args.fps)
    print(f"wrote USD replay: {out}")
    print(f"objects: {len(manifest['object_ids'])}  "
          f"incidents: {len(manifest['incident_ids'])}  frames: {manifest['frames']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
