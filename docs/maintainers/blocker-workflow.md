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
3. A registry locator naming the exact GitHub repository and pull request, plus a
   `subject_sha256` over the canonical downgrade subject. The subject binds the blocker ID, exact
   reporter, transition, action actor, action time, and both evidence arrays.
4. A live GitHub review fetched by the checker with `GITHUB_TOKEN`. The review must be the
   reviewer's latest state, be `APPROVED` on the current pull-request head, follow the recorded
   action, and have the exact marker documented below. Any current requested-changes review fails
   the action closed.
5. A provider-authenticated reviewer who differs from the pull-request author, every linked
   author and committer of a pull-request commit that changes `docs/status/blockers.json`, the
   original reporter, and the downgrade actor. Reporter and action identities must use comparable
   `github:<numeric-id>` provider IDs; missing or unlinked identities fail closed.

Evidence paths reject absolute paths, `..`, symlinks in any component, non-files, repository-root
escapes, and hash mismatches.

## Closure

Only `closed` may carry a `closure` record, and `closed` always requires one. Closure requires
resolution evidence, control evidence, and the same live provider verification bound by
`subject_sha256` to the exact closure subject, including the reporter identity. The reviewer must
also differ from the closure actor. The provider review must follow the closure time, and a closure
cannot predate the blocker or a governed downgrade.

## Provider verification

Registry fields are locators and action data, not authentication evidence. The checker re-fetches
the pull request, all reviews, the complete pull-request file and commit inventories, and each
commit that owns a blocker-registry change. It accepts no caller-supplied reviewer identity,
decision, approval timestamp, or captured provider response.

The review body must equal this marker exactly, with no surrounding prose:

```text
METRIPLANE_BLOCKER_APPROVAL_V1
repository=<owner/repository>
pull_request=<number>
change_sha=<current pull-request head SHA>
blocker_id=<MPBLK-NNNN>
action=<downgrade-or-closure>
subject_sha256=<canonical action subject SHA-256>
```

The workflow checks out full history and supplies the current repository, pull-request number, head
SHA, and base SHA on pull-request runs. It compares the current registry with that exact local base:
a newly added or changed action must point to the current pull request, while an unchanged
historical action is re-verified against the original pull request that approved it. A missing base
commit, wrong repository or action-owning pull request, stale head or review, absent or altered
marker, offline verification, malformed provider data, or superseding review fails closed. On
protected branch runs, the checker re-verifies the locator's current provider state.

`linear` remains a reserved schema value so existing planned integrations have an explicit
disposition. It cannot authorize a production action until an equivalent live Linear verifier and
cross-provider author identity binding are implemented and configured; current validation fails
such a record closed.

## Manual boundary

This implementation does not perform or approve a real downgrade or closure. The production
registry contains neither. Tests inject clearly named in-process provider fixtures; no CLI flag,
registry field, workflow input, or production path can select them, so they are not approvals.

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
4. Record only the GitHub repository, pull-request number, and exact subject SHA-256 in the action.
5. Ask the separate non-author to approve the current head with the exact marker above. Do not
   commit a claimed reviewer identity or captured response.
6. Run the checker with live provider context and the focused policy tests before review.

```bash
uv run python tools/check_blockers.py \
  --registry docs/status/blockers.json \
  --schema schemas/metriplane.blockers.v1.schema.json \
  --repo-root . \
  --github-repository Miko997/metriplane \
  --github-pull-request <number> \
  --github-change-sha <head-sha> \
  --github-base-sha <base-sha> \
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
