# Semantic, golden, and obligation change governance

MP2-017 governs intentional changes to supported or compatibility behavior, golden
evidence, and release test obligations. A pull request that changes one of these
surfaces carries a `metriplane.migration-delta.v1` manifest. The manifest binds the
exact base and head commits, the complete Git changed-path set, the author, every
changed stable identity, its before and after digest, and its compatibility window.

The independent reviewer signs the canonical manifest digest in a
`metriplane.migration-delta-approval.v1` record. The reviewer identity must differ
from the author identity and must verify through the supplied provider keyring.
Test keys and fixture identities only exercise the software path; they do not supply
release approval.

Run the read-only validator against committed source:

```console
python tools/validate_migration_delta.py \
  --repository-root . \
  --manifest build/migration-delta.json \
  --schema schemas/metriplane.migration-delta.v1.schema.json \
  --approval build/migration-delta-approval.json \
  --approval-schema schemas/metriplane.migration-delta-approval.v1.schema.json \
  --keyring /approved/read-only/provider-keyring.json \
  --functional-inventory docs/status/functional-inventory.json \
  --behavior-characterization docs/status/behavior-characterization.json \
  --obligations docs/status/release-test-obligations.json \
  --out build/migration-delta-validation.json
```

The validator compares committed Git objects. It rejects an undeclared changed
path, an undeclared supported or compatibility row, an undeclared obligation
change, a substituted digest, an author acting as reviewer, an untrusted signature,
and a replacement that drops any criterion, capability, environment, test family,
profile, or scenario from the obligation it supersedes. Validation output is
created once and is never overwritten.

The repository owner must bind a real independent reviewer or reviewer team in
`.github/CODEOWNERS` for this policy, both schemas, the validator, governed golden
paths, and `docs/status/release-test-obligations.json`. That provider identity is
not yet supplied, so this repository change prepares the enforcement path without
claiming live non-author approval or CODEOWNERS enforcement.
