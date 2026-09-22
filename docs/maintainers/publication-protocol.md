# Durable publication protocol

Metriplane publishes Atlas runs, Atlas export pairs, and Sentinel evidence
bundles through `metriplane.publication`. The public path remains the existing
file or directory expected by callers. An adjacent private
`.metriplane-publication-<uid>` store retains the authoritative
content-addressed generation, the atomic current pointer, and any active
recovery journal. The owner-qualified store name, strict owner check, and mode
`0700` permit direct use of a shared parent such as `/tmp` without allowing one
local account to supply another account's protocol state.

## Commit order

One transaction has this durable order:

1. Inventory every staged regular file and directory. Symlinks and special
   files fail closed.
2. Copy the file bytes into opaque, read-only generation blobs and fsync every
   blob and containing directory.
3. Write `publication-manifest.json` last inside the generation. Its canonical
   content binds the publication ID, ordered destinations, logical paths,
   modes, sizes, and SHA-256 digests. The generation ID is the SHA-256 digest
   of that manifest subject.
4. Exclusively rename the complete generation into `generations/<generation-id>`
   and fsync the generations directory. Existing identical generations are
   validated and reused; differing bytes cannot reuse an identity.
5. Create and fsync the active transaction journal before creating transaction
   candidates or changing a public destination. The journal retains the exact
   previous inventories and durable forward and rollback intent/progress.
6. Hold the destination parent's OS-backed exclusive publication lock for
   recovery and every public-destination mutation. A crashed process releases
   the lock; overlapping destination sets cannot acquire competing owners, and
   a second publisher cannot mistake a live transaction for an interrupted one.
7. Materialize fresh transaction candidates from the retained generation, not
   from caller-owned staging paths. For an authorized overwrite, rename each
   previous destination to the transaction directory and fsync both parents.
   The destination must still match its journaled prior inventory before the
   rename, and the renamed backup must match it afterward; a changed or newly
   appeared path remains retained and blocks progress.
   Publish each generation-derived candidate by rename and record each durable
   boundary in the journal. Later mutation through a staging hardlink therefore
   cannot change public bytes.
8. After all destinations match the generation inventory, atomically replace
   `current.json`, validate it against the retained generation, and fsync its
   directory.
9. Only then remove backups and the active journal. Retained generations and
   the current pointer remain.

Generation payloads use opaque blob names deliberately. Recursive product
discovery must not interpret a retained generation as a second Atlas run or a
second evidence bundle. Logical file names and modes remain in the manifest.

## Recovery and fail-closed rules

`recover_publication(parent, publication_id)` validates every record before it
acts. Before the durable `published` phase it rolls the compatibility
projection back to the previous destinations. Removal and restoration each
have a durable intent. A new directory is atomically renamed into a private
quarantine before its old backup is restored, so interruption cannot leave a
partly deleted public tree. Recovery recognizes already completed quarantine
and restore renames after another crash and resumes idempotently. At or after
that phase it
requires every new destination to match the manifest and completes the atomic
pointer commit. Recovery is idempotent.

Recovery refuses to proceed when a generation, manifest digest, pointer,
journal binding, destination ownership set, transaction progress/intent,
transaction ID, or public artifact differs.
It never derives a filesystem path from an unchecked journal value. A changed
destination and its retained backup remain in place for diagnosis rather than
being overwritten. The public API does not turn a missing, malformed, or
ambiguous record into success.

The maintained failpoint suite interrupts after generation commit, journal
commit, every backup, every publication rename, and pointer commit. Single-
and multi-target tests prove that recovery exposes either the complete previous
projection or the complete new projection, never a mixed successful result.
Additional negative fixtures interrupt rollback after removal and after the
restore rename, swap a staged source for a symlink, and mutate staging hardlinks
before and after public commit.

## Compatibility boundaries

No-overwrite remains the default product behavior. Callers must explicitly
authorize overwrite, and the exclusive Linux or macOS rename path still
prevents a concurrent destination from being replaced. The durable
publication protocol is enabled on the currently qualified Ubuntu and macOS
platforms and fails closed on unsupported native platforms. Existing Atlas
and Sentinel return values and public artifact layouts are unchanged. The
private store is protocol state, not an additional product run, bundle, release,
or publication authorization.

The protocol only publishes local artifacts. It does not upload, tag, release,
approve, or change repository settings. Release and exact-byte promotion gates
remain separate downstream controls.
