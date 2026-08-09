<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Process rules

Process rules tell Metriplane what the object IDs and zone labels in one recorded
bounded-workcell run mean. They describe expected process evidence; they do not
control or certify the process.

Export the working example before writing a new rule directory:

```bash
metriplane demo --export-inputs my-cell
```

Then inspect the five files under `my-cell/domain-pack/`.

## `assets.yaml`

Map each recorded object ID to a stable asset ID and type. Expected zones or
stations can document where an asset belongs. Every process reference must point
to a known asset, zone, or station.

The current input already needs a `zone` label on each relevant object state.
Although `workspace.yaml` contains polygons, `atlas run` does not infer the zone
from `pos_world`; positions alone are insufficient for this interface.

## `workspace.yaml`

Name one bounded cell, its zones, and its stations. A station refers to a known
zone. Use identifiers consistently across all files and the JSONL session.

## `process.yaml`

Define one ordered process and its expected steps. The current incident behavior
is deliberately narrow: it checks required asset presence for a step and can flag
a missing required asset after `max_wait_s` is exceeded. This is not a generic
workflow, anomaly-detection, or safety-rule engine.

The missing-tool example requires `torque_driver_1` at `station_a` and sets
`max_wait_s: 30.0`.

## `contracts.yaml` (optional)

Contracts hold supported process-condition and claim-boundary metadata, such as
the required tool, station, maximum wait, severity, and an observe-only note.
They document and preserve the configured interpretation. They do not execute
arbitrary enforcement, stop equipment, or grant safety or quality authority.

## `work_orders.csv` (optional compatibility file)

When this file is present, provide exactly one work order for each run. Its
`process_id` must match the process file. Multiple work orders are rejected
because Metriplane does not yet offer an explicit selection mechanism; split
them into separate recordings and runs. If the file is absent, the loader uses
one compatibility default. Adapted inputs should retain an explicit file so the
work-order identity is visible rather than implicit.

## Validate before running

```bash
metriplane atlas validate-pack my-cell/domain-pack
```

The validator checks schema loading, unique IDs, cross-file references, process
requirements, finite non-negative wait values, and the single-work-order
constraint. Fix every printed `ERROR` before analysis. Validation proves that the
configuration is internally acceptable; it does not prove that its labels or
physical assumptions are correct.

For field-level technical detail, see the retained
[domain-pack reference](https://github.com/Miko997/metriplane/blob/main/docs/atlas/domain_packs.md).
The first-time tutorial uses only the supported subset described on this page.
