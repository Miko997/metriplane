# Main health operations

`Main health / required` is the stable terminal for the durable state owned by
MP2-004. The state lives outside the product branch on
`metriplane-main-health-state`.

## State layout

`activation.json` is created once. `results/`, `retention/`, `history/`,
`incidents/`, `approval-evidence/`, `policy-amendments/`,
`repair-authorizations/`, and `resolutions/` are immutable. Only `state.json` is a
mutable pointer, and its generation advances by one per accepted transition. The
branch commit is the external CAS generation; concurrent stale pushes fail. A
dedicated active ruleset for `metriplane-main-health-state` prohibits deletion and
non-fast-forward updates. `validate-git` walks the complete first-parent branch,
requires exactly one validated generation per commit, and proves every earlier
immutable byte remains present. A fast-forward whole-tree replacement therefore
fails even if its new tree is internally self-consistent.

`python tools/stop_the_line.py validate-git --root <state-checkout>` verifies the
external Git chain. The underlying `validate` command verifies the
activation digest, every history predecessor, every immutable filename digest,
every retained result and receipt, generation continuity, the final pointer,
incident identity, and any resolution's authorization and approval evidence.

## Normal ingestion

Pull requests use `scope=candidate`; the tool validates the result and returns
without creating or changing state. The candidate workflow runs as
`pull_request_target`, checks out and executes only the exact pull request base,
and publishes `Main health / required` as a commit status on the exact head SHA.
Candidate-controlled code is never executed with the status-writing token. The
same trusted workflow reconciles every open pull request immediately after each
durable main-health transition and on a five-minute schedule. It overwrites earlier
success with failure when health turns red, the base becomes stale, the 36-hour
window expires, or an emergency manifest expires; a persistent commit status is
never treated as an unbounded lease. Scheduled reconciliation and durable writers
share one serialized concurrency group, so an older green snapshot cannot publish
success after a newer red transition. The
completed protected-main CI workflow and the nightly and weekly schedules are the
only normal writer triggers. A
protected-main writer binds the triggering CI run attempt, selects the exact
commit's latest Documentation and CodeQL attempts, and reads every selected
attempt's paginated provider job records. It requires exactly one Metriplane,
Documentation, and Security aggregate terminal and retains one combined result.
Missing, duplicate, cancelled, skipped, stale, wrong-attempt, wrong-SHA,
malformed, timed-out, or failing obligations do not become success.

Workflow completions that are not protected-main push results receive unique
non-writer concurrency groups. They cannot occupy or replace a durable writer.
Durable writers use the provider's maximum pending queue so
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

A repair authorization names the repository, pull request, issue, incident,
author, authorization mode, expiry, exact failing obligations, reviewed head SHA,
provider file-list digest, allowed paths, and canonical deep cadences. Provider
evidence separately binds that reviewed head to the merge commit through the
exactly two parents, the admitted base and reviewed head, and through identical
reviewed/merged tree IDs. The merged SHA must have
retained green `protected-main`, `nightly`, and `weekly` results. Expired, stale,
unrelated, broadened, unauthorized, or incomplete repairs fail closed.

The provider file count must match GitHub's declared `changed_files` count and
must not exceed the provider's 3,000-file limit. A rename contributes both its
destination `filename` and its `previous_filename`; the sorted inventory must
equal `allowed_paths`, not merely be a subset. The repair must use a merge commit:
the reviewed head is a merge parent and its tree is byte-for-byte identical to
the merge tree.

The ordinary path uses a current GitHub review from a collaborator with write,
maintain, or admin permission. Its body is exactly two lines:

```text
Main-health repair authorization: MET-NNN
Incident: <64-character incident digest>
```

Capture it after merge, then bind the canonical evidence digest and changed-path
digest into the authorization:

```console
GITHUB_TOKEN=<token> python tools/stop_the_line.py capture-approval \
  --repository Miko997/metriplane --pull-request <number> \
  --review-id <review-id> --issue MET-NNN --incident-digest <digest>
```

