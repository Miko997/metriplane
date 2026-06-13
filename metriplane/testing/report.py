from __future__ import annotations

import json
from pathlib import Path

from metriplane.testing.models import PhysicalRegressionResult


def write_json(result: PhysicalRegressionResult, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result.model_dump(by_alias=True), indent=2))
    return p


def render_md(result: PhysicalRegressionResult) -> str:
    name = Path(result.bundle_path).name
    lines = [
        f"# Physical regression test: {name}",
        "",
        f"Result: {'PASS' if result.pass_ else 'FAIL'}",
        "",
        "## Checks",
        "",
    ]
    for c in result.checks:
        mark = "PASS" if c["pass"] else "FAIL"
        lines.append(f"- {mark} {c['check']}: {c['detail']}")
    lines += ["", "## Observed", ""]
    for k, v in result.observed.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def write_md(result: PhysicalRegressionResult, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_md(result))
    return p


def print_summary(result: PhysicalRegressionResult) -> None:
    name = Path(result.bundle_path).name
    print(f"Physical regression test: {name}")
    for c in result.checks:
        print(f"  {'PASS' if c['pass'] else 'FAIL'} {c['check']}: {c['detail']}")
    print(f"Result: {'PASS' if result.pass_ else 'FAIL'}")
