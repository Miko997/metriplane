# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from massrobotics_amr_adapter.constants import DEFAULT_CONFIG, DEFAULT_SOURCE_ROOT

JsonObject = dict[str, Any]


@pytest.fixture
def config_path() -> Path:
    return DEFAULT_CONFIG


@pytest.fixture(params=("incident", "control"))
def variant(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def source_root(variant: str) -> Path:
    return DEFAULT_SOURCE_ROOT / variant


def read_jsonl(path: Path) -> list[JsonObject]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(isinstance(value, dict) for value in values)
    return values


def write_jsonl(path: Path, values: list[JsonObject]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for value in values
        ),
        encoding="utf-8",
    )


@pytest.fixture
def copy_source(tmp_path: Path) -> Callable[[str], Path]:
    def copy(variant: str = "incident") -> Path:
        root = tmp_path / variant
        shutil.copytree(DEFAULT_SOURCE_ROOT / variant, root)
        return root

    return copy


@pytest.fixture
def mutate_source(
    copy_source: Callable[[str], Path],
) -> Callable[[str, str, Callable[[list[JsonObject]], None]], Path]:
    def mutate(
        variant: str,
        filename: str,
        operation: Callable[[list[JsonObject]], None],
    ) -> Path:
        root = copy_source(variant)
        path = root / filename
        values = read_jsonl(path)
        operation(values)
        write_jsonl(path, values)
        return root

    return mutate


@pytest.fixture
def copy_config(tmp_path: Path) -> Callable[[Callable[[JsonObject], None]], Path]:
    def copy(operation: Callable[[JsonObject], None]) -> Path:
        value = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        assert isinstance(value, dict)
        operation(value)
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    return copy


def fixture_root(output_root: Path, variant: str) -> Path:
    """Accept both a single-variant output and a combined finalized profile."""

    if (output_root / "session.jsonl").is_file():
        return output_root
    if (output_root / "fixture" / "session.jsonl").is_file():
        return output_root / "fixture"
    candidate = output_root / variant
    assert candidate.is_dir(), f"missing {variant} fixture below {output_root}"
    return candidate


def jsonl_rows(path: Path) -> list[JsonObject]:
    return read_jsonl(path)


def file_inventory(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
