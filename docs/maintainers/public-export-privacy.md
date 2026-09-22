# Public export privacy protocol

Metriplane public exports are explicit projections, not copies of internal run
state. `metriplane.public_export` requires a sorted closed allowlist of dotted
leaf paths. Fields outside that set are omitted. A mapping may not be admitted
by naming only its parent; every public leaf must be named.

## Redaction boundary

The exporter replaces secret, path, host, user, session, run, and personal
identity fields before serialization. It also recognizes private-key, bearer,
GitHub-token, absolute-path, relative-path, user-home, and Windows-path canaries
in values. Callers may supply task-specific canaries; materialization fails if
any canary remains in either output.

The protected diagnostics sidecar contains only the allowlist, field paths,
counts, and classifications. It never contains rejected or redacted values.
Diagnostics are evidence that filtering occurred, not an alternate copy of the
private source.

## Filesystem and publication contract

`publish_public_export` stages in a real owner-controlled `0700` directory and
creates the public JSON and diagnostics files with no-follow, no-overwrite
`0600` descriptors. The public directory and its hidden diagnostics sibling
are committed together through the MP2-025 immutable-generation transaction.
The Publication Manifest and atomic pointer remain the authority for recovery.
Every destination component is opened with `O_NOFOLLOW`; the parent descriptor
stays pinned through publication, rollback, digest readback, and final identity
validation, so an intermediate symlink or parent swap fails closed.
Caller-selected namespaces and diagnostics outside the destination parent are
rejected.

The returned result contains only destination names and content/publication
digests. It does not expose an absolute source, checkout, user-home, or output
path. Replacing an existing export requires the explicit `overwrite=True`
choice and still uses the same journaled rollback protocol.

## Atlas compatibility

The existing `metriplane atlas privacy pseudonymize` command and its
`anonymize` compatibility alias retain their JSON/JSONL shapes, deterministic
proxies, CLI arguments, and return keys. Their staging files now use the shared
canonical JSON and `0600` writer, their directory is `0700`, and final delivery
uses `publish_transaction` rather than an independent replace/backup protocol.
Public privacy reports and return values use path-neutral `.` labels.

The shared exporter does not claim legal anonymization and does not absorb the
later MP2-145 rights, withdrawal, or retention policy. Domain-specific public
fields still require an explicit reviewed allowlist.

## Required validation

Run the MP2-026 focused suites plus public/functional inventory, traceability,
documentation, and toolchain currentness checks. The R-007 canary matrix must
cover closed allowlisting, nested values, deterministic bytes, secret/path/
identity redaction, no-overwrite, symlinks, malformed inputs, `0700/0600`
modes, diagnostics separation, and Atlas CLI compatibility on every supported
hosted profile.
