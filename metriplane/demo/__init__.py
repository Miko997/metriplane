# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Wheel-contained Metriplane adoption demo."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
import tempfile
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


_EXPECTED_EVENT_COUNT = 6
_EXPECTED_INCIDENT_COUNT = 1
_RESOURCE_PACKAGE = "metriplane.demo"
_DEMO_EXPORT_LAYOUT = (
    ("assets/assembly_cell_missing_tool.jsonl", "session.jsonl"),
    ("assets/assembly_cell/assets.yaml", "domain-pack/assets.yaml"),
    ("assets/assembly_cell/workspace.yaml", "domain-pack/workspace.yaml"),
    ("assets/assembly_cell/process.yaml", "domain-pack/process.yaml"),
    ("assets/assembly_cell/contracts.yaml", "domain-pack/contracts.yaml"),
    ("assets/assembly_cell/work_orders.csv", "domain-pack/work_orders.csv"),
)
BUNDLED_DEMO_RESOURCES = tuple(source for source, _target in _DEMO_EXPORT_LAYOUT)


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
            root / Path(path).relative_to("assets")
            for path in BUNDLED_DEMO_RESOURCES
        ]
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise _DemoError(f"Bundled demo resources are missing: {', '.join(missing)}")
        yield session, pack


def _path_exists(path: Path) -> bool:
    """Return true for files, directories, and broken symlinks."""
    return os.path.lexists(os.fspath(path))


def export_demo_inputs(destination: str | Path) -> Path:
    """Copy the bundled example inputs into a new inspectable directory."""
    output = Path(destination).expanduser().absolute()
    if _path_exists(output):
        raise _DemoError(
            "Refusing to replace an existing export path. "
            f"Choose another path or remove it yourself: {output}",
            exit_code=2,
        )

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _DemoError(f"Could not create the export parent directory: {exc}") from exc
    if not output.parent.is_dir():
        raise _DemoError(f"Export parent is not a directory: {output.parent}")

    # Stage beside the destination so the final rename stays on one filesystem.
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
    )
    published = False
    reserved_output = False
    try:
        package_root = resources.files(_RESOURCE_PACKAGE)
        for source_relative, target_relative in _DEMO_EXPORT_LAYOUT:
            source = package_root.joinpath(source_relative)
            if not source.is_file():
                raise _DemoError(f"Bundled demo resource is missing: {source_relative}")
            target = staging / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

        # Atomically reserve the destination.  A check followed by rename is not
        # sufficient on POSIX: renaming a directory can replace an empty directory
        # created by another process in that window.
        try:
            output.mkdir()
            reserved_output = True
        except FileExistsError:
            raise _DemoError(
                "Refusing to replace an export path that appeared while exporting: "
                f"{output}",
                exit_code=2,
            )

        # The six resources were fully staged before the visible destination was
        # reserved.  Move the two top-level entries into that owned directory.
        # This favors race-safe no-clobber behavior over a replace-style rename.
        for child in staging.iterdir():
            child.rename(output / child.name)
        published = True
    finally:
        if reserved_output and not published and output.is_dir():
            shutil.rmtree(output)
        if not published and staging.is_dir():
            shutil.rmtree(staging)

    return output


def _print_export_next_steps(export_dir: Path) -> None:
    session = export_dir / "session.jsonl"
    pack = export_dir / "domain-pack"
    run_dir = export_dir.with_name(f"{export_dir.name}-run")

    def quote(path: Path) -> str:
        return shlex.quote(str(path))

    print("Metriplane example inputs exported.")
    print()
    print(f"Recorded run: {session}")
    print(f"Process rules: {pack}")
    print()
    print("Inspect or edit these copies, then run:")
    print(f"  metriplane atlas validate-pack {quote(pack)}")
    print(
        "  metriplane atlas run "
        f"--session-jsonl {quote(session)} --pack {quote(pack)} "
        f"--out {quote(run_dir)}"
    )
    print(f"  metriplane atlas report --run-dir {quote(run_dir)}")
    print(
        "  metriplane atlas bundle verify "
        f"{quote(run_dir / 'evidence_bundles' / 'INC-0001.zip')}"
    )
    print(
        "  metriplane atlas test "
        f"{quote(run_dir / 'regression_tests' / 'INC-0001.yaml')} --json"
    )


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
        description=(
            "Run a complete built-in example, from a recorded incident to a "
            "verified report and a repeatable check. No camera is needed."
        ),
    )
    output_options = parser.add_mutually_exclusive_group()
    output_options.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Save the report, evidence, and repeatable check in DIR",
        metavar="DIR",
    )
    output_options.add_argument(
        "--export-inputs",
        type=Path,
        default=None,
        help="Copy the example recorded run and process rules into a new DIR",
        metavar="DIR",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_report",
        help="Open the finished HTML report in your browser",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.export_inputs is not None:
        if args.open_report:
            parser.error("--open cannot be combined with --export-inputs")
        try:
            export_dir = export_demo_inputs(args.export_inputs)
        except _DemoError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return exc.exit_code
        except (OSError, ValueError) as exc:
            print(f"ERROR: Example inputs could not be exported: {exc}", file=sys.stderr)
            return 1
        _print_export_next_steps(export_dir)
        return 0

    out_dir = (args.out.expanduser().resolve() if args.out else _next_default_out_dir())
    print("Metriplane bundled demo")
    print()
    print("Scenario:")
    print("A required torque driver is missing during an assembly step.")
    print("The fastening step is delayed by 35.0 seconds.")
    print()
    print("Input:")
    print("Timestamped object positions and process rules.")
    print()
    print(f"Output folder: {out_dir}")
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

    print("Result:")
    print(f"PASS  Incident timeline: {result.event_count} events")
    print(f"PASS  Incident report: {result.incident_count} incident")
    print("PASS  Evidence bundle: verified")
    print("PASS  Repeatable regression check: passed")
    print()
    print("Report:")
    print(result.report_path)
    print()
    print("The generated check can be run again after the software or process rules change.")

    if args.open_report:
        if _open_report(result.report_path):
            print("Browser: open request sent")
            print("If no browser opens, use the Report path above.")
        else:
            print(
                "WARNING: Could not open a browser. Open the report manually:\n"
                f"{result.report_path.resolve().as_uri()}",
                file=sys.stderr,
            )

    print("Demo complete.")
    return 0


__all__ = [
    "BUNDLED_DEMO_RESOURCES",
    "DemoResult",
    "export_demo_inputs",
    "main",
    "run_demo",
]
