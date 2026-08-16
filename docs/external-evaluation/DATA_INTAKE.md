<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Data and evaluation intake

Complete this before a scope is accepted. Short factual answers are better than
sales language. Unknown values are acceptable when they are marked as unknown.

## 1. Source overview

- Organization or project:
- Technical contact:
- Reviewer name or role:
- Source system or dataset:
- Source version, release, or commit:
- File format or API export format:
- Approximate duration and file size:
- Public, synthetic, historical, or restricted:
- Proposed evaluation window:

## 2. Rights and handling

- Who owns or controls the source data?
- May the source be used for this evaluation?
- May a normalized fixture be created?
- May the original source be copied, or must it remain referenced or withheld?
- May the adapter be published?
- May the normalized fixture be published?
- May a factual result summary be published?
- Is organization-name attribution allowed?
- Are there deletion or retention requirements?
- Are there export, privacy, security, or contractual restrictions?

Do not send confidential production data until the handling terms are agreed.
A public or synthetic substitute is preferred when it can answer the same
technical question.

## 3. Time semantics

- Authoritative timestamp field:
- Clock type: wall, monotonic, simulation, frame index, or other:
- Unit:
- Expected sample rate or step interval:
- Is time strictly ordered?
- Are duplicate or missing timestamps possible?
- Are streams synchronized? If yes, how?
- Is interpolation, resampling, or carry-forward already present upstream?

## 4. Coordinates and units

- Authoritative position fields:
- Source coordinate frame:
- Units:
- Axis meaning and handedness:
- Is Z meaningful, absent, or projected away?
- Are transforms required before evaluation?
- Are transform parameters available and versioned?
- Are zone labels already present? If yes, how were they assigned?

## 5. Entities and identity

For each process-relevant entity, provide:

- Source identity field or path.
- Stable identifier.
- Entity type or role.
- Whether the entity exists in every complete snapshot.
- Whether identity can change across the recording.
- Whether several source entities must be fused into one normalized entity.

List any entities that must not be included.

## 6. Completeness and missing data

- Is each frame a complete snapshot or a partial update?
- How is an unobserved entity represented?
- How is physical absence represented?
- Can position be unknown or invalid?
- Are nonfinite values possible?
- Is stale data marked?
- What is the maximum acceptable gap?
- Is there a documented materialization or carry-forward policy?

Metriplane does not treat unknown or omitted state as physical absence. A source
that cannot distinguish those cases may be rejected or only partially supported.

## 7. Process question

Describe one question only.

- What should happen?
- Which entities are involved?
- Which zone, station, or region matters?
- What starts the timing condition?
- What ends it?
- What maximum wait, ordering rule, or required-asset condition should be tested?
- Is the rule supplied by the organization, or proposed for review by Metriplane?
- Is there a known negative or control case?

Do not include an expected incident label in the source data. Expected outcomes
belong in test metadata, not evaluation input.

## 8. Review and completion

- Who will inspect the field mapping?
- Who will review the process rule?
- Can the reviewer rerun the portable fixture?
- How much reviewer time is available?
- Is a factual completion acknowledgement acceptable?
- What may be quoted publicly, if anything?
- Who approves publication or attribution?

## 9. Files requested for the fit check

Provide only what is needed:

- A sample schema or field list.
- A small representative trace.
- Coordinate and clock notes.
- Stable entity mapping information.
- Data-use confirmation.
- One bounded process question.

Do not send passwords, access tokens, personal data, or production credentials.
