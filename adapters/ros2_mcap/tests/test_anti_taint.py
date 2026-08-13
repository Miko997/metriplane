# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import ros2_mcap_adapter.core as core
from ros2_mcap_adapter.constants import DEFAULT_CONFIG, DEFAULT_LOCK
from ros2_mcap_adapter.decoder import DecodeError, decode_source_bytes, load_config
from ros2_mcap_adapter.fixture import (
    _domain_pack,
    _entity_mapping,
    normalize_frames,
    write_conversion,
)
from ros2_mcap_adapter.generator import build_source_bytes


def test_outcome_mutation_switch_is_not_in_public_adapter_api() -> None:
    assert "allow_outcome_test_mutation" not in inspect.signature(core.inspect_source).parameters
    assert "allow_outcome_test_mutation" not in inspect.signature(core.convert).parameters


def _semantic_inputs(source) -> dict[str, bytes]:
    config = load_config(DEFAULT_CONFIG)
    session, _ = normalize_frames(source.frames, config)
    return {
        "entity_mapping": json.dumps(_entity_mapping(), sort_keys=True).encode(),
        "session": session,
        **_domain_pack(config, 0.5),
        **{f"control:{key}": value for key, value in _domain_pack(config, 1.2).items()},
    }


def _atlas_semantics(conversion_root: Path, output_root: Path) -> dict[str, object]:
    repository_root = Path(__file__).parents[3]
    program = r"""
import json
import os
import sys
from pathlib import Path
from metriplane.external_sources.execution import run_external_fixture

fixture_root = Path(sys.argv[1])
output_root = Path(sys.argv[2])
result = {}
for variant in ("incident", "control"):
    output = output_root / variant
    summary = run_external_fixture(
        fixture_root / variant,
        output,
        run_id=f"anti_taint_{variant}",
    )
    if not summary.passed:
        raise RuntimeError(f"{variant}: {summary.errors}")
    def records(name):
        path = output / name
        return [json.loads(line) for line in path.read_text().splitlines() if line]
    result[variant] = {
        "counts": [
            summary.frame_count,
            summary.event_count,
            summary.deviation_count,
            summary.incident_count,
        ],
        "state": records("state_segment.jsonl"),
        "events": records("physical_event_log.jsonl"),
        "deviations": records("deviations.jsonl"),
        "incidents": records("incidents.jsonl"),
    }
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
"""
    environment = {
        **os.environ,
        "METRIPLANE_GIT_COMMIT": "a" * 40,
        "PYTHONPATH": str(repository_root),
    }
    result = subprocess.run(
        [sys._base_executable, "-c", program, str(conversion_root), str(output_root)],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _mutator(field: str, mode: str):
    def apply(_index, message):
        if field == "success":
            return replace(message, success=(not message.success if mode == "mutate" else False))
        value = getattr(message, field)
        replacement = f"mutated-{field}-{value}" if mode == "mutate" else ""
        return replace(message, **{field: replacement})

    return apply


@pytest.mark.parametrize("field", ["success", "result", "alarm", "action", "annotation"])
@pytest.mark.parametrize("mode", ["mutate", "clear"])
def test_all_excluded_outcome_fields_cannot_change_semantic_inputs(field: str, mode: str) -> None:
    baseline = decode_source_bytes(build_source_bytes())
    altered_bytes = build_source_bytes(outcome_transform=_mutator(field, mode))
    with pytest.raises(DecodeError, match="SHA-256"):
        decode_source_bytes(altered_bytes)
    altered = decode_source_bytes(altered_bytes, allow_outcome_test_mutation=True)
    assert altered.source_sha256 != baseline.source_sha256
    assert _semantic_inputs(altered) == _semantic_inputs(baseline)


def test_true_whole_outcome_stream_deletion_preserves_semantic_inputs() -> None:
    baseline = decode_source_bytes(build_source_bytes())
    deleted_bytes = build_source_bytes(include_outcome_stream=False)
    with pytest.raises(DecodeError, match="SHA-256"):
        decode_source_bytes(deleted_bytes)
    deleted = decode_source_bytes(deleted_bytes, allow_outcome_test_mutation=True)
    assert deleted.outcome_stream_present is False
    assert deleted.outcome_message_count == 0
    assert len(deleted.schema_inventory) == 2
    assert len(deleted.channel_inventory) == 3
    assert _semantic_inputs(deleted) == _semantic_inputs(baseline)


def test_all_outcome_mutations_and_stream_deletion_preserve_mapping_and_atlas(
    tmp_path: Path,
) -> None:
    config = load_config(DEFAULT_CONFIG)
    baseline_source = decode_source_bytes(build_source_bytes())
    baseline_root = tmp_path / "baseline-fixture"
    write_conversion(
        config=config,
        config_bytes=DEFAULT_CONFIG.read_bytes(),
        lock_bytes=DEFAULT_LOCK.read_bytes(),
        adapter_commit="1" * 40,
        source=baseline_source,
        output_root=baseline_root,
    )
    baseline_mapping = (baseline_root / "incident" / "entity-mapping.json").read_bytes()
    baseline_atlas = _atlas_semantics(baseline_root, tmp_path / "baseline-atlas")

    variants = [
        (f"{mode}-{field}", build_source_bytes(outcome_transform=_mutator(field, mode)))
        for mode in ("mutate", "clear")
        for field in ("success", "result", "alarm", "action", "annotation")
    ]
    variants.append(("delete-outcome-stream", build_source_bytes(include_outcome_stream=False)))
    for name, source_bytes in variants:
        altered_source = decode_source_bytes(source_bytes, allow_outcome_test_mutation=True)
        altered_root = tmp_path / f"{name}-fixture"
        write_conversion(
            config=config,
            config_bytes=DEFAULT_CONFIG.read_bytes(),
            lock_bytes=DEFAULT_LOCK.read_bytes(),
            adapter_commit="1" * 40,
            source=altered_source,
            output_root=altered_root,
        )
        assert (altered_root / "incident" / "entity-mapping.json").read_bytes() == baseline_mapping
        assert (altered_root / "control" / "entity-mapping.json").read_bytes() == baseline_mapping
        assert _atlas_semantics(altered_root, tmp_path / f"{name}-atlas") == baseline_atlas
