<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# A bounded Metriplane evaluation using one recorded trace

**Typical duration:** 2 to 4 weeks  
**Connection model:** recorded files only  
**Result:** `SUPPORTED`, `PARTIALLY SUPPORTED`, or `NOT SUPPORTED`

## The offer

Provide one small robotics, simulation, or workcell trace and one process
question. Metriplane will build a deterministic source adapter when the data is
suitable, preserve the field-level provenance, run the normalized state through
the existing incident-evaluation path, and return a result that another technical
reviewer can inspect and rerun.

A positive incident is not required. If the source cannot support a defensible
evaluation, the deliverable is a clear `NOT SUPPORTED` result with the blocking
reason recorded.

## What you provide

- One bounded public, synthetic, historical, or otherwise approved trace.
- A field or schema description, including timestamps, units, coordinate frames,
  entity identities, and missing-data behavior.
- One narrow process question, such as a missed handoff, delayed arrival, missing
  required asset, or zone-timing condition.
- Confirmation that the data may be used for the agreed evaluation.
- One technical reviewer who can inspect the mapping and the final result.

## What Metriplane returns

- A source-specific adapter or a documented reason the source is not supportable.
- A provenance manifest and field-level mapping into the portable fixture format.
- A normalized recorded session and bounded process rules.
- An incident timeline and human-readable report when the configured condition is
  observed.
- An integrity-verified evidence bundle and generated regression check when an
  incident exists.
- Reproduction instructions, limitations, and a concise technical summary.

## How the evaluation runs

1. **Fit check:** confirm data rights, fields, timing, coordinates, identities,
   completeness, and the process question.
2. **Adapter and fixture:** normalize the source without hiding transforms,
   carry-forward, projection, zone assignment, or information loss.
3. **Evaluation:** validate the fixture, run Metriplane, verify any evidence
   bundle, and execute the generated regression.
4. **Review:** the nominated reviewer checks the mapping, result, and limitations.

## What is not included

- Live robot or machinery control.
- Safety, quality, certification, or production approval.
- Arbitrary video understanding or unrestricted anomaly detection.
- A guarantee that an incident will be found.
- A claim of broad compatibility with the source family.
- Public use of names, data, or results without separate written permission.

## Good starting point

A sample schema or a 30 to 60 second public or synthetic trace is usually enough
for the first fit check. No production connection is required.

Repository: https://github.com/Miko997/metriplane
