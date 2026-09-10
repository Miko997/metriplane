# Maintainer testing policy

Metriplane supports Python 3.12 and 3.13. Runtime dependency ranges remain in
`pyproject.toml`; the maintainer build and test toolchain is exact:

| Tool | Required identity |
| --- | --- |
| uv | `uv==0.12.0` |
| build backend | `setuptools==82.0.1` |
| build | `build==1.5.0` |
| MkDocs | `mkdocs==1.6.1` |
| mypy | `mypy==1.20.2` |
| Playwright | `playwright==1.62.0` |
| pytest | `pytest==8.4.2` |
| Ruff | `ruff==0.16.2` |
| Twine | `twine==6.2.0` |
| PyYAML stubs | `types-PyYAML==6.0.12.20260724` |

The matching pre-commit hooks use Ruff `v0.16.2` and mypy `v1.20.2`; local
hooks and CI therefore evaluate the same tool identities.

`setuptools==82.0.1` is both the exact build-system requirement and a member of
the canonical dev group. In a fresh release environment, qualification uses the
same frozen all-groups sync as canonical CI. The exact build-system requirement
also seeds the uv cache used by the suite's deliberately offline historical
installation proof. Release builds then use `python -m build --no-isolation`
from that environment, so the retained distributions execute the installed,
lock-governed backend rather than a separately resolved build environment.

Use the exact uv executable and ignore user or system uv configuration:

```bash
uv --no-config lock --check
uv --no-config sync --frozen --all-groups
```

## Maintained Python quality

The root quality gate uses the pinned tools and stable, explicitly selected
Ruff error families. Independently locked adapter packages run their own local
quality gates. Historical evidence, retained proof trees, and the frozen Atlas
proof implementation are byte-preserved, so the root gate excludes `adapters/`,
`evidence/`, `metriplane/atlas/`, and `proofs/`:

```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
```

Strict mypy covers the maintained `metriplane` package outside the frozen Atlas
proof implementation. New package modules join that gate automatically; tests,
operational scripts, benchmarks, and isolated adapter packages remain exercised
by their runtime and package-specific gates. Atlas remains covered by its
functional, evidence-freeze, and release-blocker tests until that proof surface
is explicitly reopened under its governing policy. Imports from that excluded
namespace are treated as an external frozen boundary (`follow_imports = "skip"`),
not silenced with `ignore_errors` or per-diagnostic ignores.

MET-162 explicitly reopens the current Atlas assessment, run assessment,
process-model observer, improvement comparison, run manifest, runtime, report,
and bundle files. Its source-family freeze test names those eight paths exactly
and compares the preexisting evaluator methods, apart from the observer-wrapped
`update`, against the frozen baseline AST. All other Atlas paths and the archived
fixtures, proofs, external contract schema, and source specifications retain
their existing freeze checks. This bounded reopening does not extend the
historical SoftwareX or TIM claims. The root quality exclusions above are
unchanged; functional, compatibility, installed-artifact, and evidence tests
validate this change.

## Source profile

The canonical source command uses an empty Playwright browser cache so the
optional browser smoke test has the same result on every maintainer machine:

```bash
PLAYWRIGHT_BROWSERS_PATH=/path/to/empty/browser-cache PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

The browser-enabled smoke test is a separate local check and does not change
the canonical source result.

Pytest rejects unknown configuration and markers, treats unexpected xpasses as
failures, and promotes warnings to errors. Neither pytest configuration nor a
conftest adds the repository to `PYTHONPATH` or mutates `sys.path`; the synced
environment must provide the source installation normally.

The policy test enforces canonical collection with:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --collect-only -q -p no:cacheprovider
```

The ordered node-id stream must contain exactly 5,565 items. In the exact core
environment above, without optional GPU extras and with the empty browser
cache, the integrated source profile requires 5,550 passed and 15 expected skips.
Twelve result-schema cases run in the separate locked
cross-adapter gate, one browser smoke case requires the separately installed
Chromium binary, one GPU-equivalence case requires an optional CuPy extra, and
two functional-inventory cases require their governed retained-evidence and
non-editable installed-package profiles.
The frozen MP2-000 1,194-item snapshot is a historical artifact and is not
updated by this policy.

## Iteration and hosted qualification

Finish a coherent slice locally before pushing: inspect its producers, consumers,
schemas, migrations, failure paths and platform behavior; run affected tests,
Ruff, format, mypy, compilation and deterministic inventory checks; complete an
independent review and resolve its findings. Package behavior changes also need
separate installed wheel and sdist smoke checks. Ordinary correction cycles do
not run the complete platform matrix. Finalize the substantive PR body before
creating the qualified candidate.

CI first runs fast source validation. Only a successful prerequisite admits the
complete Linux 3.12 and 3.13 jobs and the complete macOS 3.12 and 3.13 collection.
The current protected merge contract still requires all four environments for
every stable merge candidate; the final v0.4.1 candidate must also satisfy the
complete platform requirement. This change does not substitute sentinels for
that requirement. PR concurrency cancels a superseded generation for the same PR;
main generations remain separate and are not cancelled by a PR update.

Each macOS Python version uses four fresh runners. The runner collects every
node, rejects duplicate or filtered collection, and partitions the final normal
pytest order by zero-based index modulo four. It records both the selected nodes
and their actual execution order. Selection lives in a plugin object in the
outer invocation, so nested pytest fixture processes retain their own normal
collection. No xdist or in-process parallel execution is enabled.

Each suite uploads its original stdout, stderr, JUnit XML and strict JSON report.
The report binds the exact checkout commit and tree, SHA-256 of the exact
`git ls-tree -r -z HEAD` inventory bytes, workflow, run and attempt,
Python and runner image, canonical collection, selected nodes, every phase
outcome and duration, governed skip reason, and before/after source identity.
The aggregate accepts exactly ten artifact directories for that run and attempt:
two complete Linux reports and eight macOS shards. It verifies their original
bytes, identical full collection, disjoint complete coverage in each environment,
actual execution order, per-environment pass/skip/fail totals derived from the
original outcomes, and all required successful jobs. Missing reports,
selector drift, unexpected skips, xfails, xpasses, warnings, interruptions,
source drift and extra evidence all fail closed. The single existing
`Metriplane / required` terminal depends on this aggregate.

Fresh shards must agree on the Python patch version, operating system,
architecture and runner image family. Each report retains its exact runner image
version independently because a hosted image rollout can legitimately occur
between fresh runners in one matrix generation; that rollout does not erase or
relabel any shard's recorded environment identity.

Hosted Linux installs Chromium and expects the fifteen remaining governed skips.
Hosted macOS uses the empty browser cache and expects seventeen: the sixteen
source-profile skips above plus the Linux `/proc`-specific case. Skip identities
and exact reasons are enforced by `tools/check_required_terminal.py`; a selector
cannot silently remove them. Collection-only checks prove inventory identity;
they are never reported as full-suite passes.

The lightweight `PR contract` workflow validates fresh metadata using the trusted
base validator. The heavy workflow temporarily retains its `edited` event until
the reviewed broker metadata checks are merged, normally deployed, and read back.
Only that later activation removes the heavy body-edit trigger. Neither the
lightweight metadata check nor provider readback can impersonate a source test
result or make evidence for an old SHA qualify a new one.

Retain exact identities and outcomes for each expensive result. Before another
complete run, record which source or relevant environment changed and why the
existing evidence is invalid. During iteration, test the affected subset; defer
the next full matrix until the corrected candidate is stable. Body wording,
comments, evidence uploads, unchanged readbacks and restarted monitors alone do
not invalidate source tests. Track full-suite executions by Python/platform,
full-matrix generations, cumulative runner time, implementation-to-merge wall
clock and every rerun reason. Historical evidence lacking a node collection must
say that it is unavailable. Benchmark the first four-shard hosted run against
retained original timings before claiming a macOS speedup.

## Installed profiles

Build the wheel and source distribution once, then install each artifact into
its own clean environment. Run the focused policy tests from an unrelated
directory with the checkout unavailable and `PYTHONPATH` absent. Set:

```bash
METRIPLANE_TEST_PROFILE=installed
```

The installed check records the expected site-packages root, imports the core
package modules, and rejects any imported `metriplane` module outside that
root. It also proves that an unknown warning raises under the installed
profile. Wheel and source-distribution results are separate retained checks.

The MP2-007 finalization segment also runs the installed
`TestInstalledFinalization` cases from `tests/test_release_candidate_finalization.py`
against each distribution. An unrelated harness contains only `pyproject.toml`,
the two conftests, the policy test and that release test module. It imports the
installed common controller, exercises candidate creation and public validation,
and verifies conflict recovery and tamper rejection. The harness must not import
checkout tools or substitute a passing finalizer. Its input records and artifact
fixture retain synthetic provenance; these checks grant no live release authority.

## Warning exceptions

The default warning allowlist is empty. An exception requires a reviewed entry
under `[tool.metriplane.testing]` with all of these fields:

```toml
warning_allowlist_version = 1
warning_allowlist = [
  { id = "MPWARN-0001", owner = "maintainers", reason = "Bounded upstream transition", scope = ["source"], category = "DeprecationWarning", message = "exact warning text", expires = "2027-01-01T00:00:00Z" },
]
```

IDs are unique. Owner, reason, category, exact message, source and/or installed
scope, and RFC3339 expiry are mandatory. Unknown fields, malformed entries,
duplicate IDs, expired entries, and unknown profiles stop pytest during
configuration. A valid entry applies only in its exact scope, so the same
warning still fails in every wrong-scope profile.
