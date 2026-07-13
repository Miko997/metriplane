<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Install the Exact v0.2.0 Artifact

Use Python 3.12 or newer for the core path.

```bash
git clone --branch v0.2.0 --depth 1 https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m metriplane.cli doctor
```

The core replay and Atlas commands use checked-in data and do not require
cameras, Playwright, or Chromium. The full maintainer gate is documented
separately in `docs/review_kit/09_full_maintainer_gate.md`.

The included author-run evidence package records its environment and distinct
pre-release capture commit in:

- `evidence/paper_v2_0/environment.txt`
- `evidence/paper_v2_0/git_commit.txt`
- `evidence/paper_v2_0/test_output.txt`