The operational `resolve` command accepts no caller-supplied provider evidence. It
re-fetches the review, reviewer permission, pull request, reviewed and merge
commits, and complete provider file list with `GITHUB_TOKEN`, then retains that
evidence alongside the authorization and resolution. A newer review from the
named authorized reviewer supersedes the selected approval, and any current
requested-changes review by an authorized reviewer fails closed. Comments and
reviews from identities without write, maintain, or admin permission do not alter
the decisive review state. Resolution time is generated internally and must fall
between provider capture and authorization expiry.

For a personal repository with no independent collaborator, the only exception is
the explicitly named `single-maintainer-owner-emergency` mode. The repair PR must
contain `docs/status/main-health-owner-emergency.json`, whose base SHA, open
incident digest, issue, PR number, complete sorted changed-path inventory, expiry,
and fixed `[nightly, weekly]` cadence policy match provider state exactly. The
normal PR contract body must contain exactly one verbatim copy of the corresponding
two-line owner-emergency marker. Candidate admission remains read-only and records
that independent approval did not exist. The manifest also carries the exact
incident-only amendment of `repair_requires_non_author`; it does not change the
global activation policy. Provider capture re-reads the manifest from the reviewed
head, captures the complete collaborator and pending-invitation inventories, and
requires that neither contains an eligible non-author reviewer. Admission binds
the accepted-collaborator inventory available to the workflow token; post-merge
capture requires the same canonical collaborator digest and separately rejects
an eligible pending invitation. Post-merge `captured_at` is the actual provider
retrieval time, not the earlier merge timestamp. Its manifest digest and
policy-amendment digest must match the authorization.

After that exact PR merges, run the `Main Health` workflow manually once for each
deep cadence. Capture the merged owner decision with `capture-owner-emergency`,
construct the authorization from the captured evidence, and run `resolve`. The
resolver re-fetches the owner/admin identity and merge proof, requires retained
green protected-main plus both deep results, appends the resolution through CAS,
and validates the complete retained history. No state commit is rewritten.

Publish the resolution from a dedicated state-branch clone. Keep the expected
remote commit before resolving, commit the generated immutable objects and pointer,
then reject any concurrent remote change before the non-force push:

```console
git clone --single-branch --branch metriplane-main-health-state \
  https://github.com/Miko997/metriplane.git main-health-state
expected_commit="$(git -C main-health-state rev-parse HEAD)"
python tools/stop_the_line.py validate-git --root main-health-state
GITHUB_TOKEN=<token> python tools/stop_the_line.py resolve \
  --root main-health-state \
  --authorization-json "$(cat repair-authorization.json)" \
  --repaired-main-json "$(cat repaired-protected-main-result.json)" \
  --expected-generation <generation>
git -C main-health-state add --all
git -C main-health-state commit -m "Resolve main health for <merge-sha>"
python tools/stop_the_line.py validate-git --root main-health-state
test "$(git -C main-health-state ls-remote origin \
  refs/heads/metriplane-main-health-state | cut -f1)" = "$expected_commit"
git -C main-health-state push origin \
  HEAD:refs/heads/metriplane-main-health-state
test "$(git -C main-health-state ls-remote origin \
  refs/heads/metriplane-main-health-state | cut -f1)" = \
  "$(git -C main-health-state rev-parse HEAD)"
git clone --single-branch --branch metriplane-main-health-state \
  https://github.com/Miko997/metriplane.git main-health-readback
python tools/stop_the_line.py validate-git --root main-health-readback
```

When this trusted base-branch admission workflow is first introduced while health
is already red, it cannot publish the current repair PR's trusted head status. For
that one bootstrap incident, retain the complete active ruleset and its digest,
the pre-merge provider collaborator and invitation responses and their digest,
remove only the `Main health / required` context, merge the exact qualified PR
normally, immediately restore and digest the original ruleset, and verify the
before/after documents are identical. Re-fetch the collaboration inventories
immediately after merge and require the normalized digest to match the admitted
manifest. Deletion, non-fast-forward, pull-request,
and every other required-check rule stay active throughout. This ruleset operation
admits only the code merge; it does not clear red health or substitute for retained
protected-main, nightly, weekly, provider, authorization, and resolution evidence.
