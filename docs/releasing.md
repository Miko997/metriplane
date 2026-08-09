<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Publishing Metriplane to PyPI

Metriplane uses PyPI Trusted Publishing. The release workflow builds once,
publishes those exact artifacts to TestPyPI, verifies an installation from
TestPyPI, and only then makes the production PyPI job eligible for approval.
No long-lived PyPI API token is stored in GitHub.

## Reusable manual product-understanding gate

Before declaring any adoption-focused release candidate ready, run the
[first-time-user comprehension check](validation/first-time-user-comprehension.md)
with unfamiliar testers. Record only anonymous, redacted observations for the
exact candidate commit, version, and material types. Run its calculator and
carry a pending or failed result into the release blockers; automated checks do
not substitute for this manual gate.

The structured results file is retained in the repository for release review
but is explicitly excluded from the generated documentation site.

## One-time setup

1. In the GitHub repository, create environments named exactly `testpypi` and
   `pypi` under **Settings → Environments**.
2. Add yourself as a required reviewer for the `pypi` environment. Do not add a
   required reviewer to `testpypi`; it is the automated staging registry. If
   you are the only maintainer, leave **Prevent self-review** disabled or add a
   second reviewer, otherwise the production job will deadlock.
3. Restrict the `pypi` environment to release tags and add a repository tag
   ruleset for `v*` that prevents tag updates and deletion.
4. Sign in to [TestPyPI](https://test.pypi.org/) and enable two-factor
   authentication.
5. Open [TestPyPI's pending-publisher form](https://test.pypi.org/manage/account/publishing/)
   and enter:

   | Field | Value |
   |---|---|
   | PyPI project name | `metriplane` |
   | Owner | `Miko997` |
   | Repository name | `metriplane` |
   | Workflow name | `publish-pypi.yml` |
   | Environment name | `testpypi` |

6. Sign in to [PyPI](https://pypi.org/), enable two-factor authentication, and
   open [PyPI's pending-publisher form](https://pypi.org/manage/account/publishing/).
   Enter the same values, except use `pypi` for the environment name.

The pending publishers can create the projects on the first successful
workflow run. If the project already exists under your account, add the same
publishers from that project's **Publishing** settings instead.
Pending publishers do not reserve a project name, so complete the release soon
after configuring them.

## Prepare v0.2.1

From a clean `fix/pypi-0.2.1` branch:

```bash
python3.12 -m venv /tmp/metriplane-release-venv
source /tmp/metriplane-release-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest setuptools build twine
python -m pip check
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m build
python -m twine check --strict dist/*
```

Open a pull request, wait for CI and Release Gates to pass, and merge it into
`main`. Confirm that `metriplane.__version__` is `0.2.1` before tagging.

## Publish v0.2.1

Create the tag only from the tested commit on `main`:

```bash
git switch main
git pull --ff-only
git status --short
python -c "import metriplane; assert metriplane.__version__ == '0.2.1'"
git tag -a v0.2.1 -m "Metriplane v0.2.1"
git push origin v0.2.1
```

Open **Actions → Publish Python distributions**. The workflow will:

1. run the required fixture, UI, browser, evidence, package, and ROS release gates;
2. reject a tag that is not on `main` or does not equal the package version;
3. rerun the full test suite and build the wheel and source distribution;
4. validate and smoke-test the wheel outside the checkout;
5. publish to TestPyPI and verify that registry installation;
6. pause at the protected `pypi` environment;
7. publish the same files to PyPI after you approve the deployment;
8. verify a new installation from production PyPI.

Approve production only after the TestPyPI verification job is green. After the
production verification job is also green, create a GitHub release for the
`v0.2.1` tag and paste the 0.2.1 changelog.

## Verify production

Use a new environment that is not inside the repository:

```bash
python3.12 -m venv /tmp/metriplane-pypi-check
/tmp/metriplane-pypi-check/bin/python -m pip install --upgrade pip
/tmp/metriplane-pypi-check/bin/python -m pip install "metriplane==0.2.1"
/tmp/metriplane-pypi-check/bin/python -m pip check
cd /tmp
/tmp/metriplane-pypi-check/bin/python -c "import importlib.metadata as md, metriplane; assert metriplane.__version__ == md.version('metriplane') == '0.2.1'"
/tmp/metriplane-pypi-check/bin/metriplane doctor
/tmp/metriplane-pypi-check/bin/metriplane atlas protocol export --out protocol-production
```

PyPI release files are immutable. If a published artifact is wrong, correct
the source, increase the version, and publish a new release; do not try to
replace the existing v0.2.1 files.
