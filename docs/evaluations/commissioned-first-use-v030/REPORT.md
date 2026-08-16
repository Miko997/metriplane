<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Commissioned First-Use Evaluation of Metriplane 0.3.0 Across Six External Computing Environments

**Protocol:** MP-EXT-UX-001 v1.0  
**Evidence class:** E2 commissioned external execution  
**Report version:** 1.0.0  
**Report date:** 2026-08-15

> **Compensation disclosure:** All six primary evaluators were compensated. Payment was fixed and did not depend on success, favorable feedback, public praise, a GitHub star, or endorsement. PASS and FAIL were paid equally.

> **Claim boundary:** This selected study does not establish organic adoption, customer use, company or institutional validation, market demand, production readiness, physical measurement accuracy, safety, generic robotics-data compatibility, generic ROS 2 compatibility, generic Isaac Sim compatibility, absence of other defects, or endorsement.

## 1. Executive summary

Six compensated external evaluators attempted the same frozen `metriplane==0.3.0` first-use workflow on independently controlled environments. All six accepted primary records completed the bounded packaged workflow in their observed environments.

The accepted cohort contained four Native Linux environments, one macOS environment, one WSL2 Ubuntu environment, four x86_64 systems, two ARM64/AArch64 systems, four Python 3.12 environments, and two Python 3.13 environments. Primary evaluator compensation totaled USD 22 and EUR 57. Currencies are not converted, and platform fees are excluded.

Two additional commissioned records are retained as auxiliary evidence because their execution histories violated the frozen first-attempt rules. They are not included in the six-record denominator.

## 2. Evaluation question

Could a first-time external evaluator on an eligible pre-existing environment install Metriplane 0.3.0 from PyPI and complete the packaged camera-free incident, evidence-verification, and generated-regression workflow without maintainer troubleshooting before first-attempt evidence capture?

## 3. Evaluated artifact and method

- Package: `metriplane==0.3.0`
- Installation source: PyPI
- Release tag: `v0.3.0`
- Resolved tag commit: `e8ee6c63deaee47bd450c5d6c7523d5bd699852a`
- Python boundary: 3.12 or 3.13
- Core commands: `metriplane --version`, `metriplane doctor`, `metriplane demo`
- Eligible environments: Native Linux, macOS, or an already-provisioned WSL2 Ubuntu environment

No camera, GPU, robot, Docker installation, or ROS installation was required. Browser opening was optional and outside the core result.

The frozen protocol required one measured attempt, no rehearsal, no rerun after a meaningful failure, stopping at the first meaningful failure, no maintainer or other troubleshooting before evidence preservation, fixed commands, and a pre-existing eligible environment. A valid product failure would remain a paid primary result. Protocol-invalid executions were retained separately as auxiliary evidence.

## 4. Recruitment and compensation

Evaluators were recruited through Fiverr and Freelancer for selected pre-existing, personally controlled environments. Compensation by accepted primary slot was:

| Slot | Platform | Compensation |
| --- | --- | ---: |
| T01 | Fiverr | 10 USD |
| T02 | Fiverr | 12 USD |
| T03 | Freelancer | 8 EUR |
| T04 | Freelancer | 20 EUR |
| T05 | Freelancer | 9 EUR |
| T06 | Freelancer | 20 EUR |
| **Total** | Currencies not converted | **USD 22; EUR 57** |

Compensation was outcome-neutral. Evaluator identity is not paired with compensation in this public package.

## 5. Primary cohort

| Slot | Environment | Architecture | Python | Core result | Elapsed |
| --- | --- | --- | --- | --- | --- |
| T01 | Ubuntu 24.04.4 LTS, Native Linux | x86_64 | 3.12.3 | PASS | Not recorded |
| T02 | Linux Mint 22.3, Native Linux | x86_64 | 3.12.3 | PASS | Not recorded |
| T03 | macOS 26.5.1 | ARM64/AArch64 | 3.12.13 | PASS | 25 s exact |
| T04 | Debian GNU/Linux 13, Native Linux | ARM64/AArch64 | 3.13.15 | PASS | About 30 s |
| T05 | Ubuntu 24.04.3 under WSL2 | x86_64 | 3.12.3 | PASS | About 7 min 18 s |
| T06 | Fedora Linux 42, Native Linux | x86_64 | 3.13.11 | PASS | About 2 min |

## 6. Bounded results

