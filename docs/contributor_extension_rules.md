# Contributor Extension Rules

These rules keep Metriplane extensions compatible with the 0.2.0 release
architecture.

## Preserve the perception path

Do not rewrite camera ingest, mapping, fusion, recording, or schema fields when
adding Sentinel, evidence, assistant, exporter, or integration features. Add new
behavior downstream of `FrameStateModel` unless the change is explicitly a
schema migration.

## Keep Sentinel observe-only

Sentinel code may read frames, traces, objects, contracts, events, incidents,
and evidence bundles. It must not actuate robots, send machine commands, or
enable a control path. `control_enabled` must remain false for Sentinel v1.

## Prefer typed models

Use Pydantic or dataclasses already present in the local package. Avoid passing
loosely shaped dictionaries across module boundaries when a stable event,
contract, incident, forecast, trust, or regression model exists.

## Keep release claims evidence-backed

Every public-facing claim should map to one of:

- an automated test,
- a checked-in evidence artifact,
- a benchmark result,
- a reproducible sample dataset,
- or a clearly labeled manual demonstration.

If hardware or external software is not exercised in the release, document the
surface as an adapter or deployment path rather than a measured integration.

## Maintain backward compatibility

Schema additions should be optional. Older replay files and frame-state records
must continue to load unless a versioned migration is deliberately introduced.

## Avoid hidden services

0.2.0 features must run locally by default. The operator assistant is local and
retrieval-based; it must not require an external LLM or network service for the
checked-in demo path.
