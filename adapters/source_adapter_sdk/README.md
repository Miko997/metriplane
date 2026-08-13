<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Source Adapter capability SDK

This isolated package records whether one source adapter has the evidence needed
to construct a specific External Source Contract v1 bundle. It does not decode a
source format, discover adapters, register plugins, define normalized state, or
change Atlas.

The package has no runtime dependencies. Source conversion dependencies remain
in each adapter's own environment. The ordinary Metriplane wheel does not include
this package or use it during portable fixture evaluation.

## Boundary

The capability record is metadata about an adapter boundary. It is not a second
state model. `FrameStateModel` 1.0 remains the normalized state format, External
Source Contract v1 remains the fixture protocol, and Atlas remains the evaluator.

The schema is strict. Unknown fields fail validation. There are no fields for
ROS topics, MCAP channels, HDF5 groups, simulator APIs, or vendor-specific state.
Those details stay in isolated adapter configuration and Contract v1 field
provenance.

## Evidence basis for each field group

The two public successful adapters were compared before defining this record.
The responsibility class describes why each field exists.

| Capability field group | Class | Reason |
| --- | --- | --- |
| Contract version, complete-snapshot profile, FrameStateModel version | A | Already required by External Source Contract v1 |
| Exact source artifacts, hashes, revision, and rights boundary | A | Already required by Contract v1 |
| Clock authority, field, domain, unit, and mapping | B | Existing Contract v1 declarations with reusable fail-closed checks |
| Coordinate frames, units, transform, projection, and loss | B | Existing Contract v1 declarations with reusable validation semantics |
| Stable entity identity and mapping fingerprint | B | Existing Contract v1 mapping requirement with reusable identity checks |
| Complete snapshots, exact joins, bounded materialization, omission, unknown state, and carry-forward | B | Existing complete-snapshot rules with reusable policy checks |
| Field provenance and four-layer separation | B | Existing Contract v1 provenance semantics |
| Annotation inventory and anti-taint declarations | B | Existing Contract v1 source-annotation rules |
| Adapter implementation commit and isolated lock identity | C | Repeated adapter responsibility needed to bind conversion provenance |
| Deterministic clean-run result | C | Repeated adapter responsibility not represented as one reusable permission gate |
| Conversion dependency list and portable source-dependency boundary | C | Repeated isolation responsibility across the successful adapters |
| Supported and prohibited Atlas semantics | C | Repeated claim-boundary responsibility across the successful adapters |
| ROS topics, MCAP channels, message schemas, TF chains, HDF5 keys, simulator APIs | D | Source-specific configuration and provenance, not shared SDK state |

Class meanings:

- A: already required by Contract v1;
- B: existing Contract v1 field with reusable validation semantics;
- C: repeated adapter responsibility not cleanly represented as one capability
  gate today;
- D: source-specific and excluded from the shared SDK.

`materialization_method` keeps source-stream truth separate from output snapshot
semantics. A source that already supplies complete snapshots declares `none`.
Partial streams may declare `exact_snapshot_join` only when every required value
has the identical evaluation timestamp, synchronization tolerance is zero, and
no value is carried forward. It declares synchronization as `exact_timestamp`.
Already-complete source snapshots declare synchronization as `not_applicable`.
`bounded_last_observation` requires explicit unique fields and a positive maximum
staleness. Interpolation and resampling are both restricted to `none`; hidden or
free-form policies fail validation. Partial updates cannot silently become
complete snapshots.

Information loss is also fail-closed. A verified loss capability must be declared
and list at least one concrete loss. A false declaration must use an empty list
and cannot claim verified status.

## Records

The package includes two post-hoc classifications:

- `maniskill-pickcube.json` classifies adapter commit
  `95d1134d9fb9273318c552c507952f1c5c26877e`;
- `robomimic-lowdim.json` classifies adapter commit
  `cfc285a3e757fdf742858b1c4cf685c384d01e8b`.

These files classify frozen public evidence. They do not claim the historical
adapters emitted capability records.

`record.evidence_classification` separates real external-source evidence from a
Metriplane-authored synthetic format-engineering record. A native synthetic
declaration can validate as a well-formed record, but `assess_capability()` will
not permit it as external-source evidence. Its exact Ubuntu/macOS and Python
3.12/3.13 rows remain `required` or `pending`; the record cannot predeclare them
as passing before CI.

## Canonical form and fingerprint

`canonical_json_bytes()` produces UTF-8 JSON with sorted keys, no insignificant
whitespace, finite values only, and one final line feed. This is the bounded
Metriplane capability-record canonical form. It is not an RFC 8785 claim.

`capability_fingerprint()` validates the record and hashes those canonical bytes
with SHA-256. Input JSON rejects duplicate object keys and non-finite numbers.
Artifact hashing accepts only regular nonsymlink files.

## Use

From this directory:

```sh
uv sync --frozen --extra test
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

From Python:

```python
from metriplane_source_adapter_sdk import (
    assess_capability,
    capability_fingerprint,
    load_capability,
    record_path,
)

record = load_capability(record_path("maniskill-pickcube"))
assessment = assess_capability(record)
assert assessment.external_source_permitted
print(capability_fingerprint(record))
```

`verify_repository_evidence(record, repository_root)` rehashes every referenced
repository file. It rejects unsafe paths, symlinks, missing files, and hash drift.

## Claim boundary

Schema validity means that a declaration is structurally and semantically
complete. It does not prove that source data, transforms, rights, or claims are
correct. Evidence review remains mandatory. A successful assessment applies only
to the exact adapter, source, and evidence identities in that record. It is not a
general source-family compatibility claim.
