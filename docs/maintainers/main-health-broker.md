# Main-health broker

The `metriplane-main-health-publisher` merge App is the only actor permitted by
the dedicated rulesets to update `main` and `metriplane-main-health-state` or
create, update, and delete `release-leases/**`. The separate `Protect release
tags` ruleset targets `refs/tags/v*` and prevents only update and deletion; it
has no bypass actor and deliberately permits creation of new release tags. A
distinct `metriplane-ruleset-witness` App has
repository-settings authority only, so it can read complete ruleset bodies and
bypass actors but cannot write contents, checks, or pull requests. The core
pull-request, deletion, non-fast-forward, and exact required-check rules remain
in separate active rulesets with no bypass actors. Rulesets layer; the merge App
bypasses only the dedicated mutation restrictions.

The broker is an outbound-polling system service. It never checks out or
executes pull-request code. GitHub Actions produces the three exact candidate
terminals and read-only nightly/weekly deep observations. The broker observes
provider attempts, advances the protected state branch with a normal
fast-forward CAS push, read-back-validates its complete immutable history, and
keeps `Main health / required` failed except inside one serialized exact-head
merge transaction.

After a successful state-branch push, the provider ref read may briefly expose
only the exact pre-push commit. The broker performs at most eleven read-only
ref observations over a ten-second convergence window, with one-second waits.
It never repeats the push. Only the pre-push commit is retryable: the exact new
commit advances to the existing fresh-checkout and complete history/content
validation, while any third commit or malformed response fails immediately.
Continued visibility of the pre-push commit fails closed with the expected and
last-observed commit identities, timeout, and read count. Repair-resolution
pushes use the same boundary; ordinary state reads remain one-shot drift
detectors.

## Credential boundary

Revoke every merge-App private key that was ever available to GitHub Actions
and delete `MAIN_HEALTH_APP_PRIVATE_KEY` from the `main-health-publisher`
environment before activation. Create fresh keys for both Apps and encrypt them
separately on the host:

~~~bash
sudo systemd-creds encrypt \
  --name=github-app-private-key.pem \
  /secure/input/metriplane-main-health.pem \
  /etc/credstore.encrypted/metriplane-main-health-app-key
sudo systemd-creds encrypt \
  --name=github-ruleset-witness-private-key.pem \
  /secure/input/metriplane-ruleset-witness.pem \
  /etc/credstore.encrypted/metriplane-ruleset-witness-app-key
~~~

The service reads the decrypted credentials only from
`$CREDENTIALS_DIRECTORY/github-app-private-key.pem` and
`$CREDENTIALS_DIRECTORY/github-ruleset-witness-private-key.pem`. The committed
example uses systemd's stable absolute credential paths. The signer accepts
systemd's exact root-owned `0550` per-unit directory and root-owned `0440`
regular credential files only when they are the direct, resolved children of
`$CREDENTIALS_DIRECTORY`; ordinary credential files remain owner-only and
symlinks are rejected. The merge App grants
exactly Actions read, Checks write, Contents write, Pull requests read, and
Metadata read; it has no Administration, Commit statuses, Workflows, or webhook
permission. The witness App grants exactly Administration write and Metadata
read; it has no Contents, Checks, Pull requests, Actions, Commit statuses,
Workflows, or webhook permission. The Apps and credentials must be distinct.
Both installations must belong to the unsuspended canonical `Miko997` user
account and use selected-repository mode. Each minted installation token is
additionally narrowed with GitHub's `repositories` request field to
`Miko997/metriplane`; the broker accepts it only after the response returns
exactly that repository and a token-authenticated repository read confirms the
canonical owner, full name, repository ID, and literal `main` default branch.
Every governed ruleset read repeats the repository identity/default-branch
check. The three rulesets governing main target explicit `refs/heads/main`;
they do not follow the mutable `~DEFAULT_BRANCH` alias.

The committed broker-config example is deliberately non-runnable:
`main_update_ruleset_id`, `release_lease_ruleset_id`,
`release_tag_ruleset_id`, and `settings_app_id` are `0`. Create the App-only
main-update and release-lease restrictions, the no-bypass release-tag
restriction, and the witness App; capture their positive provider IDs and
place all four IDs in the host's `/etc/metriplane/main-health-broker.json`.
`validate-config` and `run` reject every zero sentinel. The new broker also
rejects a legacy six-rule configuration that omits `release_tag_ruleset_id`.

Run the broker as the repository module, including for manual validation:

~~~bash
python -m tools.main_health_broker validate-config \
  --config /etc/metriplane/main-health-broker.json
