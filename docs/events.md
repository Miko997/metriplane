# Operational Events

Operational events are typed records emitted downstream of metric frame state.
They are used by rules, incidents, evidence bundles, regression tests, and the
Command Center.

## Event shape

Typical fields include:

| Field | Purpose |
|---|---|
| `event_id` | Stable event identifier when available. |
| `type` | Event class, such as zone, rule, contract, or incident-related event. |
| `severity` | Operator-facing severity such as info, warning, or critical. |
| `ts` | Event timestamp in seconds. |
| `object_id` | Object involved in the event, if applicable. |
| `zone_id` | Zone involved in the event, if applicable. |
| `rule_id` / `contract_id` | Contract source for Sentinel events. |
| `message` | Short human-readable explanation. |

`FrameStateModel.alerts` defaults to an empty list for compatibility with older
frame records.

## Related files

- `metriplane/sentinel/events.py`
- `metriplane/sentinel/rules.py`
- `metriplane/contracts/engine.py`
- `tests/test_sentinel_events.py`
- `evidence/experiments/event_schema_001.md`
