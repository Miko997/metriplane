# Persistent main health

MP2-004 keeps one durable stop-the-line state for protected main. The
authoritative backend is the protected
`metriplane-main-health-state` branch. Local SQLite is only a crash-safe cache
and request spool; it cannot authorize green health, skip provider attempts,
or authorize a merge.

The historical activation record remains immutable. Its original writer field
describes the activation mechanism used for those retained generations. The
App-broker policy supersedes the live writer without rewriting that history.
Every new transition remains a normal single-parent fast-forward that adds one
generation, exact result, retention record, and hash-linked history record.
The broker fetches the complete branch, validates every generation, applies
one expected-generation transition, pushes without force, re-reads the
provider ref, and validates the complete branch again.

## Cadences

Protected-main health observes the exact completed CI attempt and the exact
Documentation and CodeQL attempts for the same main SHA. Missing,
in-progress, cancelled, skipped, stale, duplicate, wrong-workflow, wrong-job,
or wrong-SHA evidence fails closed. A stable provider selection is fetched
again before it is retained. One canonical result identity binds all three run
attempts, so a fresh cached green state cannot hide a later Documentation or
CodeQL rerun.

The Main Health Deep workflow has read-only repository permissions and no App
credential. It checks out the exact provider `github.sha` and produces pinned
nightly and weekly full-suite observations. On every cycle the broker rebuilds
the authoritative set of recorded run-attempt identities from the protected
history. SQLite mirrors only a diagnostic high-water mark. The broker fetches
missing prior attempts after a rerun, blocks merges while a current-main deep
run is active, and appends every unrecorded governed attempt in provider update
order. An unreconciled deep run for another SHA is an operator-visible stop
rather than a silently skipped result.

The one-use PR 86 Actions compatibility terminal is retired. Hosted rulesets now
bind `Main health / required` exclusively to GitHub App integration 4722589, so
the deep workflow has no pull-request trigger, required-check job, checks
permission, or merge authority. Its only triggers are the governed nightly and
weekly schedules and matching repository dispatches. Deep observations run one
at a time with the bounded maximum queue, so an overlapping schedule or dispatch
does not cancel an already pending observation. The historical transition
validator remains covered as retained evidence, but no active workflow invokes
it and the obsolete `MET77_APPROVED_HEAD_SHA` variable must remain absent.

A failed global cadence turns the state red. Later successful observations do
not clear red state. Normal pull requests stop; only a provider review request
bound to the current incident, generation, base, and head can admit a repair.
Resolution normally requires an exact independent non-author `write` or `admin`
approval. A personal repository with no eligible independent collaborator or
pending write-authority invitation may instead use the incident-only
single-maintainer owner-emergency request described in the broker runbook. Both
paths require latest passing protected-main, nightly, and weekly evidence for
the merged repair SHA. An older success cannot mask a later failed attempt. The
broker reconstructs the provider evidence and appends the resolution to the
protected state branch. The former direct owner-emergency CLI and human ruleset
bypass remain retired; only the App-broker transaction can consume an active
manifest.

## Admission

The repository has exactly seven active governed rulesets:

1. Core protection blocks deletion and non-fast-forward updates, requires pull
   requests, strict up-to-date heads, and the three exact Actions terminals.
   It has no bypass.
2. Main-health admission requires Main health / required from GitHub App
   integration 4722589. It has no bypass.
3. A separate update restriction allows only integration 4722589 to update
   main.
4. State protection blocks deletion and non-fast-forward updates to the state
   branch. It has no bypass.
5. A separate state update restriction allows only integration 4722589 to
   update that branch.
6. A release-lease restriction allows only integration 4722589 to create,
   update, or delete `refs/heads/release-leases/**`.
7. Release-tag immutability blocks update and deletion of `refs/tags/v*` with
   no bypass actor. It deliberately does not restrict creation.

All three main rulesets target literal `refs/heads/main`; the runtime also
revalidates that the canonical repository's default branch is still `main` at
authentication and every hosted-ruleset boundary.

The App bypasses only the two branch-update restrictions and the release-lease
restriction. It cannot bypass the core, admission, state-protection, or
release-tag rules because rulesets aggregate.

