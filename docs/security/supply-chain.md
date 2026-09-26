# Supply-chain controls

MP2-029 binds Metriplane's repository supply-chain controls to the exact source commit.
The canonical machine-readable contract is [`supply-chain-policy.json`](../../supply-chain-policy.json).

The existing `Security / required` terminal remains the sole protected security result. It
fails closed unless both CodeQL languages and the reusable supply-chain workflow succeed for
the same `GITHUB_SHA`. The reusable workflow performs an exact repository-local dependency
delta review, OSV and pip audits,
builds and scans both governed runtime images, scans source for secrets, and retains an SPDX
JSON SBOM. The ClusterFuzz Dockerfile is explicitly classified as a CI-only OSS-Fuzz builder,
not as a shipped or deployable runtime image; its base remains digest-pinned and workflow-tested.
Scanner failures are not converted to warnings and the SBOM is never uploaded as a release
asset.

Every third-party action is pinned to a full commit SHA. Scanner binary versions are explicit.
Every Python project with a `pyproject.toml` must have a declared `uv.lock`; unexpected or
missing project locks fail policy validation. All workflow checkouts disable persisted GitHub
credentials and workflow-level `read-all` permissions are forbidden.

OSV scans a deterministic `uv export --frozen --all-extras --no-dev` runtime graph for every
current Python project; `pip-audit` independently scans the same seven runtime graphs. Runtime
extras, including the CUDA and plotting profiles, remain inside both scanner boundaries while
optional test tooling remains outside them. Lockfiles under
`examples/external_sources/**/source` are immutable provenance bytes retained from earlier
qualified conversions, are checksum-validated as evidence, and are never installed or executed
by the product. Their original bytes and vulnerability history remain unchanged while every
corresponding current adapter runtime stays under both scanners.

`LICENSE`, `NOTICE`, and `LICENSES/MIT.txt` remain required inputs. The dependency review first
fails on undeclared manifests, locks, images, or license files and requires a changed project
manifest to carry its declared lock delta. It compares each current all-extras runtime export to
the corresponding export from the exact base commit, then resolves exact-version PyPI metadata
for every project-local runtime addition or upgrade and denies GPL-3.0 and AGPL-3.0. This catches
dev-to-runtime and cross-project introductions. Missing, unknown, malformed, mismatched, oversized,
or unavailable metadata fails closed. This local exact-version
path does not require GitHub Dependency Graph or a repository-setting change. Automated results
do not replace legal review and make no new third-party license claim.

Run the repository policy check locally with:

```bash
python tools/check_supply_chain_policy.py
```

This evidence qualifies source. It is not release, publication, or promotion authority.
