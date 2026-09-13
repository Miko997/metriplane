<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Task delegation contract

MP2-016 materializes new work orders from an explicit owner-to-executor
delegation. The grantor and delegate are distinct roles. For the v0.5.0
single-maintainer model, Miko is the repository-owner grantor and the exact Codex
goal UUID is the `codex_goal` executor. The delegation grants only its signed
task, issue, repository, Linear project, base commit/tree and authority text.
It also signs the canonical Linear snapshot-claims digest; that digest excludes
only the delegation ID needed to close the record's stable-identity cycle.

Chat text, an unsigned object, an executor signature, a generated fixture or a
provider name written into JSON does not establish production authority. The
grantor signs the canonical provider-attestation envelope containing
`actor_id`, `provider` and the delegation subject digest. The existing
`ProviderAttestationVerifier` verifies that Ed25519 signature against the exact
public key selected by provider, actor and stable key ID.

## Production trust root

The only live task-delegation keyring path is
`docs/status/task-delegation-authority.json`. Its bytes must equal the Git object
at the work order's exact base commit. The record scopes every key to its owner
role, repository and Linear project; fixes its validity interval and fixture or
production class; and carries canonical key and delegation revocation state.
Changing that public trust root is a protected repository change. Private keys
must remain outside the repository, Linear, logs, evidence and chat.

No production authority record exists merely because its schema exists. If the
protected keyring is absent, has no approved owner key, or does not match the
exact base, live materialization is `BLOCKED_NEEDS_OWNER`. Codex must not create,
approve or sign the owner trust root. Fixture mode accepts only explicitly
synthetic inputs and can never supply live authority.

An absent approved keyring at the exact base is a policy blocker with exit `3`,
not malformed input and not permission to bootstrap a key. A caller-supplied
replacement path or changed committed bytes remains invalid input with exit `2`.

## READY evaluation

The materializer returns `READY` only when all of these classes pass together:

- the owner key and signature are trusted, active and valid at evaluation time;
- the stable delegation ID, distinct roles, executor UUID, finite scope,
  issued-at, expiry, exact base commit/tree, snapshot-claims digest and provider
  event/cursor agree;
- the fresh Linear snapshot names the same assignment, active delegation, issue
  state and complete reciprocal dependency edge set;
- dependency evidence, criterion-to-command coverage, path/anchor resolution,
  ownership, resources and all other MP2-016 conditions pass.

Invalid schema, identity, scope, base, signature, key or time input exits `2`.
A valid but expired, revoked, stale or unmet policy condition exits `3`. A
provider outage exits `4`. Output creation is no-overwrite. The validator is
read-only with respect to source and inputs, reconstructs the exact work order,
and rechecks delegation validity at its explicit validation time.

For v0.5.0, an independent-human review field is
`NOT_APPLICABLE_FOR_V0_5`, never `PASS`. Miko's signed grant remains authority
separate from the automated `READY` evidence. Later milestone separation-of-duty
rules remain unchanged.

## Historical evidence

`metriplane.task-assignment.v1` and `metriplane.task-work-order.v1` are retained
only so existing immutable evidence remains interpretable. New materialization
uses the v2 work-order schema and must not rewrite or upgrade historical records
in place. Legacy validation returns retained `BLOCKED_NOT_READY`, never a new
execution authorization.