The merge App has no Administration permission. A separate ruleset-witness App
has exactly Administration write and Metadata read so the broker can observe
complete bypass actors; it has no repository-content, check, pull-request, or
Actions authority. Both App installations and every token are restricted to
the one canonical repository.

At startup and every polling boundary, the broker creates or mutates one
provider-recorded App check-run ID per open pull-request head to failure.
Duplicate App checks are failed and renamed; exactly one canonical ID remains.
Humans cannot exploit a stale success because humans cannot update main.

The normal merge request and approval are provider pull-request reviews. They bind
repository, pull request, exact head, exact base, state generation, requester
identity, nonce, and a maximum ten-minute expiry. The approving provider actor
must differ from the pull-request author, requester, and every resolved commit
author or committer and must have repository `write` or `admin` permission.
Only that actor's latest decisive review counts; a later
changes-requested, dismissal, or approval for another request invalidates the
earlier approval.

Under one singleton host lock, the broker re-reads reviews, commits, all exact
checks, every active repository ruleset, all seven governed ruleset bodies
including complete bypass actors, provider time, current main, and the state
branch. Summaries and bodies must agree on identity, source, target, and
enforcement. The witness App performs one final ruleset read after orphan and
check quarantine. Normal admission also re-observes the complete protected-main
aggregate and every available latest current-main nightly or weekly attempt twice, binds them
to retained protected-state identities, and rejects active, failed, missing, or
changing evidence. It then repeats admission, state, main, core-check, and
ruleset validation immediately before success can be published. The broker
then changes the recorded merge-App check ID to literal success, accepts either
provider `clean` or the expected `mergeable: true`/`blocked` state produced by
the App-only update restriction, re-seals the complete admission context, and
calls the synchronous merge endpoint with the exact head SHA. A definite
rejection closes the check. An ambiguous response is never retried: the broker
reconciles the pull request, main ref, merge parents, and exact tree and
otherwise closes the check and records the request as terminal uncertain.
Provider timeouts, rate limits, malformed success responses, and server errors
are ambiguous, not definite rejections.

## Trust and availability

Repository administrators are an explicit trusted-settings boundary. GitHub
does not provide an atomic ruleset-read-and-merge transaction, so an
administrator could change settings after the final read. Actor exclusivity is
claimed only while hosted settings remain unchanged and the host-only App
credential remains uncompromised.

One Ubuntu host is fail-closed, not highly available. The broker is a hardened
system service under a dedicated non-login account. Its mutable state is under
/home/metriplane-health/state on the large home filesystem. The App key is a
systemd encrypted credential and is absent from GitHub Actions; the independent
ruleset-witness key is encrypted separately. The service reports systemd
readiness only after a complete successful first cycle and exits on any later
broker failure so restart policy and monitoring can observe it. Provider clock
skew, service downtime, host restart, disk failure, and restore are monitored
and tested; downtime leaves main locked.

Deployment, credential rotation, request syntax, and the exact unit contract
are in docs/maintainers/main-health-broker.md.

## Activation proof

Do not change live settings or claim PASS from committed examples. Activation
requires an independently approved exact broker commit and a disposable
same-plan proof that retains provider request IDs and raw responses:

- human push and human merge are rejected;
- direct App push is rejected by non-bypassed protection;
- exact-head App merge succeeds only with four exact terminals;
- wrong SHA, future-dated state, unreconciled provider attempt, offline service,
  cancelled/skipped/wrong-source checks, fork PR, duplicate credential,
  concurrent request, and settings drift fail closed;
- the merge commit has base and admitted head as its two parents, its tree
  equals the admitted head tree, and current main equals that merge commit;
- the state branch remains an externally read-back-verified append-only chain.

`tools/capture_repository_protection.py` writes
`repository-protection-activation-evidence.json` with the unnormalized
repository, initial and verification summary inventories, both exact ruleset
detail passes, merge-queue response, safe response headers, and one provider
request ID per request. It rejects mismatched REST/GraphQL repository identity,
malformed GraphQL data or errors, missing request IDs, summary/detail
disagreement, detail-pass drift, or inventory changes.

Only after that proof and credential rotation may the repository-protection
example change activation_state from planned to active.
