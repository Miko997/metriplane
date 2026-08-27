# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from metriplane.provenance.run_provenance import redact_persisted_config
from metriplane.schema import frame_time_s
from metriplane.sentinel.engine import iter_frames
from metriplane.sentinel.events import (
    IncidentRecord,
    RuleAlert,
    read_alerts_jsonl,
    read_incidents_json,
    write_alerts_jsonl,
    write_incidents_json,
)
from metriplane.trace.store import TraceStore

# Frames within this many seconds before/after the incident window are kept
# in the session excerpt, to give the replay context around the event.
EXCERPT_PAD_S = 2.0
_CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64}) ([ *])(.+)$")
UNSIGNED_DERIVED_SIDECARS = frozenset({"expected.yaml", "test_result.json", "test_result.md"})
REQUIRED_BUNDLE_FILES = (
    "incident.json",
    "alerts.jsonl",
    "session_excerpt.jsonl",
    "trace.csv",
    "report.md",
    "report.html",
    "replay.sh",
    "objects.yaml",
    "rules.yaml",
    "CHECKSUMS.sha256",
)


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


def validate_bundle_evidence(bundle_dir: str | Path) -> list[str]:
    """Return structural and stored-reference errors for a Sentinel bundle."""
    bundle = Path(bundle_dir)
    if bundle.is_symlink() or not bundle.is_dir():
        return [f"bundle directory does not exist: {bundle}"]

    errors: list[str] = []
    for relative_path in REQUIRED_BUNDLE_FILES:
        path = bundle / relative_path
        if path.is_symlink() or not path.is_file():
            errors.append(f"missing required bundle file: {relative_path}")
    if errors:
        return errors

    try:
        incidents = read_incidents_json(bundle / "incident.json")
        alerts = read_alerts_jsonl(bundle / "alerts.jsonl")
        frames = list(iter_frames(bundle / "session_excerpt.jsonl"))
    except Exception as exc:
        return [f"invalid bundle evidence: {type(exc).__name__}: {exc}"]

    if len(incidents) != 1:
        return [
            (f"incident.json must contain exactly one expected incident; found {len(incidents)}")
        ]
    if not frames:
        errors.append("session_excerpt.jsonl must contain at least one frame")

    incident = incidents[0]
    incident_alert_ids = list(incident.alert_ids)
    bundled_alert_ids = [alert.alert_id for alert in alerts]
    if len(set(incident_alert_ids)) != len(incident_alert_ids):
        errors.append("incident alert IDs must be unique")
    if len(set(bundled_alert_ids)) != len(bundled_alert_ids):
        errors.append("bundled alert IDs must be unique")
    if incident_alert_ids != bundled_alert_ids:
        errors.append(
            "incident alert IDs do not exactly match alerts.jsonl: "
            f"incident={incident_alert_ids}, alerts={bundled_alert_ids}"
        )

    for alert in alerts:
        if alert.run_id != incident.run_id:
            errors.append(
                "incident run_id does not match bundled alert "
                f"{alert.alert_id}: {incident.run_id!r} != {alert.run_id!r}"
            )
    for index, frame in enumerate(frames, start=1):
        if frame.run_id != incident.run_id:
            errors.append(
                "incident run_id does not match session frame "
                f"{index}: {incident.run_id!r} != {frame.run_id!r}"
            )
    return errors


def _extract_excerpt(
    session_path: str | Path, start_ts: float, end_ts: float, out_path: Path
) -> int:
    """Write frames whose ts is within [start-pad, end+pad] to out_path as JSONL."""
    lo = start_ts - EXCERPT_PAD_S
    hi = end_ts + EXCERPT_PAD_S
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for frame in iter_frames(session_path):
            if lo <= frame_time_s(frame) <= hi:
                line = frame.model_dump_json(exclude_none=True)
                f.write(line + "\n")
                count += 1
    return count


def _render_report_md(
    incident: IncidentRecord, alerts: list[RuleAlert], excerpt_frames: int
) -> str:
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
    body = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
    *,
    overwrite: bool = False,
) -> Path:
    """Build a bundle completely before replacing an explicitly approved output."""
    bundle = Path(out_dir)
    sources = [session_path, objects_path, rules_path, zones_path, config_path]
    bundle_resolved = bundle.resolve()
    for source in sources:
        if source is None:
            continue
        source_path = Path(source)
        if not source_path.exists():
            continue
        source_resolved = source_path.resolve()
        if bundle_resolved == source_resolved or bundle_resolved in source_resolved.parents:
            raise ValueError(f"bundle output would replace source input: {source_path}")
    if bundle.exists() or bundle.is_symlink():
        if not overwrite:
            raise ValueError(f"refusing to replace existing bundle without --overwrite: {bundle}")

    bundle.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{bundle.name}-", dir=bundle.parent) as temp_dir:
        temp_root = Path(temp_dir)
        stage = temp_root / "bundle"
        _create_bundle_in_place(
            incident,
            alerts,
            stage,
            session_path,
            objects_path,
            rules_path,
            zones_path,
            config_path,
        )
        backup = temp_root / "previous"
        had_previous = bundle.exists() or bundle.is_symlink()
        if had_previous and not overwrite:
            raise ValueError(
                f"refusing to replace bundle created while staging without --overwrite: {bundle}"
            )
        if had_previous:
            os.replace(bundle, backup)
        try:
            os.replace(stage, bundle)
        except Exception:
            if had_previous and (backup.exists() or backup.is_symlink()):
                os.replace(backup, bundle)
            raise
    return bundle


