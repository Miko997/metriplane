<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Inputs and outputs

## Supported recorded input

The incident workflow reads a `FrameStateModel` JSONL session: one JSON object
per line, with an optional run-header record followed by validated frames. The
authoritative model is
[`metriplane/schema.py`](https://github.com/Miko997/metriplane/blob/main/metriplane/schema.py).

A minimal frame has this shape:

```json
{
  "schema_version": "1.0",
  "source_backend": "my_estimator",
  "ts": 10.0,
  "frame_id": 2,
  "objects": [
    {
      "id": "7",
      "pos_world": [2.8, 0.8, 0.0],
      "zone": "station_a_work",
      "confidence": 0.98
    }
  ]
}
```

For the current bounded-workcell incident path:

- `source_backend` identifies the upstream source;
- `ts` is the source-clock time in seconds, or `ts_sim_ns` supplies fixed-clock
  replay time;
- `frame_id` is a non-negative integer;
- each object `id` is nonempty and unique within its object list;
- `pos_world` is an already-estimated finite 3D tuple; the current rules use the
  planar workcell interpretation rather than claiming generic 3D analysis;
- `zone` is an already-assigned label that matches the process-rule configuration;
- optional confidence values are between 0 and 1.

Positions do **not** automatically derive zone labels in this interface. Your
upstream estimator or conversion step must preclassify the zone consistently.
The v0.3.0 workflow does not accept raw video, ROS bags, rosbag2, or MCAP files.

## Process-rule input

The run needs one directory with three required files:

- `assets.yaml`: maps recorded object IDs to workcell assets;
- `workspace.yaml`: names the bounded cell, zones, and stations;
- `process.yaml`: defines ordered expectations, required assets, and maximum waits;

The exported starter also contains two compatibility files:

- `contracts.yaml` is optional. When present, it records and validates supported
  process/claim metadata; it is not a generic policy engine and does not enforce
  arbitrary contracts.
- `work_orders.csv` is optional for compatibility. When absent, the loader creates
  one default work order. For inspectable, adapted inputs, keep the file explicit
  and give it exactly one work order matching the process ID.

Validate these files before analysis:

```bash
metriplane atlas validate-pack my-cell/domain-pack
```

Validation fails closed on malformed or inconsistent references. See
[Process rules](process-rules.md) for the supported semantics.

## Run output

`metriplane atlas run` creates a new directory. The primary outputs are:

| Output | Meaning |
| --- | --- |
| `physical_event_log.jsonl` | Machine-readable event timeline. |
| `process_trace.json` | Ordered process state and completed steps. |
| `cell_truth_report.html` | Human-readable Incident Report. |
| `cell_truth_report.md` | Markdown form of the same report. |
| `evidence_bundles/INC-….zip` | Checksummed files saved for an incident. |
| `regression_tests/INC-….yaml` | Repeatable check generated from an incident. |
| `atlas_manifest.json` | Run identity, counts, inputs, and artifact paths. |

Additional technical artifacts may also be present. The report, bundle, and
regression spec are the first-time-user path.

## Zero incidents is not necessarily a failure

An analysis can validly produce events but zero incidents when no configured
maximum wait or missing-required-asset condition is violated. In that case the
report and run artifacts still describe the result, but there is no incident ID
from which to generate an incident bundle or regression spec. Confirm that zero
incidents is expected for your process rules; do not invent `INC-0001` paths.

## What the outputs establish

A passing bundle verification establishes that the bundle matches its manifest.
A passing regression establishes that its saved expectations match the required
current outputs. Neither result establishes sensor accuracy, physical truth,
safety, quality approval, or control authority.
