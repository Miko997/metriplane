<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Reproduce the MassRobotics AMR offline-replay proof

Run from an exact checkout of the MET-55 pull-request head. Use empty output
directories. The converter is local-only: it does not fetch the upstream
schema, execute upstream code, use `expected-outcome.json` as input, or depend
on ROS, MQTT, WebSockets, sender code, or receiver code.

## 1. Restore and test the isolated adapter

```bash
cd adapters/massrobotics_amr
uv sync --frozen --extra test
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd ../..
```

The ordinary Metriplane wheel has no runtime dependency on this isolated
package.

## 2. Inspect and perform three clean conversions

Use the exact hardened adapter implementation commit recorded by the finalized
fixtures, and separately identify the checkout used for Atlas run provenance.
Choose a new temporary root outside the checkout:

```bash
export MET55_ADAPTER_COMMIT="da33ad03beb8d4f3a3762cad085e2df4b2d9386c"
export MET55_COMMIT="FULL_MET55_HEAD_COMMIT"
export MET55_WORK_ROOT="$(mktemp -d)"

uv run --project adapters/massrobotics_amr \
  metriplane-massrobotics-amr inspect \
  --source-root adapters/massrobotics_amr/source/incident

for variant in incident control; do
  for index in 1 2 3; do
    uv run --project adapters/massrobotics_amr \
      metriplane-massrobotics-amr convert \
      --source-root "adapters/massrobotics_amr/source/$variant" \
      --config adapters/massrobotics_amr/config/frozen-config.json \
      --adapter-commit "$MET55_ADAPTER_COMMIT" \
      --out "$MET55_WORK_ROOT/$variant-conversion-$index"
  done
done

uv run --project adapters/massrobotics_amr \
  metriplane-massrobotics-amr finalize-equivalence \
  --conversion-root "$MET55_WORK_ROOT/incident-conversion-1" \
  --run-id incident-clean-1 \
  --conversion-root "$MET55_WORK_ROOT/incident-conversion-2" \
  --run-id incident-clean-2 \
  --conversion-root "$MET55_WORK_ROOT/incident-conversion-3" \
  --run-id incident-clean-3 \
  --conversion-root "$MET55_WORK_ROOT/control-conversion-1" \
  --run-id control-clean-1 \
  --conversion-root "$MET55_WORK_ROOT/control-conversion-2" \
  --run-id control-clean-2 \
  --conversion-root "$MET55_WORK_ROOT/control-conversion-3" \
  --run-id control-clean-3 \
  --out "$MET55_WORK_ROOT/equivalence"
```

The finalizer must report canonical equivalence for all three conversions of
each variant. Provenance is retained; only explicitly declared stable run
identities may differ before canonical comparison. Conversion must report two
identities, nine timestamps, 18 status records, nine frames, two objects per
frame, and zero carry-forward, interpolation, cross-datum transforms,
conversion events, and prediction-derived frames.

The finalizer command uses the adapter's six-root interface: three incident
conversions followed by three control conversions.

## 3. Validate and run the portable fixtures

Restore the repository's locked development environment:

```bash
uv sync --locked --group dev
```

```bash
uv run metriplane external validate \
  examples/external_sources/massrobotics_amr/incident \
  --json > "$MET55_WORK_ROOT/incident-validation.json"

uv run metriplane external validate \
  examples/external_sources/massrobotics_amr/control \
  --json > "$MET55_WORK_ROOT/control-validation.json"

for index in 1 2 3; do
  METRIPLANE_GIT_COMMIT="$MET55_COMMIT" \
    uv run metriplane external run \
      examples/external_sources/massrobotics_amr/incident \
      --out "$MET55_WORK_ROOT/incident-run-$index" \
      --run-id massrobotics_amr_incident \
      --json > "$MET55_WORK_ROOT/incident-run-$index-summary.json"

  METRIPLANE_GIT_COMMIT="$MET55_COMMIT" \
    uv run metriplane external run \
      examples/external_sources/massrobotics_amr/control \
      --out "$MET55_WORK_ROOT/control-run-$index" \
      --run-id massrobotics_amr_control \
      --json > "$MET55_WORK_ROOT/control-run-$index-summary.json"
done
```

Expected process results:

| Variant | Frames | Events | Deviations | Incidents |
| --- | ---: | ---: | ---: | ---: |
| Incident | 9 | 4 | 1 | 1 |
| Control | 9 | 3 | 0 | 0 |

The incident's exact ordered events are:

1. `required_asset_missing` at `2.0 s`;
2. `step_delayed` at `5.0 s`;
3. `required_asset_present` at `6.0 s`;
4. `step_completed` at `6.0 s`.

The control's exact ordered events are:

1. `required_asset_missing` at `2.0 s`;
2. `required_asset_present` at `4.0 s`;
3. `step_completed` at `4.0 s`.

Compare the three runs with the repository-defined canonical technical-output
mechanism. Do not remove provenance to manufacture equality.

## 4. Verify the incident-only artifacts

```bash
uv run metriplane atlas bundle verify \
  "$MET55_WORK_ROOT/incident-run-1/evidence_bundles/INC-0001.zip"

uv run metriplane atlas test \
  "$MET55_WORK_ROOT/incident-run-1/regression_tests/INC-0001.yaml" \
  --json > "$MET55_WORK_ROOT/incident-regression-result.json"
```

Both commands must report PASS. Do not run them against the control. Instead,
require that the control produced neither artifact:

```bash
for index in 1 2 3; do
  test ! -e "$MET55_WORK_ROOT/control-run-$index/evidence_bundles/INC-0001.zip"
  test ! -e "$MET55_WORK_ROOT/control-run-$index/regression_tests/INC-0001.yaml"
done
```

The proof package also preserves the generated regression bytes and a portable
copy whose only change is rebinding `source_bundle` to the colocated durable
bundle. Verify the committed artifacts directly:

```bash
uv run metriplane atlas bundle verify \
  proofs/massrobotics-amr-offline-replay-v1/artifacts/incident-evidence.zip

uv run metriplane atlas test \
  proofs/massrobotics-amr-offline-replay-v1/artifacts/incident-regression-portable.yaml \
  --json
```

Both commands must report PASS. The generated regression's evaluation rules,
tolerances, and expected values are unchanged in the portable copy.

The control's bundle verification and regression execution are N/A, not failed
or missing proof data.

## 5. Review the boundary

Confirm that durable output and ZIP-member scans contain no machine-local
absolute paths, usernames, home directories, unexpected personal data, or
upstream standard bytes. Confirm that
`expected-outcome.json` is never a converter or Atlas input. Confirm that the
ordinary wheel excludes the isolated adapter and all referenced upstream
artifacts.

Preserve the first nonzero result. Do not edit the source, process rule, or
expected values to force a pass.
