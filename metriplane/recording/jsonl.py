# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT


import time
from pathlib import Path
from typing import Iterable
import json

from metriplane.strict_parsing import iter_jsonl_path
from metriplane.provenance.run_provenance import is_header_record

from metriplane.schema import FrameStateModel


def write_jsonl(path: Path, frames: Iterable[FrameStateModel]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for frame in frames:
            f.write(json.dumps(frame.model_dump()) + "\n")


def read_jsonl(path: Path) -> list[FrameStateModel]:
    frames: list[FrameStateModel] = []
    for obj in iter_jsonl_path(path):
        if is_header_record(obj):
            continue
        frames.append(FrameStateModel.model_validate(obj))
    return frames


def replay_timing(frames: list[FrameStateModel], speed: float = 1.0) -> None:
    if not frames:
        return
    t0 = frames[0].ts
    start = time.time()
    for fr in frames:
        target = (fr.ts - t0) / max(speed, 1e-6)
        while (time.time() - start) < target:
            time.sleep(0.001)
