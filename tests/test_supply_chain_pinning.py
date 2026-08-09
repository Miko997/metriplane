# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DIGEST_REF = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")


def test_runtime_container_bases_are_immutable() -> None:
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    primary_from = next(
        line.removeprefix("FROM ").strip()
        for line in dockerfile.splitlines()
        if line.startswith("FROM ")
    )
    assert DIGEST_REF.fullmatch(primary_from)

    jetson = (ROOT / "docker" / "jetson.Dockerfile").read_text(encoding="utf-8")
    base_arg = next(
        line.split("=", 1)[1].strip()
        for line in jetson.splitlines()
        if line.startswith("ARG BASE_IMAGE=")
    )
    assert DIGEST_REF.fullmatch(base_arg)


def test_health_probe_does_not_pipe_network_content_to_an_interpreter() -> None:
    helper = (ROOT / "tools" / "mp.sh").read_text(encoding="utf-8")
    assert 'curl -fsS "$HEALTH_URL"' not in helper
    assert 'python - "$HEALTH_URL"' in helper
