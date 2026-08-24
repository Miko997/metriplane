<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Audited baseline snapshot

`docs/status/baseline-snapshot.v1.json` is the deterministic MP2-000 census of
the audited Metriplane base. Its schema version is
`metriplane.baseline-snapshot.v1`, validated by
`schemas/metriplane.baseline-snapshot.v1.schema.json` under JSON Schema Draft
2020-12.

The snapshot binds repository `Miko997/metriplane`, commit
`14c1befff886215d928f1c3f6b412b843b902671`, tree
`38dcd26db9a467c850c75d4af0e6c932c3d0ecd7`, and package version `0.3.0`.
It binds that audited current-main commit—not the eventual MP2-000 pull-request
head and not merely the earlier `v0.3.0` release commit. It preserves the full
repository history and process after v0.3.0; it does not remove, rewrite, or
replace any commit, tag, branch, evidence, or release procedure.

## Commands

`capture` is a bootstrap-only maintainer command. It requires exactly one
qualifying `READY` MP2-000 work-order instance with a regular canonical retained
passing pre-edit baseline and matching installed `metriplane` and
`metriplane-run` console scripts. An ordinary clean checkout uses the committed
artifact with `validate` or `check`; it is not expected to reconstruct bootstrap
evidence or run `capture`.

Capture only into two absent files in one fresh directory. The two leaf names
are mandatory:

```bash
python tools/baseline_snapshot.py capture \
  --repo . \
  --base-sha 14c1befff886215d928f1c3f6b412b843b902671 \
  --output /tmp/metriplane-baseline-capture/baseline-snapshot.v1.json \
  --checksum-output /tmp/metriplane-baseline-capture/baseline-snapshot.v1.sha256
```

Validate a captured pair without inspecting a repository:

```bash
python tools/baseline_snapshot.py validate \
  --snapshot /tmp/metriplane-baseline-capture/baseline-snapshot.v1.json \
  --schema schemas/metriplane.baseline-snapshot.v1.schema.json \
  --checksum /tmp/metriplane-baseline-capture/baseline-snapshot.v1.sha256
```

Validate the committed pair and independently re-census every source-derived
section from the bound Git commit:

```bash
python tools/baseline_snapshot.py check \
  --repo . \
  --snapshot docs/status/baseline-snapshot.v1.json \
  --schema schemas/metriplane.baseline-snapshot.v1.schema.json \
  --checksum docs/status/baseline-snapshot.v1.sha256
```

`--help` is available at the root and for each of `capture`, `validate`, and
`check`. A successful command exits 0. Argparse usage errors exit 2. A census,
integrity, schema, parser, environment, path-safety, or no-overwrite failure
exits 3 and does not mutate an authoritative output.

`capture` never overwrites either destination. A regular file, directory,
symlink, or dangling symlink at either path blocks publication. Both files are
fully staged on the destination filesystem before no-replace publication.
Before publication, the new snapshot passes the hash-locked reviewed schema and
all internal semantic invariants. Publication failures attempt
identity-safe rollback; clean rollback leaves both output leaves absent. A rollback,
inode-replacement, or directory-fsync problem is explicitly reported, and any
residual pair must not be treated as authoritative. An incomplete pair is not
accepted as authoritative. The caller chooses and later removes temporary
directories. The committed pair changes only through a separate reviewed
repository change.

## Encoding and checksum

The snapshot is strict UTF-8 canonical JSON: NFC strings and keys, unique keys
sorted by Unicode code point, integers only, compact separators, and no trailing newline.
BOM, invalid UTF-8, duplicate or NFC-colliding keys, lone surrogates,
floats, nonfinite values, negative zero, and noncanonical whitespace fail
closed.

`docs/status/baseline-snapshot.v1.sha256` is exactly one 92-byte record:

```text
<64 lowercase SHA-256 hex characters><two spaces>baseline-snapshot.v1.json<LF>
```

The checksum integrity-binds the exact snapshot bytes and is verified before
the JSON is parsed. `validate` verifies that pair integrity; `check` additionally
anchors the reviewed whole-snapshot digest when evidence is absent, or the
qualifying retained evidence when it is present. Uppercase, wrong length, wrong
filename, alternate spacing,
CRLF, extra lines, or a digest/content mismatch is invalid.

## What is frozen

The snapshot contains exactly these 11 root sections:

- `schema_version`
- `captured_source`
- `tracked_tree`
- `commands_and_help`
- `http_routes`
- `schemas`
- `resources`
- `workflows_and_jobs`
- `tests`
- `environment`
- `limitations`

