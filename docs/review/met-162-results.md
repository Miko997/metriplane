<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MET-162: installed before/after validation

MET-162 separates sampled process outcomes and observed waiting from legacy
incident-derived metrics. It also prevents a before/after comparison from
claiming improvement when the requirements differ or the evidence is incomplete.
This document records the bounded validation method for that change.

The published reference is `metriplane==0.4.0.post2`. The candidate is an
unreleased `metriplane==0.4.1` wheel built from the approved release-candidate
source. Its source and distribution hashes remain part of the comparison
identity. These results do not rewrite the frozen SoftwareX v0.2.0 or TIM
v0.1.3 evaluations.

## Reproduce from installed artifacts

Build the candidate using the exact toolchain and frozen environment described
in [the testing policy](../maintainers/testing-policy.md). Install the published
reference and the candidate wheel into separate clean Python 3.12 or 3.13
environments. Keep both distribution files for their hashes. For example, after
the two environments have been installed:

```console
python /path/to/checkout/tools/validate_atlas_assessment.py \
  --before-python /path/to/reference-env/bin/python \
  --after-python /path/to/candidate-env/bin/python \
  --before-artifact /path/to/metriplane-0.4.0.post2-py3-none-any.whl \
  --after-artifact /path/to/candidate/metriplane-0.4.1-py3-none-any.whl \
  --out /path/outside/checkout/met-162-review-01
```

The output directory must be new and outside the checkout. The controller uses
only the Python standard library. Workers use the selected interpreter with
`-I`, an unrelated working directory, and no `PYTHONPATH`; they reject editable
installs and imported package modules outside that interpreter's site-packages.
No private recording, separately supplied archive, simulator installation, or
download is required by the runner.

The default two trials run eleven synthetic cases against both packages, for
44 run invocations. Every input is generated locally from the reviewed script.
JSON object files serve as valid YAML domain-pack files, avoiding a dependency
on the controller's installed packages. The protocol and input hashes are saved
before the first run. All objects are explicitly observed inside or outside the
work zone, except for the deliberate missing-observation case.

## Cases and expected differences

| Case | Recording and requirement | Published behavior retained | Candidate outcome |
| --- | --- | --- | --- |
| Slow / sticky violation | Tool arrives at 1.5 s; threshold 1 s | One incident at the missing sample at 1 s | `violated`, including after completion; full observed wait 1.5 s |
| Fast | Same rule, tool arrives at 0.5 s | Zero incidents | `satisfied`; observed wait 0.5 s |
| Relaxed rule | Byte-identical slow recording; threshold 2 s | Zero incidents | `satisfied` under the changed rule; comparing against slow is `incompatible` |
| Pending | Recording ends at 0.5 s before arrival or deadline | Zero incidents | `unresolved`; elapsed lower bound is not a completed wait |
| Not exercised | Trigger material remains explicitly outside the work zone | Zero incidents | `not_exercised` |
| Arrival between samples | Missing at 0.75 s; first observed arrival at 1.25 s; threshold 1 s | Zero incidents | `satisfied` under the legacy sampled policy, with an explicit late-arrival coverage note |
| Equality | First observed arrival is exactly the 1 s threshold | Zero incidents; completion is checked first | `satisfied` under the same documented policy |
| Violated and still pending | Missing through the sample at 1 s and beyond | One incident | `violated` with an unclosed wait interval |
| Missing observation | Tool omitted from one declared complete snapshot | Existing native Atlas execution remains accepted | Coverage is insufficient for an improvement claim |
| Translated clock | Slow recording with every timestamp increased by 4.7 s | Legacy sampled arithmetic remains unchanged | Comparison with the untranslated run is `incompatible`; time-origin changes cannot supply improvement evidence |
| Cropped after arrival | Only the last two slow-recording samples, rebased to 0 s; tool is already present in the first sample | Zero incidents and immediate step completion | `satisfied` for the retained samples; comparison with the full recording is ineligible because its window/initial state differs and no preceding wait was observed |

