# Public surface inventory

This document is generated from the same static discovery object as the canonical
functional inventory. It inventories observations only and makes no runtime, platform,
hosted-provider, safety, or support claim.

## Canonical projection

- Task: `MP2-013` / `MET-78`
- Materialization: `c60407ff3f8cd4f6f67cfab644425ea88e6fa735439c285bdb4315561df7e471`
- Owned rows: `10073`
- Owned rows SHA-256: `59d99a0cd132ca680d90b428f5f07a06c24a84b7e2c639dd0f50ee4870f1dc26`
- Functional rows SHA-256: `eca022d1068ba820d185af90ba7eb7c43bf840cc89b1713fc1e57436c27aa6b8`
- Owned profile SHA-256: `4526ef03fe2582e866a0083ec501db7f9a9662641f8c0f34d09ded491b0aa7b8`
- Support profiles SHA-256: `de0fcf924d42f020995ad7fd8666d6f5ce9cc1831d2d3022e4c2477fd633b45d`
- Support disposition: `not_measured`

## Discovery families

| Family | Rows | Canonical row SHA-256 |
| --- | ---: | --- |
| `configs` | 167 | `01bd6fee2c9a6f84ac3275caf9f644f802de42e98defc6f268a3e1918a0cfe75` |
| `current_claims` | 309 | `87cff8dd6b3486c906ed50203daea6dbbe54f06b5d1b6b06563a0bfef000bfb2` |
| `examples` | 172 | `a048635863f52f43235c227c9cda8e59d005f6f8bf5642ada08fb1f8d0aed594` |
| `jobs` | 55 | `01d36d91b4128a949daeee308ff4429ec0196e7df516fec4b72e3ab0624ebd9b` |
| `manifest_keys` | 3580 | `6d8cf4e59ffccd2c1e7e95c2f4bfdda57ab191695b3e4bbec1fbad154db63ae0` |
| `model_fields` | 1389 | `0448195c64ed0f21abd2ce1f44740a0d58f69c81da1b7faca66b43d26354c45f` |
| `models` | 229 | `5bb6813f69acd7fff5fe6c0e996dec376f3c13cbfeb1640deceabb8cbd6a7f5a` |
| `proofs` | 322 | `53f3c0ca2b79820cabe475e3cebf757a8ce7cb891c4c65741a0d88a1af28ee2c` |
| `public_api` | 2286 | `d3325c6496b21dbdcfcc8ebb2791a9a11ebef72e140b074cb962b3ffa8b6d955` |
| `resources` | 1548 | `0b48b71cd1262217a0938850a066c8e2ce85aab321062eee685cd9d8bb247ec8` |
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
