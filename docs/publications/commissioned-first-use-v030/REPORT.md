<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Commissioned First-Use Evaluation of Metriplane 0.3.0 Across Six Computing Environments

**Miko Parkkinen**  
Technical report, version 1.0.0  
16 August 2026

**Evaluated software:** `metriplane==0.3.0` from PyPI  
**Protocol:** MP-EXT-UX-001 v1.0  
**Evaluated tag commit:** `e8ee6c63deaee47bd450c5d6c7523d5bd699852a`

This technical report has not undergone peer review.

## Abstract

This report evaluates the first-use experience of Metriplane 0.3.0 using a predefined, camera-free packaged workflow. Six compensated external evaluators executed the workflow on independently controlled computing environments spanning Native Linux, macOS, WSL2 Ubuntu, x86_64, ARM64/AArch64, Python 3.12, and Python 3.13. Compensation was fixed independently of the evaluation outcome. All six records accepted under the frozen protocol completed the bounded workflow. Two additional commissioned executions were retained separately because their first attempts did not satisfy the protocol requirements. The evaluation also identified WSL2-specific report-access and documentation friction, which resulted in a subsequent documentation change. The results characterize this specific first-use workflow and the observed environments. They do not constitute a general reliability, compatibility, safety, physical-accuracy, adoption, or production-readiness evaluation.

## 1. Background and objective

Metriplane is an observe-only research-software toolkit for turning recorded workcell state into inspectable incidents, integrity-verifiable evidence bundles, and generated regression checks. The purpose of this evaluation was narrower than a product benchmark or deployment study. It asked whether a first-time external evaluator, using an eligible pre-existing environment, could install Metriplane 0.3.0 from PyPI and complete the packaged camera-free workflow without maintainer troubleshooting before the first-attempt evidence was preserved.

The study was designed to produce an auditable record of first-use behavior across a deliberately varied set of computing environments. It did not evaluate camera calibration, physical tracking accuracy, a live robot, a factory process, safety behavior, or compatibility with arbitrary robotics data.

## 2. Evaluated software and workflow

The evaluated artifact was `metriplane==0.3.0`, installed from PyPI. The v0.3.0 release tag resolves to commit `e8ee6c63deaee47bd450c5d6c7523d5bd699852a`.

The bounded workflow used three user-facing commands:

```text
metriplane --version
metriplane doctor
metriplane demo
```

The packaged demo required no camera, GPU, robot, ROS installation, Docker installation, or external dataset. It generated an incident timeline and report, an evidence bundle that could be verified, and a generated regression check that could be executed. Opening the HTML report in a browser was optional and was not part of the core completion criterion.

## 3. Study design

### 3.1 Recruitment and compensation

Evaluators were recruited through Fiverr and Freelancer to cover selected pre-existing environments. Each evaluator used a personally controlled machine or local environment. Compensation was fixed before execution and did not depend on success, favorable feedback, public praise, a GitHub star, or endorsement. A valid failure would have been paid under the same terms as a successful completion.

| Slot | Recruitment platform | Compensation |
| --- | --- | ---: |
| T01 | Fiverr | USD 10 |
| T02 | Fiverr | USD 12 |
| T03 | Freelancer | EUR 8 |
| T04 | Freelancer | EUR 20 |
| T05 | Freelancer | EUR 9 |
| T06 | Freelancer | EUR 20 |
| **Total** | Currencies kept separate | **USD 22; EUR 57** |

Platform fees are not included in these totals.

### 3.2 Frozen first-attempt rules

The protocol required one measured attempt, no rehearsal, no rerun after a meaningful failure, and stopping at the first meaningful failure. The eligible environment had to exist before execution. Maintainer or other troubleshooting assistance was not permitted before the initial evidence was preserved. Records that violated these conditions were retained as auxiliary commissioned evidence rather than converted into primary first-attempt passes.

The primary cohort consists of T01 through T06. AUX-A and AUX-B are reported separately.

## 4. Environments and results

### 4.1 Primary cohort

| Slot | Operating environment | Architecture | Python | Core result | Elapsed time |
| --- | --- | --- | --- | --- | --- |
| T01 | Ubuntu 24.04.4 LTS, Native Linux | x86_64 | 3.12.3 | PASS | Not recorded |
| T02 | Linux Mint 22.3, Native Linux | x86_64 | 3.12.3 | PASS | Not recorded |
| T03 | macOS 26.5.1 | ARM64/AArch64 | 3.12.13 | PASS | 25 s, exact |
| T04 | Debian GNU/Linux 13, Native Linux | ARM64/AArch64 | 3.13.15 | PASS | About 30 s |
| T05 | Ubuntu 24.04.3 under WSL2 | x86_64 | 3.12.3 | PASS | About 7 min 18 s |
| T06 | Fedora Linux 42, Native Linux | x86_64 | 3.13.11 | PASS | About 2 min |

All six accepted primary records completed the bounded packaged workflow in their observed environments. The accepted cohort included four Native Linux environments, one macOS environment, one WSL2 Ubuntu environment, four x86_64 systems, two ARM64/AArch64 systems, four Python 3.12 environments, and two Python 3.13 environments.

The six-of-six result describes only this selected, compensated cohort and this exact packaged workflow. It is not an estimate of a population-wide installation or reliability rate.

### 4.2 Recorded outcome coverage

T01 and T03 through T06 recorded successful doctor, demo, incident, evidence-bundle, and generated-regression outcomes. T02 directly established successful installation, readiness, and bundled demo completion, but its public record predates the later structured result format. The later sub-result fields were therefore left as `NOT_RECORDED` rather than reconstructed.

