<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# Reproduce the ManiSkill PickCube External Fixture Proof

This proof has two deliberately separate reproduction levels. Level A reruns
the checked-in portable fixtures and is the normal outside-evaluator path.
Level B audits their conversion from the pinned ManiSkill source. Level B is
not required merely to evaluate the fixtures with Metriplane.

The publication candidate starts from repository commit
`1549d0a05e03db51efc0ee08edb7d9db66196b4e`. After publication, obtain the
exact commit pointed to by the immutable tag `maniskill-pickcube-proof-v1` and
confirm that it matches the `canonical_commit` recorded in
`proof-record.json`. Do not substitute mutable `main`, a pull-request head, or
the baseline commit for that final proof commit.

## Package identity warning

The published PyPI and conda-forge `metriplane==0.3.0` distributions do not
contain the `metriplane external` commands used by this proof. The repository
may still report package version `0.3.0` when a wheel is built from the proof
tag. That locally built wheel is identified by its exact Git commit and must
not be described as the published v0.3.0 artifact.

Set `METRIPLANE_GIT_COMMIT` to the exact proof commit for every run. The
environment value is written into durable provenance and prevents version
`0.3.0` alone from being mistaken for the full build identity.

## Level A — Portable fixture evaluation

Expected hands-on time is approximately 15–30 minutes after Python and Git are
available. Use Python 3.12 or 3.13. Level A does **not** require ManiSkill,
SAPIEN, Torch, h5py, Vulkan, source HDF5/JSON, the source adapter, or robot
assets.

### 1. Obtain and identify the exact proof revision

After the tag has been published:

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
git checkout --detach maniskill-pickcube-proof-v1
git rev-parse HEAD
git status --short
```

Compare the 40-character `git rev-parse HEAD` value with the canonical commit
in `proof-record.json`. The working tree must be clean. At candidate-review
time, a reviewer may instead check out the exact PR head supplied in the PR,
but that result is candidate evidence and is not a tagged reproduction.

For the commands below, replace `FULL_PROOF_COMMIT` with the exact 40-character
value:

```bash
export METRIPLANE_GIT_COMMIT=FULL_PROOF_COMMIT
```

PowerShell:

```powershell
$env:METRIPLANE_GIT_COMMIT = "FULL_PROOF_COMMIT"
```

### 2. Build the exact source and install it cleanly

Create build and evaluation environments outside the checkout. The examples
use sibling directories so no repository import path can satisfy the test.

POSIX shell:

```bash
python3.12 -m venv ../maniskill-proof-build
../maniskill-proof-build/bin/python -m pip install --upgrade pip build
../maniskill-proof-build/bin/python -m build --wheel --sdist --outdir ../maniskill-proof-dist

python3.12 -m venv ../maniskill-proof-eval
../maniskill-proof-eval/bin/python -m pip install ../maniskill-proof-dist/metriplane-0.3.0-py3-none-any.whl
../maniskill-proof-eval/bin/python -m pip check
../maniskill-proof-eval/bin/metriplane --version
```

PowerShell:

```powershell
py -3.12 -m venv ..\maniskill-proof-build
..\maniskill-proof-build\Scripts\python -m pip install --upgrade pip build
..\maniskill-proof-build\Scripts\python -m build --wheel --sdist --outdir ..\maniskill-proof-dist

py -3.12 -m venv ..\maniskill-proof-eval
..\maniskill-proof-eval\Scripts\python -m pip install ..\maniskill-proof-dist\metriplane-0.3.0-py3-none-any.whl
..\maniskill-proof-eval\Scripts\python -m pip check
..\maniskill-proof-eval\Scripts\metriplane --version
```

Python 3.13 may replace 3.12. Inspect the built wheel and confirm that the
ordinary runtime does not depend on `mani-skill`, SAPIEN, Torch, h5py, or the
isolated adapter.

### 3. Run the standard-library wrapper

The wrapper invokes only the public `metriplane` CLI and Python standard
library. It does not download source data, run the adapter, import Metriplane
internals, mutate a fixture, or use `expected-outcome.json` as Atlas input.

Copy the proof directory and the two canonical fixture directories outside the
checkout while preserving their relative layout, or let the wrapper resolve
them from the exact checkout. Write outputs to a new, empty directory outside
the checkout:

```bash
../maniskill-proof-eval/bin/python \
  proofs/maniskill-pickcube-v1/reproduce.py \
  --repo-root . \
  --out ../maniskill-proof-reproduction \
  --metriplane-commit "$METRIPLANE_GIT_COMMIT" \
  --metriplane-command ../maniskill-proof-eval/bin/metriplane
```

PowerShell:

```powershell
..\maniskill-proof-eval\Scripts\python `
  proofs\maniskill-pickcube-v1\reproduce.py `
  --repo-root . `
  --out ..\maniskill-proof-reproduction `
  --metriplane-commit $env:METRIPLANE_GIT_COMMIT `
  --metriplane-command ..\maniskill-proof-eval\Scripts\metriplane.exe
```

