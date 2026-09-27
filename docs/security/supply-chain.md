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

OSV scans deterministic `uv export --frozen --no-dev` runtime graphs for every current Python
project; `pip-audit` independently scans the same seven runtime graphs. The root project adds
`--all-extras`, keeping the CUDA and plotting profiles inside both scanner boundaries. Adapter
`test` extras remain outside the runtime graph, while the adapter's base dependencies remain
inside it. Every export is written to one absolute workspace-bound directory before scanning;
project-relative output drift fails validation. Lockfiles under
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

Both governed runtime images upgrade the base operating-system packages, install current
runtime packages, and then remove pip,
setuptools, wheel, and the bundled ensurepip wheel after installing Metriplane. Build tooling and
its vendored dependency metadata therefore do not remain in the runtime image. Image build or
HIGH/CRITICAL scan findings fail the same aggregate gate.

Run the repository policy check locally with:

```bash
python tools/check_supply_chain_policy.py
```

This evidence qualifies source. It is not release, publication, or promotion authority.
