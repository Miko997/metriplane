<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# First-time-user comprehension check

This is a manual product-understanding check. Automation can summarize recorded
observations; it cannot establish that an unfamiliar person understood
Metriplane.

For v0.3.0, the owner had no unfamiliar tester available before publication and
explicitly deferred this check on 2026-08-09. The empty record remains a
truthful post-release adoption follow-up, not a passing human-validation claim
and not a blocker for publishing the tested software release.

## Empty-template baseline

- Tester count: **0**
- Completion rate: **N/A**
- Comprehension rate: **N/A**
- Median time to report: **N/A**
- Gate: **MANUAL GATE PENDING**

These are the calculator's results for an empty template, not permanently
maintained status text. Derive the current status from
[`human-comprehension-results.json`](human-comprehension-results.json) with the
command below. No human outcome is claimed until observations are recorded.

## Materials for each tester

Give the tester only:

1. the repository README or PyPI-style page for the exact tested version; and
2. the installation instructions for that candidate or published release.

Do not explain Metriplane before the test. Do not point out the demo command,
report link, or product limits. Use an unfamiliar tester and an anonymous ID;
do not record names, contact details, recordings, or other personal data.

## Procedure

1. Start the timer when the tester receives the two materials.
2. Ask questions 1-4 without coaching.
3. For question 5, let the tester find and run the demo unaided. Stop the timer
   when they find the generated report.
4. If intervention becomes necessary, record it and continue; do not erase the
   failed attempt.
5. Ask question 6.
6. After all six questions, ask the two neutral probes below, then score the
   observations using the rubric.

Ask these six questions exactly:

1. What problem does Metriplane solve?
2. What data goes in?
3. What comes out?
4. Why is the generated repeatable test useful?
5. Can you run the demo and find the report?
6. Which term was first confusing?

After those six questions are complete, ask these neutral probes without
suggesting the expected answer:

1. Does Metriplane control or change the machinery? Please explain.
2. If deterministic replay produces the same result twice, what does that tell
   you—and what does it not tell you about the physical measurements?

## Recording rubric

Add one object per tester to `testers` in
[`human-comprehension-results.json`](human-comprehension-results.json).

Before recording the first tester, replace the three top-level `null` values:

- `candidate_commit`: the exact 40-character lowercase commit SHA;
- `candidate_version`: the candidate's package version; and
- `materials`: privacy-neutral identifiers for the page (`readme` or
  `pypi-style-page`) and instructions (`candidate-wheel`, `source-checkout`, or
  `published-package`). Do not store URLs, filesystem paths, or participant
  information in candidate metadata.

- `tester_id`: a 1-32 character anonymous ID such as `T01`, using only letters,
  numbers, underscores, and hyphens.
- `demo_command_found`: whether the tester found the command without it being
  pointed out.
- `product_understood`: `true` only when the tester can explain in ordinary
  language that Metriplane analyzes a recorded workcell incident and turns the
  result into a repeatable check. Exact project terminology is not required.
- `report_found`: whether the tester ran the demo and found its report.
- `time_to_report_seconds`: elapsed seconds, or `null` if no report was found.
- `first_failed_command`: a faithful, single-line redacted rendering of the
  first failed command (maximum 500 characters), or `null` if none failed.
  Preserve the executable, subcommand, option names, ordering, and the token
  relevant to the failure. Replace secrets with `<REDACTED>`, local or user
  paths with `<PATH>`, usernames or account identifiers with `<USER>`, and
  private URLs with `<PRIVATE_URL>`. Never record raw credentials, tokens,
  personal home paths, usernames, or private repository/package URLs.
- `first_confusing_term`: the tester's answer to question 6, or `null` if they
  reported no confusing term; limit this to 200 characters and do not add
  participant identity.
- `intervention_required`: whether a person had to explain, point, correct, or
  supply a command before the report was found.
- `controls_machinery_misconception`: score the first neutral probe as `true` if
  the tester believed Metriplane controls machinery, `false` if they clearly did
  not, or `null` if unclear.
- `deterministic_replay_equals_physical_accuracy_misconception`: `true` if the
  second neutral probe showed that the tester treated identical deterministic
  replay as proof of physical accuracy, `false` if they clearly separated the
  two, or `null` if unclear.

Do not infer a passing answer from silence. Record `null` when either
misconception cannot be assessed; an unclear result does not pass that gate.

## Gate calculation

Run:

```bash
python scripts/summarize_human_comprehension.py \
  docs/validation/human-comprehension-results.json
```

For `n` recorded testers, the calculator applies these gates:

- every tester found the demo command;
- comprehension rate = testers with `product_understood: true` / `n`, at least
  80%;
- independent completion rate = testers who found the report without
  intervention / `n`, at least 80%;
- median recorded time to the useful report is less than 300 seconds;
- every controls-machinery misconception value is explicitly `false`;
- every replay-equals-physical-accuracy misconception value is explicitly
  `false`.

With zero testers, candidate metadata may remain `null`, rates and median are
`N/A`, every gate remains pending, and the calculator exits with status 2. Once
any tester exists, candidate metadata is required and validated. With
observations, the calculator exits 0 only when all gates pass and 1 when one or
more gates fail. These results remain a manual adoption and product-understanding
input; the calculator does not manufacture or validate human responses.
