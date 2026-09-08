# Release qualification implementation status

The cumulative release framework is under implementation. The source-freeze,
artifact-build and invocation-journal segment is being qualified under MP2-007.
The complete release protocol remains unqualified. v0.4.1 tagging and publication
are held by the owner’s explicit instruction. Every release acceptance gate
remains required before a later authorization to publish.

## Source and artifact segment

The commands consume complete gate-input and target-resolution records in a
single run directory. Source capture reads the exact clean Git commit, all seven
registry/policy inputs, every tracked workflow, version metadata and the selected
release notes. It independently recomputes these inputs during validation.
Missing inputs, source drift and unavailable authority block the operation.

Every command needs its own fixed stage and next sequence under the run’s
`invocations` directory. Source and artifact producers start at `001` in a new
run. A failed producer requires a new staging run. Validator retries use the next
sequence and retain the preceding intent and any completed terminal record.

```console
uv --no-config run --frozen python tools/freeze_release_source.py --invocation-dir <run>/invocations/source-freeze/001 --gate-input <run>/gate-input.json --source-sha <exact-commit> --out <run>/source-freeze.json
uv --no-config run --frozen python tools/validate_release_source_freeze.py --invocation-dir <run>/invocations/source-freeze-validation/001 --record <run>/source-freeze.json --verify-tree-clean
uv --no-config run --frozen python tools/build_release_artifacts.py --invocation-dir <run>/invocations/artifact-build/001 --target-resolution <run>/target-resolution.json --source-freeze <run>/source-freeze.json --out-dir <run>/artifacts --manifest <run>/artifact-manifest.json
uv --no-config run --frozen python tools/validate_release_artifact_manifest.py --invocation-dir <run>/invocations/artifact-manifest-validation/001 --record <run>/artifact-manifest.json --artifacts <run>/artifacts --read-hash
```

The supervisor reserves and fsyncs its intent before the worker starts. The
worker stages output; the supervisor validates it before exclusive installation.
Consumers require exactly one matching terminal PASS producer, including its
intent, sequence, diagnostics and exact output digests. Missing or incomplete
terminal evidence blocks consumption, including after a supervisor is killed.
Retain the entire run directory and partial evidence during recovery.

A started worker group remains unsettled until the supervisor observes that it
no longer exists. Group cleanup retries for at most five seconds, including
transient permission errors while macOS reaps exited children. A permission
error alone never proves shutdown. Unconfirmed cleanup retains an incomplete
invocation and cannot install canonical artifacts or write a terminal record.

The artifact builder uses the single recipe in `metriplane.release_control` and
the installed backend pinned by `pyproject.toml` and `uv.lock`. It builds one
wheel and one sdist with `python -m build --no-isolation --sdist --wheel`, checks
metadata and fingerprints the exact bytes with the existing artifact owner.
It refuses an existing canonical destination and preserves failed build bytes.

Synthetic mode is restricted to isolated test fixtures. Tests create complete
local Git source and upstream input records, exercise the production commands,
and retain synthetic provenance. A synthetic run cannot satisfy live authority,
independent signing, durable-store independence or release qualification.

## Remaining acceptance work

MP2-007 retains all original A01–A13. Remaining work includes signed roles and
task state; complete staging and recovery; live target observation and indexed
burns; predecessor/LKG resolution; atomic candidate finalization; gate and matrix
construction with every terminal; unconditional two-store retention and indexing;
non-author approval; checkpoint-bound planning and fenced promotion locking;
exact-byte publication observation and reconciliation; chain append, CAS LKG,
pointer retention and signed invalidation. Unimplemented adapters return a
blocker and cannot create PASS records from fixture argument strings.

The official registries, full stage/producer/validator journal graph, every
remaining CLI route, mutation and crash-recovery coverage, current publisher
integration, fifth protected release terminal and reviewed deployment all remain
required software or acceptance work. No private key, independent signer, Store A,
Store B or CAS/lock/LKG backend has been bound by this segment. The owner’s
protected-main merge path and existing release criteria remain in force.

## Qualification boundaries and provider administration

Prepare and independently review a complete compatible slice before its hosted
qualification. The target is one full platform matrix per stable coherent PR
candidate and one final integrated v0.4.1 release-candidate matrix. Additional
complete runs require a recorded source or environment invalidation under the
exact-identity contract. CI's four fresh macOS shards retain the complete test
collection and all outcomes; its aggregate is source qualification evidence,
not a release gate-input, signed approval, publication or deployment record.

Keep an efficiency ledger with the exact commit and tree, source digest,
workflow/run/attempt, Python/platform and runner image, ordered collection,
pass/skip/fail counts, runner duration and rerun reason. Preserve original
reports and distinguish full-suite execution time from total workflow runner
time and elapsed wall clock. A cancelled or failed generation remains visible.
The first sharded hosted candidate supplies the measured after result; local
registry benchmarks and focused tests cannot prove macOS performance.

A fresh provider request for the same qualified source can avoid an
administrative-only commit once the reviewed normal broker policy is deployed.
The older request stays retained and expired; it is never reused. The new
request needs a unique nonce and digest, current exact head/base, current state,
collaborators and rulesets, a fresh valid lease, and an unspent canonical closed
check. An earlier admitted request, including a failed or incomplete admitted
transaction, prevents this renewal path. Scheduled deep-health overlap and
transient admission closure remain fail-closed conditions; read back the live
state before a new request. Provider-only readback cannot override qualification.

Broker policy source must be normally merged before deployment. Continue using
the deployed trusted control code for that merge, with candidate source bound
separately and never imported as live control code. Deploy the reviewed broker
and its exact validator dependencies, prove their file origins and hashes, then
read back protected-main state, all rulesets and terminal producers before
activating the lightweight-only metadata trigger. No deployment or renewal
capability is claimed before that proof.

All remaining CLI routes, non-author approval, two independent durable stores,
CAS/lock/LKG backend and deployment/readback remain acceptance work. A local
fixture or same-host directory pair cannot satisfy those bindings. Keep MET-163
In Progress and retain the explicit v0.4.1 publication/tag hold throughout this
work; neither CI efficiency nor completion of one source segment closes it.
