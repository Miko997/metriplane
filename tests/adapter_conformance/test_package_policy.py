# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools import cross_adapter_gate
from tools.cross_adapter_gate import GateError, load_registry

REPOSITORY_ROOT = Path(__file__).parents[2]


def _massrobotics_component() -> dict[str, object]:
    registry = load_registry(REPOSITORY_ROOT)
    return next(
        component
        for component in registry["adapters"]
        if component["component_id"] == "massrobotics-amr"
    )


def _fake_distribution(dist: Path, *, extra_name: str, extra_bytes: bytes) -> None:
    dist.mkdir()
    wheel = dist / "metriplane_massrobotics_amr_adapter-1.0.0-py3-none-any.whl"
    files = {
        "massrobotics_amr_adapter/__init__.py": b"",
        "massrobotics_amr_adapter/data/frozen-config.json": b"{}\n",
        "massrobotics_amr_adapter/data/source/control/identity.jsonl": b"{}\n",
        "massrobotics_amr_adapter/data/source/incident/identity.jsonl": b"{}\n",
        "massrobotics_amr_adapter/data/uv.lock": b"version = 1\n",
        extra_name: extra_bytes,
    }
    with zipfile.ZipFile(wheel, mode="w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with tarfile.open(dist / "metriplane_massrobotics_amr_adapter-1.0.0.tar.gz", mode="w:gz"):
        pass


def test_adapter_archive_rejects_a_registered_reference_only_artifact_name(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    _fake_distribution(
        dist,
        extra_name="massrobotics_amr_adapter/AMR_Interop_Standard.json",
        extra_bytes=b"independently authored test sentinel",
    )

    with pytest.raises(GateError, match="forbidden .*AMR_Interop_Standard.json"):
        cross_adapter_gate._inspect_adapter_distributions(
            REPOSITORY_ROOT,
            _massrobotics_component(),
            dist,
        )


def test_adapter_archive_rejects_a_reference_only_byte_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden_bytes = b"controlled reference-only byte-identity fault injection"
    forbidden_digest = hashlib.sha256(forbidden_bytes).hexdigest()
    monkeypatch.setattr(
        cross_adapter_gate,
        "_forbidden_referenced_digests",
        lambda _repo, _registry: {forbidden_digest},
    )
    dist = tmp_path / "dist"
    _fake_distribution(
        dist,
        extra_name="massrobotics_amr_adapter/unexpected-source.bin",
        extra_bytes=forbidden_bytes,
    )

    with pytest.raises(GateError, match="reference-only upstream bytes"):
        cross_adapter_gate._inspect_adapter_distributions(
            REPOSITORY_ROOT,
            _massrobotics_component(),
            dist,
        )
