# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Portable run-identifier policy shared by every artifact writer."""

from __future__ import annotations

import re

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED_BASENAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def validate_portable_run_id(value: str) -> str:
    """Return a validated portable run ID or raise ``ValueError``."""
    run_id = str(value)
    windows_basename = run_id.split(".", maxsplit=1)[0].rstrip(" .").casefold()
    if (
        run_id != run_id.strip()
        or _SAFE_RUN_ID.fullmatch(run_id) is None
        or run_id in {".", ".."}
        or run_id.endswith((".", " "))
        or windows_basename in _WINDOWS_RESERVED_BASENAMES
    ):
        raise ValueError(
            "run_id must be a portable 1-128 character name using letters, numbers, "
            "dots, dashes, or underscores; paths, surrounding whitespace, trailing dots, "
            "and Windows device basenames are not allowed"
        )
    return run_id
