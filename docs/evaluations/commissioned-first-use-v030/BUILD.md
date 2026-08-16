<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Build and Validation

Run from the repository root:

```bash
uv sync --locked --group dev
uv run python tools/commissioned_first_use/build_and_validate.py
uv run python -m pytest -q tests/test_commissioned_first_use_report.py
uv run python -m pytest -q
uv run mkdocs build --strict
git diff --check
```

To regenerate the aggregate JSON and checksums after an approved data or report change:

```bash
uv run python tools/commissioned_first_use/build_and_validate.py --write
uv run python tools/commissioned_first_use/build_and_validate.py
```

The committed PDF was regenerated locally with **Python 3.13.5** and **pypdf 5.9.0** to decode the previously reviewed five-page layout, then written deterministically as PDF 1.4 using the Python standard-library `zlib` implementation, ASCII85 stream encoding, and the standard PDF Helvetica fonts. No PDF dependency was added to `pyproject.toml` or `uv.lock`. Existing repository CI verifies the committed PDF and its checksum. It does not regenerate or commit the PDF.

PDF inspection commands:

```bash
pdfinfo docs/evaluations/commissioned-first-use-v030/commissioned_first_use_report.pdf
pdftotext -layout \
  docs/evaluations/commissioned-first-use-v030/commissioned_first_use_report.pdf \
  /tmp/met12-report.txt
sha256sum -c docs/evaluations/commissioned-first-use-v030/SHA256SUMS
```
