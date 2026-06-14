# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from metriplane.contracts.load import ContractLoadError, load_spatial_contract


def validate_contract(path: str | Path) -> tuple[bool, list[str]]:
    """Validate a contract file. Returns (ok, messages)."""
    try:
        package = load_spatial_contract(path)
    except ContractLoadError as e:
        return False, [str(e)]
    msgs = [
        f"contract_id={package.contract_id} schema={package.schema_version} "
        f"rules={len(package.rules)} result=PASS"
    ]
    return True, msgs


def _main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m metriplane.contracts.validate <contract.yaml>")
        return 2
    ok, msgs = validate_contract(sys.argv[1])
    for m in msgs:
        print(m)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
