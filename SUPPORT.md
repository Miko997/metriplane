<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Support

## Choose the right place

- Ask installation and usage questions in [GitHub Discussions Q&A][q-and-a].
- Propose or discuss an idea in [GitHub Discussions Ideas][ideas] before opening
  a broad integration request.
- Use the matching [GitHub issue form][issues] for a reproducible bug,
  documentation/comprehension problem, scoped integration request, or external
  reproduction/user trial.
- Follow [SECURITY.md](SECURITY.md) for vulnerabilities. Never disclose a
  suspected vulnerability in an issue or discussion.

Search existing issues and discussions before starting a new one. Keep one
problem per report.

## What to include

For a technical problem, provide:

- `metriplane --version` output and whether it was installed from PyPI, a wheel,
  or a source checkout;
- operating system and version, Python version, and architecture;
- the exact command that was run;
- expected behavior and complete actual error text;
- relevant `metriplane doctor` output, with private paths or identifiers
  redacted;
- whether `metriplane demo` succeeds;
- the smallest synthetic input and process-rule fragment that reproduces the
  problem, when needed.

Use fenced text blocks rather than screenshots for commands and errors. Do not
upload credentials, private recordings, faces, audio, customer or site names,
network details, or reports containing sensitive paths. Replace real object and
work-order identifiers with synthetic values.

## Current support boundary

Metriplane's documented beginner path is the bundled camera-free recorded-run
demo and the existing CLI for timestamped object state and bounded process
rules. Python 3.12 and 3.13 are supported. Linux/Ubuntu receives the complete CI
suite; macOS receives the camera-free suite and installed-wheel demo.

The retained WSL2 Ubuntu 24.04/Python 3.12.3 installed-wheel record and the
owner-reported native-Windows bundled-demo observation describe v0.3.0 only.
No fresh v0.4.0.post2 WSL2 or native-Windows validation is claimed. Automatic browser
opening remains environment-dependent; omit `--open` or open the printed report
path manually. A missing camera or GPU does not make the bundled demo
unavailable.

Raw or generic ROS 2, rosbag, MCAP, Isaac Sim, and generic 3D ingestion are not
part of the v0.4.0.post2 release promise. v0.4.0.post2 does support its strict,
already-normalized External Source Contract workflow and the repository's
bounded source-specific fixture cases; those cases do not establish generic
format or ecosystem compatibility. Robot control, safety logic, and quality
certification remain outside the product boundary.

Experimental or repository-only components may change and may have narrower
test coverage. Public support is best-effort community support; the project does
not promise a response time, custom integration work, hardware debugging, or
production deployment approval.

## Reports about results or evidence

If a problem could create a false verification or regression pass, treat it as
security-sensitive and use the private route in SECURITY.md. For an ordinary
result mismatch, include the command, input schema version, process rules,
expected event or incident, and actual machine-readable error. Do not attach
private evidence bundles.

The DOI-archived v0.2.0 SoftwareX artifact is frozen and is supported only as an
exact historical reproduction target. Current package behavior and the TIM
paper's v0.1.3 evaluation must remain clearly separated from that archive.

[q-and-a]: https://github.com/Miko997/metriplane/discussions/categories/q-a
[ideas]: https://github.com/Miko997/metriplane/discussions/categories/ideas
[issues]: https://github.com/Miko997/metriplane/issues/new/choose
