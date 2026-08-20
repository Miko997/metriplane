<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Cross-adapter compatibility gate v1

## Purpose and claim boundary

The suite verifies that registered Metriplane adapters and portable fixtures
continue to satisfy their documented bounded profiles and Metriplane's shared
External Source Contract and Atlas evaluation boundaries. It does not certify
conformance with upstream robotics standards, establish source truth or
physical accuracy, or prove production readiness.

The gate covers five isolated packages (the Source Adapter SDK plus ManiSkill,
robomimic, ROS 2/MCAP, and MassRobotics adapters) and five portable fixture
families with nine variants (one minimal baseline and four incident/control
pairs). CALVIN remains a registered documentation-only **NO-GO**, not an
executable adapter family.

## Two validation levels

### Level A: pull-request gate

Level A is the bounded, deterministic gate for every pull request,
`merge_group`, push to `main`, and manual dispatch. After locked package
installation, fixture replay requires neither network access nor upstream
robotics frameworks. It performs:

- registry schema validation and fail-closed package, fixture, proof, matrix,
  and CALVIN discovery;
- the exact registered isolated-package commands that are applicable;
- all nine portable fixture validations and Atlas runs;
- exact per-variant event, deviation, incident, evidence-bundle, and generated-
  regression oracles;
- incident bundle verification and generated regression execution;
- control verification that incident-only artifacts do not exist;
- clean local conversion and finalization for the ROS 2/MCAP and MassRobotics
  synthetic sources, plus registered conversion evidence and repeated replay for
  every portable fixture;
- relocation, checksum, tamper, privacy, path-leakage, provenance, registered
  notice, distribution-metadata, package-content, and dependency-boundary
  checks;
- scoped REUSE validation for the files owned by this gate; and
- strict per-component result records followed by an always-run summary.

Level A is the stable branch-protection surface. The summary fails when any
registered required result is absent, malformed, from another commit, failed,
skipped, or canceled. Its Ubuntu/Python 3.12 matrix produces 16 records: one
SDK, four adapter, nine fixture, one shared-contract, and one root-wheel record.

### Level B: exhaustive validation

Level B is scheduled and manually dispatchable. It keeps the four adapter
source suites on Ubuntu/Python 3.12 and adds Ubuntu/Python 3.13 package-build,
lint, import, CLI, metadata, and clean-install records. It runs the SDK, all
nine portable fixtures, and the installed root wheel across Ubuntu/macOS and
Python 3.12/3.13, and raises each fixture's repeated Atlas runs from three to
five. Together with the single Ubuntu/Python 3.12 shared-contract job, the
exhaustive matrix produces 53 result records.

Level B does not currently reacquire the reference-only ManiSkill or robomimic
sources, run adapter source suites on Python 3.13 or macOS, enlarge the mutation
catalog, or add fuzzing. Those remain candidates for later evidence-backed
expansion rather than implied coverage.

Level B does not defer a contract, Atlas-oracle, rights, packaging, privacy, or
registry failure that can be checked in Level A.

## Registry and discovery policy

The authoritative files are:

- `tests/adapter_conformance/registry.json`;
- `tests/adapter_conformance/registry.schema.json`; and
- `tests/adapter_conformance/result.schema.json`.

The harness environment is separately locked by
`tests/adapter_conformance/pyproject.toml` and
`tests/adapter_conformance/uv.lock`. Keeping gate-only JSON Schema and REUSE
tooling there preserves the ordinary root lock and frozen proof identities.

The registry contains the command and evidence model described in the companion
audit. Discovery walks the declared adapter, fixture, proof, and matrix roots;
it is not limited to paths selected by a workflow filter. Validation rejects:

- an unregistered package or portable fixture family;
- a registered path, proof, notice, workflow, variant, or expected artifact
  that is missing;
- duplicate component, family, variant, fixture, adapter, or result identities;
- an executable matrix decision with no registered executable evidence;
- a registered NO-GO family that acquires a prohibited adapter or fixture; or
- an unreviewed change to a fixture fingerprint, session hash, or exact oracle.

The published ManiSkill proof predates the current Ruff rendering and pins its
source bytes. Its registered format policy therefore formats an ephemeral copy,
requires exactly the five reviewed rewrites, compares every Python syntax tree,
and checks the formatted copy again. It never changes or relabels the frozen
proof source. All other packages use an in-place `ruff format --check` policy.

Adding or changing a family is a source-controlled review: update the registry,
schema-compatible fixture evidence, bounded profile documentation, relevant
tests and workflow, proof or distributed evidence paths, matrix status, and
known limitations in the same change. Discovery must pass before family tests
start.

CALVIN's registration pins its NO-GO audit and detects prohibited implementation
paths. The gate must not download CALVIN, reinterpret the audit as a skip, or
construct derived CALVIN state.

## Shared invariants and family-specific oracles

Cross-adapter compatibility means common boundaries plus exact bounded-profile
behavior. The common portable invariants are:

- External Source Contract v1 validates before Atlas;
- the declared authoritative normalized collection is complete and deterministic;
- expected outcomes are test-only and never converter inputs;
- source conversion provenance remains separate from run provenance;
- normalized source events do not invent Atlas process events;
- fixture checksums and rights declarations, required-notice presence, scoped
  REUSE metadata, distribution licence metadata, registered package content,
  and dependency exclusions hold;
- relocation does not change technical results; and
- repeated conversion or replay is canonically equivalent under the registered
  profile policy.

The cross-adapter oracle is deliberately **not** one shared golden event stream.
Frame counts, clocks, trigger frames, event times, source rights, source
materialization, proof layout, ignored fields, and adapter commands differ.
The minimal baseline has five events, each incident has four, and each control
has three; their exact frames and times are stored per variant. The current
incident type is `missing_tool_caused_delay`, but it remains an explicit
per-variant oracle rather than a new universal adapter requirement.

