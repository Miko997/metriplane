# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Stable adapter for the cumulative release-control state machine."""

from __future__ import annotations

from collections.abc import Sequence

from metriplane.release_control import tool_main


def main(argv: Sequence[str] | None = None) -> int:
    return tool_main(__file__, argv)


if __name__ == "__main__":
    raise SystemExit(main())
