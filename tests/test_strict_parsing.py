# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from metriplane.strict_parsing import (
    ParseLimits,
    REPOSITORY_DOCUMENT_LIMITS,
    StrictJsonError,
    StrictYamlError,
    iter_jsonl,
    iter_jsonl_path,
    iter_jsonl_stream,
    load_json,
    load_json_path,
    load_json_stream,
    load_yaml,
    load_yaml_path,
    load_yaml_stream,
)


LIMITS = ParseLimits(
    max_bytes=16,
    max_depth=3,
    max_nodes=8,
    max_scalar_bytes=4,
    max_jsonl_lines=2,
)


@pytest.mark.parametrize(
    ("size", "accepted"),
    [(LIMITS.max_bytes - 1, True), (LIMITS.max_bytes, True), (LIMITS.max_bytes + 1, False)],
)
def test_json_byte_limit_n_minus_one_n_n_plus_one(size: int, accepted: bool) -> None:
    payload = '"' + ("a" * (size - 2)) + '"'
    limits = ParseLimits(LIMITS.max_bytes, 8, 32, LIMITS.max_bytes, 16)
    if accepted:
        assert load_json(payload, limits=limits) == "a" * (size - 2)
    else:
        with pytest.raises(StrictJsonError, match="byte limit"):
            load_json(payload, limits=limits)


@pytest.mark.parametrize(("depth", "accepted"), [(2, True), (3, True), (4, False)])
def test_json_depth_limit_n_minus_one_n_n_plus_one(depth: int, accepted: bool) -> None:
    payload = ("[" * depth) + "0" + ("]" * depth)
    generous = ParseLimits(128, 3, 16, 16, 16)
    if accepted:
        load_json(payload, limits=generous)
    else:
        with pytest.raises(StrictJsonError, match="depth limit"):
            load_json(payload, limits=generous)


@pytest.mark.parametrize(("nodes", "accepted"), [(7, True), (8, True), (9, False)])
def test_json_node_limit_n_minus_one_n_n_plus_one(nodes: int, accepted: bool) -> None:
    payload = json.dumps([0] * (nodes - 1))
    limits = ParseLimits(256, 8, 8, 16, 16)
    if accepted:
        load_json(payload, limits=limits)
    else:
        with pytest.raises(StrictJsonError, match="node limit"):
            load_json(payload, limits=limits)


@pytest.mark.parametrize(("size", "accepted"), [(3, True), (4, True), (5, False)])
def test_json_scalar_limit_n_minus_one_n_n_plus_one(size: int, accepted: bool) -> None:
    payload = json.dumps("a" * size)
    limits = ParseLimits(128, 8, 16, 4, 16)
    if accepted:
        load_json(payload, limits=limits)
    else:
        with pytest.raises(StrictJsonError, match="scalar"):
            load_json(payload, limits=limits)


def test_json_strict_lexical_contract() -> None:
    with pytest.raises(StrictJsonError, match="repeats key"):
        load_json('{"a":1,"a":2}')
    with pytest.raises(StrictJsonError, match="non-finite"):
        load_json('{"value":NaN}')
    with pytest.raises(StrictJsonError, match="non-finite"):
        load_json('{"value":NaN}', parse_constant=lambda _value: None)
    with pytest.raises(StrictJsonError, match="Unicode scalar"):
        load_json('"\\ud800"')
    with pytest.raises(UnicodeError):
        b"\xff".decode("utf-8")
    with pytest.raises(StrictJsonError, match="UTF-8"):
        load_json(b"\xff")
    with pytest.raises(StrictJsonError, match="invalid"):
        load_json("1" * 5000)
    root = Path(__file__).resolve().parents[1]
    program = """\
from metriplane.strict_parsing import StrictYamlError, load_json, load_yaml
assert load_json(b'{"ok":true}') == {"ok": True}
try:
    load_yaml("ok: true")
except StrictYamlError as exc:
    assert str(exc) == "PyYAML is required to parse YAML"
else:
    raise AssertionError("YAML parsed without PyYAML")
"""
    completed = subprocess.run(
        [sys.executable, "-S", "-c", program],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(("size", "accepted"), [(15, True), (16, True), (17, False)])
def test_json_stream_and_path_byte_limit_triple(tmp_path: Path, size: int, accepted: bool) -> None:
    payload = '"' + ("a" * (size - 2)) + '"'
    limits = ParseLimits(16, 8, 32, 16, 16)
    source = tmp_path / f"value-{size}.json"
    source.write_text(payload, encoding="utf-8")
    operations = (
        lambda: load_json_stream(io.StringIO(payload), limits=limits),
        lambda: load_json_path(source, limits=limits),
    )
    for operation in operations:
        if accepted:
            assert operation() == "a" * (size - 2)
        else:
            with pytest.raises(StrictJsonError, match="byte limit"):
                operation()


def test_json_regular_path_rejects_links_and_fifo_without_blocking(tmp_path: Path) -> None:
    source = tmp_path / "value.json"
    source.write_text('{"ok":true}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(StrictJsonError, match="cannot open"):
        load_json_path(link)
    fifo = tmp_path / "input.fifo"
    os.mkfifo(fifo)
    script = (
        "from metriplane.strict_parsing import load_json_path, StrictJsonError\n"
        f"try:\n load_json_path({str(fifo)!r})\n"
        "except StrictJsonError:\n raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        timeout=2,
    )
    assert completed.returncode == 0


@pytest.mark.parametrize(("lines", "accepted"), [(1, True), (2, True), (3, False)])
def test_jsonl_line_limit_n_minus_one_n_n_plus_one(lines: int, accepted: bool) -> None:
    limits = ParseLimits(128, 8, 32, 16, 2)
    payload = "0\n" * lines
    if accepted:
        assert list(iter_jsonl(payload, limits=limits)) == [0] * lines
    else:
        with pytest.raises(StrictJsonError, match="line limit"):
            list(iter_jsonl(payload, limits=limits))


def test_jsonl_lexical_rules() -> None:
    limits = ParseLimits(128, 8, 32, 16, 2)
    with pytest.raises(StrictJsonError, match="repeats key"):
        list(iter_jsonl('{"a":1,"a":2}\n', limits=limits))


@pytest.mark.parametrize(("depth", "accepted"), [(2, True), (3, True), (4, False)])
def test_jsonl_record_depth_limit_triple(depth: int, accepted: bool) -> None:
    payload = ("[" * depth) + "0" + ("]" * depth) + "\n"
    limits = ParseLimits(128, 3, 32, 16, 16)
    if accepted:
        list(iter_jsonl(payload, limits=limits))
    else:
        with pytest.raises(StrictJsonError, match="depth limit"):
            list(iter_jsonl(payload, limits=limits))


@pytest.mark.parametrize(("nodes", "accepted"), [(7, True), (8, True), (9, False)])
def test_jsonl_record_node_limit_triple(nodes: int, accepted: bool) -> None:
    payload = json.dumps([0] * (nodes - 1)) + "\n"
    limits = ParseLimits(256, 8, 8, 16, 16)
    if accepted:
        list(iter_jsonl(payload, limits=limits))
    else:
        with pytest.raises(StrictJsonError, match="node limit"):
            list(iter_jsonl(payload, limits=limits))


@pytest.mark.parametrize(("size", "accepted"), [(3, True), (4, True), (5, False)])
def test_jsonl_record_scalar_limit_triple(size: int, accepted: bool) -> None:
    payload = json.dumps("a" * size) + "\n"
    limits = ParseLimits(128, 8, 16, 4, 16)
    if accepted:
        assert list(iter_jsonl(payload, limits=limits)) == ["a" * size]
    else:
        with pytest.raises(StrictJsonError, match="scalar"):
            list(iter_jsonl(payload, limits=limits))


def test_jsonl_regular_path_is_bounded(tmp_path: Path) -> None:
    source = tmp_path / "records.jsonl"
    source.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
    assert list(iter_jsonl_path(source)) == [{"a": 1}, {"b": 2}]
    link = tmp_path / "records-link.jsonl"
    link.symlink_to(source)
    with pytest.raises(StrictJsonError, match="cannot open"):
        list(iter_jsonl_path(link))


@pytest.mark.parametrize(("size", "accepted"), [(15, True), (16, True), (17, False)])
def test_jsonl_stream_and_path_byte_limit_triple(tmp_path: Path, size: int, accepted: bool) -> None:
    payload = '"' + ("a" * (size - 3)) + '"\n'
    limits = ParseLimits(16, 8, 32, 16, 16)
    source = tmp_path / f"records-{size}.jsonl"
    source.write_text(payload, encoding="utf-8")
    operations = (
        lambda: list(iter_jsonl_stream(io.StringIO(payload), limits=limits)),
        lambda: list(iter_jsonl_path(source, limits=limits)),
    )
    for operation in operations:
        if accepted:
            assert operation() == ["a" * (size - 3)]
        else:
            with pytest.raises(StrictJsonError, match="byte limit"):
                operation()


@pytest.mark.parametrize(("size", "accepted"), [(15, True), (16, True), (17, False)])
def test_yaml_byte_limit_n_minus_one_n_n_plus_one(size: int, accepted: bool) -> None:
    payload = "a" * (size - 3) + ": 1"
    limits = ParseLimits(LIMITS.max_bytes, 8, 32, LIMITS.max_bytes, 16)
    if accepted:
        load_yaml(payload, limits=limits)
    else:
        with pytest.raises(StrictYamlError, match="byte limit"):
            load_yaml(payload, limits=limits)


@pytest.mark.parametrize(("depth", "accepted"), [(2, True), (3, True), (4, False)])
def test_yaml_depth_limit_n_minus_one_n_n_plus_one(depth: int, accepted: bool) -> None:
    payload = ("[" * depth) + "0" + ("]" * depth)
    limits = ParseLimits(128, 3, 32, 16, 16)
    if accepted:
        load_yaml(payload, limits=limits)
    else:
        with pytest.raises(StrictYamlError, match="depth limit"):
            load_yaml(payload, limits=limits)


@pytest.mark.parametrize(("nodes", "accepted"), [(7, True), (8, True), (9, False)])
def test_yaml_node_limit_n_minus_one_n_n_plus_one(nodes: int, accepted: bool) -> None:
    payload = "[" + ",".join("0" for _ in range(nodes - 1)) + "]"
    limits = ParseLimits(256, 8, 8, 16, 16)
    if accepted:
        load_yaml(payload, limits=limits)
    else:
        with pytest.raises(StrictYamlError, match="node limit"):
            load_yaml(payload, limits=limits)


@pytest.mark.parametrize(("size", "accepted"), [(3, True), (4, True), (5, False)])
def test_yaml_scalar_limit_n_minus_one_n_n_plus_one(size: int, accepted: bool) -> None:
    payload = "a" * size
    limits = ParseLimits(128, 8, 16, 4, 16)
    if accepted:
        assert load_yaml(payload, limits=limits) == payload
    else:
        with pytest.raises(StrictYamlError, match="scalar"):
            load_yaml(payload, limits=limits)


@pytest.mark.parametrize(("size", "accepted"), [(15, True), (16, True), (17, False)])
def test_yaml_stream_and_path_byte_limit_triple(tmp_path: Path, size: int, accepted: bool) -> None:
    payload = "a" * (size - 3) + ": 1"
    limits = ParseLimits(16, 8, 32, 16, 16)
    source = tmp_path / f"value-{size}.yaml"
    source.write_text(payload, encoding="utf-8")
    operations = (
        lambda: load_yaml_stream(io.StringIO(payload), limits=limits),
        lambda: load_yaml_path(source, limits=limits),
    )
    for operation in operations:
        if accepted:
            assert operation() == {"a" * (size - 3): 1}
        else:
            with pytest.raises(StrictYamlError, match="byte limit"):
                operation()


def test_yaml_strict_lexical_contract() -> None:
    with pytest.raises(StrictYamlError, match="repeats key"):
        load_yaml("a: 1\na: 2\n")
    with pytest.raises(StrictYamlError, match="aliases are forbidden"):
        load_yaml("a: &x [1]\nb: *x\n")
    with pytest.raises(yaml.YAMLError):
        load_yaml("value: !!python/object/apply:os.system ['true']")
    with pytest.raises(StrictYamlError, match="non-finite"):
        load_yaml("value: .nan")


def test_yaml_path_is_bounded_and_safe(tmp_path: Path) -> None:
    source = tmp_path / "value.yaml"
    source.write_text("value: 1\n", encoding="utf-8")
    assert load_yaml_path(source) == {"value": 1}


def test_custom_safe_loader_remains_supported() -> None:
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!value", lambda loader, node: loader.construct_scalar(node))
    assert load_yaml("item: !value ok", Loader=Loader) == {"item": "ok"}


def test_invalid_limits_fail_at_construction() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        ParseLimits(0, 1, 1, 1, 1)


def test_repository_document_limit_covers_current_tracked_corpus() -> None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        path
        for directory in ("config", "configs", "docs", "schemas")
        for path in (root / directory).rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.casefold() in {".json", ".jsonl", ".yaml", ".yml"}
    ]
    largest = max(candidates, key=lambda path: path.stat().st_size)
    assert largest.stat().st_size <= REPOSITORY_DOCUMENT_LIMITS.max_bytes
    assert REPOSITORY_DOCUMENT_LIMITS.max_bytes == 64 * 1024 * 1024


def test_installed_product_consumers_use_shared_parser() -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    package_paths = [
        *sorted((root / "metriplane").rglob("*.py")),
        *sorted((root / "integrations").rglob("*.py")),
    ]
    for path in package_paths:
        relative = path.relative_to(root)
        if relative == Path("metriplane/strict_parsing.py") or relative.parts[:2] == (
            "integrations",
            "ros2",
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            direct_parser = (
                (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "json"
                    and node.func.attr in {"load", "loads"}
                )
                or (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "yaml"
                    and node.func.attr in {"load", "safe_load"}
                )
                or (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "model_validate_json"
                )
            )
            nested_unbounded_read = any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr == "read_text"
                for argument in node.args
                for item in ast.walk(argument)
            ) and (
                isinstance(node.func, ast.Name)
                and node.func.id
                in {
                    "iter_jsonl",
                    "load_json",
                    "load_yaml",
                    "strict_json_loads",
                    "strict_yaml_load",
                }
            )
            if direct_parser or nested_unbounded_read:
                violations.append(f"{relative}:{node.lineno}")
    assert violations == []


def test_replay_file_consumer_uses_whole_file_jsonl_boundary() -> None:
    source = (Path(__file__).resolve().parents[1] / "metriplane" / "run.py").read_text(
        encoding="utf-8"
    )
    assert "iter_jsonl_path(p)" in source
    assert "strict_json_loads(line)" not in source
