# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Wheel-contained Metriplane adoption demo."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


_EXPECTED_EVENT_COUNT = 6
_EXPECTED_INCIDENT_COUNT = 1
_RESOURCE_PACKAGE = "metriplane.demo"


class _DemoError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class DemoResult:
    out_dir: Path
    report_path: Path
    bundle_path: Path
    regression_path: Path
    event_count: int
    incident_count: int


def _next_default_out_dir(root: Path | None = None) -> Path:
    parent = (root or Path.cwd()).resolve()
    candidate = parent / "metriplane-demo"
    suffix = 2
    while candidate.exists():
        candidate = parent / f"metriplane-demo-{suffix}"
        suffix += 1
    return candidate


@contextmanager
def _bundled_inputs() -> Iterator[tuple[Path, Path]]:
    asset_root = resources.files(_RESOURCE_PACKAGE).joinpath("assets")
    with resources.as_file(asset_root) as extracted_root:
        root = Path(extracted_root)
        session = root / "assembly_cell_missing_tool.jsonl"
        pack = root / "assembly_cell"
        required = [
            session,
            pack / "assets.yaml",
            pack / "workspace.yaml",
            pack / "process.yaml",
            pack / "contracts.yaml",
            pack / "work_orders.csv",
        ]
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise _DemoError(f"Bundled demo resources are missing: {', '.join(missing)}")
        yield session, pack


def run_demo(out_dir: str | Path) -> DemoResult:
    """Run and verify the bundled camera-free demo."""
    output = Path(out_dir).expanduser().resolve()
    if output.exists():
        raise _DemoError(
            "Refusing to replace an existing output directory. "
            f"Choose another path or remove it yourself: {output}",
            exit_code=2,
        )

    from metriplane.atlas.bundles import verify_bundle
    from metriplane.atlas.domain_packs import validate_domain_pack
    from metriplane.atlas.regression import run_regression
    from metriplane.atlas.runtime import run_atlas

    with _bundled_inputs() as (session, pack):
        pack_errors = validate_domain_pack(pack)
        if pack_errors:
            raise _DemoError(f"Bundled domain pack is invalid: {'; '.join(pack_errors)}")
        manifest = run_atlas(
            session,
            pack,
            output,
            run_id="metriplane_demo_v1",
        )

    if (
        manifest.event_count != _EXPECTED_EVENT_COUNT
        or manifest.incident_count != _EXPECTED_INCIDENT_COUNT
    ):
        raise _DemoError(
            "Unexpected demo result: "
            f"events={manifest.event_count}, incidents={manifest.incident_count}; "
            f"expected events={_EXPECTED_EVENT_COUNT}, "
            f"incidents={_EXPECTED_INCIDENT_COUNT}"
        )

    bundle_paths = sorted((output / "evidence_bundles").glob("*.zip"))
    if len(bundle_paths) != 1:
        raise _DemoError(f"Expected one evidence bundle, found {len(bundle_paths)}")
    bundle_path = bundle_paths[0]
    bundle_result = verify_bundle(bundle_path)
    if not bundle_result["pass"]:
        details = "; ".join(str(error) for error in bundle_result.get("errors", []))
        raise _DemoError(f"Evidence bundle verification failed: {details}", exit_code=3)

    regression_paths = sorted((output / "regression_tests").glob("*.yaml"))
    if len(regression_paths) != 1:
        raise _DemoError(f"Expected one generated regression, found {len(regression_paths)}")
    regression_path = regression_paths[0]
    regression_result = run_regression(regression_path)
    if not regression_result["pass"]:
        details = "; ".join(str(error) for error in regression_result.get("errors", []))
        raise _DemoError(f"Generated regression failed: {details}", exit_code=4)

    report_path = output / "cell_truth_report.html"
    if not report_path.is_file():
        raise _DemoError(f"Demo report was not generated: {report_path}")

    return DemoResult(
        out_dir=output,
        report_path=report_path,
        bundle_path=bundle_path,
        regression_path=regression_path,
        event_count=manifest.event_count,
        incident_count=manifest.incident_count,
    )


def _open_report(report_path: Path) -> bool:
    uri = report_path.resolve().as_uri()
    try:
        return bool(webbrowser.open(uri, new=2))
    except (OSError, webbrowser.Error):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="metriplane demo",
        description="Run the bundled camera-free incident-to-regression demo.",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Write results to DIR", metavar="DIR"
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_report",
        help="Open the HTML report after a successful run",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    out_dir = (args.out.expanduser().resolve() if args.out else _next_default_out_dir())
    print("Metriplane demo: missing required tool in an assembly cell")
    print("Input: bundled camera-free object-state session")
    print(f"Output: {out_dir}")
    print()

    try:
        result = run_demo(out_dir)
    except _DemoError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"Output: {out_dir}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError) as exc:
        print(f"ERROR: Demo could not run: {exc}", file=sys.stderr)
        print(f"Output: {out_dir}", file=sys.stderr)
        return 1

    print(
        f"PASS  Incident analysis: {result.event_count} events, "
        f"{result.incident_count} incident"
    )
    print("PASS  Evidence bundle: verified")
    print("PASS  Regression check: passed")
    print(f"Report: {result.report_path}")

    if args.open_report:
        if _open_report(result.report_path):
            print("Browser: opened report")
        else:
            print(
                "WARNING: Could not open a browser. Open the report manually:\n"
                f"{result.report_path.resolve().as_uri()}",
                file=sys.stderr,
            )

    print("Demo complete.")
    return 0


__all__ = ["DemoResult", "main", "run_demo"]
