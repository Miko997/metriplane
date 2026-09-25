# Metriplane threat model

This document and the machine-readable [`security-controls.json`](../../security-controls.json)
form the MP2-028 security model. The registry is authoritative for identities and trace links;
this document explains the model. `python tools/check_security_controls.py` fails closed when a
row is incomplete, unreferenced, points to an unknown capability, lacks a real test path, or
diverges from this document.

## Scope and trust boundaries

The model covers the v0.5 product: local CLI and dashboard operation, runtime listeners, child
commands, filesystem ingestion and publication, external-source adapters, and CI/release
promotion. It does not claim that an explicitly remote deployment is safe without the remote-auth
policy, or that third-party data and hosted-provider identities are trusted merely because they
are reachable.

- `BND-01`: operator requests enter local Metriplane processes.
- `BND-02`: processes read or write configuration, recordings, state and evidence.
- `BND-03`: HTTP, metrics and WebSocket clients cross a network listener.
- `BND-04`: the runner delegates bounded authority to an allowlisted child.
- `BND-05`: third-party recordings cross into adapter normalization.
- `BND-06`: repository bytes cross into hosted qualification and release promotion.

## Assets

- `AST-01` source recordings; `AST-02` evidence bundles; `AST-03` runtime state.
- `AST-04` credentials and capabilities; `AST-05` host resources.
- `AST-06` published packages; `AST-07` security and audit records.

Confidentiality is required for credentials and protected diagnostics. Integrity and provenance
are required for recordings, evidence, state, packages and audit records. Availability is bounded
rather than unlimited: hostile inputs must be rejected before exhausting host resources.

## Actors

- `ACT-01` is the authorized local operator.
- `ACT-02` is a partially trusted same-host process.
- `ACT-03` is an untrusted remote network client.
- `ACT-04` is an untrusted archive, recording or dataset producer.
- `ACT-05` is a partially trusted child command.
- `ACT-06` is a partially trusted CI or provider identity whose claims still require binding.

## Abuse cases

- `ABU-01` reuses or discovers a local mutation capability.
- `ABU-02` reaches a remotely exposed listener without authentication.
- `ABU-03` traverses outside extraction or consumes unbounded archive resources.
- `ABU-04` substitutes a symlink or path between validation and use.
- `ABU-05` floods output, leaks descendants, or exploits PID reuse during cleanup.
- `ABU-06` places secrets, paths or protected identity data into public evidence.
- `ABU-07` injects undeclared, oversized or non-canonical adapter input.
- `ABU-08` reuses qualification or attestation from different source or artifact bytes.

Each abuse case names its affected boundaries, actors and assets and has one or more controls in
the registry. No row may remain disconnected.

## Controls, capabilities and tests

- `CTL-01` per-session mutation capability and `CTL-02` credential non-disclosure protect local
  UI and runner operations.
- `CTL-03` numeric-loopback defaults or explicit remote authentication protect listeners.
- `CTL-04` no-follow traversal and `CTL-05` calibrated resource budgets protect ingestion.
- `CTL-06` atomic exact-byte publication protects evidence generations and manifests.
- `CTL-07` bounded, identity-checked child execution protects runner cleanup.
- `CTL-08` deterministic redacted export separates public evidence from protected diagnostics.
- `CTL-09` allowlisted, offline, unprivileged normalization protects adapter acquisition.
- `CTL-10` OIDC identity and digest verification protects promotion.

Every control has an accountable MP2 owner, at least one capability from the current
capability-test ledger, and at least one checked-in test path. The validator checks all three links;
the tests also prove rejection of missing references, stale digests and documentation drift.

## Residual risk and ownership

Metriplane cannot make a hostile host, compromised owner credential, intentionally exposed
listener, or malicious upstream provider trustworthy. Those remain deployment and provider risks.
Control owners must preserve fail-closed behavior and update this registry when capability or test
identity changes. MP2-028 owns model completeness and trace validation; the control-specific owner
owns implementation. MP2-029, MP2-031 and MP2-049 consume this model for supply-chain policy,
external acquisition and release readiness respectively.
