<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# External Reproduction Note Template

Please complete this after running the [Metriplane v0.2.0 reviewer
path](review_kit/00_start_here.md).

## Person

- Name:
- Role/title:
- Organization:
- Email or public profile:
- Permission to cite or summarize this reproduction publicly:
  - [ ] Yes, with name
  - [ ] Yes, anonymously
  - [ ] No
- Permission to acknowledge in publication or repository: yes/no

## Environment

- Date:
- Operating system:
- Python version:
- Docker version, if used:
- MetriPlane release or commit:

## Commands run

Follow the [SoftwareX reproduction guide](softwarex_reproducibility.md) and
record the commands and results from the current run. Windows users must run
the workflow inside WSL2 Ubuntu; the Bash commands are not intended for native
Command Prompt or PowerShell.

Optional Docker path:

```bash
./tools/docker_demo_up.sh
curl http://localhost:8000/health
./tools/docker_clean.sh
```

## Observed result

* Did deterministic replay pass?
* Expected camera-free result: doctor 0 failures; replay `pass=true`; `mean_pos_diff_cm=0.0`; `max_pos_diff_cm=0.0`; `event_mismatch_count=0`.
* `No /dev/video* devices found` is acceptable as a warning for camera-free replay.
* Were there installation issues?
* Did health check pass, if Docker was used?
* Notes:

## Relevance statement

In 2-5 sentences, describe whether the artifact appears usable, reproducible, or relevant to robotics, automation, digital twins, physical observability, or research-software evaluation.
