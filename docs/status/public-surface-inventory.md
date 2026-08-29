# Public surface inventory

This document is generated from the same static discovery object as the canonical
functional inventory. It inventories observations only and makes no runtime, platform,
hosted-provider, safety, or support claim.

## Canonical projection

- Task: `MP2-013` / `MET-78`
- Materialization: `c60407ff3f8cd4f6f67cfab644425ea88e6fa735439c285bdb4315561df7e471`
- Owned rows: `10073`
- Owned rows SHA-256: `821fdf39647133d392c8c56a04a4ffc583a5aef1d9b2e8fadabd93ecf0a12a7e`
- Functional rows SHA-256: `712a31cee659c0333ef977e581d8e737764df2863978b029891b80be5cf9e55e`
- Owned profile SHA-256: `2d2938eba05cfebbf9c2a38327590e6e850dd63ea1627081051781ec5420346f`
- Support profiles SHA-256: `ffc71f38abec00984698f6bab6f2c2265ab74579c64dfa9d38d9d45e2c56fe1d`
- Support disposition: `not_measured`

## Discovery families

| Family | Rows | Canonical row SHA-256 |
| --- | ---: | --- |
| `configs` | 167 | `bcdd85b5d01bb9de51540f3b2510cb323a86c418f48dff796d7f83926fe515f2` |
| `current_claims` | 309 | `5a955177ef0417ef57988290c053694d79664014c34e8dd742fb633fccb3de21` |
| `examples` | 172 | `a048635863f52f43235c227c9cda8e59d005f6f8bf5642ada08fb1f8d0aed594` |
| `jobs` | 55 | `01d36d91b4128a949daeee308ff4429ec0196e7df516fec4b72e3ab0624ebd9b` |
| `manifest_keys` | 3580 | `6d8cf4e59ffccd2c1e7e95c2f4bfdda57ab191695b3e4bbec1fbad154db63ae0` |
| `model_fields` | 1389 | `0448195c64ed0f21abd2ce1f44740a0d58f69c81da1b7faca66b43d26354c45f` |
| `models` | 229 | `5bb6813f69acd7fff5fe6c0e996dec376f3c13cbfeb1640deceabb8cbd6a7f5a` |
| `proofs` | 322 | `53f3c0ca2b79820cabe475e3cebf757a8ce7cb891c4c65741a0d88a1af28ee2c` |
| `public_api` | 2286 | `d3325c6496b21dbdcfcc8ebb2791a9a11ebef72e140b074cb962b3ffa8b6d955` |
| `resources` | 1548 | `314a334727316d9c0ca2db0b2cf458f492a1f9e94f41d9ab5e06979987146c68` |
| `workflows` | 16 | `63f5a5b3dd308f0263e04a59a485a7bc721eb5bf1ed2d1b1ea5a7ee0784cad03` |

## Resource facets

| Facet | Tracked paths |
| --- | ---: |
| `adapter` | 79 |
| `benchmark` | 36 |
| `configuration` | 151 |
| `container` | 4 |
| `dataset` | 2 |
| `documentation` | 274 |
| `evidence` | 285 |
| `example` | 137 |
| `fuzzing` | 1 |
| `integration` | 19 |
| `package` | 173 |
| `proof` | 37 |
| `repository_metadata` | 28 |
| `schema` | 4 |
| `test` | 183 |
| `tooling` | 78 |
| `web_asset` | 41 |
| `workflow` | 16 |

## Source census

| Source | Count |
| --- | ---: |
| `generated_targets_excluded` | 3 |
| `manifest_json_documents` | 14 |
| `manifest_python_modules` | 290 |
| `packaged_python_modules` | 203 |
| `tracked_paths` | 1551 |
| `tracked_python_paths` | 445 |
| `workflow_documents` | 16 |

## Configuration parsers

| Parser result | Files |
| --- | ---: |
| `UTF-8 text` | 5 |
| `checksum-pinned retained-invalid` | 2 |
| `safe tracked-symlink` | 3 |
| `static Python AST` | 5 |
| `strict CSV` | 1 |
| `strict JSON` | 4 |
| `strict TOML` | 22 |
| `strict YAML` | 125 |

## Parser and trust boundaries

- Python modules are parsed with `ast`; discovered modules are never imported or executed.
- Project/package declarations and maintained TOML configurations use `tomllib`.
- JSON rejects duplicate keys and non-finite constants; YAML rejects duplicate or non-string keys.
- Artifact CSV headers use the strict CSV parser; workflow and job declarations use strict YAML.
- Exact checksum-pinned retained-invalid v0.2 provenance configurations: `configs/examples/config.m8_fusion_live.yaml`, `configs/health_demo.yaml`; changed bytes or any additional malformed configuration fail closed.
- Dynamic `__all__`, wildcard imports, unproved manifest mappings or values, unsafe symlinks, and stale source digests fail closed.
- 4 non-literal manifest payload leaves are accepted only at exact source-hash and AST-location proofs; any changed source byte fails closed.
- 3 non-literal structured manifest payloads expand only to checksum-pinned producer keys; any changed consumer or producer source byte fails closed.
- The three generated targets are excluded from direct resource-byte rows to avoid self-reference and are bound by candidate parity checks.
- Generation privately stages every target and durably journals the prior set before replacement; interrupted prepared transactions recover the prior set, while committed transactions verify the new set before cleanup. Individual replacements are atomic, but POSIX does not provide one atomic rename spanning all three paths.
- Foreign functional rows and support profiles are preserved exactly; current claims are projected from canonical claim-object digests.
