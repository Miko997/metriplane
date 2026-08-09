<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Releasing Metriplane

Metriplane uses PyPI Trusted Publishing. A release tag starts a workflow that
builds one wheel and one source distribution, records their SHA-256 hashes,
publishes those exact files to TestPyPI, verifies them, pauses for protected
production approval, and then publishes the same files to PyPI.

PyPI files are immutable. Never tag a candidate until its pull request is
merged, every required check is green, and the owner has approved the release
sequence. Never try to replace a bad published file; fix the problem and use a
new version.

## Reusable manual product-understanding gate

Before declaring any adoption-focused release candidate ready, run the
[first-time-user comprehension check](validation/first-time-user-comprehension.md)
with unfamiliar testers. Record only anonymous, redacted observations for the
exact candidate commit, version, and material types. Run its calculator and
carry a pending or failed result into the release blockers; automated checks do
not substitute for this manual gate.

The structured results file is retained in the repository for release review
but is explicitly excluded from the generated documentation site.

## One-time repository and registry setup

1. Create GitHub environments named exactly `testpypi` and `pypi` under
   **Settings → Environments**.
2. Add an owner-approved required reviewer to `pypi`. Do not require approval
   for `testpypi`, which is the automated staging registry. If the only
   maintainer is also the reviewer, configure the environment so that the
   authorized owner can approve it without deadlocking the job.
3. Restrict the `pypi` environment to release tags. Protect `v*` tags against
   update and deletion with a repository ruleset.