The gate compares each result only with its registered fixture identity and
oracle. It must not normalize all adapters toward ManiSkill, copy one family's
expected outcome into another, or weaken an exact profile-specific rejection so
that families appear uniform.

## Failure classes and evaluation order

Failures are reported against one primary class while retaining the command,
component or variant ID, commit, exit status, and relevant artifact paths.

| Class | Examples | Required boundary |
| --- | --- | --- |
| Registry/discovery | Invalid schema, unregistered directory, missing proof, stale executable matrix mapping, prohibited CALVIN path | Before package or fixture execution |
| Isolated package | Sync, unit, lint, format, type, build, import, or CLI failure | Before source conversion for that adapter |
| Source validation/conversion | Malformed source, unsafe path, unsupported transform, incomplete snapshot, conversion nondeterminism | Before Atlas |
| Contract/trust | Manifest, rights, checksum, provenance, relocation, authority, or trust-layer failure | Before Atlas |
| Atlas/oracle | Ordered events, deviations, incidents, bundle, regression, or control-absence mismatch | After successful contract validation |
| Determinism | Canonical outputs or repeated Atlas results differ | Compare complete registered technical outputs |
| Tamper/privacy/path | Mutated checksum accepted, traversal, machine-local path, or private data leak | Fail closed; never suppress a real finding |
| Rights/package | Required notice missing, scoped REUSE failure, licence-metadata drift, registered package-content mismatch, forbidden referenced bytes, or adapter leakage into the root wheel | Fail before publication evidence is accepted |
| Result aggregation | Missing, malformed, duplicate, wrong-commit, skipped, canceled, or failed result | Final summary fails |

A semantic source failure must never be converted into an Atlas incident. A
failed earlier stage suppresses dependent execution but still emits a failed
result record; it does not make the final summary disappear.

## Result records

Each component and fixture check writes a machine-readable record conforming to
`tests/adapter_conformance/result.schema.json`. Records include the exact git
commit and stable component or variant ID, validation level, command/stage,
status, duration, and bounded evidence summary. The summarizer verifies the
schema, uniqueness, expected inventory, dependency results, and exact commit.

Results are build artifacts, not committed proof replacements. Logs must avoid
machine-local absolute paths and source bytes that the registered rights policy
does not permit.

## Local commands

The aggregate local summary reproduces the Level A matrix identity and therefore
requires Linux and Python 3.12. Run from a clean repository at the commit being
evaluated:

```bash
test "$(uname -s)" = "Linux"
test -z "$(git status --porcelain --untracked-files=all)"
uv sync --locked --project tests/adapter_conformance --python 3.12
uv run --frozen --project tests/adapter_conformance \
  python tools/cross_adapter_gate.py validate-registry
uv run --frozen --project tests/adapter_conformance \
  python tools/cross_adapter_gate.py check \
  --level pr --results-dir /tmp/metriplane-cross-adapter-pr
uv run --frozen --project tests/adapter_conformance \
  python tools/cross_adapter_gate.py summarize \
  --results-dir /tmp/metriplane-cross-adapter-pr \
  --expected-commit "$(git rev-parse HEAD)"
```

The local exhaustive command uses the current Linux/Python 3.12 environment and
five replay repetitions; the scheduled or manually dispatched workflow is what
executes the complete 53-record cross-platform matrix:

```bash
uv run --frozen --project tests/adapter_conformance \
  python tools/cross_adapter_gate.py check \
  --level exhaustive \
  --results-dir /tmp/metriplane-cross-adapter-exhaustive
```

To reproduce one registered portable oracle while developing:

```bash
uv run --frozen --project tests/adapter_conformance \
  python tools/cross_adapter_gate.py check-fixture \
  --variant-id <registered-variant-id> \
  --results-dir /tmp/metriplane-cross-adapter-one
```

Use a new or empty results directory. The summarizer's `--expected-commit`
prevents stale results from a previous checkout from satisfying the gate.

## Existing workflow reconciliation

The unified gate is the always-present compatibility status. The existing
ManiSkill, robomimic, ROS 2/MCAP, MassRobotics, source-family matrix, root CI,
release, and documentation workflows remain defense in depth during adoption;
the gate does not replace their deeper profile or packaging work.

The unified workflow has no pull-request path filter and listens to
`pull_request`, `merge_group`, pushes to `main`, scheduled exhaustive runs, and
manual dispatch. Its final summary uses an unconditional execution guard and is
the only status that should be considered complete when every registered result
for the exact checkout succeeds. Specialized path-filtered jobs cannot stand in
for that summary.

Reconciliation work must preserve evidence boundaries:

- update the stale ROS matrix description to the bounded synthetic executable
  profile without counting it as proven external-source evidence;
- align MassRobotics portability wording with actual OS/Python evidence;
- retain the matrix's proven-path count of ManiSkill and robomimic unless new
  external-source evidence is reviewed; and
- keep specialized exact-head proof jobs distinct from integration-candidate
  validation where both are needed.

## Golden-update policy

CI never generates, overwrites, or accepts a changed golden outcome. There is no
automatic `--update`, approval-by-hash, or record-on-failure path.

If a bounded profile intentionally changes, a maintainer must inspect the source
and executable diff, explain the semantic reason, update the portable fixture
and its checksums through the profile's documented process, and review every
changed fingerprint, session hash, event, deviation, incident, bundle, and
regression expectation. The registry change then travels through ordinary code
review. A failing run is evidence to investigate, not authority for a new
golden.
