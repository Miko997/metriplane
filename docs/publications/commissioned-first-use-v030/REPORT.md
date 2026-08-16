<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Commissioned First-Use Evaluation of Metriplane 0.3.0 Across Six Computing Environments

**Miko Parkkinen**  
Technical report, version 1.0.0  
16 August 2026

| Item | Value |
| --- | --- |
| Evaluated software | `metriplane==0.3.0` from PyPI |
| Software identifier | `RRID:SCR_028813` |
| Protocol | `MP-EXT-UX-001 v1.0` |
| Evaluated tag commit | `e8ee6c63deaee47bd450c5d6c7523d5bd699852a` |
| Related prior software artifact | Metriplane 0.2.0, DOI [`10.5281/zenodo.20736619`](https://doi.org/10.5281/zenodo.20736619) |

## Abstract

This report evaluates the first-use experience of Metriplane 0.3.0 using a predefined, camera-free packaged workflow. Six compensated external evaluators executed the workflow on independently controlled computing environments spanning Native Linux, macOS, WSL2 Ubuntu, x86_64, ARM64/AArch64, Python 3.12, and Python 3.13. Compensation was fixed independently of the evaluation outcome. All six records accepted under the frozen protocol completed the bounded workflow.

Two additional commissioned executions were retained separately because their first attempts did not satisfy the protocol requirements. The evaluation also identified WSL2-specific report-access and documentation friction, which resulted in a subsequent documentation change. These results characterize the specified first-use workflow in the observed environments. They do not constitute a general reliability, compatibility, safety, physical-accuracy, adoption, or production-readiness evaluation. This technical report has not undergone peer review.

## 1. Background and evaluation objective

Metriplane converts recorded, normalized workcell state and process rules into an inspectable event and incident record, an integrity-verifiable evidence bundle, and a generated regression check. This study examined a narrower question: whether an external first-time evaluator on an eligible pre-existing computing environment could install Metriplane 0.3.0 from PyPI and complete the packaged camera-free workflow under a frozen procedure.

The evaluation did not assess camera calibration, physical measurement accuracy, robot control, factory deployment, unrestricted anomaly detection, generic robotics-data compatibility, safety, or certification.

## 2. Evaluated software and identifiers

The evaluated package was `metriplane==0.3.0`, installed from PyPI. The evaluated release tag resolves to commit `e8ee6c63deaee47bd450c5d6c7523d5bd699852a`.

Metriplane is registered as the research software resource **RRID:SCR_028813**. The RRID identifies Metriplane as a software resource; it does not identify this report or a particular software version.

The earlier frozen Metriplane 0.2.0 research artifact is archived separately under DOI [`10.5281/zenodo.20736619`](https://doi.org/10.5281/zenodo.20736619). That DOI identifies the v0.2.0 software artifact. It is not the identifier of the Metriplane 0.3.0 version evaluated here, and it is not the identifier of this report.

The packaged evaluation path used:

```text
metriplane --version
metriplane doctor
metriplane demo
```

No camera, GPU, robot, Docker installation, ROS installation, or browser launch was required for the core result. Browser opening was optional.

## 3. Study design

The frozen protocol required one measured attempt on an eligible pre-existing environment, no rehearsal, no rerun after a meaningful failure, and preservation of the first-attempt evidence before maintainer or other troubleshooting. A valid product failure would remain a paid result. Executions that violated the first-attempt rules were retained as auxiliary evidence rather than converted into primary passes.

Evaluators were recruited through Fiverr and Freelancer to cover selected operating systems, architectures, and supported Python versions. Compensation was fixed before execution and did not depend on success, favorable feedback, public praise, a GitHub star, or endorsement. PASS and FAIL were paid equally.

### Compensation

| Slot | Recruitment platform | Fixed compensation |
| --- | --- | ---: |
| T01 | Fiverr | 10 USD |
| T02 | Fiverr | 12 USD |
| T03 | Freelancer | 8 EUR |
| T04 | Freelancer | 20 EUR |
| T05 | Freelancer | 9 EUR |
| T06 | Freelancer | 20 EUR |
| **Total** | Currencies not converted | **USD 22; EUR 57** |

The totals exclude marketplace platform fees and are not converted between currencies.

## 4. Primary cohort and results

The accepted primary cohort contained six records.

| Slot | Environment | Architecture | Python | Result | Elapsed time |
| --- | --- | --- | --- | --- | --- |
| T01 | Ubuntu 24.04.4 LTS | x86_64 | 3.12.3 | PASS | Not recorded |
| T02 | Linux Mint 22.3 (Zena) | x86_64 | 3.12.3 | PASS | Not recorded |
| T03 | macOS 26.5.1 (build 25F80) | ARM64/AArch64 | 3.12.13 | PASS | 25 s |
| T04 | Debian GNU/Linux 13 (Trixie), 13.6 | ARM64/AArch64 | 3.13.15 | PASS | About 30 s |
| T05 | Ubuntu 24.04.3 LTS under WSL2 | x86_64 | 3.12.3 | PASS | About 7 min 18 s |
| T06 | Fedora Linux 42 Workstation | x86_64 | 3.13.11 | PASS | About 2 min |

All six accepted primary records completed the bounded packaged workflow in their observed environments.

The aggregate environment coverage was:

- four Native Linux environments, one macOS environment, and one WSL2 Ubuntu environment;
- four x86_64 systems and two ARM64/AArch64 systems;
- four Python 3.12 environments and two Python 3.13 environments.

Elapsed time was recorded exactly for one evaluator, approximately for three evaluators, and not recorded for two evaluators. The longest recorded run was the WSL2 execution, where dependency downloads accounted for most of the elapsed time.

### Structured field coverage

Assistance before evidence preservation was explicitly captured for five of six primary records. All five recorded `NO`; T02 remains `NOT_RECORDED`.

First confusion was explicitly captured for five of six primary records. Four recorded no confusion, one recorded WSL2 report-access confusion, and T02 remains `NOT_RECORDED`.

AI-assistance use was not separately captured as a structured public field. No value was inferred later.

## 5. Missing data and methodology notes

No missing value was inferred and no evaluator was rerun to fill a reporting gap. The canonical CSV preserves unknown values as `NOT_RECORDED`.

| Slot | Methodology note |
| --- | --- |
| T01 | The operating-system version reported during screening differed from the eligible pre-existing environment used for the preserved execution. The original execution was retained and was not repeated. |
| T02 | The public record predates the later structured reporting template. Installation, readiness, and demo completion are established, but several later sub-result, assistance, confusion, and timing fields remain `NOT_RECORDED`. |
| T03 | The evaluator had viewed the repository before the measured execution but had not previously installed or run Metriplane. |
| T04 | The copied public installation command appears to omit a closing quotation mark. Successful pinned package resolution establishes the intended execution; the transcription was not treated as an installation failure. |
| T05 | The core workflow completed. The evaluator nevertheless encountered WSL2-specific friction when locating and opening the generated report from Windows and when relating the stable filename to the visible report title. |
| T06 | The strongest explicit confirmation that this was the evaluator's first Metriplane installation and execution was captured after the measured run. |

T02's successful core result is retained, but unrecorded detailed fields are not converted into `NO`, `PASS`, or an empty value.

## 6. Auxiliary commissioned executions

Two additional commissioned executions are retained outside the primary denominator.

| Record | First-attempt status | Later technical result | Reason for exclusion |
| --- | --- | --- | --- |
| AUX-A | Invalid precondition | Follow-up completed | The required WSL2 and Python environment was provisioned during execution, and work continued after failed preconditions. |
| AUX-B | Failed | Second run completed | The first attempt failed in a non-writable Windows system directory; written working-directory guidance was provided and a second run was performed. |

The later successful technical outcomes are useful for understanding installation and WSL2 behavior, but they are not protocol-compliant primary first-attempt passes.

## 7. Usability finding and engineering response

The primary WSL2 record and the auxiliary WSL2 executions exposed a common documentation and report-access problem. Users could complete the Linux-side workflow but still hesitate when opening the generated HTML report from Windows, selecting a writable starting directory, or relating the stable filename `cell_truth_report.html` to the report title.

The observation was documented in [GitHub issue #60](https://github.com/Miko997/metriplane/issues/60), addressed in [PR #61](https://github.com/Miko997/metriplane/pull/61), and merged as commit [`5e5396f0756b47ff02f6f0831ec62a44ea21c118`](https://github.com/Miko997/metriplane/commit/5e5396f0756b47ff02f6f0831ec62a44ea21c118).

The remediation changed documentation only. It added writable-directory guidance, explicit output-path guidance, Windows report-opening guidance, and clarification of the stable filename. Runtime code, CLI behavior, evidence verification, generated regression behavior, the v0.3.0 tag, and the original cohort denominator remained unchanged. No post-fix execution was added to the original results.

## 8. Interpretation and limitations

The study was small, selected, commissioned, compensated, and not random. Its result is limited to the packaged workflow and the specific observed environments. A six-of-six result in this cohort is not an estimate of a population-wide installation rate.

The evaluation did not examine:

- unpaid or organic adoption;
- customer or organizational use;
- market demand;
- production readiness;
- physical robots, factories, cameras, or physical measurement;
- safety, certification, or quality release;
- broad operating-system or architecture support;
- generic ROS 2, Isaac Sim, or robotics-data compatibility;
- the absence of other defects.

The result should therefore be interpreted as a bounded first-use observation, not as a general product-validity claim.

## 9. Data availability and reproducibility

The publication package includes:

- `public_results.csv`, the canonical six-row primary table;
- `auxiliary_records.csv`, the canonical two-row auxiliary table;
- `summary.json`, aggregate values derived from the tables;
- `SOURCE_MANIFEST.json`, public source provenance;
- `SHA256SUMS`, file-integrity hashes;
- `LICENSE.txt`, the MIT License.

Public tables use only the record labels T01 through T06, AUX-A, and AUX-B. They do not include legal identities, billing records, private messages, order identifiers, or private evidence paths.

## 10. Conclusion

Six accepted commissioned records completed the same frozen Metriplane 0.3.0 packaged first-use workflow in six independently controlled computing environments. Two additional executions were retained separately because their first attempts did not satisfy the protocol. The study also produced a concrete WSL2 documentation improvement.

These findings describe the evaluated workflow and environments. They do not establish broad compatibility, adoption, physical accuracy, safety, or production readiness.

## Public references

1. [Metriplane v0.3.0 release](https://github.com/Miko997/metriplane/releases/tag/v0.3.0)
2. [Metriplane software RRID: SCR_028813](https://scicrunch.org/resolver/RRID:SCR_028813)
3. [Metriplane v0.2.0 frozen research artifact, DOI 10.5281/zenodo.20736619](https://doi.org/10.5281/zenodo.20736619)
4. [Public commissioned-evaluation discussion, GitHub issue #27](https://github.com/Miko997/metriplane/issues/27)
5. [WSL2 documentation finding, GitHub issue #60](https://github.com/Miko997/metriplane/issues/60)
6. [Documentation response, GitHub PR #61](https://github.com/Miko997/metriplane/pull/61)