- **Core completion:** 6 of 6 accepted primary records completed the bounded packaged workflow in their observed environments.
- **Environment count:** 4 Native Linux, 1 macOS, and 1 WSL2 Ubuntu.
- **Architecture count:** 4 x86_64 and 2 ARM64/AArch64.
- **Python count:** 4 Python 3.12 and 2 Python 3.13.
- **Compensation totals:** USD 22 and EUR 57, kept separate.
- **Elapsed-time coverage:** 1 exact, 3 approximate, and 2 not recorded.
- **Assistance coverage:** Five of six primary records explicitly captured assistance before evidence preservation, and all five recorded `NO`. T02 remains `NOT_RECORDED`.
- **First-confusion coverage:** Five of six primary records captured the field. Four recorded no confusion, one recorded WSL2 report-access confusion, and T02 remains `NOT_RECORDED`.

T02 establishes successful installation, readiness, and bundled demo completion. It does not separately establish every later structured sub-result. The affected values remain `NOT_RECORDED` in `public_results.csv`.

AI-assistance use was not separately captured as a structured public field. No value was inferred later.

## 7. Missing data and methodology notes

No missing value was inferred, and no evaluator was rerun to fill a gap. The complete machine-readable missing-field lists are in `public_results.csv`.

| Slot | Human-readable methodology note |
| --- | --- |
| T01 | **Environment disclosure.** Pre-screening stated Ubuntu 22.04.4. The preserved one-time execution used an eligible pre-existing Ubuntu 24.04.4 environment. No rerun occurred. |
| T02 | **Missing structured fields.** The public record predates the later structured template. Several later sub-results, assistance fields, and timing were not reconstructed. |
| T03 | **Prior repository exposure.** The evaluator had viewed the repository but had not previously installed or executed Metriplane. A timing wrapper would not have stopped on failure, but no command failed. |
| T04 | **Public transcription detail.** The copied public installation command appears to omit a closing quotation mark. Successful pinned package resolution establishes the intended command. |
| T05 | **WSL2 usability note.** Core execution remained valid. Report-access and stable-filename observations led to a documentation-only response. |
| T06 | **First-use confirmation timing.** The strongest first-ever-install and run confirmation was captured after the measured run. |

## 8. Auxiliary commissioned records

| Record | First-attempt status | Later result | Reason excluded from primary denominator |
| --- | --- | --- | --- |
| AUX-A | Invalid precondition | Follow-up completed | The required WSL2 and Python environment was provisioned during execution, and work continued after failed preconditions. |
| AUX-B | Failed | Second run completed | Execution continued after failure, written working-directory guidance was supplied, and a rerun was performed. |

The later technical completions remain useful auxiliary evidence, but they are not protocol-compliant primary first-attempt passes.

## 9. Engineering response

The WSL2 observations led to GitHub issue [#60](https://github.com/Miko997/metriplane/issues/60), pull request [#61](https://github.com/Miko997/metriplane/pull/61), and merge commit [`5e5396f`](https://github.com/Miko997/metriplane/commit/5e5396f0756b47ff02f6f0831ec62a44ea21c118).

The remediation changed documentation only. It added writable-directory guidance, explicit output-path guidance, Windows report-opening guidance, and stable-filename guidance. Runtime code, CLI behavior, the `cell_truth_report.html` filename, evidence verification, generated regression behavior, the v0.3.0 tag, and the original cohort remained unchanged. No post-fix run was added to the original denominator.

## 10. Limitations

The sample was small, selected, compensated, and not random. Results apply only to the observed environments and bounded packaged workflow. No physical robot, factory, camera, physical measurement, third-party robotics source, ROS 2 integration, Isaac Sim integration, safety case, certification, or production deployment was evaluated. Some fields were not recorded for every record, WSL2 browser dispatch remains environment-dependent, and other defects may remain.

## 11. Claim boundaries

The permitted claim is the bounded result stated in the executive summary. Required disclosures are that the study was commissioned and compensated, the workflow was bounded, and the environments were selected and observed. The full prohibited-claim list is in `CLAIMS.md`.

## 12. Evidence and reproducibility

`public_results.csv` is the canonical six-row primary table. `auxiliary_records.csv` is the canonical two-row auxiliary table. `summary.json` is generated from those files. `SOURCE_MANIFEST.json` maps the material claims to public GitHub sources, local public data files, and generic private archive references that disclose no private identifiers. Artifact hashes are in `SHA256SUMS`.

The public package contains cohort slots and public technical sources only. Private crosswalks, private source records, contracts, billing records, order records, messages, and internal project-management links are not included.

## 13. Conclusion

The six accepted commissioned records support only the bounded statement that the packaged Metriplane 0.3.0 workflow completed in the six observed environments under the recorded conditions. The WSL2 usability finding produced a documentation-only response. The result must not be upgraded into adoption, organizational validation, production-readiness, safety, or general-platform claims.
