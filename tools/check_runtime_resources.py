#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Generate or verify the exact runtime-resource classification."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "metriplane.runtime-resource-registry.v1"
REGISTRY_PATH = Path("docs/status/runtime-resource-registry.json")
SOURCE_ROOTS = ("web/dashboard", "configs", "calib")
DATASET_SOURCE = "datasets/demo/atlas/assembly_cell_missing_tool.jsonl"

PACKAGED_COPIES = {
    "configs/atlas/saved_queries.yaml": "metriplane/resources/configs/atlas/saved_queries.yaml",
    "configs/fusion_health_300fps.yaml": "metriplane/resources/configs/fusion_health_300fps.yaml",
}
REUSED_PACKAGED = {
    "configs/domain_packs/assembly_cell/assets.yaml": (
        "metriplane/demo/assets/assembly_cell/assets.yaml"
    ),
    "configs/domain_packs/assembly_cell/contracts.yaml": (
        "metriplane/demo/assets/assembly_cell/contracts.yaml"
    ),
    "configs/domain_packs/assembly_cell/process.yaml": (
        "metriplane/demo/assets/assembly_cell/process.yaml"
    ),
    "configs/domain_packs/assembly_cell/work_orders.csv": (
        "metriplane/demo/assets/assembly_cell/work_orders.csv"
    ),
    "configs/domain_packs/assembly_cell/workspace.yaml": (
        "metriplane/demo/assets/assembly_cell/workspace.yaml"
    ),
    DATASET_SOURCE: "metriplane/demo/assets/assembly_cell_missing_tool.jsonl",
}
TOOL_INTERFACES = {
    f"tools/{name}.py": f"metriplane/runner/tools/{name}.py"
    for name in (
        "analyze_id_stability_jsonl",
        "calibrate_planar_homography",
        "debug_alignment",
        "list_cameras",
        "report_alignment",
        "zones_report_jsonl",
    )
}


def _git_rows(root: Path) -> list[tuple[str, str, str]]:
    result = subprocess.run(
        ["git", "ls-files", "-s", "--", *SOURCE_ROOTS, DATASET_SOURCE],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    rows: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        metadata, path = line.split("\t", 1)
        mode, object_id, stage = metadata.split()
        if stage != "0":
            raise ValueError(f"unmerged runtime resource: {path}")
        rows.append((path, mode, object_id))
    return sorted(rows)


def _blob(root: Path, object_id: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", object_id], cwd=root, check=True, capture_output=True
    ).stdout


def _classification(path: str) -> tuple[str, str | None]:
    if path.startswith("web/dashboard/") and path != "web/dashboard/README.md":
        return "packaged", "metriplane/resources/dashboard/" + path.removeprefix("web/dashboard/")
    if path in PACKAGED_COPIES:
        return "packaged", PACKAGED_COPIES[path]
    if path in REUSED_PACKAGED:
        return "packaged_existing", REUSED_PACKAGED[path]
    if path.endswith("/README.md") or path == "web/dashboard/README.md":
        return "source_documentation", None
    if path.startswith("calib/"):
        return "explicit_site_input", None
    if path.startswith("configs/"):
        return "explicit_configuration_input", None
    raise ValueError(f"unclassified runtime resource: {path}")


def build_registry(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path, mode, object_id in _git_rows(root):
        classification, installed_path = _classification(path)
        entry: dict[str, Any] = {
            "classification": classification,
            "git_mode": mode,
            "git_object": object_id,
            "path": path,
            "sha256": hashlib.sha256(_blob(root, object_id)).hexdigest(),
        }
        if installed_path is not None:
            entry["installed_path"] = installed_path
        entries.append(entry)

    interfaces = []
    for source, installed_path in sorted(TOOL_INTERFACES.items()):
        source_bytes = (root / source).read_bytes()
        installed_bytes = (root / installed_path).read_bytes()
        if source_bytes != installed_bytes:
            raise ValueError(f"installed tool interface differs from source: {source}")
        interfaces.append(
            {
                "module": installed_path.removesuffix(".py").replace("/", "."),
                "source_path": source,
                "installed_path": installed_path,
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            }
        )

    for entry in entries:
        installed_path = entry.get("installed_path")
        if (
            installed_path is not None
            and (root / entry["path"]).read_bytes() != (root / installed_path).read_bytes()
        ):
            raise ValueError(f"packaged resource differs from source: {entry['path']}")

    return {
        "entries": entries,
        "interfaces": interfaces,
        "owner_task": "MP2-042",
        "schema_version": SCHEMA_VERSION,
        "source_roots": [*SOURCE_ROOTS, DATASET_SOURCE],
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("write", "check"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    expected = _canonical(build_registry(root))
    target = root / REGISTRY_PATH
    if args.mode == "write":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(expected)
        return 0
    try:
        current = target.read_bytes()
    except OSError as exc:
        print(f"runtime resource registry unavailable: {exc}")
        return 1
    if current != expected:
        print("runtime resource registry is stale")
        return 1
    print("runtime resource registry is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
