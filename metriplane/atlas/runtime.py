# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from metriplane.schema import FrameStateModel

from metriplane.atlas.domain_packs import DomainPack, load_domain_pack
from metriplane.atlas.event_ledger import write_events
from metriplane.atlas.improvement import recommend_actions
from metriplane.atlas.models import AtlasRunManifest, FlowMetrics
from metriplane.atlas.process_model import AssetObservation, ProcessEvaluator
from metriplane.atlas.reality_graph import RealityGraph
from metriplane.atlas.reports import render_markdown, write_report
from metriplane.atlas.training import training_case_from_incident, write_training_case


@dataclass(frozen=True)
class AtlasRunPaths:
    out_dir: Path
    event_log: Path
    deviations: Path
    incidents: Path
    reality_graph: Path
    process_trace: Path
    manifest: Path
    metrics: Path
    flow_csv: Path
    report_md: Path
    report_html: Path
    bundles_dir: Path
    regression_dir: Path
    training_dir: Path
    improvement_actions: Path
    dashboard_html: Path
    twinverify_usda: Path
    privacy_report: Path
    connector_dir: Path

    @classmethod
    def from_out_dir(cls, out_dir: str | Path) -> "AtlasRunPaths":
        root = Path(out_dir)
        return cls(
            out_dir=root,
            event_log=root / "physical_event_log.jsonl",
            deviations=root / "deviations.jsonl",
            incidents=root / "incidents.jsonl",
            reality_graph=root / "reality_graph.json",
            process_trace=root / "process_trace.json",
            manifest=root / "atlas_manifest.json",
            metrics=root / "metrics.json",
            flow_csv=root / "flow_metrics.csv",
            report_md=root / "cell_truth_report.md",
            report_html=root / "cell_truth_report.html",
            bundles_dir=root / "evidence_bundles",
            regression_dir=root / "regression_tests",
            training_dir=root / "training_cases",
            improvement_actions=root / "improvement_actions.json",
            dashboard_html=root / "atlas_dashboard.html",
            twinverify_usda=root / "twinverify_replay.usda",
            privacy_report=root / "privacy_report.json",
            connector_dir=root / "connectors",
        )


