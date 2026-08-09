<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Contributing

The current root
[contribution guide](https://github.com/Miko997/metriplane/blob/main/CONTRIBUTING.md)
states the review, understanding, licensing, and attribution responsibilities for
submitted work. It is still intentionally narrow; development setup, privacy,
evidence boundaries, and pull-request guidance will be expanded in a separate
community-readiness change.

For current local development, use Python 3.12 or 3.13 in a virtual environment:

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest "mkdocs>=1.6,<2"
```

For a documentation or comprehension change:

1. Describe the user problem and keep the pull request focused.
2. Use **Metriplane** in current product-facing text; preserve lowercase
   `metriplane` for commands, imports, package names, paths, schemas, and URLs.
3. Derive every command from the actual CLI and mark unautomated procedures as
   manual.
4. Do not broaden support claims beyond
   [Supported Environments](https://github.com/Miko997/metriplane/blob/main/docs/SUPPORTED_ENVIRONMENTS.md).
5. Do not rewrite frozen v0.2.0 evidence, checksums, DOI metadata, or historical
   measurements.
6. Never submit private or proprietary recordings without permission,
   minimization, and a compatible license.
7. Run the focused documentation checks and the complete relevant test suite.

Build this front door locally with:

```bash
python -m pip install "mkdocs>=1.6,<2"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_docs_front_door.py
python -m mkdocs build --strict --site-dir /tmp/metriplane-docs-site
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

The stock MkDocs theme and explicit navigation are intentional. Add a page only
when it gives an unfamiliar user a clearer supported path; the front door should
not become a second unstructured archive.
