<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# External evaluation FAQ

## What does Metriplane need?

Timestamped state for a small set of stable entities, plus enough information to
interpret time, coordinates, units, identity, completeness, and one bounded
process rule. The source does not have to use Metriplane's native format when a
defensible adapter can be built.

## Does this require cameras or video?

No. The evaluation uses recorded state. Video may be useful as optional context,
but it is not required and is not treated as authoritative state unless a
separate, explicit perception process produced the fields being evaluated.

## Does this require a production connection?

No. Public, synthetic, historical, or otherwise approved files are preferred.
The evaluation does not connect to or control a live production system.

## Can Metriplane read any ROS bag, simulator log, or robotics dataset?

No. Compatibility is source-specific. The source must pass a fit review and, when
needed, a bounded adapter must be built and audited. One successful fixture does
not prove general support for the whole source family.

## What counts as a successful evaluation?

A successful evaluation is one that reaches a defensible conclusion with
reproducible evidence. That conclusion may be `SUPPORTED`,
`PARTIALLY SUPPORTED`, or `NOT SUPPORTED`. Finding an incident is not required.

## What happens if no incident is found?

The result is reported as no incident under the exact supplied rule and recorded
state. Metriplane does not create an evidence bundle or generated incident
regression when no incident exists.

## What does evidence verification prove?

It proves that the saved evidence bundle is internally intact and matches its
recorded checksums. It does not prove that the original measurements were
physically accurate or that the process rule was correct.

## Can source labels be used as the incident answer?

No. Source labels, rewards, success fields, or expected outcomes may be retained
as test metadata or provenance, but they do not become hidden Metriplane incident
truth.

## What if the source has partial updates?

Partial updates must be materialized into bounded complete snapshots with an
explicit policy, or the source is rejected. Unknown or omitted state is not
silently interpreted as physical absence.

## Who reviews the result?

The organization nominates a technical reviewer who can inspect the field
mapping, process rule, result, and limitations. Rerunning the portable fixture is
preferred when practical.

## Who owns the adapter and fixture?

That is agreed before work begins. The adapter may remain private, be delivered
under a private license, or be proposed as an open-source contribution. Original
source material does not need to be published for an adapter to be public.

## Will the organization be named publicly?

Only with explicit written permission. Data-use permission, organization-name
attribution, quotation, logo use, and public result publication are separate
choices.

## Is the completion acknowledgement an endorsement?

No. It records what was supplied, reviewed, or rerun. It should not say that the
organization recommends Metriplane or considers it production-ready, safe, or
certified.

## How long does the evaluation take?

A well-scoped evaluation usually takes 2 to 4 weeks. Missing field semantics,
rights review, or reviewer delays can extend the schedule without expanding the
scope.