def _json_dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _jsonl_dump(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _iter_frames(path: str | Path) -> list[FrameStateModel]:
    frames: list[FrameStateModel] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON on line {line_number}: {exc}") from exc
        if data.get("type") == "run_header":
            continue
        try:
            frames.append(FrameStateModel.model_validate(data))
        except Exception as exc:
            raise ValueError(f"invalid FrameStateModel on line {line_number}: {exc}") from exc
    if not frames:
        raise ValueError(f"no frame records found in {path}")
    return frames


def _station_for_zone(pack: DomainPack, zone_id: str | None) -> str | None:
    if zone_id is None:
        return None
    station = pack.workspace.station_by_zone().get(zone_id)
    return station.station_id if station else None


def _copy_pack_configs(pack: DomainPack, out_dir: Path) -> None:
    cfg = out_dir / "configs"
    cfg.mkdir(parents=True, exist_ok=True)
    for name in ("assets.yaml", "workspace.yaml", "process.yaml", "contracts.yaml", "work_orders.csv"):
        src = pack.root / name
        if src.exists():
            shutil.copyfile(src, cfg / name)


def run_atlas(
    session_jsonl: str | Path,
    pack_dir: str | Path,
    out_dir: str | Path,
    run_id: str | None = None,
) -> AtlasRunManifest:
    session_path = Path(session_jsonl)
    if not session_path.exists():
        raise ValueError(f"session_jsonl does not exist: {session_path}")
    pack = load_domain_pack(pack_dir)
    paths = AtlasRunPaths.from_out_dir(out_dir)
    if paths.out_dir.exists():
        # Derived artifacts may be overwritten, but never the source session.
        shutil.rmtree(paths.out_dir)
    paths.out_dir.mkdir(parents=True, exist_ok=True)

    frames = _iter_frames(session_path)
    run_id = run_id or frames[0].run_id or "atlas_demo"
    work_order_id = pack.work_orders[0].work_order_id
    evaluator = ProcessEvaluator(run_id=run_id, process=pack.process, work_order_id=work_order_id)
    graph = RealityGraph(run_id)
    graph.bootstrap(pack.assets, pack.workspace, pack.process, [wo.work_order_id for wo in pack.work_orders])

    asset_by_object = pack.assets.by_object_id()
    events = []
    state_segment_rows: list[dict] = []
    first_ts = frames[0].ts
    last_ts = frames[-1].ts
    station_occupancy: dict[str, float] = {}
    last_station_by_asset: dict[str, tuple[str, float]] = {}

    for frame in frames:
        objects = frame.fused if frame.fused else frame.objects
        observations: list[AssetObservation] = []
        for obj in objects:
            asset = asset_by_object.get(obj.id)
            if asset is None:
                continue
            zone_id = obj.zone
            station_id = _station_for_zone(pack, zone_id)
            observations.append(AssetObservation(
                asset=asset,
                ts=frame.ts,
                frame_id=frame.frame_id,
                zone_id=zone_id,
                station_id=station_id,
            ))
            graph.add_observation(asset.asset_id, zone_id, station_id, frame.ts)
            if station_id:
                prev = last_station_by_asset.get(asset.asset_id)
                if prev and prev[0] == station_id:
                    station_occupancy[station_id] = station_occupancy.get(station_id, 0.0) + max(0.0, frame.ts - prev[1])
                last_station_by_asset[asset.asset_id] = (station_id, frame.ts)
        emitted = evaluator.update(observations, frame.ts, frame.frame_id)
        events.extend(emitted)
        for event in emitted:
            graph.add_event(event)
        state_segment_rows.append(frame.model_dump())

    for incident in evaluator.incidents:
        graph.add_incident(incident)

    for incident in evaluator.incidents:
        paths.bundles_dir.mkdir(parents=True, exist_ok=True)
    write_events(paths.event_log, events)
    _jsonl_dump(paths.deviations, [d.model_dump() for d in evaluator.deviations])
    _jsonl_dump(paths.incidents, [i.model_dump() for i in evaluator.incidents])
    _json_dump(paths.reality_graph, graph.export().model_dump())
    _json_dump(paths.process_trace, {
        "schema_version": "metriplane.atlas.process_trace.v1",
        "run_id": run_id,
        "work_order_id": work_order_id,
        "completed_steps": evaluator.completed_steps,
        "active_missing": {
            step: {"start_ts": start, "event_ids": event_ids}
            for step, (start, event_ids) in sorted(evaluator.active_missing.items())
        },
    })

    wait_time = {
        deviation.process_step_id or deviation.deviation_id: deviation.duration_s or 0.0
        for deviation in evaluator.deviations
    }
    metrics = FlowMetrics(
        run_id=run_id,
        observed_duration_s=round(last_ts - first_ts, 3),
        event_count=len(events),
        incident_count=len(evaluator.incidents),
        station_occupancy_s={k: round(v, 3) for k, v in sorted(station_occupancy.items())},
        wait_time_s={k: round(v, 3) for k, v in sorted(wait_time.items())},
        bottlenecks=sorted(wait_time, key=wait_time.get, reverse=True)[:3],
    )
    _json_dump(paths.metrics, metrics.model_dump())
    with paths.flow_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "key", "value"])
        for key, value in metrics.station_occupancy_s.items():
            writer.writerow(["station_occupancy_s", key, value])
        for key, value in metrics.wait_time_s.items():
            writer.writerow(["wait_time_s", key, value])

    actions = recommend_actions(evaluator.incidents)
    _json_dump(paths.improvement_actions, [action.model_dump() for action in actions])

    artifacts = {
        "physical_event_log": str(paths.event_log),
        "deviations": str(paths.deviations),
        "incidents": str(paths.incidents),
        "reality_graph": str(paths.reality_graph),
        "process_trace": str(paths.process_trace),
        "metrics": str(paths.metrics),
        "flow_metrics_csv": str(paths.flow_csv),
        "cell_truth_report_md": str(paths.report_md),
        "cell_truth_report_html": str(paths.report_html),
        "evidence_bundles": str(paths.bundles_dir),
        "regression_tests": str(paths.regression_dir),
        "training_cases": str(paths.training_dir),
        "improvement_actions": str(paths.improvement_actions),
        "atlas_dashboard": str(paths.dashboard_html),
        "twinverify_usda": str(paths.twinverify_usda),
        "privacy_report": str(paths.privacy_report),
        "connector_exports": str(paths.connector_dir),
    }
    manifest = AtlasRunManifest(
        run_id=run_id,
        source_session_jsonl=str(session_path),
        domain_pack=str(pack.root),
        cell_id=pack.workspace.cell_id,
        frame_count=len(frames),
        event_count=len(events),
        deviation_count=len(evaluator.deviations),
        incident_count=len(evaluator.incidents),
        artifacts=artifacts,
    )

    report_md = render_markdown(manifest, events, evaluator.deviations, evaluator.incidents, metrics, actions)
    write_report(paths.report_md, paths.report_html, report_md)
    _copy_pack_configs(pack, paths.out_dir)

    _json_dump(paths.manifest, manifest.model_dump())

    from metriplane.atlas.bundles import export_bundle
    from metriplane.atlas.regression import create_regression_from_bundle

    for incident in evaluator.incidents:
        bundle_zip = paths.bundles_dir / f"{incident.incident_id}.zip"
        export_bundle(paths.out_dir, incident.incident_id, bundle_zip, state_segment_rows)
        paths.regression_dir.mkdir(parents=True, exist_ok=True)
        create_regression_from_bundle(bundle_zip, paths.regression_dir / f"{incident.incident_id}.yaml")
        training_case = training_case_from_incident(incident)
        write_training_case(
            training_case,
            paths.training_dir / f"{incident.incident_id}.md",
            paths.training_dir / f"{incident.incident_id}.json",
        )

    from metriplane.atlas.connectors import export_connectors
    from metriplane.atlas.dashboard import build_dashboard
    from metriplane.atlas.privacy import privacy_report
    from metriplane.atlas.usd import export_usda

    build_dashboard(paths.out_dir, paths.dashboard_html)
    export_usda(paths.out_dir, paths.twinverify_usda)
    privacy_report(paths.out_dir, paths.privacy_report)
    export_connectors(paths.out_dir, paths.connector_dir)

    return manifest
