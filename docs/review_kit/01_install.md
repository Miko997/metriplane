<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Install

Use Python 3.12 or newer.

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
python -m metriplane.cli doctor
```

For the exact local evidence package captured on this branch, see:

- `evidence/paper_v2_0/environment.txt`
- `evidence/paper_v2_0/git_commit.txt`
- `evidence/paper_v2_0/test_output.txt`

If optional tooling is unavailable, the core replay and Atlas commands below
still use checked-in data and do not require cameras.
