# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from pathlib import Path

from metriplane.recording.jsonl import read_jsonl

def test_read_jsonl_parses_sample() -> None:
    frames = read_jsonl(Path("tests/data/sample_session.jsonl"))
    assert len(frames) == 2
    assert frames[0].schema_version == "1.0"
    assert frames[1].frame_id == 2
