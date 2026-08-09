# Dependency pinning boundary

Metriplane pins third-party GitHub Actions to immutable commit SHAs and pins the
runtime container bases used by the checked-in Dockerfiles to manifest-list
SHA-256 digests. Dependabot monitors Python, GitHub Actions, and Docker references
for updates.

The Docker image digests are supply-chain inputs, not research evidence. Updating
a digest does not change the frozen v0.2.0 SoftwareX artifact or the v0.1.3 TIM
evaluation boundary.

Python packages installed during CI and image builds are not yet fully
hash-locked. Those commands remain visible rather than being hidden from
OpenSSF Scorecard. A later change may introduce generated, reviewed lock files
with hashes once they are validated across the supported Python 3.12/3.13 and
Linux/macOS matrix. Version-only pins are not treated as equivalent to immutable
hash pins.

The health-status helper fetches JSON using Python's standard library and parses
it as data. It does not pipe downloaded content into an interpreter.
