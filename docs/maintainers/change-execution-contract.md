# Change execution contract

This repository implements the planning contract for every change after MP2-004.
The linked Linear work order and current repository state remain required inputs;
this file does not grant scope that the assigned issue does not own.

## Start gate

Before editing, bind the assigned issue, exact dependency-complete base commit and
tree, tracked repository instructions, finite EXISTING/CREATE paths, owners,
consumers, validators, commands, environments, manual resources, and every
acceptance result to one canonical no-overwrite materialization. An independent
read-only reviewer must return `READY`. Missing or conflicting authority returns
`BLOCKED_NOT_READY`.

Use the exact supported tool versions from `docs/maintainers/testing-policy.md`.
Do not substitute a newer executable merely because it is on `PATH`.

## Repository protection

Hosted capability capture and offline policy validation are separate operations:

```console
python tools/capture_repository_protection.py \
  --repository Miko997/metriplane \
  --captured-at <ISO-8601> \
  --output-dir <capture-directory>
python tools/check_repository_protection.py capture \
  --policy docs/status/repository-protection-policy.json \
  --capability <capture-directory>/repository-protection-capability.json \
  --settings <capture-directory>/repository-protection-settings.json
```

The current repository has no merge queue. Its truthful mode is capability-limited
serialized strict-up-to-date merging. That mode does not claim enforceable
actor-exclusive merges or tags. It requires one candidate at a time and a fresh
strict check result at the exact merge SHA. Hosted setting changes remain an owner
operation and require a new capture.

The hosted required-check set must equal the four MP2-004 terminal names exactly;
legacy, missing, or extra contexts fail offline validation. Each aggregate consumes
the checked-out SHA reported by its dependency job rather than copying an expected
event SHA into the result.

Files under `docs/status/examples/` are schema and fault-test fixtures, not claims
about live provider state. Release or activation evidence must come from a fresh
`capture_repository_protection.py` run whose capability and settings records share
one capture time and source-digest set and pass the offline policy validator.

The five required terminal names and their sole producers are recorded in
`docs/status/required-terminals.json`. MP2-004 owns the four aggregate CI and
health terminals. MP2-007 owns the active `Release / required` terminal and
`.github/workflows/release-required.yml` is its sole producer.

## Release qualification

MP2-007 owns one cumulative state machine for `v0.4` through `v1.0`. Its
schemas, registries, stable tools, fixtures, and runbook are closed finite
interfaces. The existing `publish-pypi.yml` workflow and
`tools/release_artifacts.py` are integrated consumers, not a second release
state machine. A tag may identify a candidate but cannot stage, approve, or
promote one by itself.

Ordinary pull requests execute the deterministic fake-release and mutation
suite. Synthetic role and approval fixtures are test-only and fail every live
authority predicate. Live promotion additionally requires a provider-bound
executor delegation, distinct non-author approval, complete terminal matrix,
two independent read-verified stores, fenced CAS attempt index and lock,
exact-byte reconciliation, and the retained chain/LKG/pointer close path.
Missing external proof remains `BLOCKED_NOT_READY`; no hosted setting, tag,
release, publication, or merge mutation is implied by local framework success.

## Main health

Candidate checks read global health and never write it. Completed protected-main
CI reconciliation, nightly, and weekly results are the only normal writers. The
protected-main writer observes the triggering CI attempt and the exact commit's
latest Documentation and CodeQL attempts through paginated provider job APIs. It
requires one exact aggregate terminal in each selected attempt and ingests them as
one result; missing, duplicate, non-successful, or timed-out terminals retain failure.
The selected provider attempts must remain unchanged in a second paginated read
immediately before acceptance; a changed selection is observed again.
Non-main and non-push workflow completions use unique non-writer concurrency
groups and cannot displace the durable writer. Durable writers use the provider's
maximum FIFO pending queue instead of pending-run replacement. The
`metriplane-main-health-state` branch is a separate append-only state and retention
backend; a normal fast-forward push is the external compare-and-swap. Every result,
retention receipt, incident, history entry, authorization, and resolution is
read-back verified before the state pointer advances.

Candidate admission requires fresh green state for the exact base commit.
Scheduled qualification and persistence are separate jobs, so an early deep-check
failure is still retained. A delayed result that no longer names live `main` is
rejected before ingestion.

The first protected-main result creates the one-time activation record and marks
all earlier history `not_measured`. A failure turns health red. Later ordinary
green results remain red. Resolution requires an issue-bound, unexpired,
provider-authenticated non-author approval for the exact obligations, repair SHA,
and changed paths, plus retained green protected-main and required deep results.
The resolver re-fetches GitHub provider state with `GITHUB_TOKEN`; a supplied JSON
claim cannot authorize repair. If no non-author is available, repair remains
blocked.

## Pull requests

The MP2-004 transition pull request uses the previous repository template. After
MP2-004 merges and this file, the template, and validator read-validate, pull
requests use exactly these H2 headings in order: `Outcome`, `Changes`,
`Validation`, and `Boundaries`. The nine review prompts and eight checklist
obligations remain as H3 content. `tools/check_pr_contract.py` rejects missing,
extra, or reordered sections; raw transcript/prompt/log attribution markers; and
an over-limit body without a named non-author exception. It does not attempt
AI-style detection.

For an oversized body, the CI validator reads GitHub reviews and requires an
`APPROVED` review on the exact current head from a non-author, with body prefix
`MP2-004 compact-body exception sha256=<body-sha256>:` and a non-empty reason.
Editing the pull-request body retriggers CI validation and invalidates an approval
whose digest no longer names the exact body bytes.

## Stop conditions

Stop before an unauthorized setting mutation, tag, publication, release claim,
scope expansion, compatibility removal, evidence rewrite, or self-approved repair.
Preserve retained evidence even when reverting code. A failed unmerged candidate
does not falsify global main health; a genuine protected-main or scheduled failure
does.