def _create_bundle_in_place(
    incident: IncidentRecord,
    alerts: list[RuleAlert],
    out_dir: str | Path,
    session_path: str | Path,
    objects_path: str | Path | None = None,
    rules_path: str | Path | None = None,
    zones_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Path:
    """Build a portable, self-contained evidence bundle in a fresh directory."""
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
    ):
        if src is not None and Path(src).exists():
            shutil.copyfile(src, bundle / name)
    if config_path is not None and Path(config_path).exists():
        try:
            import yaml

            raw_config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            sanitized = redact_persisted_config(raw_config)
            (bundle / "config.yaml").write_text(
                yaml.safe_dump(sanitized, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:
            raise ValueError(f"cannot sanitize bundle config: {exc}") from exc

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

    Returns (ok, messages). ok is True only if the single expected incident
    reproduces with the same observable semantics and all checksums validate.
    """
    from metriplane.sentinel.engine import evaluate_session
    from metriplane.sentinel.incidents import build_incidents
    from metriplane.sentinel.registry import load_registry
    from metriplane.sentinel.rules import load_rules

    bundle = Path(bundle_dir)
    messages: list[str] = []
    ok = True

    # 1. checksums. Regression inputs/results are explicitly derived sidecars,
    # not immutable incident evidence, and may be regenerated between checks.
    try:
        chk_errors = verify_checksums(
            bundle,
            exclude=set(UNSIGNED_DERIVED_SIDECARS),
        )
    except Exception as exc:
        return False, [f"FAIL checksum: {type(exc).__name__}: {exc}"]
    if chk_errors:
        for e in chk_errors:
            messages.append(f"FAIL checksum: {e}")
        return False, messages
    else:
        messages.append("PASS: checksum verified")

    evidence_errors = validate_bundle_evidence(bundle)
    if evidence_errors:
        return False, messages + [f"FAIL evidence: {error}" for error in evidence_errors]

    # 2. reproduce incident
    try:
        expected = read_incidents_json(bundle / "incident.json")
        if len(expected) != 1:
            return False, messages + [
                "FAIL: incident.json must contain exactly one expected incident; "
                f"found {len(expected)}"
            ]
        exp = expected[0]

        rules_path = bundle / "rules.yaml"
        objects_path = bundle / "objects.yaml"
        if not rules_path.exists():
            return False, messages + ["FAIL: rules.yaml missing from bundle"]

        ruleset = load_rules(rules_path)
        registry = load_registry(objects_path) if objects_path.exists() else None
        alerts, _ = evaluate_session(bundle / "session_excerpt.jsonl", ruleset, registry)
        incidents = build_incidents(alerts)
    except Exception as exc:
        return False, messages + [f"FAIL: bundle verification error: {type(exc).__name__}: {exc}"]

    if not incidents:
        return False, messages + ["FAIL: no incident reproduced"]

    def mismatches(inc: IncidentRecord) -> list[str]:
        expected_objects = set(exp.object_ids)
        observed_objects = set(inc.object_ids)
        expected_zones = set(exp.zones)
        observed_zones = set(inc.zones)
        fields = (
            ("rule_id", exp.rule_id, inc.rule_id),
            ("run_id", exp.run_id, inc.run_id),
            ("severity", exp.severity, inc.severity),
            ("status", exp.status, inc.status),
            ("object_ids", sorted(expected_objects), sorted(observed_objects)),
            ("zones", sorted(expected_zones), sorted(observed_zones)),
            ("opened_ts", exp.opened_ts, inc.opened_ts),
            ("closed_ts", exp.closed_ts, inc.closed_ts),
            ("duration_s", exp.duration_s, inc.duration_s),
            ("alert_ids", list(exp.alert_ids), list(inc.alert_ids)),
        )
        return [
            f"{field} expected {expected_value!r}, observed {observed_value!r}"
            for field, expected_value, observed_value in fields
            if expected_value != observed_value
        ]

    candidate_mismatches = [(inc, mismatches(inc)) for inc in incidents]
    _, best_mismatches = min(candidate_mismatches, key=lambda item: len(item[1]))
    if not best_mismatches:
        messages.append("PASS: incident reproduced")
    else:
        ok = False
        messages.append("FAIL: incident not reproduced with expected semantics")
        messages.extend(f"FAIL incident mismatch: {mismatch}" for mismatch in best_mismatches)

    return ok, messages
