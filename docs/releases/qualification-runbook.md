<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Cumulative release qualification

MP2-007 defines one release state machine for every milestone from `v0.4`
through `v1.0`. A release attempt is an immutable sequence. It cannot skip a
stage, reopen a failed stage, replace retained output, or treat a tag as
authority.

## Ordered state machine

Every attempt runs these stages in order:

1. resolve signed role assignments and provider-observed task state;
2. stage the candidate independently of tags;
3. observe every release target and retain any burn;
4. resolve the actual last-known-good predecessor and closed decision;
5. freeze the source and build the candidate once through
   `tools/release_artifacts.py`;
6. terminalize the complete environment, scenario, and obligation matrix;
7. retain and read-verify evidence in two independent stores and the attempt
   index;
8. obtain conflict-free provider-authenticated approval from the assigned
   non-author reviewer;
9. bind a promotion plan to the candidate, approval, controls, target state,
   index checkpoint, actions, and expiry;
10. acquire the fenced compare-and-swap promotion lock;
11. observe publication and reconcile exact bytes for every target;
12. retain both-store receipts, append the success chain, advance last known
    good, and retain its pointer envelope and index entry;
13. close the attempt. A later product contradiction uses the signed
    invalidation path and never rewrites the successful record.

The exact milestone and test inventories are in
`docs/status/release-targets.json` and
`docs/status/release-test-obligations.json`. The `v0.4` predecessor is the
observed `v0.3.0` genesis. Later milestones require the preceding closed
decision and last-known-good transition.

An annotated version-tag push starts only prepublication qualification and the
TestPyPI artifact path. Production publication is a separate, approved
`Publish Python distributions` dispatch bound to the retained qualification.
After its `Verify production artifact identity and installation` job succeeds,
postpublication reconciliation is dispatched with that production run ID and
the final two-store authority bundle. A tag event cannot enter
`post-publication`, and reconciliation rejects a production run that is not the
completed successful publication workflow or whose retained verification record
does not name the exact tagged candidate and version being reconciled.

## Local qualification

Use the repository-pinned `uv==0.12.0` and disable external pytest plugins:

```console
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --frozen python -m pytest -q \
  tests/release/test_local_fake_release.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --frozen python -m pytest -q \
  tests/test_release_contracts.py tests/test_release_workflow.py
uv run --frozen python tools/check_release_readiness.py \
  --repository . --mode fixture
```

The fake-release suite proves deterministic state transitions, mutation
failures, target burns, exact-byte conflicts, concurrent writers, expired and
dead-owner lock recovery, kill-after-CAS reconstruction, and output
no-overwrite. Synthetic records are test inputs only.

## Live stop gates

`--mode live` fails closed until all of these external facts exist and read
back exactly:

- a digest-bound executor delegation and task-state observation from the live
  providers;
- an approval from the assigned non-author reviewer, distinct from the author;
- two independent durable evidence stores and a fenced CAS attempt-index,
  lock, and last-known-good backend;
- every populated target, environment, scenario, obligation, receipt,
  candidate, predecessor, platform, and open-BOM prerequisite required by
  MP2-018;
- hosted protection recapture and a retained real merge-path proof.

No fixture identity, repository-owner check, tag, environment approval, or
locally written signature can satisfy those predicates. Missing authority
leaves the attempt `BLOCKED_NOT_READY` and cannot reach a publication job.

## Hosted trust inputs

Live validation reads its trust root independently of the candidate and the
transported authority bundle. Configure these repository values before a live
attempt:

- `RELEASE_PROVIDER_ATTESTATION_KEYRING_B64`: strict base64 of canonical JSON
  with schema version `metriplane.provider-attestation-keyring.v1` and an
  ordered, unique `keys` list. Each row contains only `actor_id`, `provider`,
  and a 32-byte Ed25519 `public_key_hex` value. Never place a private signing
  key in this value, the repository, or a workflow secret.
  Verification uses Python cryptography when present and otherwise fails over
  to the GitHub runner's Node.js built-in Ed25519 implementation.
- `RELEASE_PROVIDER_ATTESTATION_KEYRING_DIGEST`: SHA-256 of that exact canonical
  keyring object. The same digest is required as an explicit qualification and
  production-dispatch input. Key rotation between qualification and production
  therefore fails closed.
- `RELEASE_AUTHORITY_POLICY_DIGEST`: SHA-256 of canonical JSON containing only
  `provider_attestation_keyring_digest` and schema version
  `metriplane.release-authority-policy.v1`. Live role assignments and approval
  decisions carry both identities and validators compare them to the supplied
  protected inputs.
- `RELEASE_AUTHORITY_STORE_A_URL` and `RELEASE_AUTHORITY_STORE_B_URL`: distinct
  HTTPS read-back endpoints for the same immutable authority bundle.
- `RELEASE_AUTHORITY_RUN_ID`, `RELEASE_AUTHORITY_BUNDLE_SHA256`, and
  `RELEASE_EVIDENCE_MANIFEST_SHA256`: the exact identities supplied by the
  external authority run.

Configure `RELEASE_AUTHORITY_STORE_A_TOKEN` and
`RELEASE_AUTHORITY_STORE_B_TOKEN` as separate repository secrets. The release
and publication workflows decode only the public keyring, compare the two
store bundles byte for byte, and pass both observed readbacks into every deep
live validator. `provider-attestation-v1` signatures are 64-byte Ed25519
signatures encoded as 128 lowercase hexadecimal characters over the canonical
provider, actor, and subject-digest message.

## Failure and recovery

A partial target, digest mismatch, mutable observation, unknown terminal,
store outage, or stale writer is retained as a blocker or burn. A retry uses a
new invocation and sequence. Kill-after-CAS recovery may reconstruct only the
exact committed operation named by the immutable recovery envelope. Conflicting
successors fail; successful, failed, cancelled, skipped, blocked, burn, and
recovery records are never overwritten.
