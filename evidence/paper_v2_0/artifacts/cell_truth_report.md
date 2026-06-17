# Cell Truth Report

## Executive summary

- Observed duration: 70.0 s.
- Physical events recorded: 6.
- Process deviations detected: 1.
- Incidents generated: 1.
- Evidence bundles generated: 1.
- This report is derived from replayed planar state, not raw video judgement.

## Timeline

- 0.0: Kit arrives at the cell completed. (`evt_0001`)
- 10.0: Workpiece arrives at station A completed. (`evt_0002`)
- 20.0: torque_driver_1 was not present for Torque driver available before fastening. (`evt_0003`)
- 55.0: Torque driver available before fastening waited 35.0 s for torque_driver_1. (`evt_0004`)
- 70.0: Torque driver 1 was present for Torque driver available before fastening. (`evt_0005`)
- 70.0: Torque driver available before fastening completed. (`evt_0006`)

## Time loss table

| issue | asset | station/zone | duration | evidence |
|---|---|---|---:|---|
| Torque driver available before fastening waited 35.0 s for torque_driver_1. | torque_driver_1 | station_a | 35.0 s | frame:4, step:torque_driver_available |

## Deviations

| deviation | severity | process step | assets | evidence |
|---|---|---|---|---|
| missing_required_asset | warning | torque_driver_available | torque_driver_1 | evt_0003, evt_0004 |

## Incidents and evidence

| incident | severity | summary | events |
|---|---|---|---|
| INC-0001: torque_driver_1 missing during Torque driver available before fastening | warning | Torque driver available before fastening waited because torque_driver_1 was absent. | evt_0003, evt_0004 |

## Training and improvement

- Add a required-tool staging check: INC-0001 shows a required asset was absent while a process step waited. Add a visible pre-step tool/material check. Caveat: Recommendation is derived from replay evidence and is not a guaranteed causal fix without before/after validation.

## Artifact links

- Event ledger: `runs/atlas/assembly_cell_missing_tool/physical_event_log.jsonl`
- Reality graph: `runs/atlas/assembly_cell_missing_tool/reality_graph.json`
- Regression tests: `runs/atlas/assembly_cell_missing_tool/regression_tests`

## Limitations

- This report is derived from calibrated planar state streams.
- It depends on tracked/tagged assets.
- It is not a certified safety or quality decision system.
