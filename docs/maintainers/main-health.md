# Main health operations

`Main health / required` is the default-branch aggregate terminal for the durable
state owned by MP2-004. `Main health admission / required` is the dedicated
App-owned admission check on each pull request head. The state lives outside the
product branch on `metriplane-main-health-state`.

## State layout

`activation.json` is created once. `results/`, `retention/`, `history/`,
`incidents/`, `approval-evidence/`, `policy-amendments/`,
`repair-authorizations/`, and `resolutions/` are immutable. Only `state.json` is a
mutable pointer, and its generation advances by one per accepted transition. The
branch commit is the external CAS generation; concurrent stale pushes fail. Two
dedicated active rulesets cover `metriplane-main-health-state`. The immutable
ruleset prohibits deletion and non-fast-forward updates with no bypass actors. A
separate writer ruleset restricts updates and grants an `always` bypass only to
the isolated Main Health GitHub App and the repository owner used for governed
repair. During an owner-emergency merge, that writer ruleset is temporarily
frozen with no bypass actors and remains frozen through post-merge provider
capture. `validate-git` walks the complete first-parent branch,
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
without creating or changing state. The trusted default-branch workflow mutates
one `Main health admission / required` check run on each exact open pull request
head during its five-minute reconciliation and immediately after every durable
transition. A separate name avoids GitHub's rule that a same-named check and
legacy commit status must both pass. Pull request events do not run privileged
admission or occupy the serialized publisher queue, and candidate-controlled code is
never executed with the App token. The token is a repository-scoped installation
token from the dedicated Main Health GitHub App. Its private key is available only
through the `main-health-publisher` environment, whose deployment branch policy
admits `main` only. Runtime tokens request Actions read, Checks write, contents
write, and pull requests read; they never request commit-status write. The
required-check ruleset is pinned to this App, not to the shared GitHub Actions
integration.

The invalidator checks out trusted `main` code and changes the existing App check
to failure for every open head before the reconciler starts. Failure remains when
health turns red, the base becomes stale, or the 36-hour window expires. Each head
and check name has one mutable App-owned check run, so a stable SHA cannot exhaust
GitHub's 1,000-entry status or same-name check-run limits. The check's
`external_id` binds the exact head SHA, origin run ID, origin attempt, random
nonce, and one provider-derived deadline.

Before publishing success, reconciliation derives one absolute six-minute
deadline from GitHub's authenticated `Date` response and dispatches three
independent, default-branch-only expiry runs with that exact deadline and check-run
identity. Each closer updates one fixed-name App marker check, binds its own run
and attempt into the marker `external_id`, and waits against authenticated provider
time. Reconciliation verifies all three distinct Actions runs, jobs, and wait steps
are still in progress. With at least three minutes remaining, it dispatches a
separate success publisher and never writes success itself. The publisher has a
two-minute job timeout, revalidates all three closers, requires at least three
minutes at startup, and rechecks provider time for at least 60 seconds of margin
before each success write. The timeout and margins ensure no success publisher can
remain live at the shared deadline. At that deadline, any one of the three expiry
writers can change only the exact generation to failure. Publisher workflows are
serialized with `queue: max`, but expiry and bounded-publisher jobs deliberately
hold no publisher concurrency lock; a lost coordinator or publisher therefore
cannot block a closer. An older attempt that observes a newer `external_id` is a
no-op. If a newer mutation lands between an expiry writer's identity read and
PATCH, the expiry can only write failure and omits `external_id`, so the race can
conservatively reject a newer generation but cannot create success, extend green,
or restore an older identity.

If dispatch, arming, active-run verification, or success verification fails,
reconciliation retains or restores failure. An EXIT/INT/TERM cleanup covers every
handled bounded-publisher exit after a success write; the three already active
closers cover abrupt publisher runner loss. Every durable writer first publishes
provider-verified failure on its measured main SHA. Only after CAS and read-back does the successful
`persist-health` job update the one isolated-App `Main health writer / latest`
check, whose `external_id` binds that main SHA to the exact state commit, run ID,
and attempt. A five-minute tick reads the main ref, state ref, writer check,
exact run, and exact attempt jobs
before and after validation; it requires all snapshots to remain unchanged and
exactly one successful `persist-health` job. Immediate reconciliation requires the
same provider check plus the successful dependency's exact main and state-commit
outputs. Both paths recheck main, state, writer check, and PR base/head at the
success boundary. A response that cannot be provider-verified fails the job and
leaves or restores failure. The completed protected-main CI workflow, nightly and weekly schedules,
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