4. Configure Trusted Publishers for the `metriplane` project in both
   [TestPyPI](https://test.pypi.org/manage/account/publishing/) and
   [PyPI](https://pypi.org/manage/account/publishing/):

   | Field | TestPyPI | PyPI |
   | --- | --- | --- |
   | Owner | `Miko997` | `Miko997` |
   | Repository | `metriplane` | `metriplane` |
   | Workflow | `publish-pypi.yml` | `publish-pypi.yml` |
   | Environment | `testpypi` | `pypi` |

5. Require two-factor authentication on both registry accounts.
6. Confirm that GitHub Actions has read access to repository contents and that
   only the two publishing jobs receive `id-token: write`.

No long-lived registry token belongs in GitHub secrets.

## Prepare a release-candidate pull request

Use a clean branch from the latest `main`. The release-candidate pull request is
the only place that changes the package version.

1. Set `metriplane.__version__` to the intended version.
2. Confirm distribution metadata and `metriplane --version` use that same
   value.
3. Finalize the changelog, migration notes, README quickstart, and release
   notes. Remove all pre-release wording that is no longer true.
4. Confirm supported-environment wording matches executed checks.
5. Verify that the frozen v0.2.0 evidence, tag, DOI metadata, checksums,
   `CITATION.cff`, and `.zenodo.json` were not rewritten.
6. Run the human-comprehension gate or record it accurately as an unfinished
   manual gate.
7. Open the pull request and wait for CI, Documentation, and Release Gates.

Do not merge the final candidate, tag it, or publish it until the owner gives
explicit approval.

## Validate the candidate locally

Run from a clean checkout. Replace `<version>` with the exact candidate version,
keep the same shell for the following blocks, and use separate temporary
environments for the source tree, wheel, and source distribution.

```bash
release_version="<version>"
python3.12 -m venv /tmp/metriplane-release-source
source /tmp/metriplane-release-source/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest setuptools build twine
python -m pip check
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
release_artifact_root="$(mktemp -d)"
python -m build --outdir "$release_artifact_root/dist"
python -m twine check --strict "$release_artifact_root"/dist/*
python tools/release_artifacts.py create-manifest \
  --dist "$release_artifact_root/dist" \
  --manifest "$release_artifact_root/SHA256SUMS" \
  --version "$release_version"
python tools/release_artifacts.py inspect-sdist \
  --sdist "$release_artifact_root/dist/metriplane-${release_version}.tar.gz" \
  --version "$release_version"
```

Test the wheel outside the checkout:

```bash
wheel_path="$(realpath "$release_artifact_root"/dist/metriplane-${release_version}-*.whl)"
python3.12 -m venv /tmp/metriplane-release-wheel
/tmp/metriplane-release-wheel/bin/python -m pip install --upgrade pip
/tmp/metriplane-release-wheel/bin/python -m pip install \
  "$wheel_path"
(
  cd /tmp
  /tmp/metriplane-release-wheel/bin/python -m pip check
  /tmp/metriplane-release-wheel/bin/metriplane --version
  /tmp/metriplane-release-wheel/bin/metriplane --help
  /tmp/metriplane-release-wheel/bin/metriplane doctor
  /tmp/metriplane-release-wheel/bin/metriplane demo
)
```

Then test the source distribution independently. Installing the wheel does not
prove that the source distribution contains enough files to build and run.

```bash
sdist_path="$(realpath "$release_artifact_root"/dist/metriplane-${release_version}.tar.gz)"
python3.12 -m venv /tmp/metriplane-release-sdist
/tmp/metriplane-release-sdist/bin/python -m pip install --upgrade pip
/tmp/metriplane-release-sdist/bin/python -m pip install \
  "$sdist_path"
(
  cd /tmp
  /tmp/metriplane-release-sdist/bin/python -m pip check
  /tmp/metriplane-release-sdist/bin/metriplane --version
  /tmp/metriplane-release-sdist/bin/metriplane doctor
  /tmp/metriplane-release-sdist/bin/metriplane demo
)
```

Inspect both archives before approval. They must contain package source,
license and notice files, metadata, and every bundled-demo resource. They must
not contain credentials, local paths, generated runs, caches, private media,
editor files, or unrelated research archives.

## Create the annotated tag

Only after the owner approves and the final release-candidate pull request is
merged, update local `main` to the exact remote commit. Replace `<version>` and
`<approved-main-sha>` deliberately.

```bash
release_version="<version>"
approved_main_sha="<approved-main-sha>"
git switch main
git pull --ff-only
git status --short
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$approved_main_sha"
test "$(python -c 'import metriplane; print(metriplane.__version__)')" = \
  "$release_version"
git tag -a "v${release_version}" -m "Metriplane v${release_version}"
git push origin "v${release_version}"
```

The publication workflow rejects:

- a lightweight rather than annotated tag;
- a tag whose name differs from the package version;
- a tag whose commit is not in the history of remote `main`;
- a build that produces anything other than one wheel and one source
  distribution;
- a source distribution that is incomplete or unsafe;
- files whose SHA-256 hashes change between build, upload, or registry
  publication.

## Staged publication and protected production approval

The workflow performs this sequence:

1. verify tag provenance;
2. run the reusable Release Gates;
3. rerun the complete test suite;
4. build the wheel and source distribution once;
5. run strict metadata validation;
6. test the wheel outside the checkout;
7. install and test the source distribution in a different environment;
8. upload the two files with a SHA-256 manifest;
9. publish those files to TestPyPI;
10. compare TestPyPI's file hashes with the build manifest and install the
    staged package;
11. stop at the protected `pypi` environment;
12. after owner approval, publish the same downloaded files to PyPI;
13. compare production PyPI's hashes with the same manifest and verify a clean
    production installation.

Do not approve the `pypi` environment until the TestPyPI verification job is
green and its version, doctor, demo, bundle-verification, and regression-check
results have been reviewed. A failed TestPyPI stage means stop, diagnose, and
prepare a new version if any immutable file was already accepted by a registry.

## Verify production and finish the release

After the workflow's production verification is green, perform one more owner
check from a clean environment:

```bash
release_version="<version>"
python3.12 -m venv /tmp/metriplane-production-check
/tmp/metriplane-production-check/bin/python -m pip install --upgrade pip
/tmp/metriplane-production-check/bin/python -m pip install \
  "metriplane==${release_version}"
(
  cd /tmp
  /tmp/metriplane-production-check/bin/python -m pip check
  /tmp/metriplane-production-check/bin/metriplane --version
  /tmp/metriplane-production-check/bin/metriplane doctor
  /tmp/metriplane-production-check/bin/metriplane demo --open
)
```

Only then finalize the GitHub release body, merge the separately validated
website release pull request, deploy the website, and update repository
discovery metadata.

### Stop gate: Zenodo and citation metadata

Before creating the GitHub release, the owner must verify that Zenodo's GitHub
integration will **not** automatically archive v0.3.0. The frozen v0.2.0 DOI
must not be attached to v0.3.0, and no v0.3.0 DOI may be claimed before a
separate, intentionally described archive exists. If automatic archiving is
enabled or its behavior is uncertain, stop before creating the GitHub release.

See [Citing Metriplane](user-guide/citing.md) for the separate software,
frozen-artifact, and paper citation paths.

## v0.3.0 release-candidate checklist

This section is a preparation checklist, not evidence that v0.3.0 is published.

- [ ] Final candidate version is `0.3.0` in the package, CLI, and metadata.
- [ ] Primary README path is
      `python -m pip install "metriplane==0.3.0"` followed by
      `metriplane demo --open`.
- [ ] Linux Release Gates pass on Python 3.12 and 3.13.
- [ ] The bundled camera-free demo passes on macOS with Python 3.12 and 3.13.
- [x] WSL2 wording is bounded to the recorded Ubuntu 24.04/Python 3.12.3
      installed-wheel camera-free and headless owner run; automatic browser
      opening is not claimed.
- [ ] Native Windows is not advertised.
- [ ] Wheel and source distribution pass independent clean installations.
- [ ] The exact artifact SHA-256 manifest is recorded from the workflow run.
- [ ] Frozen v0.2.0 evidence and research-integrity checks pass.
- [ ] Human-comprehension results are recorded, or the manual gate remains open.
- [ ] Final release-candidate pull request has explicit owner approval.
- [ ] Zenodo automatic archiving is confirmed disabled before GitHub release.

The prepared v0.3.0 migration, release, and launch drafts live under
[`docs/releases/`](releases/). Fill their explicit placeholders only from the
actual approved release and registry results.
