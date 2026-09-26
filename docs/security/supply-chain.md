# Supply-chain controls

MP2-029 binds Metriplane's repository supply-chain controls to the exact source commit.
The canonical machine-readable contract is [`supply-chain-policy.json`](../../supply-chain-policy.json).

The existing `Security / required` terminal remains the sole protected security result. It
fails closed unless both CodeQL languages and the reusable supply-chain workflow succeed for
the same `GITHUB_SHA`. The reusable workflow performs dependency review, OSV and pip audits,
builds and scans both governed runtime images, scans source for secrets, and retains an SPDX
JSON SBOM. The ClusterFuzz Dockerfile is explicitly classified as a CI-only OSS-Fuzz builder,
not as a shipped or deployable runtime image; its base remains digest-pinned and workflow-tested.
Scanner failures are not converted to warnings and the SBOM is never uploaded as a release
asset.

Every third-party action is pinned to a full commit SHA. Scanner binary versions are explicit.
Every Python project with a `pyproject.toml` must have a declared `uv.lock`; unexpected or
missing project locks fail policy validation. All workflow checkouts disable persisted GitHub
credentials and workflow-level `read-all` permissions are forbidden.

`LICENSE`, `NOTICE`, and `LICENSES/MIT.txt` remain required inputs. Dependency license review
denies GPL-3.0 and AGPL-3.0 additions pending an explicit policy change; this check does not
alter the project's MIT license or assert that automated results replace legal review.

Run the repository policy check locally with:

```bash
python tools/check_supply_chain_policy.py
```

This evidence qualifies source. It is not release, publication, or promotion authority.