~~~

## Host setup

The host requires Python 3.12, Git, OpenSSL, and systemd credential support.
Set `APPROVED_SHA` to the independently approved exact commit. Install that
detached commit in the root-owned `/home/metriplane-main-health-broker`, create
its stdlib-only virtual environment, create the dedicated non-login account,
and keep both immutable code and mutable state on the large `/home` filesystem:

~~~bash
export APPROVED_SHA=<40hex-independently-approved-commit>
sudo useradd --system --home-dir /home/metriplane-health \
  --create-home --shell /usr/sbin/nologin metriplane-health
sudo install -d -o metriplane-health -g metriplane-health -m 0700 \
  /home/metriplane-health/state
sudo git clone --filter=blob:none --no-checkout \
  https://github.com/Miko997/metriplane.git \
  /home/metriplane-main-health-broker
sudo git -C /home/metriplane-main-health-broker fetch --depth=1 origin \
  "$APPROVED_SHA"
sudo git -C /home/metriplane-main-health-broker checkout --detach "$APPROVED_SHA"
test "$(sudo git -C /home/metriplane-main-health-broker rev-parse HEAD)" = \
  "$APPROVED_SHA"
sudo python3.12 -m venv /home/metriplane-main-health-broker/.venv
sudo install -d -o root -g metriplane-health -m 0750 /etc/metriplane
sudo install -o root -g metriplane-health -m 0640 \
  /home/metriplane-main-health-broker/docs/status/examples/main-health-broker-config.json \
  /etc/metriplane/main-health-broker.json
sudoedit /etc/metriplane/main-health-broker.json
sudo sh -c 'cd /home/metriplane-main-health-broker && \
  exec .venv/bin/python -m tools.main_health_broker validate-config \
  --config /etc/metriplane/main-health-broker.json'
sudo install -D -m 0644 \
  /home/metriplane-main-health-broker/scripts/systemd/metriplane-main-health-broker.service \
  /etc/systemd/system/metriplane-main-health-broker.service
sudo systemctl daemon-reload
sudo systemctl disable --now metriplane-main-health-broker.service
if sudo systemctl is-enabled --quiet metriplane-main-health-broker.service; then
  exit 1
fi
if sudo systemctl is-active --quiet metriplane-main-health-broker.service; then
  exit 1
fi
~~~

The host is now staged, but the broker must remain disabled and stopped. With
the staged witness credential, apply and read back the exact governed ruleset
bodies. Confirm that every newly staged mutation rule is exact except for
disabled enforcement, activate it with the complete exact body, and then
validate the complete active inventory plus all seven governed ruleset details
through the witness App. Only after that validation succeeds, enable and start
the broker:

~~~bash
sudo systemctl enable --now metriplane-main-health-broker.service
sudo systemctl is-active metriplane-main-health-broker.service
sudo systemctl show metriplane-main-health-broker.service \
  --property=Type,ActiveState,SubState
sudo journalctl -u metriplane-main-health-broker.service \
  --grep='ready after one successful full cycle' --lines=1
~~~

Replace only the `main_update_ruleset_id`, `release_lease_ruleset_id`,
`release_tag_ruleset_id`, and `settings_app_id` zero sentinels in the installed
host configuration before `validate-config`; all other committed identities
and boundaries remain exact.

`Restrict release lease writers` is an active branch ruleset with include
`refs/heads/release-leases/**`, the broker Integration ID `4722589` as its sole
`always` bypass actor, and exactly `creation`, `update`, and `deletion` rules.
`Protect release tags` is an active tag ruleset with include `refs/tags/v*`, an
empty exclude list, no bypass actors, and exactly `update` and `deletion` rules.
It has no creation rule so a new release identity can be created once, while an
existing release tag cannot be moved or removed.

Migrate an already-running six-rule broker only during a deliberate broker
freeze. Merge the independently approved seven-rule implementation through the
healthy six-rule broker while `Protect release tags` remains absent or
disabled. Preserve the old executable and configuration, stop the service, and
require it to be inactive. Install the exact protected-main broker commit,
create or read back `Protect release tags` in `disabled` mode, and add only its
positive provider ID as `release_tag_ruleset_id` in the live configuration.
After the new broker's `validate-config` passes, activate the tag ruleset, read
the complete seven-rule inventory twice, and start the new broker. Its first
cycle accepts only the exact seven-rule inventory: six active rules, an
inactive or missing tag rule, or any eighth active rule fails closed. If the
new broker cannot complete a successful cycle after activation, stop it and
disable `Protect release tags` before restoring or restarting the preserved
six-rule broker.

