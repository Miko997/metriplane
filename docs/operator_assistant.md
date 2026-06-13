# Grounded Operator Assistant

`metriplane ask` answers natural-language questions about a run **from structured
artifacts only**, with citations to the local files it used. It is grounded: it never
invents incidents or interprets raw video, and it works with **no external LLM**.

## Usage

```bash
metriplane ask --run-dir <run_dir> "when was the exit lane blocked?"
metriplane ask --bundle evidence/incidents/INC-0001 "which rule triggered this incident?"
metriplane ask --run-dir <run_dir> "which camera was unreliable?" --json
```

## Supported question types (intents)

| Intent | Example | Reads |
|---|---|---|
| `incident_search` | "what incident happened?" | `incident.json` / incidents |
| `object_history` | "where did cart_01 go?" | session traces |
| `zone_occupancy` | "was the exit lane blocked?" | incidents + trace dwell |
| `rule_explanation` | "which rule triggered the incident?" | `rules.yaml` |
| `camera_health` | "which camera was unreliable?" | `camera_trust.json` (or analyzes the session) |

Unknown questions return the list of supported question types rather than guessing.

## Citations

Every answer cites the local artifacts it used (path relative to the run root, source type,
and record id where applicable). Citation paths are validated to stay inside the run/bundle
root — path traversal is rejected.

## Deterministic vs optional LLM

The default provider is **deterministic and template-based** — retrieval and answer
construction require no model and are fully tested. An optional summarization provider
could be layered on later; if added it must be off by default, never receive raw video,
receive only selected structured facts, and disclose the provider in the output.

## Example

```text
$ metriplane ask --bundle evidence/incidents/INC-DIST-001 "which rule triggered this incident?"
Rule cart_person_distance is a min_distance rule (severity critical). Minimum distance: 0.6 m.

Evidence:
  - rules.yaml [cart_person_distance] (rules)
```

## Privacy / safety

- No external LLM by default; no raw video is read or sent anywhere.
- Only known run/bundle directories are read; citation paths cannot escape the root.
- Missing artifacts are reported as limitations, not errors.

## Limitations

- Deterministic keyword intent classification (no semantic model).
- Answers reflect what the artifacts contain; if a run lacks an artifact, the assistant
  says so rather than guessing.
