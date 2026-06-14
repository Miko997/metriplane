# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any


class DeterministicProvider:
    """Default summary provider: joins pre-built fact strings. No external model."""

    name = "deterministic"

    def summarize(self, *, question: str, facts: list[dict[str, Any]]) -> str:
        lines = [str(f.get("text", "")) for f in facts if f.get("text")]
        return "\n".join(lines) if lines else "No matching records found."