One immutable owner-repair request in retained protected-state history predates
both release rulesets. History validation accepts its former five-ruleset
digest inventory only when the complete canonical request has digest
`d6ea4e6491127bb1eba199e677d4934144140e70eafe75e3321afb4fccb7c396`.
That compatibility is limited to retained-history validation; live capture,
resolution, and every new owner request require the exact seven-ruleset
inventory.

The systemd unit is `Type=notify`. It becomes active only after one complete
successful broker cycle, including authentication, orphan reconciliation,
failed-check establishment, exact hosted-ruleset validation, and protected-state
validation. A first-cycle failure never reports readiness. A later broker
failure exits the process so `Restart=on-failure` and service monitoring observe
it; the daemon does not catch and hide a persistent failure.

This is a system service, so user linger is neither required nor accepted as
availability evidence. The host must have synchronized time, monitored disk
space, service-failure alerting, and a tested restore procedure. Host downtime
fails closed by leaving the App check failed and `main` inaccessible to human
updates; it is not a high-availability claim. The committed one-minute poll
interval bounds provider load, and installation tokens are reused until their
final eleven minutes rather than minted on every cycle.

## Admission

A requester submits a `COMMENTED` pull-request review containing exactly:

~~~text
metriplane-merge-request:v1
{"base_ref":"main","base_sha":"<40hex>","expires_at":"<RFC3339>","head_sha":"<40hex>","health_generation":1,"nonce":"<32hex>","pull_request":1,"repository":"Miko997/metriplane","requester_id":1,"schema_version":1}
~~~

An independent non-author with repository `write` or `admin` permission submits
an `APPROVED` review after that request:

~~~text
metriplane-merge-approval:v1 <sha256-of-canonical-request>
~~~

The approval body may end at the digest or include one terminal newline.

For a personal repository with no other eligible `write` or `admin`
collaborator and no pending invitation carrying that authority, the repository
owner may instead submit this exact `COMMENTED` review on an owner-authored PR:

~~~text
metriplane-owner-merge-request:v1
{"authorization_mode":"single-maintainer-owner-attestation","base_ref":"main","base_sha":"<40hex>","changed_paths_digest":"<64hex>","collaboration_digest":"<64hex>","expires_at":"<RFC3339>","head_sha":"<40hex>","health_generation":1,"nonce":"<32hex>","pull_request":1,"repository":"Miko997/metriplane","requester_id":141511110,"ruleset_digests":{"20613848":"<64hex>","21487681":"<64hex>","21500579":"<64hex>","21533351":"<64hex>","21633569":"<64hex>","22071973":"<64hex>","22170798":"<64hex>"},"schema_version":1,"state_commit":"<40hex>"}
~~~

This request is the explicit owner decision and has the same maximum ten-minute
provider lease. The witness App reads the complete collaborator and pending
invitation inventories twice and requires their canonical digest, every changed
path, all seven exact hosted-ruleset digests, and the protected state commit to
match the request at every admission pass. Adding an eligible collaborator or
invitation disables the single-maintainer path immediately. It does not create
a human push, settings, required-check, or merge bypass.

Provider reviews that carry an owner-request marker but are anchored to a prior
head remain immutable audit history and cannot authorize the current head. The
broker ignores those prior-head requests during current-head selection and
retained post-merge evidence reconstruction, while a malformed review anchor or
any marker review anchored to the current head must still pass the complete
request and live-context validation.

