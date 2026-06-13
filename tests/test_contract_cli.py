from __future__ import annotations

import json

from metriplane.contracts.cli import main as contracts_main

CONTRACT = "configs/contracts/sentinel_demo.yaml"
FIXTURE = "tests/fixtures/contracts/sentinel_minimal_session.jsonl"
EXPECTED = "tests/fixtures/contracts/sentinel_expected.yaml"
OBJECTS = "configs/objects.example.yaml"


def test_validate_returns_zero_for_valid():
    assert contracts_main(["validate", CONTRACT]) == 0


def test_validate_returns_nonzero_for_invalid(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("contract_id: x\nrules:\n  - id: r\n    type: minimum_distance\n")
    assert contracts_main(["validate", str(bad)]) == 1


def test_test_command_passes_against_expected(capsys):
    rc = contracts_main([
        "test", "--contract", CONTRACT, "--input", FIXTURE,
        "--expect", EXPECTED, "--objects", OBJECTS,
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "result=PASS" in out
    assert "false_positives=0" in out
    assert "missed=0" in out


def test_test_command_writes_json_output(tmp_path):
    out_path = tmp_path / "result.json"
    rc = contracts_main([
        "test", "--contract", CONTRACT, "--input", FIXTURE,
        "--expect", EXPECTED, "--objects", OBJECTS, "--output", str(out_path),
    ])
    assert rc == 0
    data = json.loads(out_path.read_text())
    assert data["phase"] == 16
    assert data["pass"] is True
    assert data["false_positives"] == 0
    assert data["missed"] == 0


def test_test_command_detects_mismatch(tmp_path, capsys):
    wrong = tmp_path / "wrong.yaml"
    wrong.write_text("expected_incidents: 1\nrules:\n  - nonexistent_rule\n")
    rc = contracts_main([
        "test", "--contract", CONTRACT, "--input", FIXTURE,
        "--expect", str(wrong), "--objects", OBJECTS,
    ])
    assert rc == 1
    assert "result=FAIL" in capsys.readouterr().out
