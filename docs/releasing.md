<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Releasing Metriplane

Metriplane uses PyPI Trusted Publishing. A release tag starts a workflow that
builds one wheel and one source distribution, records their SHA-256 hashes,
publishes those exact files to TestPyPI, and verifies them. Production
publication is a separate owner-only manual dispatch that names the successful
tag workflow run, version, and an exact confirmation phrase. The `pypi`
environment is an additional protection layer, not the only approval control.

PyPI files are immutable. Never tag a candidate until its pull request is
merged, every required check is green, and the owner has approved the release
sequence. Never try to replace a bad published file; fix the problem and use a
new version.

## Reusable manual product-understanding check

For adoption feedback, run the
[first-time-user comprehension check](validation/first-time-user-comprehension.md)
with unfamiliar testers. Record only anonymous, redacted observations for the
exact candidate commit, version, and material types. Run its calculator and
report pending, failed, or passing results exactly; automated checks do not
substitute for human observations.

For v0.3.0, no unfamiliar tester was available before publication. On
2026-08-09 the owner explicitly deferred this check to a post-release adoption
follow-up. The retained zero-tester result remains `MANUAL GATE PENDING`, does
not block the software release, and must not be described as a passing human
validation.

The structured results file is retained in the repository for release review
but is explicitly excluded from the generated documentation site.

## One-time repository and registry setup

1. Create GitHub environments named exactly `testpypi` and `pypi` under
   **Settings → Environments**.
2. Add an owner-approved required reviewer to `pypi`. Do not require approval
   for `testpypi`, which is the automated staging registry. If the only
   maintainer is also the reviewer, configure the environment so that the
   authorized owner can approve it without deadlocking the job. The workflow's
   separate owner-only manual dispatch remains mandatory even if environment
   protection is absent or misconfigured.
3. Restrict `testpypi` to release tags and restrict `pypi` to protected
   `main`. The manual production dispatch rejects any other ref or a stale main
   commit. Keep the active repository ruleset `Protect release tags` targeted
   at tags with the sole include `refs/tags/v*`, empty exclusions and bypass
   actors, and exactly the `update` and `deletion` rules. Do not add a creation
   rule: new release tags must remain creatable.
