<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Run Deterministic Replay

```bash
RUNS=evidence/paper_v2_0/runs ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl
```

Captured output:

- `evidence/paper_v2_0/logs/deterministic_replay.txt`
- `evidence/paper_v2_0/runs/demo-evidence/replay_determinism.csv`
- `evidence/paper_v2_0/runs/demo-evidence/replay_determinism.sha256`

Expected result: `pass=true`, `mean_pos_diff_cm=0.0`,
`max_pos_diff_cm=0.0`, and `event_mismatch_count=0`.
