# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/publications/commissioned-first-use-v030"


def test_publication_pdf_is_binary_and_checksums_match() -> None:
    pdf = (PACKAGE / "commissioned_first_use_evaluation.pdf").read_bytes()
    assert len(pdf) > 5_000
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf[-1_024:]
    assert b"ELLIPSIZATION" not in pdf

    for line in (PACKAGE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", maxsplit=1)
        artifact = PACKAGE / name
        assert artifact.is_file(), name
        actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert actual == expected, name


def test_publication_identifiers_are_present() -> None:
    names = ("README.md", "REPORT.md", "summary.json", "SOURCE_MANIFEST.json")
    combined = "\n".join((PACKAGE / name).read_text(encoding="utf-8") for name in names)
    assert "RRID:SCR_028813" in combined
    assert "10.5281/zenodo.20736619" in combined