The explicit `--metriplane-command` prevents another `metriplane` executable on
`PATH` from being selected. The wrapper must return zero and write
`../maniskill-proof-reproduction/reproduction-result.json`. It checks:

- both fixture validations pass;
- incident counts are 75 frames, 4 events, 1 deviation, and 1 incident;
- control counts are 75 frames, 3 events, 0 deviations, and 0 incidents;
- the incident evidence bundle verifies;
- the incident-generated regression passes;
- the control creates no evidence bundle and no generated regression;
- results agree with `proof-record.json`;
- durable artifacts contain no machine-local path leak or source-specific
  camera/tracking/calibration language; and
- moved outputs remain usable.

Preserve the first nonzero exit and `reproduction-result.json`. Do not edit
rules or expected values to force a pass.

### 4. Raw public CLI commands

The wrapper is not the only documented path. Activate the fresh evaluation
environment, or replace every `metriplane` below with its full path. Run these
commands from a directory in which the fixture paths resolve:

```bash
metriplane external validate \
  examples/external_sources/maniskill_pickcube/incident \
  --json > incident-validation.json

metriplane external validate \
  examples/external_sources/maniskill_pickcube/control \
  --json > control-validation.json

METRIPLANE_GIT_COMMIT=FULL_PROOF_COMMIT \
  metriplane external run \
    examples/external_sources/maniskill_pickcube/incident \
    --out incident-run \
    --run-id maniskill_pickcube_incident \
    --json > incident-run-summary.json

METRIPLANE_GIT_COMMIT=FULL_PROOF_COMMIT \
  metriplane external run \
    examples/external_sources/maniskill_pickcube/control \
    --out control-run \
    --run-id maniskill_pickcube_control \
    --json > control-run-summary.json

metriplane atlas bundle verify \
  incident-run/evidence_bundles/INC-0001.zip

metriplane atlas test \
  incident-run/regression_tests/INC-0001.yaml \
  --json > incident-regression-result.json
```

Then verify explicitly that these control paths do not contain an artifact:

```bash
test ! -e control-run/evidence_bundles/INC-0001.zip
test ! -e control-run/regression_tests/INC-0001.yaml
```

On PowerShell, use `Test-Path` and require both results to be `False`.

The expected machine-readable counts are:

| Fixture | Frames | Events | Deviations | Incidents |
| --- | ---: | ---: | ---: | ---: |
| Incident | 75 | 4 | 1 | 1 |
| Control | 75 | 3 | 0 | 0 |

Bundle verification and regression execution must report `"pass": true`.
The control's lack of incident-derived artifacts is expected behavior, not
missing proof data.

## Level B — Full source-to-fixture conversion

Level B is an advanced provenance audit for Linux x86_64 and CPython 3.12. It
may require a software Vulkan device because upstream scene construction makes
render-material objects, although the adapter does not render. It uses the
pinned ManiSkill environment, SAPIEN, Torch, h5py, immutable source archive,
and the isolated adapter. The MET-15 verification used `uv 0.12.0`; use that
exact `uv` version for the same environment restoration and record
`uv --version`. Plan for substantially more setup time than Level A.

Software Vulkan is an external system prerequisite rather than a Python
dependency frozen by `uv.lock`. Install a Vulkan implementation appropriate to
the Linux distribution and record the exact package/driver version and selected
device. If upstream scene construction cannot initialize, preserve that first
failure rather than substituting an unrecorded driver or claiming Level B pass.

### 1. Restore the frozen adapter environment

From the exact proof revision:

```bash
UV_CACHE_DIR=/tmp/maniskill-pickcube-uv \
  uv sync --no-config --project adapters/maniskill_pickcube --frozen
```

The public adapter implementation is commit
`95d1134d9fb9273318c552c507952f1c5c26877e`; its adapter tree must agree with
the proof revision. The dependency lock included with the fixtures has SHA-256
`f28f8618680de09c94e855a8b5d2a995ab6241b96c462650cada9c896335ec80`.

### 2. Acquire and verify the immutable source

Choose an empty source root outside the repository:

```bash
SOURCE_DIR="$(mktemp -d)"
CONVERSION_DIR="$(mktemp -d)"

uv run --project adapters/maniskill_pickcube maniskill-pickcube acquire \
  --out "$SOURCE_DIR/source" \
  --json > acquisition-result.json
```

Require these exact identities before conversion:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| ZIP | 36,590,010 | `b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8` |
| HDF5 | 29,349,195 | `03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a` |
| JSON | 228,218 | `16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90` |

Record the copied ZIP, HDF5, and JSON hashes before conversion:

```bash
sha256sum \
  "$SOURCE_DIR/source/PickCube-v1.zip" \
  "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.h5" \
  "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.json" \
  > "$SOURCE_DIR/source-before.sha256"
```

Recompute all three after all conversions. Any change is a failure.

### 3. Inspect all stored state

