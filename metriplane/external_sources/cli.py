# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Command-line interface for portable external fixture bundles."""

from __future__ import annotations

import argparse
import json
import sys

from metriplane.external_sources.execution import (
    ExternalRunSummary,
    ExternalValidationSummary,
    normalize_external_fixture,
    run_external_fixture,
    summary_json,
    validate_external_fixture,
)
from metriplane.external_sources.sandbox import (
    AcquisitionIdentity,
    AdapterSandboxError,
    load_acquisition_allowlist,
)


def _terminal_text(value: object) -> str:
    """Render untrusted fixture text without terminal control characters."""
    return json.dumps(str(value), ensure_ascii=True)[1:-1]


def _print_validation_human(summary: ExternalValidationSummary) -> None:
    if summary.passed:
        print(
            f"PASS {_terminal_text(summary.fixture_id)} frames={summary.frame_count} "
            f"objects={summary.normalized_object_count}"
        )
        return
    print("FAIL external fixture validation", file=sys.stderr)
    for error in summary.errors:
        print(f"- {_terminal_text(error)}", file=sys.stderr)


def _print_run_human(summary: ExternalRunSummary) -> None:
    if not summary.passed:
        print("FAIL external fixture run", file=sys.stderr)
        for error in summary.errors:
            print(f"- {_terminal_text(error)}", file=sys.stderr)
        return
    print(
        f"PASS {_terminal_text(summary.fixture_id)} "
        f"run_id={_terminal_text(summary.run_id)} "
        f"frames={summary.frame_count} events={summary.event_count} "
        f"deviations={summary.deviation_count} incidents={summary.incident_count}"
    )
    if summary.report_path is not None:
        print(f"report: {_terminal_text(summary.report_path)}")
    if summary.provenance is not None:
        print(f"provenance: {_terminal_text(summary.provenance.path)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        "metriplane external",
        description="Validate and run a portable external fixture bundle.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a complete external fixture without running Atlas",
    )
    validate_parser.add_argument("fixture", help="External fixture directory")
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the versioned machine-readable summary",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Validate a fixture and run it through the existing Atlas engine",
    )
    run_parser.add_argument("fixture", help="External fixture directory")
    run_parser.add_argument("--out", required=True, help="New Atlas run directory")
    run_parser.add_argument(
        "--run-id",
        default=None,
        help="Optional safe deterministic run ID (ASCII letters/digits/._-)",
    )
    run_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the named output using Atlas overwrite safeguards",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the versioned machine-readable summary",
    )

    normalize_parser = subparsers.add_parser(
        "normalize",
        help="Run an allowlisted source adapter in the offline normalization sandbox",
    )
    normalize_parser.add_argument("source", help="Source directory containing the pinned artifact")
    normalize_parser.add_argument("--out", required=True, help="New canonical fixture directory")
    normalize_parser.add_argument(
        "--adapter-script",
        required=True,
        help="Relative Python adapter script within the read-only source directory",
    )
    normalize_parser.add_argument(
        "--allowlist", required=True, help="Reviewed acquisition allowlist JSON"
    )
    normalize_parser.add_argument("--repository", required=True)
    normalize_parser.add_argument("--revision", required=True)
    normalize_parser.add_argument("--artifact", required=True)
    normalize_parser.add_argument("--artifact-size", required=True, type=int)
    normalize_parser.add_argument("--artifact-sha256", required=True)

    args = parser.parse_args(argv)
    if args.command == "validate":
        validation_summary = validate_external_fixture(args.fixture)
        if args.json:
            print(summary_json(validation_summary))
        else:
            _print_validation_human(validation_summary)
        return 0 if validation_summary.passed else 2

    if args.command == "normalize":
        try:
            result = normalize_external_fixture(
                args.source,
                args.out,
                adapter_script=args.adapter_script,
                acquisition=AcquisitionIdentity(
                    repository=args.repository,
                    revision=args.revision,
                    artifact=args.artifact,
                    size=args.artifact_size,
                    sha256=args.artifact_sha256,
                ),
                acquisition_allowlist=load_acquisition_allowlist(args.allowlist),
            )
        except (AdapterSandboxError, ValueError) as exc:
            print(f"FAIL external fixture normalization: {_terminal_text(exc)}", file=sys.stderr)
            return 2
        print(
            "PASS external fixture normalization "
            f"output={_terminal_text(args.out)} elapsed_seconds={result.elapsed_seconds:.3f}"
        )
        return 0

    run_summary = run_external_fixture(
        args.fixture,
        args.out,
        run_id=args.run_id,
        overwrite=bool(args.overwrite),
    )
    if args.json:
        print(summary_json(run_summary))
    else:
        _print_run_human(run_summary)
    return 0 if run_summary.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