The audited census includes 1,469 Git blobs/symlinks with modes and blob object
IDs, both installed root console-script help surfaces, 48 terminal HTTP or
WebSocket declaration rows, 6 tracked `*.schema.json` files, the bounded
256-resource seed, all 15 workflow files with complete normalized triggers and
job IDs, and 1,194 ordered root pytest collection node IDs. Rows come from the
exact commit through `git ls-tree` and `git cat-file`; mutable worktree files and
symlink targets are not followed.

Test collection and execution retain raw stdout/stderr SHA-256 identities plus
semantic `*_count` fields. The passing base has zero failures and zero errors;
recorded skips, xfails, xpasses, warnings, deselections, and retries remain
explicit rather than being silently omitted. Timing and temporary paths do not
become semantic result fields.

The tracked-tree canonical row digest is
`39c5f21f491926d6c45d4a8090ecc8ec16893000f5637020a199b7bc6cd0b03f`.
The route-row digest is
`c278c306fe36d7251da0a04d710fe02d8d90758c911c325e4c827a0b41e7abaf`.
The merged resource path-array digest is
`fc3bbd56c48c54bedddc92caee716a97bd95718228ff2eb7d34826c4dbc32033`;
its repository-seed and package-data subset digests are respectively
`3ac908ab77d8e31e6b760ab1a598f69ff614ed2ce10dcd44b9524eb80a0c9477`
and `51e103bed72e65a6913af2762544bb67645c4b440f494b8353e03a93ff6a60d1`.
The root `uv.lock` digest is
`5857debd56a7d0a82bb7057c4edae136644b0887765423e73be41002f8ba5f70`.
Workflow job IDs preserve authored order; the complete canonical workflow-row
digest is
`76a647b24cba2203386722406fdd6626757fabcb79390dc1afb8fc20f36bc93c`.

`validate` checks checksum, strict canonical parsing, the hash-locked reviewed schema,
schema validity, and all snapshot-internal count/order/digest invariants.
`check` first performs the same validation, then resolves the exact Git commit
and tree and recomputes tracked entries, terminal routes, schemas, resources,
and workflows. It validates the frozen installed-help identities and stream
digests recorded by bootstrap `capture`; it does not execute the invoking
interpreter's currently installed console scripts. When the exact qualifying
local MP2-000 evidence is present, `check` also regenerates and exact-compares the retained
test and environment projections. In an ordinary clean checkout where that
evidence root is absent, it accepts only the exact reviewed committed snapshot
SHA-256 before re-censusing the source-derived sections. A present symlink,
partially materialized MP2-000 exact-base namespace, malformed record, or
otherwise invalid evidence root is an error;
it never downgrades to the evidence-absent fallback. `check` does not pretend
that a different machine re-executed historical tests or observations.

## Environment boundary

The environment section records the exact observed OS release, kernel,
architecture, CPython patch/build and cache tag, uv version, lock digest,
installed distribution inventory, filesystem encoding, and allowlisted
home/XDG/cache/temporary-path assumptions. Its profile is
`bootstrap-lock-derived-root-suite` and its support disposition is exactly
`not_measured`.

That row may prove MP2-000 on the one observed bootstrap cell. It is not a Linux,
Ubuntu, macOS, Windows, Python, browser, container, hardware, or release-support
pass. MP2-007 owns the permanent supported-environments registry and must make
those support dispositions independently.

## Deliberate limitations and downstream owners

- The two root help captures are a bootstrap seed, not the complete CLI action
  inventory. MP2-011 owns leaf/action discovery.
- The 48 terminal rows freeze declarations and forwarding provenance, not full
  HTTP/service/page/UI behavior. MP2-012 owns that complete inventory.
- Runner job-prefix matching currently accepts tails more broadly than the
  normalized `{job_id}` templates. This is observed code overacceptance, not a
  supported behavior claim. MP2-012 owns inventory and MP2-015 owns behavior
  characterization.
- The 256 rows are a bounded repository/package-data resource seed. Deferred
  config, evidence, calibration, documentation, tooling, and generated paths
  remain present; they are not claimed absent or retired. MP2-013 owns complete
  public/config/artifact/example/proof/resource/workflow/claim classification.
- Six tracked JSON Schema files are frozen. Generated runtime model schemas are
  not yet inventoried; MP2-013 owns that classification.
- MP2-010 consumes this artifact as a census seed, not a complete typed baseline
  registry. MP2-014 imports the active `MP2-000.OBL.*` lineage. MP2-016 later
  migrates and validates the bootstrap records without rewriting their identity.
- The frozen 0.3.0 version, installed-help streams, and root test obligations
  remain active stop-the-line goldens. A legitimate change requires approval
  and supersession through MP2-017; later work must not silently derive or
  replace them from the current package version.

The snapshot observes existing state. It does not characterize every success or
failure contract, change compatibility, expand support, merge a pull request,
tag or publish a release, declare v0.4 complete, or begin later-milestone work.