```bash
uv run --project adapters/maniskill_pickcube maniskill-pickcube inspect \
  --trajectory "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.h5" \
  --metadata "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.json" \
  --episode-id 0 \
  --json > inspection-result.json
```

The inspection must identify `traj_0`, 74 transitions, 75 stored states, and
the 50-step registered RL horizon as provenance only. It independently restores
all 75 states with `env.unwrapped.set_state_dict(state)` and reads named APIs;
it must not integrate actions or render.

### 4. Convert three clean roots

Each output root must be empty and outside the checked-in fixture directories:

```bash
for index in 1 2 3; do
  uv run --project adapters/maniskill_pickcube maniskill-pickcube convert \
    --trajectory "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.h5" \
    --metadata "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.json" \
    --config adapters/maniskill_pickcube/config/frozen-config.json \
    --adapter-commit 95d1134d9fb9273318c552c507952f1c5c26877e \
    --out "$CONVERSION_DIR/clean-$index" \
    --json > "$CONVERSION_DIR/clean-$index.json"
done
```

### 5. Finalize equivalence

```bash
uv run --project adapters/maniskill_pickcube maniskill-pickcube finalize-equivalence \
  --conversion-root "$CONVERSION_DIR/clean-1" --run-id real-source-clean-1 \
  --conversion-root "$CONVERSION_DIR/clean-2" --run-id real-source-clean-2 \
  --conversion-root "$CONVERSION_DIR/clean-3" --run-id real-source-clean-3 \
  --out "$CONVERSION_DIR/final" \
  --json > "$CONVERSION_DIR/equivalence-result.json"
```

Require `equivalent: true`, 28 compared variant artifacts, incident fixture
fingerprint
`954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2`,
and control fixture fingerprint
`8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e`.

### 6. Compare with the published fixtures and recheck source bytes

Compare every finalized incident and control artifact with the exact tagged
fixture trees:

- `examples/external_sources/maniskill_pickcube/incident`
- `examples/external_sources/maniskill_pickcube/control`

Inventories and bytes must agree. The shared finalized `session.jsonl` must
have SHA-256
`7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`.

The following standard-library comparison rejects missing, extra, or changed
fixture files. `conversion-summary.json` is intentionally excluded because it
records conversion-root operational output and is not part of either canonical
14-file fixture tree.

```bash
python - "$CONVERSION_DIR/final" . <<'PY'
from pathlib import Path
import sys

generated = Path(sys.argv[1])
repository = Path(sys.argv[2])
for variant in ("incident", "control"):
    left = generated / variant
    right = repository / "examples/external_sources/maniskill_pickcube" / variant
    left_inventory = {
        path.relative_to(left).as_posix(): path.read_bytes()
        for path in left.rglob("*") if path.is_file()
    }
    right_inventory = {
        path.relative_to(right).as_posix(): path.read_bytes()
        for path in right.rglob("*") if path.is_file()
    }
    if left_inventory != right_inventory:
        missing = sorted(set(right_inventory) - set(left_inventory))
        extra = sorted(set(left_inventory) - set(right_inventory))
        changed = sorted(
            name for name in set(left_inventory) & set(right_inventory)
            if left_inventory[name] != right_inventory[name]
        )
        raise SystemExit(
            f"{variant} fixture mismatch: missing={missing}, extra={extra}, changed={changed}"
        )
print("incident and control fixture inventories and bytes match")
PY

sha256sum \
  "$SOURCE_DIR/source/PickCube-v1.zip" \
  "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.h5" \
  "$SOURCE_DIR/source/extracted/PickCube-v1/motionplanning/trajectory.json" \
  > "$SOURCE_DIR/source-after.sha256"

cmp "$SOURCE_DIR/source-before.sha256" "$SOURCE_DIR/source-after.sha256"
```

Require `cmp` to return zero and all values to remain the locked hashes above.

Level B establishes deterministic conversion under the recorded environment.
It does not establish physical accuracy, official task outcome, or independent
external validation.

## Maintainer-only deterministic proof build

The proof publication itself is rebuilt from frozen fixtures and public
Metriplane commands:

```bash
python tools/build_maniskill_pickcube_proof.py \
  --repo-root . \
  --out proofs/maniskill-pickcube-v1 \
  --metriplane-commit FULL_PROOF_COMMIT \
  --publication-date 2026-08-12
```

The normal publication build requires a clean tree. `--allow-dirty` exists
only for a controlled candidate build where uncommitted proof files are the
known publication input; do not use it for final publication evidence. Build
twice into separate empty roots and compare all deterministic artifacts
byte-for-byte. A stale hash, raw-source inclusion, path leak, or unexpected
working-tree modification is a failure.

## Reporting a discrepancy

Preserve the exact tag/commit, operating system, architecture, Python version,
installation command, first failed command, complete machine-readable output,
and `reproduction-result.json`. Report what happened without changing the
polygon, waits, source, fixtures, or expected semantics. PASS and FAIL are
equally useful. Use [`evaluator-report-template.md`](evaluator-report-template.md)
for a structured report.