The between-sample case is a characterization of
`legacy_sampled_missing_v1`, not proof that a continuous-time deadline was met.
The change preserves legacy event ordering, deviations, incident counts,
`metrics.json`, and `process_trace.json`. The runner compares these artifacts
semantically across the published and candidate implementations for every case.

Nine comparison scenarios exercise rule relaxation, faster arrival under fixed
rules, unchanged observations, pending evidence, an unexercised rule, missing
observations, old artifacts without the new assessment, a translated clock,
and cropping away the original wait.
Only the fixed-rule
faster-arrival pair should claim improvement. An eligible unchanged pair should
report no change. The historical false-improvement statement for rule relaxation
is retained as the before result, rather than silently relabeled.
The positive pair uses the same complete sample grid and initial material/tool
zones; only the tool's observed arrival changes.

Native bundle probes verify incident bundles, generate and run a regression
from each ZIP, then alter a copy's report without updating checksums and require
verification to fail. Each trial checks both package versions reading their own
bundles and reading the other version's bundles. This exercises compatibility
and deterministic replay while preserving original artifacts.

## Retained outputs and result status

The runner writes `protocol.json`, per-invocation requests, exact commands,
exit statuses, raw standard output and standard error, original run artifacts,
comparison artifacts, and bundle probes. `results.json`, `comparisons.json`,
`bundle-probes.json`, and `checks.json` are machine-readable summaries.
`summary.json` reports the aggregate verdict and every failed check;
`CHECKSUMS.sha256` covers the retained output files. Environment records include
package versions, Python and platform identities, package origins, installed
source hashes, and the installed distribution's `RECORD` hash. Optional artifact
arguments additionally record the supplied wheel or sdist hashes. For wheels,
every packaged Python source file must also match its installed counterpart.

**Candidate execution passed on 2026-09-07: 181 of 181 checks.** The retained run
`met162-installed-proof-02` contains 44 run invocations, 34 comparisons, and eight
bundle probes. Both environments used Python 3.12.13 on Linux x86-64 with the
same non-Metriplane package versions from the repository's frozen lock. Both
wheel source inventories matched the corresponding installed environments.

| Check | Observed result |
| --- | --- |
| Repeated run semantics | 22/22 package/case pairs match across the two trials |
| Legacy events, deviations, incidents, metrics and trace | 22/22 before/after case-trial comparisons match |
| Explicit candidate outcomes and waits | 22/22 outcome checks and 22/22 wait checks pass |
| Same recording with relaxed rule | `incompatible`; both completed waits are 1.5 s; no improvement claim |
| Faster arrival under the same rules and sample window | `eligible` / `improved`; observed wait 1.5 → 0.5 s and incidents 1 → 0 |
| Unchanged eligible recording | `eligible` / `unchanged`; wait delta 0 s |
| Pending, unexercised, missing-observation and old-artifact comparisons | `insufficient_evidence` / `not_comparable` |
| Translated clock | `incompatible` / `not_comparable` |
| Cropped recording starting after arrival | `insufficient_evidence` / `not_comparable`; initial-state and time-window differences are also recorded |
| Native and cross-version bundle probes | 8/8 originals verify, 8/8 generated regressions replay successfully, and 8/8 tampered copies fail verification |

Retained identities:

| Artifact | SHA-256 |
| --- | --- |
| Published 0.4.0.post2 wheel | `2e206db012b16d2021ae98fc52a03a831d99746c4e4ff9a4bc7eefa5102a7f38` |
| Unreleased final candidate wheel | `acf60b0c41948638097221d601a724b77a685dd47f9f9f8e2e7330b903275eca` |
| Reviewer runner used for this execution | `9dacd116d2da1e86a02d7c22baa2f81c9bbcd0910dd725c8e401ef8886ad0fd4` |
| `protocol.json` | `3859feaf6753f49d66afb7d51f786718ee528dd678b512a6ac1048a2e891881a` |
| `summary.json` | `ba7923951931a8e7dc8a8ccd81b5182b13d12967f963f04382f6ab24df9c6e1f` |
| Retained `CHECKSUMS.sha256` inventory | `dc7669287173b9df453f51d6bb79b045f0c8330c3235fdeb35615b119c7810ac` |

