# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

from metriplane.sentinel.engine import iter_frames
from metriplane.sentinel.events import (
    IncidentRecord,
    RuleAlert,
    write_alerts_jsonl,
    write_incidents_json,
)
from metriplane.trace.store import TraceStore

# Frames within this many seconds before/after the incident window are kept
# in the session excerpt, to give the replay context around the event.
EXCERPT_PAD_S = 2.0
_CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64}) ([ *])(.+)$")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_checksums(bundle_dir: Path, exclude: set[str]) -> Path:
    """Write CHECKSUMS.sha256 over every file in the bundle except `exclude`."""
    lines: list[str] = []
    for p in sorted(bundle_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(bundle_dir).as_posix()
        if rel in exclude:
            continue
        lines.append(f"{_sha256_file(p)}  {rel}")
    out = bundle_dir / "CHECKSUMS.sha256"
    out.write_text("\n".join(lines) + "\n")
    return out


def _safe_checksum_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe checksum path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe checksum path: {value}")
    return path.as_posix()


def verify_checksums(
    bundle_dir: Path,
    *,
    exclude: set[str] | None = None,
) -> list[str]:
    """Return integrity errors for the bundle's exact regular-file inventory."""
    errors: list[str] = []
    bundle = Path(bundle_dir)
    checksum_file = bundle / "CHECKSUMS.sha256"
    if not checksum_file.is_file() or checksum_file.is_symlink():
        return ["CHECKSUMS.sha256 not found"]

    ignored = set(exclude or set())
    ignored.add("CHECKSUMS.sha256")
    inventory: set[str] = set()
    for path in sorted(bundle.rglob("*")):
        rel = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            errors.append(f"bundle symlink is not allowed: {rel}")
        elif path.is_file() and rel not in ignored:
            inventory.add(rel)
        elif not path.is_dir() and not path.is_file():
            errors.append(f"bundle entry is not a regular file: {rel}")

    recorded: dict[str, str] = {}
    for line_number, line in enumerate(
        checksum_file.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        match = _CHECKSUM_RE.fullmatch(line)
        if match is None:
            errors.append(f"malformed checksum entry on line {line_number}")
            continue
        expected, _, raw_rel = match.groups()
        try:
            rel = _safe_checksum_path(raw_rel)
        except ValueError as exc:
            errors.append(f"checksum line {line_number}: {exc}")
            continue
        if rel in ignored:
            errors.append(f"checksum entry is not allowed: {rel}")
            continue
        if rel in recorded:
            errors.append(f"duplicate checksum entry: {rel}")
            continue
        recorded[rel] = expected.lower()

    for rel in sorted(inventory - set(recorded)):
        errors.append(f"file missing checksum entry: {rel}")
    for rel in sorted(set(recorded) - inventory):
        errors.append(f"checksum references missing file: {rel}")
    for rel, expected in recorded.items():
        if rel not in inventory:
            continue
        actual = _sha256_file(bundle / rel)
        if actual != expected:
            errors.append(f"checksum mismatch: {rel}")
    return errors


def _extract_excerpt(session_path: str | Path, start_ts: float, end_ts: float,
                     out_path: Path) -> int:
    """Write frames whose ts is within [start-pad, end+pad] to out_path as JSONL."""
    lo = start_ts - EXCERPT_PAD_S
    hi = end_ts + EXCERPT_PAD_S
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for frame in iter_frames(session_path):
            if lo <= frame.ts <= hi:
                line = frame.model_dump_json(exclude_none=True)
                f.write(line + "\n")
                count += 1
    return count


def _render_report_md(incident: IncidentRecord, alerts: list[RuleAlert],
                      excerpt_frames: int) -> str:
    lines = [
        f"# Incident {incident.incident_id}",
        "",
        f"- **Rule:** `{incident.rule_id}`",
        f"- **Severity:** {incident.severity}",
        f"- **Status:** {incident.status}",
        f"- **Run:** `{incident.run_id or 'unknown'}`",
        f"- **Opened:** {incident.opened_ts}",
        f"- **Closed:** {incident.closed_ts}",
        f"- **Duration:** {incident.duration_s} s",
        f"- **Objects:** {', '.join(incident.object_ids) or '-'}",
        f"- **Zones:** {', '.join(incident.zones) or '-'}",
        "",
        "## Summary",
        "",
        incident.summary,
        "",
        "## Evidence",
        "",
        f"- Alerts in this incident: {len(incident.alert_ids)}",
        f"- Total alerts recorded: {len(alerts)}",
        f"- Session excerpt frames: {excerpt_frames}",
        "",
        "## Reproduce",
        "",
        "```bash",
        "./replay.sh",
        "```",
        "",
        "This re-runs incident detection over the bundled session excerpt and",
        "verifies the incident reproduces and all checksums match.",
        "",
    ]
    return "\n".join(lines)


def _render_report_html(incident: IncidentRecord, md: str) -> str:
    body = (
        md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        f"<title>Incident {incident.incident_id}</title>\n"
        "<style>body{font-family:system-ui,sans-serif;max-width:48rem;"
        "margin:2rem auto;padding:0 1rem;line-height:1.5}"
        "pre{background:#f4f4f4;padding:1rem;overflow:auto;white-space:pre-wrap}"
        "</style></head><body>\n"
        f"<pre>{body}</pre>\n"
        "</body></html>\n"
    )


_REPLAY_SH = """\
#!/usr/bin/env bash
# Self-contained incident reproduction for {incident_id}.
# Re-runs incident detection on the bundled session excerpt and verifies the
# incident reproduces and checksums match.
set -euo pipefail
cd "$(dirname "$0")"

metriplane incidents verify-bundle .
"""


def create_bundle(
    incident: IncidentRecord,
    alerts: list[RuleAlert],
    out_dir: str | Path,
    session_path: str | Path,
    objects_path: str | Path | None = None,
    rules_path: str | Path | None = None,
    zones_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Path:
    """Build a portable, self-contained evidence bundle for one incident."""
    bundle = Path(out_dir)
    bundle.mkdir(parents=True, exist_ok=True)

    # Incident + alerts (only alerts belonging to this incident)
    write_incidents_json([incident], bundle / "incident.json")
    incident_alerts = [a for a in alerts if a.alert_id in set(incident.alert_ids)]
    write_alerts_jsonl(incident_alerts, bundle / "alerts.jsonl")

    # Session excerpt around the incident window
    start = incident.opened_ts
    end = incident.closed_ts if incident.closed_ts is not None else incident.opened_ts
    excerpt_path = bundle / "session_excerpt.jsonl"
    n_frames = _extract_excerpt(session_path, start, end, excerpt_path)

    # Trace CSV for the excerpt
    store = TraceStore(registry_path=objects_path)
    store.load_session(excerpt_path)
    store.export_csv(bundle / "trace.csv")

    # Copy the configs that define the incident
    for src, name in (
        (objects_path, "objects.yaml"),
        (rules_path, "rules.yaml"),
        (zones_path, "zones.yaml"),
        (config_path, "config.yaml"),
    ):
        if src is not None and Path(src).exists():
            shutil.copyfile(src, bundle / name)

    # Reports
    md = _render_report_md(incident, incident_alerts, n_frames)
    (bundle / "report.md").write_text(md)
    (bundle / "report.html").write_text(_render_report_html(incident, md))

    # replay.sh
    replay = bundle / "replay.sh"
    replay.write_text(_REPLAY_SH.format(incident_id=incident.incident_id))
    replay.chmod(0o755)

    # Checksums last (over everything except the checksum file itself)
    write_checksums(bundle, exclude={"CHECKSUMS.sha256"})
    return bundle


def verify_bundle(bundle_dir: str | Path) -> tuple[bool, list[str]]:
    """
    Verify a bundle reproduces its incident and its checksums match.

    Returns (ok, messages). ok is True only if both the incident reproduces
    (same rule_id and object set) and all checksums validate.
    """
    from metriplane.sentinel.engine import evaluate_session
    from metriplane.sentinel.events import read_incidents_json
    from metriplane.sentinel.incidents import build_incidents
    from metriplane.sentinel.registry import load_registry
    from metriplane.sentinel.rules import load_rules

    bundle = Path(bundle_dir)
    messages: list[str] = []
    ok = True

    # 1. checksums
    chk_errors = verify_checksums(bundle)
    if chk_errors:
        ok = False
        for e in chk_errors:
            messages.append(f"FAIL checksum: {e}")
    else:
        messages.append("PASS: checksum verified")

    # 2. reproduce incident
    expected = read_incidents_json(bundle / "incident.json")
    if not expected:
        return False, messages + ["FAIL: no incident in bundle"]
    exp = expected[0]

    rules_path = bundle / "rules.yaml"
    objects_path = bundle / "objects.yaml"
    if not rules_path.exists():
        return False, messages + ["FAIL: rules.yaml missing from bundle"]

    ruleset = load_rules(rules_path)
    registry = load_registry(objects_path) if objects_path.exists() else None
    alerts, _ = evaluate_session(bundle / "session_excerpt.jsonl", ruleset, registry)
    incidents = build_incidents(alerts)

    match = any(
        inc.rule_id == exp.rule_id
        and set(inc.object_ids) == set(exp.object_ids)
        for inc in incidents
    )
    if match:
        messages.append("PASS: incident reproduced")
    else:
        ok = False
        messages.append("FAIL: incident not reproduced")

    return ok, messages