The broker accepts only the reviewer's latest decisive provider review, so a
later changes-requested, dismissal, or differently bound approval revokes an
earlier approval. It re-reads the pull request, every commit actor, reviews,
exact Actions checks, the complete inventory of all active repository rulesets
and all seven governed ruleset bodies, current `main`, provider clock, and the
protected state branch immediately before admission. Inventory summaries and
detail bodies must agree on ID, name, enforcement, target, source, and source
type. A protected-main result identity binds the exact CI, Documentation, and
CodeQL run attempts together. Provider update time determines the latest attempt
across workflow-run IDs. Distinct identities tied at the latest provider time,
or any repeated attempt identity, fail closed. A cached green state never skips
a new companion rerun and an already retained aggregate never creates a
freshness-only state commit. The six numeric protected-main records from the
pre-App history predate run-attempt evidence and are allowlisted by exact run ID
and canonical result digest. The broker preserves them as opaque history rather
than inferring an attempt; new numeric records are rejected and legacy successes
cannot satisfy current aggregate or repair evidence. Before normal admission,
the broker observes that
aggregate twice,
requires every governed deep-health attempt in the complete provider inventory
to be retained, observes every available latest current-main nightly or weekly
run and exact job twice, and rejects any change between observations. It then
repeats the pull request, approval, state, main, core-check, and ruleset reads.
Under one singleton lock,
it records the request as in-flight, mutates one recorded App check-run ID to
literal `success`, and waits only while GitHub is still computing whether the
exact head can merge. A provider `blocked` state with `mergeable: true` is the
expected steady state under the App-only main-update restriction, not a reason
to wait forever; the broker accepts it only after repeating the exact core-check,
ruleset, review, state, main, and lease validation. It then calls the synchronous
merge endpoint with the exact head SHA, leaving the non-bypassed core and
admission rulesets as the provider's final enforcement boundary. It never retries
an ambiguous merge response; it reconciles the pull request, ref, two parents,
and exact tree, then records either `merged` or terminal `uncertain`. An
unproved interrupted transaction also closes the App check. The consumed
request digest remains in the provider-owned check external ID, so a restored
local spool reconstructs the no-retry decision from GitHub before admission.
Protected-state Git smart HTTP uses the fixed `x-access-token` GitHub App
username through a process-scoped Basic authorization header. The installation
token is never embedded in the remote URL, and terminal prompts stay disabled.
Pull requests above GitHub's complete 250-commit pull-inventory bound are not
admitted; for every smaller pull request, the provider-reported count, unique
commit SHAs, and final head SHA must exactly match the returned inventory. Every
commit must also have complete provider-resolved `author` and `committer`
objects with positive integer IDs and nonempty logins. Null, partial, or
malformed commit identities fail closed before reviewer independence is
evaluated.

The witness App performs a final exact ruleset read after orphan and check
quarantine and after all other admission validation, immediately before the
merge App can publish success. Any settings drift in that interval fails closed
without opening the merge gate.

Capture activation evidence with the same independently approved checkout:

~~~bash
python -m tools.capture_repository_protection \
  --repository Miko997/metriplane \
  --captured-at 2026-08-26T00:00:00Z \
  --output-dir /secure/evidence/repository-protection
~~~

`repository-protection-activation-evidence.json` retains the unnormalized
repository response, both stable ruleset summary inventories, both exact detail
passes for every ruleset, the merge-queue response, and each request's status,
safe response headers, and GitHub request ID. The raw REST repository identity
and GraphQL `nameWithOwner` must bind the requested repository; malformed
GraphQL data or any GraphQL `errors` field fails closed. Missing request IDs,
summary/detail drift, detail-pass drift, or inventory drift also makes capture
fail closed. Authorization, cookie, and related headers are redacted before
retention.

Repository administrators remain a trusted settings boundary because GitHub
does not offer an atomic ruleset-read-and-merge transaction. Any omitted
`bypass_actors`, settings drift, future-dated state, unreconciled provider
attempt, clock skew, duplicate identity, fork, missing approval,
cancelled/skipped check, process restart, or provider ambiguity fails closed.

## Production publication lease

The same singleton loop observes only active `workflow_dispatch` runs of the
literal `.github/workflows/publish-pypi.yml`. Before creating a lease, it binds
the provider workflow ID, path, name, repository, `main` head, run ID and
attempt, and both the dispatching and triggering actors to the canonical owner.
It requires successful production-request, dispatch-time blocker-validation,
and artifact-verification jobs, with every non-publication job's step inventory
held to the ordinary strict provider vocabulary. The environment-approved
publication job must be in progress with its exact lease-wait step in progress.
Only at that pre-lease boundary may any later raw publication-job step—fenced
blocker, reassertion, rehash, upload, or generated cleanup—be represented as
either `queued` or `pending`, always with a null conclusion. Any `pending` step
outside that boundary, any started or completed later step, or any other status
or conclusion fails closed.

The workflow, `tools/release_artifacts.py`, `tools/check_blockers.py`, and the
blocker schema at the release commit must be byte-identical Git blobs to the
independently approved broker checkout. The broker then revalidates current
`main` and the exact seven hosted rulesets immediately before reserving the
durable transaction. Any governed authority change therefore requires a new
broker review and deployment before production publication can proceed.

