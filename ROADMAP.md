<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Roadmap

This roadmap prioritizes making Metriplane easy to discover, install, understand,
and try before expanding its technical scope. It is a planning document, not a
release promise. Work lands through small, reviewable pull requests.

## Product direction

Metriplane turns replayed or calibrated workcell state into an incident timeline,
a human-readable report, a checksummed evidence bundle, local verification, and a
repeatable regression check.

The v0.4.0 release path is:

```bash
python -m pip install "metriplane==0.4.0"
metriplane demo --open
```

A new user should reach a verified incident report and a passing generated
regression check in under two minutes, without cloning the repository or requiring
a camera, GPU, ROS 2, Docker, or browser-test tooling.

## Release boundaries

- `v0.2.0` remains the immutable DOI-archived research artifact for the
  SoftwareX submission.
- `v0.2.1` is the published packaging predecessor; its release record remains
  historical and is not a v0.3.0 or v0.4.0 research boundary.
- `v0.3.0` is the usability and adoption software release. It does not establish
  a new research measurement or DOI boundary.
- `v0.4.0` is the reduced Truth Recovery core release. It has no DOI and does
  not establish a new research measurement boundary.
- New and actively maintained product-facing text uses **Metriplane**. Historical
  frozen artifacts are not rewritten solely to change capitalization.
- Package names, imports, commands, URLs, schema identifiers, and environment
  variables retain their existing technical casing.

## Maintenance baseline

As of 9 August 2026, PRs #11–#14 and #16–#24 have been merged into `main` as
stabilization, adoption, documentation, release-engineering, and
community-readiness work. The v0.2.1 PyPI artifacts remain unchanged historical
release artifacts; v0.3.0 is a separate software release.

