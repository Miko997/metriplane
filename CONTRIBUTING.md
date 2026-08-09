<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Contributing to Metriplane

Thank you for helping make Metriplane easier to understand, test, and use.
Keep each contribution focused on one clear problem. Before starting a large
change or a new integration, open an integration-request issue so the intended
scope can be checked against the project's current boundaries.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
The [support guide](SUPPORT.md) routes usage questions, reproducible defects,
and documentation problems to the right project channel. Do not report a
vulnerability or disclose sensitive recordings in a public issue; follow
[SECURITY.md](SECURITY.md) instead.

## Supported development environment

Use Python 3.12 or 3.13. The complete suite is tested on Ubuntu with both Python
versions. The camera-free suite and installed-wheel demo are tested on macOS.
WSL2 is not currently advertised as supported, and native Windows is not
supported. A camera and GPU are optional for the bundled demo and most tests.

From a clean clone on Linux or macOS:

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest playwright build twine
python -m playwright install chromium
```

Use `python3.13` instead when testing that interpreter. On Ubuntu, Playwright's
system packages can be installed with `python -m playwright install chromium
--with-deps`. That command may request operating-system privileges.

Check the installation before changing code:

```bash
metriplane --version
metriplane doctor
metriplane demo
```

## Tests

Run the complete suite from the repository root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Run the narrowest relevant test while iterating. Examples:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_demo.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_rule_engine.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_community_health.py
```

Changes to the browser UI must also pass:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/e2e
```

Packaging changes must be checked as built artifacts, not only as an editable
install:

```bash
python -m build
python -m twine check --strict dist/*
```

CI runs the full Linux and macOS combinations and the repository's Release
Gates. A pull request is not ready to merge until every required check is green.

## Branch and pull-request workflow

1. Update `main` and create a short-lived branch for one problem.
2. Make the smallest coherent change and add or update tests.
3. Update user-facing documentation when behavior, commands, artifacts, or
   support boundaries change.
4. Run focused tests and the complete suite.
5. Open a pull request using the repository template. Explain the user-visible
   result, compatibility impact, and evidence/research impact.
6. Address review findings without silently broadening the pull request.

Do not include generated run directories, virtual environments, caches,
credentials, private data, or unrelated formatting changes.

## Add a bounded fixture

Prefer a small synthetic fixture that demonstrates one behavior. A fixture must:

- use the existing timestamped state schema and stable, non-identifying object
  identifiers;
- cover a bounded workcell scenario with an explicit expected result;
- be deterministic and small enough to review in a pull-request diff;
- include a focused test that explains why the fixture exists;
- include only data you have the right to contribute under the repository
  license.

Place test-only inputs under the relevant `tests/fixtures/` directory. Do not
add a fixture to `evidence/paper_v2_0/`, and do not present a new fixture as part
of an archived research evaluation.

For a fixture derived from a real recording, document how it was minimized and
de-identified. Synthetic data is strongly preferred.

## Privacy and contributed recordings

You are responsible for obtaining permission to contribute every recording and
derived file. Before submission:

- remove images, video, audio, biometric data, names, customer or site names,
  exact locations, device serial numbers, network addresses, credentials, and
  other identifying metadata;
- replace real object and work-order identifiers with stable synthetic values;
- inspect reports, manifests, command output, and paths for information copied
  from the original environment;
- confirm that a minimal synthetic reproducer cannot replace the real data;
- state the data's origin, permission, license, and de-identification steps in
  the pull request without disclosing private details.

Never attach private production data to an issue or pull request. Maintainers
may reject or remove material whose consent, ownership, or privacy status is
unclear.

## Changes that affect evidence

Call out any change to event generation, incident analysis, timestamps, report
content, checksums, bundle layout, verification, replay, regression behavior,
schemas, or default process rules. Add tests for both the intended result and a
relevant failure path. Describe whether existing artifacts remain readable and
whether output differences are expected.

The SoftwareX research artifact is frozen at tag `v0.2.0`, commit
`8e35ed5bb20837f7dc46354777407b848d7ce17a`. Do not edit, regenerate,
reformat, or relabel its evidence, checksums, measurements, or DOI metadata.
The TIM paper's evaluated software boundary remains v0.1.3. Current code and new
fixtures must not be described as having produced those historical results.

## Licensing and attribution

Contributors are responsible for all submitted code, documentation, fixtures,
and media. Do not submit third-party material unless its license is compatible
with this repository and all required copyright notices and attribution are
preserved. Identify copied or adapted material and its license in the pull
request. By submitting a contribution, you represent that you have the right to
license it under the terms used by this repository.
