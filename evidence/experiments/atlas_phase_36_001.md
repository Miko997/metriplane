# Atlas Phase 36 Evidence 001

Status: PASS for local physical regression CI v2 foundation.

Implemented artifacts:

- `metriplane/atlas/regression.py`
- `regression_tests/INC-0001.yaml`
- `metriplane atlas test`

Verification:

- Tests generate regression specs from bundles and run them from ZIP-only evidence.
- The regression runner fails when expected evidence is absent.

Limitations:

- CI integration is through pytest and CLI commands; no separate workflow file is added in this branch.
