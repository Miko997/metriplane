<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Strict structured-data parsing

Metriplane uses `metriplane.strict_parsing` as the shared lexical and resource
boundary for JSON, JSONL, and YAML. The parser rejects invalid UTF-8, duplicate
mapping keys, non-finite JSON constants, unsafe YAML tags, YAML aliases, and
documents above finite byte, depth, node, scalar, or JSONL-line limits.

`REPOSITORY_DOCUMENT_LIMITS` is calibrated for the current governed corpus: its
64 MiB document ceiling is above the largest tracked structured document while
remaining finite. Protocols with smaller messages should pass a narrower frozen
`ParseLimits` value. Every limit is covered by N-1/N/N+1 tests.

Use the path helpers for filesystem inputs so size and regular-file checks occur
before allocation. The text/bytes helpers are appropriate only when the caller
has already received a bounded value. Custom YAML loaders must inherit from
`yaml.SafeLoader`; unsafe loaders are rejected.

The root wheel uses this module for every JSON, JSONL, and YAML parse boundary.
That scope includes `metriplane` (including Atlas) and the packaged Isaac and
Omniverse integration modules. The separately packaged ROS 2 source tree is not
part of the root wheel. JSONL file consumers use the descriptor-backed iterator,
so the byte and line ceilings apply to the complete input rather than to each
record in isolation. The test census covers the root-wheel package roots and
rejects direct `json.load(s)` and `yaml.load`/`safe_load` calls, Pydantic
`model_validate_json` bypasses, and unbounded `read_text()`-to-parser chains.

One discovered group is deliberately not rewritten by this change:

- isolated source adapters authenticate exact config/source identities and ship
  as separate distributions. Their package-local validation stays in place;
  the cross-adapter and installed-adapter suites remain the compatibility
  boundary. Internal JSON serialize/deserialize copies are not input parsers.

Repository-only governance tools keep their existing fail-closed, protocol-
specific parsers. In particular, this task does not alter the Main Health
broker or stop-the-line authority boundary. Those parsers are not installed
product consumers and cannot become an alternate product parsing API.