4. Activate the App-only `main` update ruleset and the protected
   `release-leases/**` ruleset described in
   [Release blocker workflow](maintainers/blocker-workflow.md#production-serialization).
   Confirm that only the broker App can mutate lease refs and that it
   acknowledges an exact lease with its App-owned
   `Release serialization / required` check. Production publication is fail
   closed until this MET-77 dependency is live.
5. Configure Trusted Publishers for the `metriplane` project in both
   [TestPyPI](https://test.pypi.org/manage/account/publishing/) and
   [PyPI](https://pypi.org/manage/account/publishing/):

   | Field | TestPyPI | PyPI |
   | --- | --- | --- |
   | Owner | `Miko997` | `Miko997` |
   | Repository | `metriplane` | `metriplane` |
   | Workflow | `publish-pypi.yml` | `publish-pypi.yml` |
   | Environment | `testpypi` | `pypi` |

6. Require two-factor authentication on both registry accounts.
7. Confirm that GitHub Actions has read access to repository contents and that
   only the TestPyPI and production publishing jobs receive `id-token: write`.

No long-lived registry token belongs in GitHub secrets.

## Prepare a release-candidate pull request

Use a clean branch from the latest `main`. The release-candidate pull request is
the only place that changes the package version.

1. Set `metriplane.__version__` to the intended version.
2. Confirm distribution metadata and `metriplane --version` use that same
   value.
3. Finalize the changelog, migration note, README quickstart, and substantive
   release copy. The migration note must be final, but release notes and launch
   materials remain explicitly **DRAFT — UNPUBLISHED** with unfilled commit,
   date, workflow, and artifact-hash fields until production verification.
4. Confirm supported-environment wording matches executed checks.
5. Verify that the frozen v0.2.0 evidence, tag, DOI metadata, checksums,
   `CITATION.cff`, and `.zenodo.json` were not rewritten.
6. Run the human-comprehension check when unfamiliar testers are available. For
   v0.3.0, retain the accurate zero-tester pending record as the explicitly
   deferred post-release follow-up; do not claim that human validation passed.
7. Open the pull request and wait for CI, Documentation, and Release Gates.

Do not merge the final candidate, tag it, or publish it until the owner gives
explicit approval.

## Validate the candidate locally

Run from a clean checkout. Replace `<version>` with the exact candidate version,
keep the same shell for the following blocks, and use separate temporary
environments for the source tree, wheel, and source distribution. Source
qualification uses the exact root lock and tool identities in the
[maintainer testing policy](maintainers/testing-policy.md); it does not resolve a
parallel release-only toolchain. The canonical frozen sync installs the exact
setuptools build backend, and the retained distribution build runs without an
isolated resolver.

```bash
release_version="<version>"
release_source_root="$(mktemp -d)"
export UV_PROJECT_ENVIRONMENT="$release_source_root/.venv"
export UV_NO_CONFIG=1
test "$(uv --version | awk '{print $2}')" = "0.12.0"
uv --no-config lock --check
uv --no-config sync --frozen --all-groups
uv --no-config pip check
uv --no-config run --frozen python -m playwright install chromium --with-deps
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  uv --no-config run --frozen python -m pytest -q
release_artifact_root="$(mktemp -d)"
uv --no-config run --frozen python -m build \
  --no-isolation \
  --outdir "$release_artifact_root/dist"
uv --no-config run --frozen python -m twine check --strict \
  "$release_artifact_root"/dist/*
uv --no-config run --frozen python tools/release_artifacts.py create-manifest \
  --dist "$release_artifact_root/dist" \
  --manifest "$release_artifact_root/SHA256SUMS" \
  --version "$release_version"
uv --no-config run --frozen python tools/release_artifacts.py inspect-sdist \
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

Run the complete documented evidence-to-regression proof with the installed
wheel, outside the checkout. Both Atlas runs use the same explicit run identity
so the deterministic files are directly comparable:

```bash
metriplane_cmd=/tmp/metriplane-release-wheel/bin/metriplane
wheel_python=/tmp/metriplane-release-wheel/bin/python
proof_root="$(mktemp -d)"
proof_inputs="$proof_root/inputs"
proof_run_a="$proof_root/run-a"
proof_run_b="$proof_root/run-b"

"$metriplane_cmd" demo --export-inputs "$proof_inputs"
"$metriplane_cmd" atlas validate-pack "$proof_inputs/domain-pack"

for proof_run in "$proof_run_a" "$proof_run_b"; do
  "$metriplane_cmd" atlas run \
    --session-jsonl "$proof_inputs/session.jsonl" \
    --pack "$proof_inputs/domain-pack" \
    --out "$proof_run" \
    --run-id v040-release-proof
  "$metriplane_cmd" atlas report --run-dir "$proof_run"
  "$metriplane_cmd" atlas bundle verify \
    "$proof_run/evidence_bundles/INC-0001.zip"
  "$metriplane_cmd" atlas test \
    "$proof_run/regression_tests/INC-0001.yaml" --json
done

for artifact in \
  physical_event_log.jsonl deviations.jsonl incidents.jsonl \
  reality_graph.json process_trace.json flow_metrics.csv; do
  cmp -- "$proof_run_a/$artifact" "$proof_run_b/$artifact"
done
```

The declared negative case mutates only a disposable copy of the directory-form
bundle. Verification must exit 3, report `pass: false`, and name the changed
file:

```bash
negative_bundle="$proof_root/tampered-bundle"
cp -R "$proof_run_a/evidence_bundles/INC-0001" "$negative_bundle"
printf '\n' >> "$negative_bundle/incident.json"
set +e
negative_json="$("$metriplane_cmd" atlas bundle verify "$negative_bundle")"
negative_status=$?
set -e
test "$negative_status" -eq 3
printf '%s\n' "$negative_json" | "$wheel_python" -c \
  'import json,sys; r=json.load(sys.stdin); assert r["pass"] is False; assert "checksum mismatch: incident.json" in r["errors"]'
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

## Staged publication and explicit production promotion

The workflow performs this sequence:

1. verify tag provenance;
2. run the reusable Release Gates;
3. sync the canonical lock, prove its exact governed tool versions, install the
   locked Playwright browser and runtime dependencies, and rerun the complete
   test suite;
4. build the wheel and source distribution once with the locked build frontend
   and setuptools backend, without an isolated resolver;
5. run strict metadata validation;
6. test the wheel outside the checkout;
7. install and test the source distribution in a different environment;
8. upload the two files with a SHA-256 manifest;
9. publish those files to TestPyPI;
10. compare TestPyPI's file hashes with the build manifest and install the
    staged package;
11. stop after verified TestPyPI publication;
12. from the latest `main`, have the owner manually run **Publish Python
    distributions** with the successful tag workflow run ID, exact version,
    and exact confirmation
    `publish metriplane <version> to production`;
13. verify that the named source run was a successful tag run for the same
    annotated tag and commit and that it has one unexpired immutable artifact;
14. re-download that exact artifact set and compare it with TestPyPI before the
    `pypi` environment is entered;
15. wait for the App-only main-update broker to create the exact protected
    publish-lease ref and acknowledge that all main updates are fenced;
16. revalidate live blocker approvals while the lease is held, then reassert the
    lease, its exact App check, and exact current `main` immediately before the
    trusted publishing action;
17. publish the verified files to PyPI;
18. while the lease remains active, compare production PyPI's hashes with the
    same manifest and verify a clean production installation;
19. wait for the broker to re-prove exact `main`, retire its exact lease, and
    complete the same App check successfully before main updates resume.

Do not start the production workflow dispatch until the TestPyPI verification
job is green and its version, doctor, demo, bundle-verification, and
regression-check results have been reviewed. If the environment also pauses,
approve it only after confirming the dispatch inputs. A failed TestPyPI stage
means stop, diagnose, and prepare a new version if any immutable file was
already accepted by a registry.

Any `main` drift detected before step 17 burns the candidate; stop and create a
new tag. A failed or ambiguous production upload or verification deliberately
leaves the App-owned lease active. Do not delete it by hand or retry
publication. Reconcile the PyPI file hashes and broker state first, then use the
broker's audited recovery path. Drift detected after PyPI accepts immutable
bytes is a release incident, not an unpublished candidate.

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

### Stop gate: Zenodo and citation metadata

Before creating the GitHub release, the owner must verify that Zenodo's GitHub
integration will **not** automatically archive v0.4.0.post1. The frozen v0.2.0 DOI
must not be attached to v0.4.0.post1, and no v0.4.0.post1 DOI may be claimed before a
separate, intentionally described archive exists. If automatic archiving is
enabled or its behavior is uncertain, stop before creating the GitHub release.

See [Citing Metriplane](user-guide/citing.md) for the separate software,
frozen-artifact, and paper citation paths.

Only then finalize the GitHub release body. Attach the retained workflow copies
of the wheel, source distribution, and `SHA256SUMS`; do not rebuild or rename
them. Download all three GitHub Release assets into a new directory, require the
exact three-name inventory, verify the manifest, and compare every SHA-256 value
with the retained workflow artifact and both public registries. Any missing,
extra, or changed asset stops release completion.

After that readback succeeds, merge the separately validated website release
pull request, deploy the website, and update repository discovery metadata.

## v0.4.0.post1 publication-recovery stop gates

v0.4.0.post1 publishes the existing reduced Truth Recovery core scope under the
corrected publication identity. It adds no product capability or assurance.
Stop the candidate before tagging or publication if any condition is false:

- `0.4.0.post1` and `v0.4.0.post1` were confirmed unoccupied before the candidate was
  frozen;
- `v0.4.0` still identifies
  `6a87936b5471c320efa6bcd7f5d1fe5569ca57b9`, no 0.4.0 registry package or
  GitHub Release exists, and no artifact from failed workflow `33695500256` is
  reused;
- the active `Protect release tags` provider ruleset has exact include
  `refs/tags/v*`, empty exclusions and bypass actors, and exactly `update` and
  `deletion` rules, leaving creation permitted;
- the exact candidate commit and tree descend from dependency-complete protected
  `main` and remain unchanged throughout qualification;
- MP2-007 and MP2-014 through MP2-017 remain explicitly deferred to v0.4.1
  Assurance Hardening rather than being described as passed, completed, or
  waived;
- historical v2.5.x authority packets were not consumed or recreated as release
  authority;
- current-version external-fixture evaluations are separate, checksummed
  materializations and the frozen source-specific v0.3.0 proof trees are
  unchanged;
- release claims do not expand static inventories or deterministic software
  checks into production-safety, physical-accuracy, generic-robotics, or v1.0
  assurance claims;
- release notes and launch materials still carry their draft marker and
  unfilled production fields; and
- generated inventories are current for the exact staged candidate.

Any candidate-code or release-document change after qualification and before
tagging invalidates the candidate and requires qualification of the new exact
commit. Local pre-tag builds are disposable checks. The tag workflow's retained
wheel, source distribution, and SHA-256 manifest are the build-once publication
set and must not be rebuilt for production promotion.

## v0.4.0.post1 release-candidate checklist

This section is a preparation checklist, not evidence that v0.4.0.post1 is published.

- [ ] Version `0.4.0.post1` and tag `v0.4.0.post1` were confirmed unoccupied.
- [ ] Final candidate version is `0.4.0.post1` in the package, CLI, and metadata;
      the tag invariant remains `tag == "v" + exact package version`.
- [ ] The failed `v0.4.0` identity and workflow are preserved exactly, and no
      failed-workflow artifact is reused.
- [ ] Exact candidate commit and tree are recorded from dependency-complete
      protected `main`.
- [ ] Primary README path is
      `python -m pip install "metriplane==0.4.0.post1"` followed by
      `metriplane demo --open`.
- [ ] Pinned Ruff lint and format, strict mypy, tracked Python compilation,
      strict documentation, and generated-inventory currentness checks pass.
- [ ] Complete source qualification and the focused MP2-002 and MP2-013 checks
      pass on the exact candidate.
- [ ] Linux Release Gates pass on Python 3.12 and 3.13.
- [ ] The bundled camera-free demo passes on macOS with Python 3.12 and 3.13.
- [ ] Any WSL2 or native-Windows wording is backed by a fresh v0.4.0.post1 candidate
      record; historical v0.3.0 observations are not relabeled.
- [ ] Wheel and source distribution pass independent clean installations.
- [ ] The canonical bundled example, complete documented
      evidence-to-regression workflow, deterministic repeat, and one declared
      negative case pass in their declared clean environments.
- [ ] The exact artifact SHA-256 manifest is recorded from the workflow run.
- [ ] Frozen v0.2.0 evidence and research-integrity checks pass.
- [ ] Frozen source-specific v0.3.0 fixture/proof identities remain unchanged;
      v0.4.0.post1 compatibility evaluation uses explicit disposable projections.
- [ ] The release notes identify the reduced Truth Recovery scope, all deferred
      Assurance Hardening work, and every actual limitation without expanding
      support claims.
- [ ] Final release-candidate pull request has explicit owner approval.
- [ ] Zenodo automatic archiving is confirmed disabled before GitHub release.

The prepared v0.4.0.post1 migration note, draft release notes, and draft launch
materials live under [`docs/releases/`](releases/). Fill their explicit
placeholders only from the actual approved release, retained build-once
artifacts, successful tag and production runs, and final registry readback.

The v0.3.0 release files and the recorded v0.3.0 human-comprehension,
WSL2, and native-Windows facts remain historical evidence. Do not update them to
describe v0.4.0.post1.

### Post-publication documentation reconciliation

The immutable tag necessarily contains the explicitly marked draft release
notes and launch checklist: production workflow IDs, retained artifact hashes,
registry readback, and the GitHub release URL do not exist when the tag is
created. Build the final GitHub release body directly from that verified live
evidence.

After publication succeeds, use a separate documentation-only pull request on
protected `main` to fill the v0.4.0.post1 release-note and launch-material fields,
remove their draft notices, and record the completed checklist. This follow-up
does not modify the tag, rebuild artifacts, or invalidate the already published
candidate. Run only the documentation, generated-inventory currentness, and
clean-worktree gates appropriate to that follow-up.