The retained MET-162 engineering candidate was built from working changes on
base commit `17bb62d61a567dee65b41674d2129c7e113b7b3a`; its complete installed
source-file hash inventory is retained in `protocol.json`. It predates the
v0.4.1 release-candidate version transition and does not qualify a later
artifact. The final release check must repeat the comparison against the exact
retained v0.4.1 candidate bytes. The identities above describe the earlier
execution, not a later rebuild or release.

## Closure of the original 21-case study

The same installed candidate also re-executed the retained 21-case ManiSkill /
robomimic study through its unchanged `run_study.py` and independent
`baseline.py`. Both workflows ran twice, producing 84 fresh invocations in
`met162-original-matrix-final`. The source study, its original outputs, and
its expectations were read-only inputs; bytecode writes were disabled.

This supplementary execution uses the separately retained original study
package. The self-contained synthetic runner above does not require that
archive. With the original package available, the matrix command is:

```console
PYTHONDONTWRITEBYTECODE=1 /path/to/candidate-env/bin/python \
  /path/to/retained-study/run_study.py \
  --out /path/to/new/met162-original-matrix-final --trials 2
```

| Original-study check | Candidate result |
| --- | --- |
| Historical semantic records | 84/84 match exactly: 42 independent-baseline records and 42 Metriplane records |
| Repeatability | 42/42 workflow/case pairs match across the two trials |
| Input acceptance and rejection | 84/84 decisions match the frozen expectations, including deliberate invalid cases |
| Additive requirement assessments | 22/22 accepted candidate runs have the expected sampled-policy outcome and observed wait |
| ManiSkill incident/control comparison | `incompatible` / `not_comparable`; observed wait is 0.25 s in both recordings |
| robomimic incident/control comparison | `incompatible` / `not_comparable`; observed wait is 2.1 s in both recordings |
| Generated evidence | Four incident bundles verify and four generated regressions pass |
| Copied ZIP tamper probe | Original verifies; changing the copied state segment without updating its hashes fails verification with exit 3 |
| Historical files | All 1,978 package-manifest entries verify; all 1,982 existing study files remain byte-identical, with no added files |

Pending recordings now explicitly report `unresolved`, and the untriggered case
reports `not_exercised`. Equality and between-sample cases preserve their legacy
events; between-sample arrivals report `satisfied` under the sampled policy with
the explicit late-arrival note. This does not replace the original study's
separate literal-deadline characterization or claim a continuous-time deadline
fix. The incident/control comparisons preserve legacy deviation durations
while refusing to reinterpret their rule changes as improved performance.

The retained supplementary output includes `original-semantic-comparison.json`,
`explicit-assessment-audit.json`, `input-acceptance-audit.json`, native comparison
and verification outputs, and the before/after file-preservation audit.

| Supplementary artifact | SHA-256 |
| --- | --- |
| `closure-summary.json` | `df6e2531c1b05633af51f8ac59e21b234a080d5b831d86e8dc5de886e2cb9c55` |
| `preservation-audit.json` | `fd861ab2bc488397658b2ba5d0360b40916f8195d4d5b2f7f80f257b7dd4a5c9` |
| Supplementary `CHECKSUMS.sha256` inventory | `41b41da3e31d63ad1be8940f05e66362a3f955a0c69e3ca3ded22e09e4fb5c62` |

This is a replay of retained normalized recordings and their documented study
variants. It is not a fresh upstream dataset conversion or a new field study.
Earlier candidate proof directories remain retained and unchanged; their 1,870
and 1,413 checksummed files were verified again after the final execution.

These synthetic checks support bounded software correctness, compatibility,
and reviewer reproducibility. They do not measure external adoption, operator
time savings, physical accuracy, field reliability, or independent human review.
