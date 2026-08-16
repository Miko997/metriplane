<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane external evaluation package

This package is for a small, bounded evaluation of Metriplane using one recorded
robotics or workcell trace. It is designed so a technical contact can assess the
scope, provide the right information, and review the result without a production
connection or a long discovery process.

The basic offer is simple:

> Provide one recorded trace and one process question. Metriplane will either
> produce an inspectable, reproducible result or document exactly why the source
> is not supportable under the current contract.

A positive incident is not required. A useful evaluation may end as
`SUPPORTED`, `PARTIALLY SUPPORTED`, or `NOT SUPPORTED`.

## Start here

1. [Read the one-page offer](ONE_PAGE_OFFER.md) or
   [open the PDF](metriplane_recorded_state_evaluation.pdf).
2. [Complete the data intake](DATA_INTAKE.md).
3. [Review the acceptance criteria](ACCEPTANCE_CRITERIA.md).
4. Use the [statement-of-work template](SOW_TEMPLATE.md) only after the technical
   scope is clear.

## Package contents

- [One-page offer](ONE_PAGE_OFFER.md): the forwardable summary.
- [Data intake](DATA_INTAKE.md): the minimum source, field, rights, and reviewer
  information needed to assess fit.
- [Acceptance criteria](ACCEPTANCE_CRITERIA.md): the gates and outcome model.
- [Evaluation agreement / SOW template](SOW_TEMPLATE.md): a plain-language
  operational template that still requires legal review before signature.
- [Target qualification model](TARGET_QUALIFICATION.md): a scoring method that
  favors real data fit and reviewer availability over prestige.
- [Target scoring sheet](target_qualification.csv): an empty CSV template.
- [Partner FAQ](FAQ.md): concise answers to common technical and process
  questions.
- [Factual acknowledgement template](FACTUAL_ACKNOWLEDGEMENT.md): a neutral
  completion record, not an endorsement request.
- [Permission options](PERMISSION_OPTIONS.md): separate choices for data use,
  attribution, publication, retention, and redaction.

## Technical basis

The package is built around Metriplane's existing recorded-state boundary:

- [External Source Contract v1](../specs/external-source-contract-v1.md)
- [Portable external fixture workflow](../user-guide/external-fixtures.md)
- [ManiSkill PickCube external fixture proof](https://github.com/Miko997/metriplane/blob/maniskill-pickcube-proof-v1/proofs/maniskill-pickcube-v1/README.md)

The contract keeps source facts, adapter-derived facts, operator-configured
rules, and Metriplane-derived results separate. It does not turn source labels
into incident truth, and it does not claim broad compatibility before a real
adapter and fixture have passed the documented gates.

## Scope boundary

This is a recorded, local, observe-only evaluation. It does not control a robot,
connect to a production line, certify safety or quality, verify the accuracy of
the original measurements, or require a favorable result. Public or synthetic
data is preferred when it can answer the same technical question.
