<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# What Metriplane does

## The human problem

A recording may show that a workcell step was late without explaining which
expected object was missing, when the delay crossed a rule threshold, or how to
check the same condition after a change. Metriplane turns a compatible recording
and explicit process rules into a reviewable incident result.

## What happens

```text
Input
  Timestamped object states + process rules

Metriplane
  Replays the recorded run and checks what happened

Output
  Incident timeline
  Incident Report
  Verified evidence bundle
  Repeatable regression check
```

For example, the bundled recording has no required torque driver at the assembly
station when it is needed. The configured 30-second wait is exceeded; the sample
run records a 35.0-second delay, six events, and one incident. Its generated
regression check can be rerun after software or process-rule changes so the same
expected result does not disappear silently.

## Terms in plain language

- **Recorded run:** timestamped observations saved from one workcell session.
- **Object state:** an already-estimated object identifier with its timestamped
  position and, for this workflow, an already-assigned zone label.
- **Event:** one detected change or process condition in the replayed run.
- **Incident:** related events grouped into one problem worth reviewing. A valid
  run can have zero incidents when no configured problem occurs.
- **Evidence bundle:** the incident inputs and results plus checksums that reveal
  missing or changed files.
- **Regression check:** a repeatable test generated from one incident and run
  again after a change.
- **Process rules:** the expected objects, locations, ordered steps, and maximum
  waiting time for one bounded workflow.
- **Deterministic replay:** the same validated input and configuration produce
  the same software result. This does not prove that the original sensors,
  object identification, positions, or zone labels were physically accurate.

## Boundaries

Metriplane is observe-only. It does not:

- command a robot or machine;
- stop a process or enforce a contract;
- certify safety, regulatory compliance, or product quality;
- infer zones from coordinates in this recorded-run path;
- ingest raw video, rosbag, or MCAP files through the v0.3.0 workflow;
- prove that a deterministic result is physically correct.

The technical category is **open-source robotics incident replay and regression
testing for bounded workcells**. Architecture and research terminology are useful
after this input/result boundary is understood; they are not prerequisites for
running the bundled example.

