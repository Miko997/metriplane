# Main health operations

`Main health / required` is the stable terminal for the durable state owned by
MP2-004. The state lives outside the product branch on
`metriplane-main-health-state`.

## State layout

`activation.json` is created once. `results/`, `retention/`, `history/`,
`incidents/`, `repair-authorizations/`, and `resolutions/` are immutable. Only
`state.json` is a mutable pointer, and its generation advances by one per accepted
transition. The branch commit is the external CAS generation; concurrent stale
pushes fail.

`python tools/stop_the_line.py validate --root <state-checkout>` verifies the
activation digest, every history predecessor, every immutable filename digest,
every retained result and receipt, generation continuity, the final pointer,
incident identity, and any resolution's authorization and approval evidence.

## Normal ingestion

Pull requests use `scope=candidate`; the tool validates the result and returns
without creating or changing state. The completed protected-main CI workflow and
the nightly and weekly schedules are the only normal writer triggers. A
protected-main writer binds the triggering CI run attempt, selects the exact
commit's latest Documentation and CodeQL attempts, and reads every selected
attempt's paginated provider job records. It requires exactly one Metriplane,
Documentation, and Security aggregate terminal and retains one combined result.
Missing, duplicate, cancelled, skipped, stale, wrong-attempt, wrong-SHA,
malformed, timed-out, or failing obligations do not become success.

Workflow completions that are not protected-main push results receive unique
non-writer concurrency groups. They cannot occupy or replace the single pending
durable-writer slot. Durable writers use the provider's maximum pending queue so
one protected-main or scheduled result cannot replace another while it waits.

Candidate admission reads the external branch and requires fresh green evidence
for the pull request's exact base SHA. Evidence older than 36 hours fails closed.
Only the MP2-004 transition can pass before the state branch exists; once the base
contains the health tool, a missing state branch is an error.

The first global result consumes `docs/status/main-health-policy.json`, creates the
activation boundary, and records the earlier interval as `not_measured`. A failing
global result opens an incident and makes the terminal red. Ordinary success never
clears an open incident.

The scheduled product check is a read-only job. The durable writer has an
`always()` dependency on it, so checkout, setup, install, cancellation, and test
failures become a retained failure result. Before any write, the writer fetches
`origin/main` and rejects a delayed result whose measured SHA is no longer current.

## Repair

A repair authorization must name the repository, pull request, issue, author,
different reviewer, expiry, exact failing obligations, exact proposed repair SHA,
digest of the provider file list, allowed paths, and required deep cadences. The
repaired SHA must have retained green `protected-main` plus all required cadence
results. Self-approved, expired, stale, unrelated, broadened, or incomplete
repairs fail closed.

Use a GitHub review whose body is exactly
`Main-health repair authorization: MET-NNN`. Capture it first, then bind the
canonical evidence digest and changed-path digest into the authorization:

```console
GITHUB_TOKEN=<token> python tools/stop_the_line.py capture-approval \
  --repository Miko997/metriplane --pull-request <number> \
  --review-id <review-id> --issue MET-NNN
```

The operational `resolve` command accepts no caller-supplied approval evidence. It
re-fetches the named review, pull request, current reviewed commit, and complete
provider file list with `GITHUB_TOKEN`, then retains that evidence alongside the
authorization and resolution. A newer review from the named reviewer supersedes
the selected approval, and any current requested-changes review fails closed.

This repository currently has one authenticated collaborator. Therefore no live
repair can be approved until a provider-authenticated non-author reviewer is
explicitly bound. Green activation and normal ingestion do not waive that rule.
