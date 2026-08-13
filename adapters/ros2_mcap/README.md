<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# Bounded ROS 2/MCAP recorded-state adapter

This isolated package implements only
`metriplane.ros2_mcap_recorded_state.v1`. It converts one exact
Metriplane-authored synthetic MCAP recording into portable External Source
Contract v1 bundles. It is format-engineering evidence, not external-source
evidence or general ROS 2, MCAP, rosbag2, or TF2 support.

The converter consumes two explicitly configured `PoseStamped` channels and a
two-edge `/tf_static` chain. Message `header.stamp` in the declared `ROS_TIME`
domain is the sole evaluation clock. Required state must be co-timestamped.
There is no topic discovery, interpolation, extrapolation, carry-forward, or
inferred absence.

The `/metriplane/source_outcome` stream is excluded from normalized state.
Normal inspection and conversion accept only the exact frozen source: 28,735
bytes with SHA-256
`c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99`.
An internal test-only decoder mode admits either whole-stream deletion or
outcome-value mutation to prove that excluded fields cannot affect normalized
state or Atlas inputs. That mode is not available from the public API or CLI.
Partial, renamed, retyped, or malformed outcome streams fail closed.

Conversion dependencies remain in this package. Portable fixtures do not
contain MCAP bytes and do not require ROS or MCAP packages.

## Publication boundary

Conversion and finalization are frozen to Linux x86_64. Before publication,
the complete same-parent candidate tree is read and synchronized through
non-following directory descriptors; every regular file is bound by bytes,
SHA-256, and inode metadata, and links or non-file entries fail closed.
Publication uses Linux `renameat2(RENAME_NOREPLACE)` and requires a fresh,
absent destination. Directory replacement is rejected even if the legacy
`--overwrite` option is supplied; source generation follows the same
fresh-destination rule, and callers must select a new output path. This
keeps the namespace transition atomic without an absent-output window or an
unverified displaced tree. The published namespace and complete tree are
independently rechecked against the authenticated snapshot before success is
returned. A platform or filesystem without the atomic no-clobber operation is
rejected. This is a descriptor-authenticated point-in-time guarantee: a writer
with the same operating-system privileges could still mutate an ordinary
writable output after the final verification and successful return, so callers
must enforce access separation or immutability for any later custody guarantee.

## Licensing

The independently authored adapter code is MIT. `schemas.py` and the frozen
MCAP contain exact embedded ROS interface schema text: `std_msgs`,
`builtin_interfaces`, and `geometry_msgs` text remains Apache-2.0, while
`tf2_msgs` text remains BSD-3-Clause. The Metriplane-authored outcome schema,
container structure, and message values are MIT. The repository copy of the
MCAP has an adjacent `.license` sidecar with the composite SPDX expression.
The exact Willow Garage copyright notice, BSD conditions, upstream commit, and
schema blob identity are retained in
[`src/ros2_mcap_adapter/THIRD_PARTY_NOTICES.md`](src/ros2_mcap_adapter/THIRD_PARTY_NOTICES.md),
which is also included in the adapter wheel.
Portable normalized fixtures omit the MCAP and embedded schema bytes and are
MIT.