| Pull request | Merged outcome |
| --- | --- |
| [#11](https://github.com/Miko997/metriplane/pull/11) | Portable macOS maintainer checks and explicit pytest setup. The independent focused rerun on macOS/Python 3.13.7 passed (`4 passed`); issue #6 remains open as the external reproduction record. |
| [#12](https://github.com/Miko997/metriplane/pull/12) | Atlas now requires explicit overwrite before replacing unrelated existing temporary output. |
| [#13](https://github.com/Miko997/metriplane/pull/13) | Broken SoftwareX reproducibility links were repaired. |
| [#14](https://github.com/Miko997/metriplane/pull/14) | Atlas regression expectations now require distinct actual outputs. |
| [#16](https://github.com/Miko997/metriplane/pull/16) | Bundled demo, root CLI discovery, release-path hardening, and the Ubuntu/macOS Python 3.12/3.13 validation matrix. |
| [#17](https://github.com/Miko997/metriplane/pull/17) | Accurate environment support boundaries. |
| [#18](https://github.com/Miko997/metriplane/pull/18) | Human-readable quickstart, demo, CLI, report, and active UI wording. |
| [#19](https://github.com/Miko997/metriplane/pull/19) | Installed-package discovery, version reporting, doctor checks, and wheel resources. |
| [#20](https://github.com/Miko997/metriplane/pull/20) | Documentation front door and the supported after-demo tutorial. |
| [#21](https://github.com/Miko997/metriplane/pull/21) | Concurrent Atlas output no-clobber protection. |
| [#22](https://github.com/Miko997/metriplane/pull/22) | Owner-runnable first-time-user comprehension protocol and honest empty-results record. |
| [#23](https://github.com/Miko997/metriplane/pull/23) | Reusable build-once publication pipeline and release/citation preparation. |
| [#24](https://github.com/Miko997/metriplane/pull/24) | Community support, private security-reporting, conduct, issue, and pull-request policies. |

The v0.3.0 release incorporates that merged baseline and its own version and
release-copy changes.

The v0.4.0 release advances the bounded, local, observe-only Truth Recovery
core without rewriting the v0.3.0 usability record or the frozen research
boundaries above.

## Phase 1: instant evidence demo (implemented in v0.3.0)

Goal: make the core value visible from an ordinary PyPI installation.

- Bundle one small, camera-free session and one assembly-cell domain pack in the
  wheel using package resources.
- Add `metriplane demo` to run the complete incident-to-regression workflow in a
  fresh output directory.
- Add `--open` to open the generated local HTML report after successful completion.
- Keep `metriplane demo` headless so it also works in CI, containers, and SSH sessions.
- Print a short result summary: event count, incident count, bundle verification,
  regression result, and report path.
- Make repeated runs safe and explicit; never silently remove unrelated output.
- Keep the demo deterministic and offline after package installation.
- Return a non-zero exit status with an actionable message when a stage fails.

Completion gate:

- A clean environment completes the two-command path in under two minutes.
- The result contains six events, one incident, a verified bundle, and a passing
  generated regression check.
- Repeated runs produce equivalent deterministic results.
- The built-wheel demo is CI-tested outside a source checkout on Linux and macOS
  with Python 3.12 and 3.13.
- WSL2 Ubuntu 24.04 has a bounded owner-run validation for the Python 3.12.3
  installed-wheel camera-free and headless path. Automatic browser opening is
  not claimed because the validation environment had no default HTML handler.
  One owner-reported native-Windows Command Prompt demo completion is recorded,
  but it does not establish broader platform support.

## Phase 2: discoverable command line and first screen (implemented in v0.3.0)

Goal: let users understand the primary workflow without reading the source tree.

- Make `metriplane --help` list a small set of primary actions, including `demo`,
  `doctor`, `atlas`, `start`, and schema or protocol export.
- Keep advanced and maintainer commands available under their existing namespaces.
- Rewrite the README first screen around the outcome, two-command demo, expected
  result, three concrete use cases, and the `v0.3.0`/`v0.2.0` distinction.
- Add a short result animation or recording only after the command output is stable.
- Use **Metriplane** consistently across current user-facing package, website, and
  documentation surfaces.

Completion gate:

- A first-time user can find and run the demo from `metriplane --help`.
- README commands are executed in CI from the built wheel.
- The first README screen explains the input, output, and scope without requiring
  manuscript context.

## Phase 3: documentation front door (implemented in v0.3.0)

Goal: replace the raw documentation directory as the primary navigation surface.

- Publish a small documentation site with Quickstart, Concepts, CLI, Domain packs,
  Integrations, Troubleshooting, Contributing, and Research artifact sections.
- Generate or validate CLI reference material from the shipped command interface.
- Consolidate integration status into one authoritative, CI-linked table.
- Remove obsolete Omniverse Launcher instructions and clearly identify supported,
  experimental, historical, and external integrations.
- Keep the SoftwareX reproduction path available as a separate frozen-artifact path.

Completion gate:

- PyPI and the repository point to the documentation landing page rather than a raw
  directory listing.
- Every quickstart is tested or explicitly marked as manual.
- No current integration guide requires deprecated tooling.

## Phase 4: supported environments and contribution path (implemented in v0.3.0)

Goal: make expected compatibility and contribution steps explicit.

- Maintain the full supported suite on Linux with Python 3.12 and 3.13.
- Maintain the macOS camera-free suite and installed-wheel demo on Python 3.12
  and 3.13; do not claim live-camera support without hardware validation.
- Keep the WSL2 claim bounded to the recorded Ubuntu 24.04/Python 3.12.3
  installed-wheel camera-free and headless run; archived v0.2.0 WSL2
  reproduction instructions do not establish broader v0.3.0 support.
- Keep native Windows limited to the owner-reported bundled-demo observation
  until it receives an explicit environment record and broader validation.
- Add issue forms, a pull-request template, `SECURITY.md`, a Code of Conduct, support
  guidance, and an actionable contribution guide.
- Publish bounded starter issues only when their acceptance tests and scope are clear.

Completion gate:

- Supported platform/version combinations are stated in
  [`docs/SUPPORTED_ENVIRONMENTS.md`](docs/SUPPORTED_ENVIRONMENTS.md) and enforced
  in CI.
- A contributor can set up tests, choose an issue, and prepare a pull request from the
  documented path.

## Phase 5: one ecosystem wedge (future; outside v0.4.0)

Goal: let teams apply Metriplane to recorded data they already have.

- Add one read-only rosbag2/MCAP importer for already-estimated poses or typed events.
- Do not make raw-camera perception the first importer milestone.
- Include one small redistributable recording fixture and a five-minute tutorial.
- Add machine-readable regression output suitable for pytest/JUnit and CI systems.
- Provide several small, CI-tested examples before adding more domain breadth.

Completion gate:

- A user can convert the supported recording fixture into an incident report, verify
  its bundle, and run its regression check from documented commands.
- Import is read-only and does not control robots or modify source recordings.

## Adoption validation

Product readiness is measured by successful use, not repository traffic alone.

- Record at least three independent clean quickstart runs.
- Record at least five bounded trials using data not created for the bundled demo.
- Track time-to-first-report and the command or concept where users stop.
- Prefer fixes that remove a repeated setup or comprehension failure over adding a
  new feature with no demonstrated user path.

## Non-goals for this roadmap

- Changing the frozen `v0.2.0` tag or archived evidence.
- Robot or machine control, safety certification, or production-factory validation.
- A broad rewrite of working internals before the instant demo is usable.
- Adding integrations without a small fixture, documentation, and a validation path.
