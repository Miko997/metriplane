<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Negative-test record

The isolated packages fail closed on the malformed and unsupported paths below.
The frozen SDK suite passes 146 tests and the frozen adapter suite passes 101
tests. Public exact-head workflow results remain pending.

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

Mutating or deleting `success`, `result`, `alarm`, `action`, and `annotation`
must not change normalized state, mapping, operator rules, Atlas events, or Atlas
incidents. The exact complete outcome stream or its complete absence is allowed.
A partial or structurally altered stream rejects conversion.

## Filesystem and provenance

- source mutation during conversion;
- source/output or config/output overlap;
- source, config, output, or nested symlink attacks;
- path traversal or unsafe destination replacement;
- adapter commit mismatch, dirty adapter subtree, untracked files, or mode drift;
- hostile Git environment overrides;
- stale lock, mapping fingerprint mismatch, or capability fingerprint mismatch;
- machine-local path leakage.

## Status

Candidate rejections are documented in [SOURCE-CANDIDATES.md](SOURCE-CANDIDATES.md).
The SDK schema, two post-hoc records, native synthetic record, and exact generated
identities validate locally. Three clean conversions are byte-equivalent. These
tests do not turn the synthetic result into external-source evidence.
