<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Security Policy

## Supported versions

Security reports are accepted for the current `main` branch and the latest
version published on PyPI. Older releases are not supported. In particular,
v0.2.0 is a frozen research artifact and will not be rewritten; an applicable
fix belongs in a later software release.

Support means that a report will be assessed against the current project. It
does not promise a response time, remediation deadline, or bug bounty.

## Report a vulnerability privately

Do not open a public GitHub issue, discussion, or pull request for a suspected
vulnerability. Do not include secrets, private recordings, exploit details, or
personal data in any public project channel.

Use GitHub's verified private vulnerability reporting form:
[open a private report](https://github.com/Miko997/metriplane/security/advisories/new).
Reports are not public. GitHub limits the advisory discussion to the reporter
and authorized advisory participants until publication.

Include only the information needed to assess the report:

- affected Metriplane version or commit;
- operating system, Python version, and installation method;
- affected command, artifact, or component;
- impact and conditions required to reproduce it;
- minimal reproduction steps or a synthetic reproducer;
- whether the issue may have exposed or altered private data or evidence;
- any known mitigations.

Do not send real credentials or unnecessary production recordings. If sensitive
supporting material is necessary, first ask through the verified private route
how it should be transferred.

## What belongs here

Use private reporting for issues that could compromise confidentiality,
integrity, or availability, including unsafe archive handling, path traversal,
command injection, verification bypasses, credential disclosure, or a way to
produce a false evidence or regression result.

Ordinary bugs, documentation problems, and feature requests belong in the
public issue forms. A dependency advisory should be reported privately when it
has a concrete security impact on Metriplane; include the advisory identifier
and the affected execution path.
