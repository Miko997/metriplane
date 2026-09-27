# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Canonical dependency-bearing path classification helpers."""

from __future__ import annotations

from pathlib import PurePosixPath


def is_dockerfile_path(path: str | PurePosixPath) -> bool:
    """Return whether a path uses one of the governed Dockerfile naming forms."""

    name = PurePosixPath(path).name
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")
