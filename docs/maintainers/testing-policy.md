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

The ordered node-id stream must contain exactly 2,461 items. In the exact core
environment above, without optional GPU extras and with the empty browser
cache, the integrated source profile has 2,445 passed and 16 expected skips.
Twelve result-schema cases run in the separate locked
cross-adapter gate, one browser smoke case requires the separately installed
Chromium binary, one GPU-equivalence case requires an optional CuPy extra, and
two functional-inventory cases require their governed retained-evidence and
non-editable installed-package profiles.
The frozen MP2-000 1,194-item snapshot is a historical artifact and is not
updated by this policy.

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
