# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("metriplane atlas")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate-pack", help="Validate an Atlas domain pack")
    validate.add_argument("pack")

    run = sub.add_parser("run", help="Run Atlas Cell Black Box over a replay session")
    run.add_argument("--session-jsonl", required=True)
    run.add_argument("--pack", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--run-id", default=None)
    run.add_argument("--overwrite", action="store_true")

    run_pack = sub.add_parser("run-pack", help="Run a named checked-in domain pack")
    run_pack.add_argument("pack_name")
    run_pack.add_argument("--demo", action="store_true")
    run_pack.add_argument("--out", required=True)
    run_pack.add_argument("--session-jsonl", default=None)
    run_pack.add_argument("--overwrite", action="store_true")

    report = sub.add_parser("report", help="Print Cell Truth Report path for a run")
    report.add_argument("--run-dir", required=True)

    bundle = sub.add_parser("bundle", help="Export or verify Atlas evidence bundles")
    bundle_sub = bundle.add_subparsers(dest="bundle_cmd", required=True)
    bundle_export = bundle_sub.add_parser("export")
    bundle_export.add_argument("--incident-id", required=True)
    bundle_export.add_argument("--run-dir", required=True)
    bundle_export.add_argument("--out", required=True)
    bundle_export.add_argument("--overwrite", action="store_true")
    bundle_verify = bundle_sub.add_parser("verify")
    bundle_verify.add_argument("bundle")

    replay = sub.add_parser("replay-bundle", help="Verify that a bundle has a replayable state segment")
    replay.add_argument("bundle")

    regression = sub.add_parser("regression", help="Create Atlas physical regression specs")
    regression_sub = regression.add_subparsers(dest="regression_cmd", required=True)
    regression_create = regression_sub.add_parser("create")
    regression_create.add_argument("--bundle", required=True)
    regression_create.add_argument("--out", required=True)

    test = sub.add_parser("test", help="Run an Atlas physical regression spec")
    test.add_argument("spec")
    test.add_argument("--json", action="store_true")

    training = sub.add_parser("training", help="Create training cases from bundles")
    training_sub = training.add_subparsers(dest="training_cmd", required=True)
    training_create = training_sub.add_parser("create")
    training_create.add_argument("--bundle", required=True)
    training_create.add_argument("--out", required=True)

    query = sub.add_parser("query", help="Query Atlas run artifacts")
    query_sub = query.add_subparsers(dest="query_cmd", required=True)
    query_events = query_sub.add_parser("events")
    query_events.add_argument("--run-dir", required=True)
    query_events.add_argument("--asset", default=None)
    query_events.add_argument("--zone", default=None)
    query_events.add_argument("--station", default=None)
    query_events.add_argument("--step", default=None)
    query_events.add_argument("--type", default=None)
    query_events.add_argument("--json", action="store_true")
    query_saved = query_sub.add_parser("saved")
    query_saved.add_argument("--run-dir", required=True)
    query_saved.add_argument("--query-file", default="configs/atlas/saved_queries.yaml")
    query_saved.add_argument("--query-id", required=True)
    query_saved.add_argument("--json", action="store_true")
    query_list = query_sub.add_parser("list-saved")
    query_list.add_argument("--query-file", default="configs/atlas/saved_queries.yaml")
    query_index = query_sub.add_parser("index")
    query_index.add_argument("--root", required=True)

    dashboard = sub.add_parser("dashboard", help="Build Atlas nontechnical dashboard artifacts")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_cmd", required=True)
    dashboard_build = dashboard_sub.add_parser("build")
    dashboard_build.add_argument("--run-dir", required=True)
    dashboard_build.add_argument("--out", default=None)

    twinverify = sub.add_parser("twinverify", help="Export Atlas replay artifacts for TwinVerify/USD workflows")
    twinverify_sub = twinverify.add_subparsers(dest="twinverify_cmd", required=True)
    twinverify_export = twinverify_sub.add_parser("export-usd")
    twinverify_export.add_argument("--run-dir", required=True)
    twinverify_export.add_argument("--out", default=None)

    lake = sub.add_parser("lake", help="Build and query a local Atlas evidence lake")
    lake_sub = lake.add_subparsers(dest="lake_cmd", required=True)
    lake_build = lake_sub.add_parser("build")
    lake_build.add_argument("--root", required=True)
    lake_build.add_argument("--db", required=True)
    lake_query = lake_sub.add_parser("query")
    lake_query.add_argument("--db", required=True)
    lake_query.add_argument("--table", choices=["runs", "events", "incidents"], default="events")
    lake_query.add_argument("--asset", default=None)
    lake_query.add_argument("--type", default=None)
    lake_query.add_argument("--cell", default=None)
    lake_trends = lake_sub.add_parser("trends")
    lake_trends.add_argument("--db", required=True)
    lake_trends.add_argument("--out", default=None)

    connectors = sub.add_parser("connectors", help="Export Atlas connector-lite payloads")
    connectors_sub = connectors.add_subparsers(dest="connectors_cmd", required=True)
    connectors_export = connectors_sub.add_parser("export")
    connectors_export.add_argument("--run-dir", required=True)
    connectors_export.add_argument("--out", default=None)

    edge = sub.add_parser("edge", help="Atlas edge-appliance helper commands")
    edge_sub = edge.add_subparsers(dest="edge_cmd", required=True)
    edge_doctor = edge_sub.add_parser("doctor")
    edge_doctor.add_argument("--runs-root", required=True)
    edge_doctor.add_argument("--min-free-mb", type=int, default=512)
    edge_retention = edge_sub.add_parser("retention-plan")
    edge_retention.add_argument("--runs-root", required=True)
    edge_retention.add_argument("--keep-last", type=int, default=20)
    edge_bundle = edge_sub.add_parser("bundle")
    edge_bundle.add_argument("--runs-root", required=True)
    edge_bundle.add_argument("--out", required=True)

    multicell = sub.add_parser("multicell", help="Compare multiple Atlas cell runs")
    multicell_sub = multicell.add_subparsers(dest="multicell_cmd", required=True)
    multicell_compare = multicell_sub.add_parser("compare")
    multicell_compare.add_argument("--root", required=True)
    multicell_compare.add_argument("--out-json", default=None)
    multicell_compare.add_argument("--out-md", default=None)

    privacy = sub.add_parser("privacy", help="Build Atlas privacy reports and proxy exports")
    privacy_sub = privacy.add_subparsers(dest="privacy_cmd", required=True)
    privacy_report = privacy_sub.add_parser("report")
    privacy_report.add_argument("--run-dir", required=True)
    privacy_report.add_argument("--out", default=None)
    privacy_anon = privacy_sub.add_parser("anonymize")
    privacy_anon.add_argument("--run-dir", required=True)
    privacy_anon.add_argument("--out", required=True)
    privacy_anon.add_argument("--overwrite", action="store_true")

    improvement = sub.add_parser("improvement", help="Compare Atlas before/after improvement runs")
    improvement_sub = improvement.add_subparsers(dest="improvement_cmd", required=True)
    improvement_compare = improvement_sub.add_parser("compare")
    improvement_compare.add_argument("--before-run", required=True)
    improvement_compare.add_argument("--after-run", required=True)
    improvement_compare.add_argument("--out", required=True)

    protocol = sub.add_parser("protocol", help="Export and validate Open Atlas Protocol artifacts")
    protocol_sub = protocol.add_subparsers(dest="protocol_cmd", required=True)
    protocol_export = protocol_sub.add_parser("export")
    protocol_export.add_argument("--out", required=True)
    protocol_compat = protocol_sub.add_parser("compat")
    protocol_compat.add_argument("--pack", default=None)
    protocol_compat.add_argument("--bundle", default=None)

    pilot = sub.add_parser("pilot", help="Create external-pilot templates")
    pilot_sub = pilot.add_subparsers(dest="pilot_cmd", required=True)
    pilot_kit = pilot_sub.add_parser("kit")
    pilot_kit.add_argument("--out", required=True)

    freeze = sub.add_parser("freeze", help="Build Atlas evidence-freeze artifacts")
    freeze_sub = freeze.add_subparsers(dest="freeze_cmd", required=True)
    freeze_build = freeze_sub.add_parser("build")
    freeze_build.add_argument("--root", default=".")
    freeze_build.add_argument("--out", required=True)
    freeze_audit = freeze_sub.add_parser("audit")
    freeze_audit.add_argument("--root", default=".")

    bench = sub.add_parser("bench", help="Run Atlas benchmarks")
    bench_sub = bench.add_subparsers(dest="bench_cmd", required=True)
    bench_core = bench_sub.add_parser("core")
    bench_core.add_argument("--out", required=True)
    bench_core.add_argument("--session-jsonl", default="datasets/demo/atlas/assembly_cell_missing_tool.jsonl")
    bench_core.add_argument("--pack", default="configs/domain_packs/assembly_cell")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "validate-pack":
            from metriplane.atlas.domain_packs import validate_domain_pack
            errors = validate_domain_pack(args.pack)
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 2
            print(f"PASS {args.pack}")
            return 0

        if args.cmd == "run":
            from metriplane.atlas.runtime import run_atlas
            manifest = run_atlas(args.session_jsonl, args.pack, args.out, args.run_id, overwrite=args.overwrite)
            print(f"run_id={manifest.run_id} events={manifest.event_count} incidents={manifest.incident_count}")
            print(f"report: {manifest.artifacts['cell_truth_report_html']}")
            return 0

        if args.cmd == "run-pack":
            if args.pack_name != "assembly_cell":
                pack = Path("configs/domain_packs") / args.pack_name
            else:
                pack = Path("configs/domain_packs/assembly_cell")
            session = args.session_jsonl or "datasets/demo/atlas/assembly_cell_missing_tool.jsonl"
            from metriplane.atlas.runtime import run_atlas
            manifest = run_atlas(session, pack, args.out, run_id=f"{args.pack_name}_demo", overwrite=args.overwrite)
            print(f"run_id={manifest.run_id} events={manifest.event_count} incidents={manifest.incident_count}")
            print(f"report: {manifest.artifacts['cell_truth_report_html']}")
            return 0

        if args.cmd == "report":
            report_path = Path(args.run_dir) / "cell_truth_report.html"
            if not report_path.exists():
                print(f"missing report: {report_path}")
                return 2
            print(report_path)
            return 0

        if args.cmd == "bundle":
            from metriplane.atlas.bundles import export_bundle, verify_bundle
            if args.bundle_cmd == "export":
                path = export_bundle(
                    args.run_dir,
                    args.incident_id,
                    args.out,
                    overwrite=args.overwrite,
                )
                print(path)
                return 0
            result = verify_bundle(args.bundle)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["pass"] else 3

        if args.cmd == "replay-bundle":
            from metriplane.atlas.bundles import verify_bundle
            result = verify_bundle(args.bundle)
            if not result["pass"]:
                print(json.dumps(result, indent=2, sort_keys=True))
                return 3
            print(f"bundle replay segment verified: {args.bundle}")
            return 0

        if args.cmd == "regression":
            from metriplane.atlas.regression import create_regression_from_bundle
            spec = create_regression_from_bundle(args.bundle, args.out)
            print(f"wrote {args.out} ({spec.test_id})")
            return 0

        if args.cmd == "test":
            from metriplane.atlas.regression import run_regression
            result = run_regression(args.spec)
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"{'PASS' if result['pass'] else 'FAIL'} {result['test_id']}")
                for error in result["errors"]:
                    print(f"- {error}")
            return 0 if result["pass"] else 4

        if args.cmd == "training":
            import zipfile
            from tempfile import TemporaryDirectory
            from metriplane.atlas.bundles import safe_extract
            from metriplane.atlas.models import AtlasIncident
            from metriplane.atlas.training import training_case_from_incident, write_training_case
            bundle_path = Path(args.bundle)
            if bundle_path.is_dir():
                incident_path = bundle_path / "incident.json"
                incident = AtlasIncident.model_validate(json.loads(incident_path.read_text()))
                case = training_case_from_incident(incident)
                write_training_case(case, args.out)
            else:
                with TemporaryDirectory() as tmp:
                    with zipfile.ZipFile(bundle_path) as archive:
                        safe_extract(archive, tmp)
                    incident = AtlasIncident.model_validate(json.loads((Path(tmp) / "incident.json").read_text()))
                    case = training_case_from_incident(incident)
                    write_training_case(case, args.out)
            print(f"wrote {args.out}")
            return 0

        if args.cmd == "query":
            from metriplane.atlas.query import explain_query, index_runs, query_run_events, run_saved_query
            if args.query_cmd == "events":
                rows = query_run_events(args.run_dir, args.asset, args.zone, args.station, args.step, args.type)
                if args.json:
                    print(json.dumps(rows, indent=2, sort_keys=True))
                else:
                    for row in rows:
                        print(f"{row['event_id']} {row['event_type']} {row.get('asset_id')} {row['message']}")
                return 0
            if args.query_cmd == "saved":
                rows = run_saved_query(args.run_dir, args.query_file, args.query_id)
                if args.json:
                    print(json.dumps(rows, indent=2, sort_keys=True))
                else:
                    for row in rows:
                        print(f"{row['event_id']} {row['event_type']} {row.get('asset_id')} {row['message']}")
                return 0
            if args.query_cmd == "list-saved":
                print(json.dumps(explain_query(args.query_file), indent=2, sort_keys=True))
                return 0
            print(json.dumps(index_runs(args.root), indent=2, sort_keys=True))
            return 0

        if args.cmd == "dashboard":
            from metriplane.atlas.dashboard import build_dashboard
            path = build_dashboard(args.run_dir, args.out)
            print(path)
            return 0

        if args.cmd == "twinverify":
            from metriplane.atlas.usd import export_usda
            path = export_usda(args.run_dir, args.out)
            print(path)
            return 0

        if args.cmd == "lake":
            from metriplane.atlas.evidence_lake import build_lake, lake_query, trend_summary
            if args.lake_cmd == "build":
                print(json.dumps(build_lake(args.root, args.db), indent=2, sort_keys=True))
                return 0
            if args.lake_cmd == "query":
                print(json.dumps(lake_query(args.db, args.table, args.asset, args.type, args.cell), indent=2, sort_keys=True))
                return 0
            print(json.dumps(trend_summary(args.db, args.out), indent=2, sort_keys=True))
            return 0

        if args.cmd == "connectors":
            from metriplane.atlas.connectors import export_connectors
            print(json.dumps(export_connectors(args.run_dir, args.out), indent=2, sort_keys=True))
            return 0

        if args.cmd == "edge":
            from metriplane.atlas.edge import edge_doctor, retention_plan, write_edge_bundle
            if args.edge_cmd == "doctor":
                result = edge_doctor(args.runs_root, args.min_free_mb)
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0 if result["pass"] else 1
            if args.edge_cmd == "retention-plan":
                print(json.dumps(retention_plan(args.runs_root, args.keep_last), indent=2, sort_keys=True))
                return 0
            print(write_edge_bundle(args.runs_root, args.out))
            return 0

        if args.cmd == "multicell":
            from metriplane.atlas.multicell import compare_cells
            print(json.dumps(compare_cells(args.root, args.out_json, args.out_md), indent=2, sort_keys=True))
            return 0

        if args.cmd == "privacy":
            from metriplane.atlas.privacy import anonymize_run, privacy_report
            if args.privacy_cmd == "report":
                print(json.dumps(privacy_report(args.run_dir, args.out), indent=2, sort_keys=True))
                return 0
            print(json.dumps(
                anonymize_run(args.run_dir, args.out, overwrite=args.overwrite),
                indent=2,
                sort_keys=True,
            ))
            return 0

        if args.cmd == "improvement":
            from metriplane.atlas.improvement import compare_runs
            print(json.dumps(compare_runs(args.before_run, args.after_run, args.out), indent=2, sort_keys=True))
            return 0

        if args.cmd == "protocol":
            from metriplane.atlas.protocol import compat_check, export_protocol
            if args.protocol_cmd == "export":
                print(json.dumps(export_protocol(args.out), indent=2, sort_keys=True))
                return 0
            result = compat_check(args.pack, args.bundle)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["pass"] else 2

        if args.cmd == "pilot":
            from metriplane.atlas.pilot import create_pilot_kit
            print(json.dumps(create_pilot_kit(args.out), indent=2, sort_keys=True))
            return 0

        if args.cmd == "freeze":
            from metriplane.atlas.freeze import build_freeze, claim_audit
            if args.freeze_cmd == "build":
                print(json.dumps(build_freeze(args.root, args.out), indent=2, sort_keys=True))
                return 0
            print(json.dumps(claim_audit(args.root), indent=2, sort_keys=True))
            return 0

        if args.cmd == "bench":
            from metriplane.atlas.bench import bench_core
            result = bench_core(args.session_jsonl, args.pack, args.out)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["bundles_pass"] and result["regressions_pass"] else 1
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