SQLite reserves one fence before the first provider write. A unique durable
slot prevents a second run from entering publication even across processes or
restarts. The broker creates
`refs/heads/release-leases/pypi-<run-id>-<run-attempt>` first and only then
creates `Release serialization / required` in progress with external ID
`metriplane-publish-lease.v1:<run-id>:<run-attempt>:<commit>`. Its canonical
JSON output binds the repository, ref, run, attempt, commit, schema, and state.
The lease expires two hours after the workflow enters its wait step.

The durable fence suppresses every later broker-mediated `main` merge. The
broker accepts normal progression only through fenced blocker validation,
lease reassertion, upload, production verification, and the in-progress
reconciliation observer. It repeats workflow, source-authority, current-main,
and hosted-ruleset proof before release. It records `releasing`, deletes and
read-back-proves absence of the exact ref, and only then completes the same
check ID with `success`. Those mutation boundaries make both crash points
restart-safe.

A failed job, identity mutation, main drift, missing provider object, or expiry
completes the exact acknowledgment with `failure` but retains any lease ref and
the durable broker fence. Provider ambiguity leaves the current state in place
and terminates the broker cycle. Neither condition is auto-deleted: it is a
release incident requiring independent exact-byte and provider reconciliation
during a controlled settings freeze. A reservation that is proved to have made
no provider mutation may be abandoned automatically.

## Red-state repair

Normal admission stops while the protected state is red. A repair requester
submits a distinct `COMMENTED` review bound to the current incident and state
generation:

~~~text
metriplane-repair-request:v1
{"base_ref":"main","base_sha":"<40hex>","expires_at":"<RFC3339>","head_sha":"<40hex>","incident_digest":"<64hex>","issue":"MET-77","nonce":"<32hex>","pull_request":1,"repository":"Miko997/metriplane","requester_id":1,"schema_version":1,"state_generation":1}
~~~

The request expires no more than ten minutes after its provider submission
time. An independent non-author with repository `write` or `admin` permission
then submits this exact `APPROVED` review at the repair head:

~~~text
Main-health repair authorization: MET-77
Incident: <64hex-incident-digest>
~~~

The latest decisive review for every participating actor governs. A
changes-requested review, a fork, a stale generation, an incident mismatch, or
an approval from the author, requester, or any commit actor fails closed. The
broker uses the same serialized, single-use exact-head merge transaction as
normal admission.

If no eligible independent collaborator or pending invitation exists, the
owner-authored repair PR may carry
`docs/status/main-health-owner-emergency.json` and exactly one matching two-line
marker in its body. The manifest binds the base, incident, issue, PR, complete
changed-path inventory, collaborator digest, failing obligations, expiry, and
incident-only policy amendment. After qualification, the owner submits:

~~~text
metriplane-owner-repair-request:v1
{"authorization_mode":"single-maintainer-owner-emergency","base_ref":"main","base_sha":"<40hex>","changed_paths_digest":"<64hex>","collaboration_digest":"<64hex>","expires_at":"<RFC3339>","head_sha":"<40hex>","incident_digest":"<64hex>","issue":"MET-77","manifest_digest":"<64hex>","nonce":"<32hex>","policy_amendment_digest":"<64hex>","pull_request":1,"repository":"Miko997/metriplane","requester_id":141511110,"ruleset_digests":{"20613848":"<64hex>","21487681":"<64hex>","21500579":"<64hex>","21533351":"<64hex>","21633569":"<64hex>","22071973":"<64hex>","22170798":"<64hex>"},"schema_version":1,"state_commit":"<40hex>","state_generation":1}
~~~

The broker validates that request and manifest against live provider state on
all three admission passes. The successful App check retains the canonical
request digest in its external ID. After merge, the broker requires that exact
check, App merge actor, merge parents and tree, unchanged single-maintainer and
ruleset digests, and the manifest before constructing resolution evidence.

Merging the repair does not clear red state. The latest retained observation
for each cadence must pass; an older success cannot mask a newer failure. The
read-only workflows must record passing protected-main, nightly, and weekly
results for the exact merge SHA. An authorized operator can request both deep
observations without giving either workflow the App credential:

~~~bash
gh api --method POST repos/Miko997/metriplane/dispatches \
  -f event_type=main-health-nightly
gh api --method POST repos/Miko997/metriplane/dispatches \
  -f event_type=main-health-weekly
~~~

The broker then re-fetches the closed pull request, retained request and any
approval reviews, commits, merge parents and tree, current main, collaborator
inventory, rulesets, exact App check, and provider time. It captures the
provider authorization evidence and appends the governed repair resolution to
the protected state branch with a normal fast-forward CAS push. There is no
direct owner-emergency CLI, human bypass, or local-spool recovery path.
