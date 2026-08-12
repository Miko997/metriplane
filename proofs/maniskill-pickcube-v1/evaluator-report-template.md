<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# ManiSkill PickCube proof evaluator report

Do not delete unanswered fields. Write `not provided`, `not applicable`, or
`not performed` where appropriate. Remove secrets and private machine-local
paths before making the report public, and state what was redacted.

## 1. Evaluator and evaluation

- Evaluator name or attributable identifier:
- Organization, if voluntarily provided:
- Country:
- Evaluation performed: [ ] A, portable rerun  [ ] B, full source conversion
- Evaluation date in `YYYY-MM-DD`:
- Start and finish times with timezone:
- Active setup time:
- Total elapsed time:

## 2. Environment

- Operating system and exact version:
- Architecture:
- Python version (`python --version` output):
- Machine type: [ ] personally controlled local machine  [ ] CI  [ ] other
- Exact proof tag:
- Exact proof commit (`git rev-parse HEAD`, 40 characters):
- Did the commit match `proof-record.json`? [ ] yes  [ ] no
- Was the working tree clean before evaluation? [ ] yes  [ ] no
- Installation method and exact wheel filename:
- Output of `python -m pip check`:
- Were ManiSkill/SAPIEN/Torch/h5py/adapter dependencies absent in Evaluation A?
  [ ] yes  [ ] no  [ ] not applicable
- Other relevant environment details:

## 3. First-use record

- First command attempted:
- First failed command, or `none`:
- Exact exit code:
- Complete first-failure output or attached filename:
- First confusing term or instruction, or `none`:
- What did you expect instead?
- Maintainer assistance required? [ ] no  [ ] yes
- If yes, list every instruction or intervention received:
- Did you preserve the first meaningful failure before trying a workaround?
  [ ] yes  [ ] no  [ ] no failure
- Workarounds attempted after preserving the failure:

## 4. Portable validation and run result

### Incident fixture

- Validation: [ ] pass  [ ] fail  [ ] not performed
- Frames observed:
- Events observed:
- Event types in observed order:
- Deviations observed:
- Incidents observed:
- Incident types:
- Evidence bundle present? [ ] yes  [ ] no
- Evidence verification: [ ] pass  [ ] fail  [ ] not performed
- Generated regression present? [ ] yes  [ ] no
- Regression execution: [ ] pass  [ ] fail  [ ] not performed

### Control fixture

- Validation: [ ] pass  [ ] fail  [ ] not performed
- Frames observed:
- Events observed:
- Event types in observed order:
- Deviations observed:
- Incidents observed:
- Evidence bundle absent as expected? [ ] yes  [ ] no
- Generated regression absent as expected? [ ] yes  [ ] no

### Portability and wrapper

- `reproduce.py` exit code:
- `reproduction-result.json` attached or public path:
- Output directory moved after execution? [ ] yes  [ ] no
- Path-portability result after move: [ ] pass  [ ] fail  [ ] not performed
- Report usable after move? [ ] yes  [ ] no  [ ] not performed
- Dashboard usable after move? [ ] yes  [ ] no  [ ] not performed
- USDA artifact usable after move? [ ] yes  [ ] no  [ ] not performed
- Incident evidence/regression usable after move?
  [ ] yes  [ ] no  [ ] not performed
- Machine-local path leak scan: [ ] pass  [ ] fail  [ ] not performed
- Path or wording discrepancies found:

## 5. Full conversion result

Complete this section for Evaluation B; otherwise write `not performed`.

- Dataset revision acquired:
- ZIP byte size / SHA-256 before conversion:
- HDF5 byte size / SHA-256 before conversion:
- JSON byte size / SHA-256 before conversion:
- Episode / HDF5 group:
- Transitions / stored states / restored states:
- Was rendering performed? [ ] no  [ ] yes
- Were actions integrated? [ ] no  [ ] yes
- Three separate clean conversions completed? [ ] yes  [ ] no
- Equivalence finalizer result: [ ] pass  [ ] fail
- Compared artifact count:
- Incident fixture fingerprint:
- Control fixture fingerprint:
- Generated fixtures byte-identical to the tagged fixtures? [ ] yes  [ ] no
- ZIP SHA-256 after conversion:
- HDF5 SHA-256 after conversion:
- JSON SHA-256 after conversion:
- Source files unchanged? [ ] yes  [ ] no
- Conversion discrepancies:

## 6. Overall observed result

- Overall result: [ ] pass  [ ] fail  [ ] incomplete
- First discrepancy from `proof-record.json`, or `none`:
- Additional discrepancy details:
- Did you change source, fixture, polygon, waits, rules, or expected values?
  [ ] no  [ ] yes
- If yes, explain exactly what changed and exclude the modified run from an
  unqualified reproduction claim:
- If a failure was later resolved, preserve the original failure and describe
  the resolution separately:
- Files attached or public evidence URLs:

## 7. Independence, compensation, and permissions

- Had you installed or run Metriplane before this evaluation? [ ] no  [ ] yes
- Relationship to Metriplane or its maintainer, if any:
- Compensation declaration:
  [ ] no compensation
  [ ] compensated; amount/type and payer disclosed below
  [ ] prefer to disclose privately; do not represent this as public evidence
- Compensation details:
- Public attribution permission:
  [ ] yes, use my attributable identifier
  [ ] no, keep my identity private
- Organization attribution permission:
  [ ] yes
  [ ] no
  [ ] no organization provided
- Quotation permission:
  [ ] yes, exact quotations may be used with attribution
  [ ] yes, quotations may be used anonymously
  [ ] no quotation permission
- Privacy preference and requested redactions:
- May the machine-readable result be published? [ ] yes  [ ] no

## 8. Evaluator declaration

Check each statement that is true:

- [ ] I performed the evaluation described above on the recorded environment.
- [ ] I reported the first meaningful failure and did not hide a negative
  result.
- [ ] I did not modify rules or expected results to force success.
- [ ] I understand that PASS is not an endorsement and FAIL is useful technical
  evidence.
- [ ] I understand that this bounded evaluation does not establish official
  PickCube outcome, physical accuracy, safety, production readiness, or general
  ManiSkill compatibility.
- [ ] My compensation and publication permissions are recorded accurately.

- Evaluator identifier:
- Date:
