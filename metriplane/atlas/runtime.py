# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import ctypes
import errno
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from metriplane.atlas.domain_packs import (
    DomainPack,
    load_domain_pack,
    validate_domain_pack,
)
from metriplane.atlas.event_ledger import write_events
from metriplane.atlas.improvement import recommend_actions
from metriplane.atlas.models import AtlasRunManifest, FlowMetrics
from metriplane.atlas.process_model import AssetObservation, ProcessEvaluator
from metriplane.atlas.reality_graph import RealityGraph
from metriplane.atlas.reports import render_markdown, write_report
from metriplane.atlas.training import training_case_from_incident, write_training_case
from metriplane.schema import FrameStateModel


@dataclass(frozen=True)
class AtlasRunPaths:
    out_dir: Path
    event_log: Path
    deviations: Path
    incidents: Path
    reality_graph: Path
    process_trace: Path
    state_segment: Path
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
            state_segment=root / "state_segment.jsonl",
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
    previous_time: float | None = None
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
            frame = FrameStateModel.model_validate(data)
            evaluation_time = _frame_time(frame)
        except Exception as exc:
            raise ValueError(f"invalid FrameStateModel on line {line_number}: {exc}") from exc
        if previous_time is not None and evaluation_time < previous_time:
            raise ValueError(
                "non-monotonic frame time on line "
                f"{line_number}: {evaluation_time} follows {previous_time}"
            )
        previous_time = evaluation_time
        frames.append(frame)
    if not frames:
        raise ValueError(f"no frame records found in {path}")
    return frames


def _frame_time(frame: FrameStateModel) -> float:
    """Return the validated evaluation clock for an Atlas frame."""
    source_time = float(frame.ts)
    if not math.isfinite(source_time):
        raise ValueError("ts must be finite")
    if frame.ts_sim_ns is None:
        return source_time
    if frame.ts_sim_ns < 0:
        raise ValueError("ts_sim_ns must be non-negative")
    simulation_time = float(frame.ts_sim_ns) / 1_000_000_000.0
    if not math.isfinite(simulation_time):
        raise ValueError("ts_sim_ns is outside the supported range")
    return simulation_time


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


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_generated_out_dir(out_dir: Path) -> bool:
    """Existing outputs are never safe to replace without explicit consent."""
    return False


def _remove_output(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def _raise_rename_error(error_number: int, destination: Path) -> None:
    raise OSError(error_number, os.strerror(error_number), str(destination))


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a staged directory only if ``destination`` is absent.

    POSIX ``rename`` replaces an existing destination, so an existence check before
    ``os.replace`` cannot provide no-clobber semantics. Use each supported operating
    system's exclusive rename operation instead. Unsupported platforms fail closed
    rather than risk replacing data.
    """
    if os.name == "nt":
        # Windows rename fails when the destination already exists.
        os.rename(source, destination)
        return

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)

    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            _raise_rename_error(errno.ENOTSUP, destination)
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        at_fdcwd = -100
        rename_noreplace = 1
        if (
            renameat2(
                at_fdcwd,
                source_bytes,
                at_fdcwd,
                destination_bytes,
                rename_noreplace,
            )
            != 0
        ):
            _raise_rename_error(ctypes.get_errno(), destination)
        return

    if sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            _raise_rename_error(errno.ENOTSUP, destination)
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        rename_excl = 0x00000004
        if renamex_np(source_bytes, destination_bytes, rename_excl) != 0:
            _raise_rename_error(ctypes.get_errno(), destination)
        return

    _raise_rename_error(errno.ENOTSUP, destination)


def run_atlas(
    session_jsonl: str | Path,
    pack_dir: str | Path,
    out_dir: str | Path,
    run_id: str | None = None,
    overwrite: bool = False,
) -> AtlasRunManifest:
    """Build an Atlas run completely before replacing any existing output."""
    session_path = Path(session_jsonl)
    pack_path = Path(pack_dir)
    output = Path(out_dir)
    output_resolved = output.resolve()
    session_resolved = session_path.resolve()
    pack_resolved = pack_path.resolve()

    if output_resolved == session_resolved or output_resolved in session_resolved.parents:
        raise ValueError("refusing output that contains the source session")
    if (
        output_resolved == pack_resolved
        or output_resolved in pack_resolved.parents
        or pack_resolved in output_resolved.parents
    ):
        raise ValueError("refusing output that overlaps the source domain pack")
    if output.exists() or output.is_symlink():
        if not overwrite:
            raise ValueError(
                "Refusing to overwrite existing output directory "
                f"without --overwrite: {output}"
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temp_dir:
        temp_root = Path(temp_dir)
        stage = temp_root / "run"
        manifest = _run_atlas_in_place(
            session_path,
            pack_path,
            stage,
            run_id=run_id,
            overwrite=False,
        )

        if not overwrite:
            try:
                _rename_directory_no_replace(stage, output)
            except FileExistsError as exc:
                raise ValueError(
                    "Refusing to overwrite output created while the run was staged "
                    f"without --overwrite: {output}"
                ) from exc
        else:
            backup = temp_root / "previous"
            had_previous = output.exists() or output.is_symlink()
            if had_previous:
                os.replace(output, backup)
            try:
                os.replace(stage, output)
            except Exception:
                if had_previous and (backup.exists() or backup.is_symlink()):
                    os.replace(backup, output)
                raise
    return manifest


def _run_atlas_in_place(
    session_jsonl: str | Path,
    pack_dir: str | Path,
    out_dir: str | Path,
    run_id: str | None = None,
    overwrite: bool = False,
) -> AtlasRunManifest:
    session_path = Path(session_jsonl)
    if not session_path.exists():
        raise ValueError(f"session_jsonl does not exist: {session_path}")
    pack_path = Path(pack_dir)
    paths = AtlasRunPaths.from_out_dir(out_dir)
    output_resolved = paths.out_dir.resolve()
    session_resolved = session_path.resolve()
    pack_resolved = pack_path.resolve()
    if output_resolved == session_resolved or output_resolved in session_resolved.parents:
        raise ValueError("refusing output that contains the source session")
    if (
        output_resolved == pack_resolved
        or output_resolved in pack_resolved.parents
        or pack_resolved in output_resolved.parents
    ):
        raise ValueError("refusing output that overlaps the source domain pack")

    pack_errors = validate_domain_pack(pack_path)
    if pack_errors:
        details = "\n".join(f"- {error}" for error in pack_errors)
        raise ValueError(f"invalid domain pack {pack_path}:\n{details}")
    pack = load_domain_pack(pack_path)
    if paths.out_dir.exists() or paths.out_dir.is_symlink():
        if not overwrite:
            raise ValueError(
                "Refusing to overwrite existing output directory "
                f"without --overwrite: {paths.out_dir}"
            )
        _remove_output(paths.out_dir)
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
    first_ts = _frame_time(frames[0])
    last_ts = _frame_time(frames[-1])
    station_occupancy: dict[str, float] = {}
    last_station_by_asset: dict[str, tuple[str, float]] = {}

    for frame in frames:
        frame_time = _frame_time(frame)
        objects = frame.fused if frame.fused is not None else frame.objects
        observations: list[AssetObservation] = []
        observed_asset_ids: set[str] = set()
        for obj in objects:
            asset = asset_by_object.get(obj.id)
            if asset is None:
                continue
            observed_asset_ids.add(asset.asset_id)
            zone_id = obj.zone
            station_id = _station_for_zone(pack, zone_id)
            observations.append(AssetObservation(
                asset=asset,
                ts=frame_time,
                frame_id=frame.frame_id,
                zone_id=zone_id,
                station_id=station_id,
            ))
            graph.add_observation(asset.asset_id, zone_id, station_id, frame_time)
            if station_id:
                prev = last_station_by_asset.get(asset.asset_id)
                if prev and prev[0] == station_id:
                    station_occupancy[station_id] = station_occupancy.get(station_id, 0.0) + max(0.0, frame_time - prev[1])
                last_station_by_asset[asset.asset_id] = (station_id, frame_time)
            else:
                last_station_by_asset.pop(asset.asset_id, None)
        for asset_id in set(last_station_by_asset) - observed_asset_ids:
            last_station_by_asset.pop(asset_id, None)
        emitted = evaluator.update(observations, frame_time, frame.frame_id)
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
            step: {
                "asset_id": evaluator.active_missing_asset.get(step),
                "start_ts": start,
                "event_ids": event_ids,
            }
            for step, (start, event_ids) in sorted(evaluator.active_missing.items())
        },
    })
    _jsonl_dump(paths.state_segment, state_segment_rows)

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

    def artifact_path(path: Path) -> str:
        return path.relative_to(paths.out_dir).as_posix()

    artifacts = {
        "physical_event_log": artifact_path(paths.event_log),
        "deviations": artifact_path(paths.deviations),
        "incidents": artifact_path(paths.incidents),
        "reality_graph": artifact_path(paths.reality_graph),
        "process_trace": artifact_path(paths.process_trace),
        "state_segment": artifact_path(paths.state_segment),
        "metrics": artifact_path(paths.metrics),
        "flow_metrics_csv": artifact_path(paths.flow_csv),
        "cell_truth_report_md": artifact_path(paths.report_md),
        "cell_truth_report_html": artifact_path(paths.report_html),
        "evidence_bundles": artifact_path(paths.bundles_dir),
        "regression_tests": artifact_path(paths.regression_dir),
        "training_cases": artifact_path(paths.training_dir),
        "improvement_actions": artifact_path(paths.improvement_actions),
        "atlas_dashboard": artifact_path(paths.dashboard_html),
        "twinverify_usda": artifact_path(paths.twinverify_usda),
        "privacy_report": artifact_path(paths.privacy_report),
        "connector_exports": artifact_path(paths.connector_dir),
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
