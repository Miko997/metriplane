# Metriplane v0.2.0 SoftwareX revision evidence

Author: Miko Parkkinen  
Version: 2026-09-06  
Material: revision-only control inputs, recorded outputs, and a core reproduction wrapper.

This directory deposits the exact supplementary archive accompanying the
SoftwareX revision of the Metriplane v0.2.0 paper. It contains the 30 August 2026
no-incident and deliberately failing expectation controls, and the separately
recorded 6 September 2026 core reproduction execution.

## Download and verify

Download [SoftwareX_Revision_Supplement.zip](SoftwareX_Revision_Supplement.zip)
and [SHA256SUMS.txt](SHA256SUMS.txt), then verify before extracting:

```sh
sha256sum -c SHA256SUMS.txt
unzip SoftwareX_Revision_Supplement.zip
```

Archive SHA-256:
`e5ed910ae2e3d404c51e5838a36a8c0bef959ac75f6ae4876a658dc165452786`

The archive includes its reproduction instructions, recorded environments,
command outputs and nested checksum inventories. It is byte-identical to the
revision supplement supplied with the manuscript.

## Artifact boundary

The evaluated software remains Metriplane v0.2.0 at commit
`8e35ed5bb20837f7dc46354777407b848d7ce17a`.
The original archived release is identified by
[doi:10.5281/zenodo.20736619](https://doi.org/10.5281/zenodo.20736619).
This separate evidence deposit neither changes that release nor replaces its
original checked-in author evidence. The original controls used Python 3.13.13;
the later core execution used Ubuntu 24.04.3 and Python 3.12.13.

These records characterize one configured workcell and a presence-based oracle.
They do not establish complete event-sequence equivalence, physical ground
truth, causal inference, or general workcell effectiveness.

## Citation and licence

Cite this material as: Parkkinen M. Metriplane v0.2.0 SoftwareX revision evidence:
controls and core reproduction. Version 2026-09-06. GitHub; 2026.
Use the full commit-specific permalink for this directory to identify the exact
deposited version, together with the archive checksum above.

The repository's existing [MIT licence](../../LICENSE) and the copyright/SPDX
notices retained in the archived files apply. The archive has not been repacked
or relicensed for this deposit.
