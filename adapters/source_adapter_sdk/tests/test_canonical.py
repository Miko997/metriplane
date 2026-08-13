# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import metriplane_source_adapter_sdk.canonical as canonical_module
from metriplane_source_adapter_sdk import (
    CanonicalJsonError,
    artifact_sha256,
    canonical_json_bytes,
    canonical_sha256,
    load_json,
)


def test_canonical_json_sorts_keys_and_uses_no_padding() -> None:
    assert canonical_json_bytes({"z": 1, "a": [True, None]}) == b'{"a":[true,null],"z":1}\n'


def test_canonical_json_preserves_utf8() -> None:
    assert canonical_json_bytes({"name": "Metripläne"}) == '{"name":"Metripläne"}\n'.encode()


def test_canonical_json_has_exactly_one_final_line_feed() -> None:
    assert canonical_json_bytes({"line": "value\n"}).endswith(b'\\n"}\n')


def test_canonical_sha256_hashes_canonical_bytes() -> None:
    value = {"b": 2, "a": 1}
    assert canonical_sha256(value) == hashlib.sha256(b'{"a":1,"b":2}\n').hexdigest()


def test_load_json_rejects_duplicate_keys(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.json"
    source.write_text('{"field":1,"field":2}', encoding="utf-8")
    with pytest.raises(CanonicalJsonError, match="duplicate"):
        load_json(source)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_load_json_rejects_nonfinite_constants(tmp_path: Path, constant: str) -> None:
    source = tmp_path / "nonfinite.json"
    source.write_text(f'{{"value":{constant}}}', encoding="utf-8")
    with pytest.raises(CanonicalJsonError, match="non-finite"):
        load_json(source)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nonfinite_values(value: float) -> None:
    with pytest.raises(CanonicalJsonError, match="non-finite"):
        canonical_json_bytes({"value": value})


@pytest.mark.parametrize("value", [{1: "bad"}, b"bad", {"bad"}])
def test_canonical_json_rejects_values_outside_json_domain(value: object) -> None:
    with pytest.raises(CanonicalJsonError):
        canonical_json_bytes(value)


def test_load_json_rejects_invalid_utf8(tmp_path: Path) -> None:
    source = tmp_path / "invalid.json"
    source.write_bytes(b"\xff")
    with pytest.raises(CanonicalJsonError, match="UTF-8"):
        load_json(source)


def test_load_json_rejects_invalid_syntax(tmp_path: Path) -> None:
    source = tmp_path / "invalid.json"
    source.write_text("{", encoding="utf-8")
    with pytest.raises(CanonicalJsonError, match="invalid JSON"):
        load_json(source)


def test_artifact_sha256_hashes_regular_file(tmp_path: Path) -> None:
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"metriplane")
    assert artifact_sha256(source) == hashlib.sha256(b"metriplane").hexdigest()


def test_artifact_sha256_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unavailable"):
        artifact_sha256(tmp_path / "missing")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_artifact_sha256_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"source")
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="nonsymlink"):
        artifact_sha256(link)


def test_artifact_sha256_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="regular"):
        artifact_sha256(tmp_path)


def test_artifact_sha256_rejects_same_size_mutation_with_restored_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"before")
    original = source.stat()
    real_read = os.read
    mutated = False

    def mutate_then_read(descriptor: int, count: int) -> bytes:
        nonlocal mutated
        if not mutated:
            mutated = True
            source.write_bytes(b"after!")
            os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        return real_read(descriptor, count)

    monkeypatch.setattr(canonical_module.os, "read", mutate_then_read)
    with pytest.raises(ValueError, match="changed while hashing"):
        artifact_sha256(source)


def test_artifact_sha256_rejects_same_byte_path_replacement_during_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"same bytes")
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"same bytes")
    real_read = os.read
    replaced = False

    def replace_then_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            replacement.replace(source)
        return real_read(descriptor, count)

    monkeypatch.setattr(canonical_module.os, "read", replace_then_read)
    with pytest.raises(ValueError, match="changed while hashing"):
        artifact_sha256(source)
