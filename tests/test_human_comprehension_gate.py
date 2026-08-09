# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/validation/first-time-user-comprehension.md"
RESULTS = ROOT / "docs/validation/human-comprehension-results.json"
SCRIPT = ROOT / "scripts/summarize_human_comprehension.py"


def _load_calculator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("human_comprehension", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tester(index: int, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "tester_id": f"fixture-{index}",
        "demo_command_found": True,
        "product_understood": True,
        "report_found": True,
        "time_to_report_seconds": 240,
        "first_failed_command": None,
        "first_confusing_term": None,
        "intervention_required": False,
        "controls_machinery_misconception": False,
        "deterministic_replay_equals_physical_accuracy_misconception": False,
    }
    record.update(overrides)
    return record


def _document(
    testers: list[dict[str, object]],
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "metriplane.human_comprehension_results.v1",
        "candidate_commit": "a" * 40,
        "candidate_version": "0.3.0",
        "materials": {
            "product_page": "readme",
            "installation_instructions": "candidate-wheel",
        },
        "testers": testers,
    }
    payload.update(overrides)
    return payload


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_protocol_preserves_six_questions_and_adds_neutral_probes() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    questions = (
        "1. What problem does Metriplane solve?",
        "2. What data goes in?",
        "3. What comes out?",
        "4. Why is the generated repeatable test useful?",
        "5. Can you run the demo and find the report?",
        "6. Which term was first confusing?",
    )
    assert all(question in text for question in questions)
    assert "README or the release candidate's PyPI-style page" in text
    assert "Do not explain Metriplane before the test" in text
    assert "Does Metriplane control or change the machinery?" in text
    assert "what does it not tell you about the physical measurements?" in text


def test_protocol_requires_privacy_neutral_metadata_and_redaction() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    required = (
        "candidate_commit",
        "candidate_version",
        "materials",
        "<REDACTED>",
        "<PATH>",
        "<USER>",
        "<PRIVATE_URL>",
        "Never record raw credentials",
    )
    assert all(fragment in text for fragment in required)
    assert "## Empty-template baseline" in text
    assert "## Current status" not in text


def test_repository_results_remain_valid_after_real_observations_are_added() -> None:
    calculator = _load_calculator()
    results = calculator.load_results(RESULTS)
    lines, exit_code = calculator.summarize(results)
    output = "\n".join(lines)

    if results["testers"]:
        assert results["candidate_commit"] is not None
        assert results["candidate_version"] is not None
        assert results["materials"] is not None
        assert exit_code in {0, 1}
        assert "MANUAL GATE PENDING" not in output
    else:
        assert exit_code == 2
        assert "MANUAL GATE PENDING" in output


def test_empty_dataset_is_pending_without_fabricating_percentages(tmp_path: Path) -> None:
    calculator = _load_calculator()
    path = _write(
        tmp_path / "empty.json",
        _document(
            [],
            candidate_commit=None,
            candidate_version=None,
            materials=None,
        ),
    )
    lines, exit_code = calculator.summarize(calculator.load_results(path))
    output = "\n".join(lines)
    assert exit_code == 2
    assert "MANUAL GATE PENDING" in output
    assert "Tester count: 0" in output
    assert "Independent completion rate: N/A" in output
    assert "Comprehension rate: N/A" in output


def test_calculator_applies_thresholds_without_rounding_them(tmp_path: Path) -> None:
    calculator = _load_calculator()
    records = [_tester(index) for index in range(5)]
    records[4].update(
        {
            "product_understood": False,
            "report_found": False,
            "time_to_report_seconds": None,
            "intervention_required": True,
        }
    )
    path = _write(tmp_path / "synthetic-unit-test-input.json", _document(records))

    lines, exit_code = calculator.summarize(calculator.load_results(path))
    output = "\n".join(lines)
    assert exit_code == 0
    assert "Candidate version: 0.3.0" in output
    assert "Independent completion rate: 80.0%" in output
    assert "Comprehension rate: 80.0%" in output
    assert "Median time to report: 240.0 seconds" in output


def test_unclear_misconception_cannot_pass(tmp_path: Path) -> None:
    calculator = _load_calculator()
    path = _write(
        tmp_path / "unclear.json",
        _document([_tester(1, controls_machinery_misconception=None)]),
    )
    lines, exit_code = calculator.summarize(calculator.load_results(path))
    output = "\n".join(lines)
    assert exit_code == 1
    assert "FAIL  Nobody believed Metriplane controls machinery" in output


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"candidate_commit": None}, "required when testers exist"),
        ({"candidate_commit": "abc"}, "full 40-character lowercase Git SHA"),
        ({"candidate_version": "release tomorrow"}, "release-like version"),
        ({"candidate_version": "1" * 65}, "at most 64 characters"),
        ({"materials": {"product_page": "https://private.invalid"}}, "materials must"),
        (
            {
                "materials": {
                    "product_page": ["readme"],
                    "installation_instructions": "candidate-wheel",
                }
            },
            "materials.product_page",
        ),
        (
            {
                "materials": {
                    "product_page": "readme",
                    "installation_instructions": {"kind": "candidate-wheel"},
                }
            },
            "materials.installation_instructions",
        ),
        (
            {
                "materials": {
                    "product_page": "readme",
                    "installation_instructions": "private-url",
                }
            },
            "materials.installation_instructions",
        ),
    ),
)
def test_candidate_metadata_boundary(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    calculator = _load_calculator()
    path = _write(tmp_path / "metadata.json", _document([_tester(1)], **overrides))
    with pytest.raises(ValueError, match=message):
        calculator.load_results(path)


def test_empty_dataset_rejects_partially_populated_candidate_metadata(tmp_path: Path) -> None:
    calculator = _load_calculator()
    path = _write(
        tmp_path / "partial.json",
        _document([], candidate_version=None, materials=None),
    )
    with pytest.raises(ValueError, match="entirely null or entirely populated"):
        calculator.load_results(path)


@pytest.mark.parametrize("tester_id", ("", "a" * 33, "A B", "a@example.com", "/home/a"))
def test_tester_ids_are_short_anonymous_identifiers(
    tmp_path: Path,
    tester_id: str,
) -> None:
    calculator = _load_calculator()
    path = _write(tmp_path / "id.json", _document([_tester(1, tester_id=tester_id)]))
    with pytest.raises(ValueError, match="anonymous ID"):
        calculator.load_results(path)


@pytest.mark.parametrize(
    "command",
    (
        "",
        "x" * 501,
        "metriplane demo\n--open",
        "metriplane demo --out /home/alice/private",
        "metriplane demo --out=/home/alice/private",
        "TOKEN=secret-value metriplane demo",
        "ssh alice@internal-host",
        "pip install https://127.0.0.1/private.whl",
    ),
)
def test_failed_command_rejects_unbounded_or_unredacted_content(
    tmp_path: Path,
    command: str,
) -> None:
    calculator = _load_calculator()
    path = _write(
        tmp_path / "command.json",
        _document([_tester(1, first_failed_command=command)]),
    )
    with pytest.raises(ValueError):
        calculator.load_results(path)


def test_failed_command_accepts_faithful_redaction_placeholders(tmp_path: Path) -> None:
    calculator = _load_calculator()
    command = (
        "TOKEN=<REDACTED> metriplane demo --out <PATH> "
        "--index-url <PRIVATE_URL> --owner <USER>"
    )
    path = _write(
        tmp_path / "redacted-command.json",
        _document([_tester(1, first_failed_command=command)]),
    )
    results = calculator.load_results(path)
    assert results["testers"][0]["first_failed_command"] == command


@pytest.mark.parametrize("elapsed", (float("nan"), float("inf"), float("-inf"), -1))
def test_time_to_report_must_be_finite_and_nonnegative(
    tmp_path: Path,
    elapsed: float,
) -> None:
    calculator = _load_calculator()
    path = _write(
        tmp_path / "elapsed.json",
        _document([_tester(1, time_to_report_seconds=elapsed)]),
    )
    with pytest.raises(ValueError, match="non-negative or null"):
        calculator.load_results(path)


@pytest.mark.parametrize(
    ("records", "expected_exit"),
    (
        ([_tester(index) for index in range(5)], 0),
        (
            [
                *[_tester(index) for index in range(3)],
                *[
                    _tester(index, product_understood=False)
                    for index in range(3, 5)
                ],
            ],
            1,
        ),
        ([_tester(1, time_to_report_seconds=299)], 0),
        ([_tester(1, time_to_report_seconds=300)], 1),
        (
            [
                _tester(
                    1,
                    deterministic_replay_equals_physical_accuracy_misconception=True,
                )
            ],
            1,
        ),
        (
            [
                _tester(
                    1,
                    deterministic_replay_equals_physical_accuracy_misconception=None,
                )
            ],
            1,
        ),
    ),
)
def test_gate_boundaries(records: list[dict[str, object]], expected_exit: int) -> None:
    calculator = _load_calculator()
    _, exit_code = calculator.summarize(
        {
            "candidate_commit": "a" * 40,
            "candidate_version": "0.3.0",
            "materials": {
                "product_page": "readme",
                "installation_instructions": "candidate-wheel",
            },
            "testers": records,
        }
    )
    assert exit_code == expected_exit


def test_cli_exit_codes_cover_pending_pass_fail_and_invalid(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calculator = _load_calculator()
    pending = _write(
        tmp_path / "pending.json",
        _document([], candidate_commit=None, candidate_version=None, materials=None),
    )
    passing = _write(tmp_path / "passing.json", _document([_tester(1)]))
    failing = _write(
        tmp_path / "failing.json",
        _document([_tester(1, demo_command_found=False)]),
    )
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")

    assert calculator.main([str(pending)]) == 2
    assert "MANUAL GATE PENDING" in capsys.readouterr().out
    assert calculator.main([str(passing)]) == 0
    assert "HUMAN COMPREHENSION GATE: PASS" in capsys.readouterr().out
    assert calculator.main([str(failing)]) == 1
    assert "HUMAN COMPREHENSION GATE: FAIL" in capsys.readouterr().out
    assert calculator.main([str(invalid)]) == 2
    assert "results: ERROR" in capsys.readouterr().err


def test_release_checklist_links_protocol_and_site_excludes_results() -> None:
    releasing = (ROOT / "docs/releasing.md").read_text(encoding="utf-8")
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")

    assert "validation/first-time-user-comprehension.md" in releasing
    assert "validation/human-comprehension-results.json" in mkdocs
    assert "tests/test_human_comprehension_gate.py" in workflow
    assert "scripts/summarize_human_comprehension.py" in workflow
