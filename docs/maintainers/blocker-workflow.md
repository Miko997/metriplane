# Release blocker workflow

The canonical release-blocker registry is `docs/status/blockers.json`. Its closed syntax is
`schemas/metriplane.blockers.v1.schema.json`, and `tools/check_blockers.py` is the semantic and
release-decision authority consumed by Release Gates.

## Release decision

Every unresolved P0, unresolved P1, and unresolved security blocker blocks release. Here,
unresolved means either `open` or `controlled`; controls do not silently convert a blocker into a
closure. An open or controlled non-security P2 is valid and does not block release.

The checker has three stable exit states:

| Exit | Meaning |
| ---: | --- |
| `0` | Registry is valid and no release-blocking record is unresolved. |
| `1` | Registry is valid, but at least one P0, P1, or security record is unresolved. |
| `2` | Schema, transition, evidence, approval, ordering, or input validation failed closed. |

Its `--json` output is deterministic and contains no wall-clock field.

## Classification changes

`initial_severity` and `initial_security` are immutable. Escalation is allowed without a downgrade
record. Lowering severity from P0 to P1/P2 or P1 to P2, or changing `security` from `true` to
`false`, requires exactly one `downgrade` record that matches the immutable and current
classifications.

A downgrade is valid only when all of the following are present and verified:

1. At least one repository-relative reproduction-evidence file with its SHA-256.
2. At least one repository-relative control-evidence file with its SHA-256.
3. A provider-authenticated GitHub or Linear approval from an actor who is neither the change
   author nor the original reporter.
4. An approval `subject_sha256` over the canonical downgrade subject, binding the blocker ID,
   exact transition, author, time, and both evidence arrays.
5. Approval at or after the recorded change.

Evidence paths reject absolute paths, `..`, symlinks in any component, non-files, repository-root
escapes, and hash mismatches.

## Closure

Only `closed` may carry a `closure` record, and `closed` always requires one. Closure requires
resolution evidence, control evidence, and independent provider-authenticated approval bound by
`subject_sha256` to the exact closure subject. The approval must follow the closure time, and a
closure cannot predate the blocker or a governed downgrade.

## Manual boundary

This implementation does not perform or approve a real downgrade or closure. The production
registry contains neither. Synthetic fixtures demonstrate enforcement only and are not approvals.

The current repository/workspace has no eligible provider-authenticated non-author reviewer:
Miko/Miko997 is the author, and the Linear integration account is not an eligible human. Therefore
the live downgrade lane is `NOT_INVOKED_FAIL_CLOSED`. Any future real downgrade remains invalid
until a separately named provider-authenticated non-author independently approves its exact
evidence subject. An implementation-readiness review does not satisfy that approval.

## Maintainer procedure

1. Add or update the blocker in sorted `MPBLK-NNNN` order without changing its immutable initial
   classification.
2. Retain evidence as ordinary repository files and record exact SHA-256 values.
3. For a downgrade or closure, compute the canonical subject only after all action fields and
   evidence records are final.
4. Obtain the separate provider-authenticated non-author approval and record its actor identity,
   provider, timestamp, decision, and exact subject SHA-256.
5. Run the checker and focused policy tests before review.

```bash
uv run python tools/check_blockers.py \
  --registry docs/status/blockers.json \
  --schema schemas/metriplane.blockers.v1.schema.json \
  --repo-root . \
  --json
uv run python -m pytest -q tests/test_blocker_workflow.py
```

## Temporary trace

MP2-014 owns the future canonical requirement-capability-code-test-doc graph. Until then, these
reviewed rows are the finite MP2-006 trace:

| Acceptance | Requirement | Code and data | Tests | CI and docs |
| --- | --- | --- | --- | --- |
| `MP2-006.A01` | P0/P1/security records block release until governed closure. | `schemas/metriplane.blockers.v1.schema.json`, `docs/status/blockers.json`, `tools/check_blockers.py` | `tests/test_blocker_workflow.py` positive, negative, determinism, and security cases | `.github/workflows/release-gates.yml`, this document |
| `MP2-006.A02` | Downgrade requires reproduction/control evidence and independent approval. | `schemas/metriplane.blockers.v1.schema.json`, `tools/check_blockers.py` | `tests/test_blocker_workflow.py` downgrade, compatibility, and report-contract cases | `.github/workflows/release-gates.yml`, this document |
