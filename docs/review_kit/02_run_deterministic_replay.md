<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Run Deterministic Replay

Write rerun output to a temporary directory rather than the archived evidence
package:

```bash
RUNS=/tmp/metriplane-softwarex-runs \
  ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl
```

Expected result: `pass=true`, 24 frames, 72 object pairs,
`mean_pos_diff_cm=0.0`, `max_pos_diff_cm=0.0`, and
`event_mismatch_count=0`.

The archived author-run output remains under
`evidence/paper_v2_0/runs/demo-evidence/` and
`evidence/paper_v2_0/logs/deterministic_replay.txt`.