The scheduled product check is a read-only job. It runs only after writer
invalidation and checks out the invalidator's exact main SHA. The durable writer has an
`always()` dependency on it, so checkout, setup, install, cancellation, and test
failures become a retained failure result. Before any write, the writer fetches
`origin/main` and rejects a delayed result unless the deep checkout, invalidator,
writer checkout, and current main ref are the same exact SHA.

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
from GitHub's authenticated response time and must fall between provider capture
and authorization expiry. Local machine-clock skew cannot extend that boundary.

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
snapshot, the live state-branch ref, both active default-branch rulesets, and both
active state-branch rulesets itself with an owner-authenticated token. The
validated local state checkout must equal
that ref before and after candidate validation; the immutable admission records its
exact commit and generation. `Protect main` must retain the pull-request, deletion,
non-fast-forward, and three non-health required-check protections without a
bypass. `Protect main health admission` must contain only
`Main health admission / required`, pin it to the dedicated Main Health App integration,
and grant repository role `5` only the `pull_request` bypass mode. The state branch
normally uses a non-bypassable deletion/non-fast-forward ruleset plus a separate
update ruleset that permits writes only from that App or the exact repository
owner. After exact-head qualification and independent approval, the update
ruleset must be changed to the same active update restriction with an empty bypass
inventory before owner admission begins. This temporary freeze prevents any state
writer from changing the admitted ref across the GraphQL merge. This split is
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
all four rulesets, live state ref, and a stable collaboration snapshot twice at
the merge boundary, then checks the same state ref and all four rulesets once more
immediately before merge.
It then submits a GraphQL merge with `expectedHeadOid` through the governed
pull-request-only bypass. No status is fabricated, and the frozen state rulesets
must remain unchanged during the merge. The command is idempotent while the
admitted state ref remains current:
if GitHub completed the merge but the client lost the response, a prompt rerun
accepts only the provider-recorded exact head, owner merge actor, merge timestamp,
unchanged admission, state binding, and policy, then reconstructs the same
`owner-merge-gate.json`. Post-merge capture re-fetches the admission comment,
stable collaboration snapshot, all four rulesets, exact live state ref, pull
request, permission, and both commits while the writer remains frozen. Provider
timestamps must bracket the merge, and
the merge must precede manifest expiry. Post-merge `captured_at` is the actual provider
response time at retrieval, not the caller's local clock or the earlier merge
timestamp. Its manifest digest and
policy-amendment digest must match the authorization.

Retain the JSON outputs from `capture-owner-admission` and
`merge-owner-emergency` as `owner-admission.json` and
`owner-merge-gate.json`. Immediately after that exact PR merges, retain
`provider-evidence.json` while the state writer remains frozen. Only then restore
the audited normal writer ruleset with the App and owner bypass actors and verify
the live response. Run the `Main Health` deep cadences through trusted
default-branch repository dispatches after that restoration.

Capture the merged owner decision with the provider admission and raw merge gate,
construct the authorization from the captured evidence, and run `resolve`. The
resolver re-fetches the owner/admin identity and merge proof, requires retained
green protected-main plus both deep results, appends the resolution through CAS,
and validates the complete retained history. No state commit is rewritten.

Publish the resolution from a dedicated state-branch clone. Keep the expected
remote commit before resolving, commit the generated immutable objects and pointer,
then reject any concurrent remote change before the non-force push:

```console
gh api --method PUT repos/Miko997/metriplane/rulesets/21533351 \
  --input state-writer-frozen.json > state-writer-frozen-response.json
git clone --single-branch --branch metriplane-main-health-state \
  https://github.com/Miko997/metriplane.git main-health-state
GITHUB_TOKEN=<token> python tools/stop_the_line.py capture-owner-admission \
  --root main-health-state --repository Miko997/metriplane \
  --pull-request <number> --issue MET-NNN --incident-digest <digest> \
  --expected-head-sha <reviewed-head> \
  --protection-ruleset-id 20613848 \
  --main-health-ruleset-id 21500579 \
  --state-protection-ruleset-id 21487681 \
  --state-writer-ruleset-id 21533351 \
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
gh api --method PUT repos/Miko997/metriplane/rulesets/21533351 \
  --input state-writer-normal.json > state-writer-normal-response.json
gh api repos/Miko997/metriplane/rulesets/21533351 \
  > state-writer-verified-response.json
gh api --method POST repos/Miko997/metriplane/dispatches \
  -f event_type=main-health-nightly
gh api --method POST repos/Miko997/metriplane/dispatches \
  -f event_type=main-health-weekly
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

## Publisher configuration

The Main Health App `metriplane-main-health-publisher` (App and integration ID
`4722589`) is installed only on `Miko997/metriplane`. Its repository
permissions are Actions read, contents write, pull requests read, and commit
statuses write, plus Checks write. Commit-status write is retained only because
GitHub requires it when selecting an App as a required-check source; workflow
tokens do not request it and the workflows contain no commit-status transport.
Webhooks are disabled and workflow write is not granted. The
repository variables `MAIN_HEALTH_APP_ID` and `MAIN_HEALTH_APP_SLUG` identify the
installation. `MAIN_HEALTH_APP_PRIVATE_KEY` is an environment secret in
`main-health-publisher`, and that environment's custom deployment branch policy
contains only `main`.

The main-health admission ruleset pins `Main health admission / required` to the App's
integration ID. State ruleset `21487681` contains deletion and non-fast-forward
restrictions with no bypass actors. Writer ruleset `21533351` contains only the
update restriction with exactly two `always` bypass actors: App integration
`4722589` for normal CAS writes and repository owner user `141511110` for governed
repair. An owner-emergency merge temporarily changes only that bypass inventory to
empty. Admission, merge, and post-merge capture require the frozen configuration;
the normal two-actor configuration is restored and verified before deep cadence or
resolution writes resume.
Changing any App permission, environment branch policy, required-check source, or
state-branch bypass inventory is a security-policy change and requires the same
evidence and review as writer code.
