<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Negative-test record

The isolated packages fail closed on the malformed and unsupported paths below.
The frozen SDK suite passes 146 tests and the hardened adapter suite passes 115
tests. The reviewed exact head completed the required public workflows,
including Ubuntu and macOS portable evaluation on Python 3.12 and 3.13. The
live pull request is authoritative for any later additive head.

## Source and container

- wrong source SHA-256 or byte count;
- truncated or corrupted MCAP;
- malformed record or CDR payload;
- unsupported compression or encoding;
- missing, altered, duplicated, or unexpected schema;
- schema hash mismatch;
- channel/schema mismatch;
- missing, renamed, unexpected, or duplicated semantic topic mapping.

## Clock

- missing or default dynamic message timestamp;
- nonmonotonic or duplicated evaluation timestamp;
- mixed or unexpected clock relationship;
- nominal-rate-only timing;
- MCAP log-time substitution;
- publish/header/log disagreement;
- trigger and required-state timestamp mismatch.

## Frames and transforms

- missing, unknown, or wrong frame;
- transform cycle or ambiguous path;
- missing, extra, reordered, duplicated, or conflicting static transform;
- dynamic transform in a static-only profile;
- invalid or nonfinite quaternion;
- nonfinite translation or position;
- unavailable exact path;
- latest-at, interpolation, or extrapolation request.

## Identity and units

- duplicate source entity or normalized ID;
- missing required entity;
- unexpected alias or topic metadata;
- array/order-only identity;
- missing or changed unit;
- undeclared conversion, nonfinite position, or wrong dimensionality.

## Materialization

- partial required snapshot;
- missing, duplicated, stale, or reordered trigger;
- nonzero synchronization skew;
- undeclared carry-forward or tolerance;
- wrong frame count or sequence.

## Anti-taint

Mutating `success`, `result`, `alarm`, `action`, and `annotation` in the
internal anti-taint harness must not change normalized state, mapping, operator
rules, Atlas events, or Atlas incidents. That harness also constructs a
complete-absence variant solely to prove semantic invariance. Public inspection
and conversion accept only the exact frozen complete outcome stream; deletion,
partial input, or structural alteration rejects at source identity.

## Filesystem and provenance

- source mutation during conversion;
- source/output or config/output overlap;
- source, config, output, or nested symlink attacks;
- path traversal, late destination creation, candidate inode/content
  replacement, parent replacement, or unsafe destination replacement;
- source, config, or lock mutation after the atomic namespace transition but
  before publication commit;
- any attempt to replace an existing conversion, finalization, or generated
  source destination, including with the legacy `--overwrite` flag;
- adapter commit mismatch, dirty adapter subtree, untracked files, or mode drift;
- hostile Git environment overrides;
- stale lock, mapping fingerprint mismatch, or capability fingerprint mismatch;
- machine-local path leakage.

Successful publication is a descriptor-authenticated point-in-time guarantee.
Later custody still requires access separation or immutability against a writer
with the same operating-system privileges.

## Status

Candidate rejections are documented in [SOURCE-CANDIDATES.md](SOURCE-CANDIDATES.md).
The SDK schema, two post-hoc records, native synthetic record, and exact generated
identities validate locally. Three clean conversions are byte-equivalent. These
tests do not turn the synthetic result into external-source evidence.
