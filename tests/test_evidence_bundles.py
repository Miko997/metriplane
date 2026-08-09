# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metriplane.sentinel.bundles import (
    create_bundle,
    verify_bundle,
    verify_checksums,
    write_checksums,
)
from metriplane.sentinel.engine import evaluate_session
from metriplane.sentinel.incidents import build_incidents
from metriplane.sentinel.registry import load_registry
from metriplane.sentinel.rules import load_rules

CONFIG_OBJECTS = "configs/objects.example.yaml"
CONFIG_RULES = "configs/rules.example.yaml"


def make_frame(ts, frame_id, objects, run_id="bundle_test"):
    objs = [
        {"id": str(o["id"]), "pos_world": o.get("pos"),
         "vel_world": o.get("vel"), "zone": o.get("zone")}
        for o in objects
    ]
    return json.dumps({
        "schema_version": "1.0", "source_backend": "dummy", "run_id": run_id,
        "ts": ts, "frame_id": frame_id, "objects": objs, "events": [],
    })


@pytest.fixture
def scenario(tmp_path):
    """Cart_01 sits in exit_lane → one forbidden_zone incident."""
    lines = [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "main"}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(2.0, 2, [{"id": 7, "pos": [1.1, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(3.0, 3, [{"id": 7, "pos": [1.2, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(4.0, 4, [{"id": 7, "pos": [2.0, 0.0, 0.0], "zone": "main"}]),
    ]
    session = tmp_path / "session.jsonl"
    session.write_text("\n".join(lines) + "\n")

    ruleset = load_rules(CONFIG_RULES)
    registry = load_registry(CONFIG_OBJECTS)
    alerts, _ = evaluate_session(session, ruleset, registry)
    incidents = build_incidents(alerts)
    assert incidents, "scenario must produce at least one incident"
    return {
        "session": session,
        "alerts": alerts,
        "incidents": incidents,
        "incident": incidents[0],
    }


def test_bundle_files_present(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    for name in ["incident.json", "alerts.jsonl", "session_excerpt.jsonl",
                 "trace.csv", "report.md", "report.html", "replay.sh",
                 "CHECKSUMS.sha256", "objects.yaml", "rules.yaml"]:
        assert (out / name).exists(), f"missing {name}"


def test_bundle_replay_sh_executable(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    import os
    assert os.access(out / "replay.sh", os.X_OK)


def test_bundle_verifies_ok(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    ok, messages = verify_bundle(out)
    assert ok, messages
    assert any("incident reproduced" in m for m in messages)
    assert any("checksum verified" in m for m in messages)


def _resign_sentinel_bundle(bundle: Path) -> None:
    write_checksums(bundle, exclude={"CHECKSUMS.sha256"})


def test_bundle_verifier_requires_exactly_one_expected_incident(
    tmp_path: Path,
    scenario,
) -> None:
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"],
        alerts=scenario["alerts"],
        out_dir=out,
        session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS,
        rules_path=CONFIG_RULES,
    )
    incident_path = out / "incident.json"
    expected = json.loads(incident_path.read_text(encoding="utf-8"))
    incident_path.write_text(json.dumps([expected[0], expected[0]]), encoding="utf-8")
    _resign_sentinel_bundle(out)

    ok, messages = verify_bundle(out)

    assert ok is False
    assert any("exactly one expected incident" in message for message in messages)


@pytest.mark.parametrize(
    ("field", "value", "reported_field"),
    [
        ("severity", "critical", "severity"),
        ("status", "open", "status"),
        ("object_ids", ["cart_01", "unexpected"], "object_ids"),
        ("zones", ["exit_lane", "unexpected"], "zones"),
        ("opened_ts", 1.25, "opened_ts"),
        ("closed_ts", 3.25, "closed_ts"),
        ("duration_s", 99.0, "duration_s"),
        ("alert_ids", [], "alert_count"),
    ],
)
def test_bundle_verifier_reports_incident_semantic_mismatches(
    tmp_path: Path,
    scenario,
    field: str,
    value: object,
    reported_field: str,
) -> None:
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"],
        alerts=scenario["alerts"],
        out_dir=out,
        session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS,
        rules_path=CONFIG_RULES,
    )
    incident_path = out / "incident.json"
    expected = json.loads(incident_path.read_text(encoding="utf-8"))
    expected[0][field] = value
    incident_path.write_text(json.dumps(expected), encoding="utf-8")
    _resign_sentinel_bundle(out)

    ok, messages = verify_bundle(out)

    assert ok is False
    assert any(
        f"FAIL incident mismatch: {reported_field} expected" in message
        for message in messages
    )


def test_checked_in_bundle_with_editable_regression_oracle_verifies() -> None:
    bundle = Path("evidence/incidents/INC-0001")

    ok, messages = verify_bundle(bundle)

    assert ok, messages
    assert (bundle / "expected.yaml").is_file()


def test_checked_in_distribution_bundle_verifies() -> None:
    bundle = Path("evidence/incidents/INC-DIST-001")

    ok, messages = verify_bundle(bundle)

    assert ok, messages


def test_bundle_verifier_returns_clean_failure_for_bad_inputs(tmp_path: Path) -> None:
    missing_ok, missing_messages = verify_bundle(tmp_path / "missing")
    assert missing_ok is False
    assert missing_messages

    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "CHECKSUMS.sha256").write_text("not a checksum\n")
    malformed_ok, malformed_messages = verify_bundle(malformed)
    assert malformed_ok is False
    assert any("FAIL" in message for message in malformed_messages)


def test_bundle_creation_refuses_existing_output_without_consent(
    tmp_path: Path,
    scenario,
) -> None:
    out = tmp_path / "bundle"
    out.mkdir()
    sentinel = out / "important.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="without --overwrite"):
        create_bundle(
            incident=scenario["incident"],
            alerts=scenario["alerts"],
            out_dir=out,
            session_path=scenario["session"],
            objects_path=CONFIG_OBJECTS,
            rules_path=CONFIG_RULES,
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"

    create_bundle(
        incident=scenario["incident"],
        alerts=scenario["alerts"],
        out_dir=out,
        session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS,
        rules_path=CONFIG_RULES,
        overwrite=True,
    )
    assert verify_bundle(out)[0] is True
    assert not sentinel.exists()


def test_bundle_verifier_rejects_symlink_before_replay(
    tmp_path: Path,
    scenario,
) -> None:
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"],
        alerts=scenario["alerts"],
        out_dir=out,
        session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS,
        rules_path=CONFIG_RULES,
    )
    outside = tmp_path / "outside.json"
    outside.write_text((out / "incident.json").read_text(encoding="utf-8"))
    (out / "incident.json").unlink()
    (out / "incident.json").symlink_to(outside)

    ok, messages = verify_bundle(out)

    assert ok is False
    assert any("symlink" in message for message in messages)


def test_bundle_sanitizes_copied_runtime_config(tmp_path: Path, scenario) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "camera_device: "
        "rtsp://camera-user:super-secret@camera.local/stream?token=query-secret\n"
        "api_key: nested-secret\n",
        encoding="utf-8",
    )
    out = tmp_path / "bundle"

    create_bundle(
        incident=scenario["incident"],
        alerts=scenario["alerts"],
        out_dir=out,
        session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS,
        rules_path=CONFIG_RULES,
        config_path=config,
    )

    exported = (out / "config.yaml").read_text(encoding="utf-8")
    assert "camera-user" not in exported
    assert "super-secret" not in exported
    assert "query-secret" not in exported
    assert "nested-secret" not in exported
    assert "camera.local/stream" in exported
    assert verify_bundle(out)[0] is True


def test_checksums_detect_tampering(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    # tamper with the report
    (out / "report.md").write_text("tampered")
    errors = verify_checksums(out)
    assert any("report.md" in e for e in errors)


def test_bundle_verify_fails_on_tamper(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    (out / "trace.csv").write_text("garbage")
    ok, _ = verify_bundle(out)
    assert ok is False


def test_bundle_verifier_fails_closed_on_signed_malformed_excerpt(
    tmp_path: Path,
    scenario,
) -> None:
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"],
        alerts=scenario["alerts"],
        out_dir=out,
        session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS,
        rules_path=CONFIG_RULES,
    )
    excerpt = out / "session_excerpt.jsonl"
    excerpt.write_text(
        excerpt.read_text(encoding="utf-8") + "{not-json\n",
        encoding="utf-8",
    )
    _resign_sentinel_bundle(out)

    ok, messages = verify_bundle(out)

    assert ok is False
    assert any("invalid frame record" in message for message in messages)


def test_excerpt_only_contains_window(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    excerpt = (out / "session_excerpt.jsonl").read_text().strip().splitlines()
    assert len(excerpt) >= 1
    for line in excerpt:
        rec = json.loads(line)
        assert isinstance(rec["ts"], (int, float))


def test_excerpt_uses_authoritative_fixed_clock_time(tmp_path: Path) -> None:
    source_rows = [
        make_frame(100.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "main"}]),
        make_frame(101.0, 1, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(102.0, 2, [{"id": 7, "pos": [1.1, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(103.0, 3, [{"id": 7, "pos": [1.2, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(104.0, 4, [{"id": 7, "pos": [2.0, 0.0, 0.0], "zone": "main"}]),
    ]
    rows: list[dict] = []
    for sim_second, source_row in enumerate(source_rows):
        row = json.loads(source_row)
        row["ts_sim_ns"] = sim_second * 1_000_000_000
        rows.append(row)
    session = tmp_path / "fixed-clock-session.jsonl"
    session.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    ruleset = load_rules(CONFIG_RULES)
    registry = load_registry(CONFIG_OBJECTS)
    alerts, _ = evaluate_session(session, ruleset, registry)
    incidents = build_incidents(alerts)
    assert len(incidents) == 1

    out = tmp_path / "bundle"
    create_bundle(
        incident=incidents[0],
        alerts=alerts,
        out_dir=out,
        session_path=session,
        objects_path=CONFIG_OBJECTS,
        rules_path=CONFIG_RULES,
    )

    excerpt = [
        json.loads(line)
        for line in (out / "session_excerpt.jsonl").read_text().splitlines()
        if line
    ]
    assert [row["ts_sim_ns"] for row in excerpt] == [
        row["ts_sim_ns"] for row in rows
    ]
    assert verify_bundle(out)[0] is True


def test_bundle_only_includes_incident_alerts(tmp_path, scenario):
    from metriplane.sentinel.events import read_alerts_jsonl
    out = tmp_path / "bundle"
    inc = scenario["incident"]
    create_bundle(
        incident=inc, alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    bundled = read_alerts_jsonl(out / "alerts.jsonl")
    assert {a.alert_id for a in bundled} == set(inc.alert_ids)
