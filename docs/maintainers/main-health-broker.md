# Main-health broker

The `metriplane-main-health-publisher` GitHub App is the only actor permitted by
the dedicated update rulesets to update `main` and
`metriplane-main-health-state`. The core pull-request, deletion,
non-fast-forward, and exact required-check rules remain in separate active
rulesets with no bypass actors. Rulesets layer; the App bypasses only each
dedicated `update` restriction.

The broker is an outbound-polling system service. It never checks out or
executes pull-request code. GitHub Actions produces the three exact candidate
terminals and read-only nightly/weekly deep observations. The broker observes
provider attempts, advances the protected state branch with a normal
fast-forward CAS push, read-back-validates its complete immutable history, and
keeps `Main health / required` failed except inside one serialized exact-head
merge transaction.

## Credential boundary

Revoke every App private key that was ever available to GitHub Actions and
delete `MAIN_HEALTH_APP_PRIVATE_KEY` from the `main-health-publisher`
environment before activation. Create one replacement key and encrypt it on
the host:

~~~bash
sudo systemd-creds encrypt \
  --name=github-app-private-key.pem \
  /secure/input/metriplane-main-health.pem \
  /etc/credstore.encrypted/metriplane-main-health-app-key
~~~

The service reads the decrypted credential only from
`$CREDENTIALS_DIRECTORY/github-app-private-key.pem`. The committed example
uses systemd's stable absolute credential path. The App installation grants
only Actions read, Checks write, Contents write, Pull requests read, and
Metadata read. It has no Administration, Commit statuses, Workflows, or webhook
permission. The installation must belong to the unsuspended canonical
`Miko997` user account, use selected-repository mode, and expose exactly those
permissions. Each minted installation token is additionally narrowed with
GitHub's `repositories` request field to `Miko997/metriplane`; the broker caches
it only after the token response returns exactly that repository and a
token-authenticated repository read confirms the canonical owner, full name,
and repository ID.

The committed broker-config example is deliberately non-runnable:
`main_update_ruleset_id` is `0`. Create the App-only main update restriction,
capture its positive provider ruleset ID, and place that ID in the host's
`/etc/metriplane/main-health-broker.json`. `validate-config` and `run` reject
the zero sentinel.

Run the broker as the repository module, including for manual validation:

~~~bash
python -m tools.main_health_broker validate-config \
  --config /etc/metriplane/main-health-broker.json
~~~

## Host setup

The host requires Python 3.12, Git, OpenSSL, and systemd credential support.
Set `APPROVED_SHA` to the independently approved exact commit. Install that
detached commit under `/opt/metriplane-main-health-broker`, create its stdlib-only
virtual environment, create the dedicated non-login account, and keep mutable
data on the large `/home` filesystem:

~~~bash
export APPROVED_SHA=<40hex-independently-approved-commit>
sudo useradd --system --home-dir /home/metriplane-health \
  --create-home --shell /usr/sbin/nologin metriplane-health
sudo install -d -o metriplane-health -g metriplane-health -m 0700 \
  /home/metriplane-health/state
sudo git clone --filter=blob:none --no-checkout \
  https://github.com/Miko997/metriplane.git \
  /opt/metriplane-main-health-broker
sudo git -C /opt/metriplane-main-health-broker fetch --depth=1 origin \
  "$APPROVED_SHA"
sudo git -C /opt/metriplane-main-health-broker checkout --detach "$APPROVED_SHA"
test "$(sudo git -C /opt/metriplane-main-health-broker rev-parse HEAD)" = \
  "$APPROVED_SHA"
sudo python3.12 -m venv /opt/metriplane-main-health-broker/.venv
sudo install -d -o root -g metriplane-health -m 0750 /etc/metriplane
sudo install -o root -g metriplane-health -m 0640 \
  /opt/metriplane-main-health-broker/docs/status/examples/main-health-broker-config.json \
  /etc/metriplane/main-health-broker.json
sudoedit /etc/metriplane/main-health-broker.json
sudo sh -c 'cd /opt/metriplane-main-health-broker && \
  exec .venv/bin/python -m tools.main_health_broker validate-config \
  --config /etc/metriplane/main-health-broker.json'
sudo install -D -m 0644 \
  /opt/metriplane-main-health-broker/scripts/systemd/metriplane-main-health-broker.service \
  /etc/systemd/system/metriplane-main-health-broker.service
sudo systemctl daemon-reload
sudo systemctl enable --now metriplane-main-health-broker.service
~~~

Replace only the `main_update_ruleset_id` zero sentinel in the installed host
configuration before `validate-config`; all other committed identities and
boundaries remain exact.

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

The broker accepts only the reviewer's latest decisive provider review, so a
later changes-requested, dismissal, or differently bound approval revokes an
earlier approval. It re-reads the pull request, every commit actor, reviews, exact
Actions checks, the complete active branch-ruleset inventory and all five
governed ruleset bodies, current `main`, provider clock, and the protected state
branch immediately before admission. Under one singleton lock,
it records the request as in-flight, mutates one recorded App check-run ID to
literal `success`, and immediately calls the synchronous merge endpoint with
the exact head SHA. It never retries
an ambiguous merge response; it reconciles the pull request, ref, two parents,
and exact tree, then records either `merged` or terminal `uncertain`. An
unproved interrupted transaction also closes the App check. The consumed
request digest remains in the provider-owned check external ID, so a restored
local spool reconstructs the no-retry decision from GitHub before admission.
Pull requests above GitHub's complete 250-commit pull-inventory bound are not
admitted; for every smaller pull request, the provider-reported count, unique
commit SHAs, and final head SHA must exactly match the returned inventory. Every
commit must also have complete provider-resolved `author` and `committer`
objects with positive integer IDs and nonempty logins. Null, partial, or
malformed commit identities fail closed before reviewer independence is
evaluated.

Repository administrators remain a trusted settings boundary because GitHub
does not offer an atomic ruleset-read-and-merge transaction. Any omitted
`bypass_actors`, settings drift, stale state, clock skew, duplicate identity,
fork, missing approval, cancelled/skipped check, process restart, or provider
ambiguity fails closed.

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

The broker then re-fetches the closed pull request, retained request and
approval reviews, commits, merge parents and tree, current main, collaborator
permission, and provider time. It captures the provider approval evidence and
appends the governed repair resolution to the protected state branch with a
normal fast-forward CAS push. There is no owner-emergency or local-spool
recovery path.
