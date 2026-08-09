# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fresh-process shim for macOS launcher children."""

from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    """Create a process group, enter the requested directory, and exec argv."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("launcher child requires a working directory and command", file=sys.stderr, flush=True)
        return 64

    cwd, *command = args
    try:
        os.setpgrp()
        os.chdir(cwd)
    except OSError as exc:
        print(f"launcher child failed: {exc}", file=sys.stderr, flush=True)
        return 126

    try:
        os.execvpe(command[0], command, os.environ)
    except OSError as exc:
        print(f"launcher child failed: {exc}", file=sys.stderr, flush=True)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