Assistance before evidence preservation was explicitly captured for five of the six primary records. All five recorded no assistance. T02 did not record this field in the later structured format.

First confusion was explicitly captured for five of the six primary records. Four recorded no confusion. T05 recorded WSL2 report-access confusion. T02 did not record this field.

Elapsed time was captured for four records: one exact value and three approximate values. It was not recorded for T01 or T02.

AI-assistance use was not separately captured as a structured public field. No value was inferred later.

## 5. Missing data and protocol notes

No evaluator was rerun or contacted to fill missing fields. The complete field-level record is available in `public_results.csv`.

| Slot | Methodology note |
| --- | --- |
| T01 | Pre-screening stated Ubuntu 22.04.4, while the preserved one-time execution used an eligible pre-existing Ubuntu 24.04.4 environment. No rerun occurred. |
| T02 | The record predates the later structured template. Missing sub-results, assistance fields, first-confusion data, and timing were not reconstructed. |
| T03 | The evaluator had viewed the repository before the measured run but had not previously installed or executed Metriplane. |
| T04 | The copied public installation line appears to omit a closing quotation mark. Successful pinned package resolution establishes the intended command. |
| T05 | The core workflow completed, but the evaluator paused when opening the generated Linux report path from Windows and found the stable report filename unclear. |
| T06 | The strongest explicit confirmation that this was the evaluator's first Metriplane installation and run was captured after the measured execution. |

These notes are part of the result, not corrections to the original evaluator records.

## 6. Auxiliary commissioned executions

Two additional executions produced useful technical information but did not satisfy the frozen first-attempt rules.

| Record | Initial status | Later result | Reason for exclusion |
| --- | --- | --- | --- |
| AUX-A | Invalid precondition | Follow-up completed | WSL2 and the required Python environment were provisioned during execution, and work continued after failed preconditions. |
| AUX-B | Failed first attempt | Second run completed | Virtual-environment creation failed in a non-writable Windows system directory. Written working-directory guidance was supplied and a second run was performed. |

The later successful technical results are retained in `auxiliary_records.csv`. They are not included in the six-record primary denominator.

## 7. Usability finding and engineering response

The WSL2 records identified a small documentation and report-access cluster. A Windows user could complete the core workflow but still pause when translating a Linux output path into a Windows-accessible path. The stable filename `cell_truth_report.html` also did not immediately communicate that it was the generated incident report.

The observation was documented publicly in GitHub issue #60. PR #61 added WSL2 writable-directory guidance, explicit output-path guidance, Windows report-opening instructions, and stable-filename guidance. The documentation-only change was merged as commit `5e5396f0756b47ff02f6f0831ec62a44ea21c118`.

The response did not change Metriplane runtime behavior, the report filename, evidence verification, generated regression behavior, the v0.3.0 tag, or the original cohort. No post-fix execution was added to the v0.3.0 result denominator.

## 8. Interpretation and limitations

This evaluation provides evidence about a specific packaged first-use path under recorded conditions. It shows that six compensated external evaluators completed that path in six observed environments accepted under the frozen protocol. It also shows that protocol-invalid executions can reveal useful usability information without being counted as primary passes.

The study has several important limitations:

- The sample was small, selected, compensated, and not random.
- The result does not measure organic adoption, customer demand, or institutional use.
- Only the packaged camera-free workflow was evaluated.
- No live camera, physical measurement, robot, factory, control system, or safety function was evaluated.
- No generic ROS 2, Isaac Sim, robotics-data, Linux, macOS, ARM64, or WSL2 compatibility claim follows from these observations.
- Some structured fields were not recorded for all records, most notably T02.
- Browser dispatch from WSL2 remains dependent on the local Windows and WSL configuration.
- Successful first use does not establish production readiness or absence of other defects.

## 9. Data availability and reproducibility

This publication package contains:

- `REPORT.md`, the canonical human-readable report;
- `commissioned_first_use_evaluation.pdf`, the rendered report;
- `public_results.csv`, the six accepted primary records;
- `auxiliary_records.csv`, the two excluded auxiliary records;
- `summary.json`, machine-readable aggregate values;
- `SOURCE_MANIFEST.json`, public source provenance;
- `SHA256SUMS`, integrity hashes for the package.

The public tables use cohort labels rather than evaluator names. Public GitHub result links are retained for technical traceability. Marketplace orders, billing records, legal identities, private messages, and private administrative records are not distributed because they contain personal or financial information.

The report package was prepared from Metriplane repository merge commit `d2a13b800853a2acea1240ec8af6c34ef442dd77`.

## 10. Conclusion

Six compensated external evaluators produced six accepted primary records for the same frozen Metriplane 0.3.0 packaged first-use workflow. All six accepted records completed the bounded workflow in their observed environments. Two additional commissioned executions were retained separately because their initial execution histories did not satisfy the protocol. The study also identified WSL2-specific report-access and documentation friction that led to a documentation-only engineering response.

The result should be interpreted as a bounded first-use evaluation, not as evidence of general reliability, adoption, physical accuracy, safety, broad compatibility, or production readiness.

## Public references

1. Metriplane v0.3.0 release: https://github.com/Miko997/metriplane/releases/tag/v0.3.0
2. Public commissioned-result thread: https://github.com/Miko997/metriplane/issues/27
3. WSL2 documentation finding: https://github.com/Miko997/metriplane/issues/60
4. Documentation response: https://github.com/Miko997/metriplane/pull/61
5. Documentation merge commit: https://github.com/Miko997/metriplane/commit/5e5396f0756b47ff02f6f0831ec62a44ea21c118
