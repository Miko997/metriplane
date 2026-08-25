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
without creating or changing state. The trusted default-branch workflow publishes
`Main health / required` on each exact open pull request head during its five-minute
reconciliation and immediately after every durable transition. Pull request events
do not run privileged admission or occupy the serialized writer queue, and
candidate-controlled code is never executed with the status-writing token. The
checkout-free invalidator overwrites earlier success with failure for every open
head before the reconciler starts. The reconciler keeps failure when health turns red, the base
becomes stale, or the 36-hour window expires; a persistent commit status is never
treated as an unbounded lease. All status publishers and durable writers are
trusted triggers in one serialized concurrency group, so an older green snapshot
cannot publish success after a newer red transition. Every writer first publishes
provider-verified failure on its measured main SHA. Only after CAS and read-back
does the successful `persist-health` job publish a GitHub Actions status binding
that main SHA to the exact state commit, run ID, and attempt. A five-minute tick
reads the main ref, state ref, writer status, exact run, and exact attempt jobs
before and after validation; it requires all snapshots to remain unchanged and
exactly one successful `persist-health` job. Immediate reconciliation requires the
same provider status plus the successful dependency's exact main and state-commit
outputs. Both paths recheck main, state, writer status, and PR base/head at the
success boundary. A success response that cannot be provider-verified is followed
by failure. The completed protected-main CI workflow, nightly and weekly schedules,
and default-branch-only `repository_dispatch` deep runs are the only normal writer
triggers. A
protected-main writer binds the triggering CI run attempt, selects the exact
commit's latest Documentation and CodeQL attempts, and reads every selected
attempt's paginated provider job records. It requires exactly one Metriplane,
Documentation, and Security aggregate terminal and retains one combined result.
Missing, duplicate, cancelled, skipped, stale, wrong-attempt, wrong-SHA,
malformed, timed-out, or failing obligations do not become success.

Durable writers use the provider's maximum pending queue so one protected-main,
scheduled, or reconciliation result cannot replace another while it waits.

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

The operational `resolve` command accepts the retained provider evidence as an
artifact, not as an assertion to trust. It re-fetches the review, reviewer
permission, pull request, reviewed and merge commits, and complete provider file
list with `GITHUB_TOKEN`, then requires every field except the later capture time
to match before retaining the evidence alongside the authorization and resolution.
A newer review from the named authorized reviewer supersedes the selected approval,
and any current requested-changes review by an authorized reviewer fails closed.
Comments and reviews from identities without write, maintain, or admin permission
do not alter the decisive review state. Resolution time is generated internally
and must fall between provider capture and authorization expiry.

For a personal repository with no independent collaborator, the only exception is
the explicitly named `single-maintainer-owner-emergency` mode. The repair PR must
contain `docs/status/main-health-owner-emergency.json`, whose base SHA, open
incident digest, issue, PR number, complete sorted changed-path inventory, expiry,
and fixed `[nightly, weekly]` cadence policy match provider state exactly. The
normal PR contract body must contain exactly one verbatim copy of the corresponding
two-line owner-emergency marker. Automated reconciliation never grants a red-health
owner emergency; it continues to publish failure. Caller-supplied provider JSON is
not accepted as operational admission evidence. `capture-owner-admission` fetches
the live pull request, complete file list, a stable invitation/collaborator
snapshot, and both active default-branch rulesets itself with an
owner-authenticated token. `Protect main` must retain the pull-request, deletion,
non-fast-forward, and three non-health required-check protections without a
bypass. `Protect main health admission` must contain only
`Main health / required`, pin it to GitHub Actions integration `15368`, and grant
repository role `5` only the `pull_request` bypass mode. This permanent split is
the truthful single-maintainer capability boundary; it never permits a direct
push, tag, or bypass of the other required checks. Admission records that
independent approval did not exist and publishes the canonical admission payload
and digest in an unedited GitHub comment before merge. The manifest also carries the exact
incident-only amendment of `repair_requires_non_author`; it does not change the
global activation policy. Provider capture re-reads the manifest from the reviewed
head, captures the complete collaborator and pending-invitation inventories, and
requires that neither contains an eligible non-author reviewer. Admission requires
their combined canonical digest to match the manifest. The provider comment starts
a five-minute lease; editing it invalidates the admission. `merge-owner-emergency`
re-fetches the comment, pull request, complete paths, manifest, owner permission,
both rulesets, and a stable collaboration snapshot twice at the merge boundary.
It then submits a GraphQL merge with `expectedHeadOid` through the governed
pull-request-only bypass. No status is fabricated and no ruleset changes during
the merge. The command is idempotent: if GitHub completed the merge but the client
lost the response, a rerun accepts only the provider-recorded exact head, owner
merge actor, merge timestamp, unchanged admission, and unchanged policy, then
reconstructs the same `owner-merge-gate.json`. Post-merge capture re-fetches the
admission comment, stable collaboration snapshot, both rulesets, pull request,
permission, and both commits. Provider timestamps must bracket the merge, and
the merge must precede manifest expiry. Post-merge `captured_at` is the actual provider
retrieval time, not the earlier merge timestamp. Its manifest digest and
policy-amendment digest must match the authorization.

Retain the JSON outputs from `capture-owner-admission` and
`merge-owner-emergency` as `owner-admission.json` and
`owner-merge-gate.json`. After that exact PR merges, run the `Main Health`
deep cadences through trusted default-branch repository dispatches:

```console
gh api --method POST repos/Miko997/metriplane/dispatches \
  -f event_type=main-health-nightly
gh api --method POST repos/Miko997/metriplane/dispatches \
  -f event_type=main-health-weekly
```

Capture the merged owner decision with the provider admission and raw merge gate,
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
GITHUB_TOKEN=<token> python tools/stop_the_line.py capture-owner-admission \
  --root main-health-state --repository Miko997/metriplane \
  --pull-request <number> --issue MET-NNN --incident-digest <digest> \
  --expected-head-sha <reviewed-head> \
  --protection-ruleset-id 20613848 \
  --main-health-ruleset-id 21500579 \
  > owner-admission.json
GITHUB_TOKEN=<token> python tools/stop_the_line.py merge-owner-emergency \
  --root main-health-state --repository Miko997/metriplane \
  --pull-request <number> --issue MET-NNN --incident-digest <digest> \
  --admission-json owner-admission.json > owner-merge-gate.json
GITHUB_TOKEN=<token> python tools/stop_the_line.py capture-owner-emergency \
  --repository Miko997/metriplane --pull-request <number> \
  --issue MET-NNN --incident-digest <digest> \
  --admission-json owner-admission.json \
  --merge-gate-json owner-merge-gate.json > provider-evidence.json
expected_commit="$(git -C main-health-state rev-parse HEAD)"
python tools/stop_the_line.py validate-git --root main-health-state
GITHUB_TOKEN=<token> python tools/stop_the_line.py resolve \
  --root main-health-state \
  --authorization-json "$(cat repair-authorization.json)" \
  --approval-evidence-json provider-evidence.json \
  --repaired-main-json "$(cat repaired-protected-main-result.json)" \
  --owner-admission-json owner-admission.json \
  --owner-merge-gate-json owner-merge-gate.json \
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

Automated reconciliation never converts red health into an owner-emergency
success. The governed merge command uses only the recorded pull-request bypass
for the exact qualified head while every other ruleset protection stays active.
Resolution requires the exact reviewed head, ordered merge parents, owner merge
actor, unchanged split-policy digests, and admitted collaboration digest. The
bypass admits only the code merge; it does not clear red health or substitute for retained
protected-main, nightly, weekly, provider, authorization, and resolution evidence.
