<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Target qualification model

This model is meant to prevent prestige-first outreach. A smaller organization
with a usable trace and an available reviewer is a better target than a famous
organization with no data path or decision owner.

Score each category from 0 to 3. Record evidence for the score. Do not raise a
score because the organization is well known.

## Hard stops

Do not pursue the evaluation when any of these is true:

- No clear right to use the proposed data.
- The request requires live robot or production control.
- The organization will not provide field, clock, coordinate, or identity
  semantics.
- No technical reviewer is available.
- The only available input is sensitive production video and no approved
  substitute exists.
- The organization requires a guaranteed positive result, testimonial, or public
  endorsement.
- The schedule cannot support review and closure.

## Scoring categories

| Category | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Trace fit | No usable recorded state | Unclear or mostly incompatible | Bounded state appears adaptable | Clear bounded trace with relevant fields |
| Rights path | No rights path | Unclear owner or restrictions | Approval possible but not confirmed | Use and handling rights already confirmed |
| Field semantics | No schema or meanings | Major gaps | Most key fields documented | Clock, coordinates, identity, and missing data are clear |
| Reviewer availability | No reviewer | Contact exists but no time | Reviewer can inspect | Reviewer can inspect and rerun |
| Process question | Vague product interest | Broad use case only | Narrow question needs refinement | One clear bounded condition |
| Delivery friction | Production access or heavy procurement | High security or integration burden | Moderate review burden | Public, synthetic, or easy approved file transfer |
| Independence | Existing close collaborator | Relationship may weaken independence | Relevant external technical contact | Independent organization and reviewer |
| Timeline | No credible window | More than 12 weeks | 5 to 12 weeks | Can complete within 2 to 4 weeks |

Maximum score: 24.

## Decision bands

- **20 to 24: pursue now.** Data, reviewer, and scope are strong enough for a
  direct technical approach.
- **15 to 19: qualify first.** Ask for a schema, sample, reviewer, or rights
  clarification before proposing a schedule.
- **9 to 14: keep warm.** The target may become viable, but current friction is
  too high for active evaluation work.
- **0 to 8: decline.** Record the reason and stop outreach.

A hard stop overrides the numeric score.

## Required notes

For every scored target, record:

- The proposed source and revision.
- The likely process question.
- The person who can approve data use.
- The person who can review the technical result.
- The main uncertainty.
- The smallest next action.
- Any prior contact or duplicate-route risk.

Use [target_qualification.csv](target_qualification.csv) as the working sheet.
Keep private contact details and organization-specific legal notes outside the
public repository.
