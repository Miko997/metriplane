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

`initial_severity` and `initial_security` are immutable. Before the first governed downgrade,
escalation is allowed without a downgrade record. Every candidate is compared with the accepted
classification at the exact validation base. Lowering severity from P0 to P1/P2 or P1 to P2, or
changing `security` from `true` to `false`, requires exactly one `downgrade` record that matches
the accepted and current classifications. After that action is accepted, schema v1 freezes both
the downgrade record and its resulting classification.

The registry is append-only relative to the exact validation base. A retained blocker ID cannot
be deleted; its reporter, opening time, source, and initial classifications cannot be rewritten;
and a retained downgrade or closure record cannot be removed or changed. A retained downgrade
also freezes the resulting severity and security classification. New records and Git-tracked
commits provide the audit trail instead of mutating accepted action history.

A downgrade is valid only when all of the following are present and verified:

1. At least one repository-relative reproduction-evidence file with its SHA-256, tracked as a
   regular-file blob at the exact validated commit.
2. At least one repository-relative control-evidence file with the same commit-bound proof.
3. A registry locator naming the exact GitHub repository and pull request, plus a
   `subject_sha256` over the canonical downgrade subject. The subject binds the blocker ID, exact
   reporter, transition, action actor, action time, and both evidence arrays.
4. A live GitHub review fetched by the checker with `GITHUB_TOKEN`. The decisive review state must
   be `APPROVED` on the current pull-request head, follow the recorded action, and have the exact
   marker documented below. `COMMENTED` does not clear `CHANGES_REQUESTED`; only that reviewer's
   later `APPROVED` state or a provider-visible dismissal does.
5. A provider-authenticated reviewer whose live repository permission is `write`, `maintain`, or
   `admin` and who differs from the pull-request author, every linked
   author and committer of every commit in the approval pull request, the original reporter, and
   the downgrade actor. The all-commit rule conservatively covers rename chains into
   `docs/status/blockers.json`. Reporter and action identities must use comparable
   `github:<numeric-id>` provider IDs; missing or unlinked identities fail closed.

Evidence paths reject absolute paths and `..`. The checker reads the exact path from the validated
Git commit, requires mode `100644` or `100755`, and compares the committed blob bytes with the
recorded SHA-256. Ignored, untracked, symlink, tree, current-worktree-only, and mismatched evidence
fails closed.

## Closure

Only `closed` may carry a `closure` record, and `closed` always requires one. Closure requires
resolution evidence, control evidence, and the same live provider verification bound by
`subject_sha256` to the exact closure subject, including the reporter identity. The reviewer must
also differ from the closure actor. The provider review must follow the closure time, and a closure
cannot predate the blocker or a governed downgrade.

## Provider verification

Registry fields are locators and action data, not authentication evidence. The checker re-fetches
the pull request, all reviews, the complete pull-request file and commit inventories, and each
commit that owns a blocker-registry change. Pull-request lists and every commit's file list are
paginated to exhaustion. The enumerated commit count must equal the provider-backed pull-request
total; pull requests above GitHub's 250-commit REST inventory limit fail closed rather than
silently omitting actors. A commit inventory that reaches GitHub's 3,000-file REST ceiling also
fails closed because provider exhaustion cannot be proven. For each approval candidate it fetches
the repository collaborator
permission endpoint and binds the returned provider user to the review identity. It accepts no
caller-supplied reviewer identity, authorization, decision, approval timestamp, or captured
provider response.

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
a newly added action must point to the current pull request, while an unchanged
historical action is re-verified against the original pull request that approved it. A missing base
commit, wrong repository or action-owning pull request, stale head or review, absent or altered
marker, offline verification, malformed provider data, or superseding review fails closed. On
protected branch and release runs, the checker compares the validated commit to its exact history
base, requires every approval pull request to be provider-confirmed as merged, and requires that
provider merge commit to be an ancestor of the exact validated release SHA.

The production workflow requires the annotated release tag to remain the exact current `main`
commit, reruns live provider validation at manual dispatch, then fetches and rechecks exact current
`main` immediately before the trusted publish action after protected-environment approval. Any
intervening `main` change burns that candidate and requires a new tag. A dismissed or edited
approval therefore invalidates production even if the earlier tag workflow passed.

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
  --validated-sha <head-sha> \
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
