# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml

from metriplane.atlas.models import (
    AssetRegistryModel,
    ProcessModel,
    WorkOrderModel,
    WorkspaceModel,
)


@dataclass(frozen=True)
class DomainPack:
    root: Path
    assets: AssetRegistryModel
    workspace: WorkspaceModel
    process: ProcessModel
    work_orders: list[WorkOrderModel]
    contracts_path: Path | None = None


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"missing required domain-pack file: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in {path}")
    return data


def _read_work_orders(path: Path, process_id: str) -> list[WorkOrderModel]:
    if not path.exists():
        return [WorkOrderModel(work_order_id="WO-DEMO-001", process_id=process_id)]
    rows: list[WorkOrderModel] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row.get("work_order_id") or not row.get("process_id"):
                raise ValueError(f"work order row must include work_order_id and process_id in {path}")
            rows.append(WorkOrderModel(**{k: v for k, v in row.items() if v not in ("", None)}))
    return rows


def load_domain_pack(path: str | Path) -> DomainPack:
    root = Path(path)
    assets = AssetRegistryModel.model_validate(_read_yaml(root / "assets.yaml"))
    workspace = WorkspaceModel.model_validate(_read_yaml(root / "workspace.yaml"))
    process = ProcessModel.model_validate(_read_yaml(root / "process.yaml"))
    work_orders = _read_work_orders(root / "work_orders.csv", process.process_id)
    contracts_path = root / "contracts.yaml"
    return DomainPack(
        root=root,
        assets=assets,
        workspace=workspace,
        process=process,
        work_orders=work_orders,
        contracts_path=contracts_path if contracts_path.exists() else None,
    )


def validate_domain_pack(path: str | Path) -> list[str]:
    errors: list[str] = []
    try:
        pack = load_domain_pack(path)
    except Exception as exc:
        return [str(exc)]

    object_ids: set[str] = set()
    asset_ids: set[str] = set()
    for asset in pack.assets.assets:
        if asset.object_id in object_ids:
            errors.append(f"duplicate object_id: {asset.object_id}")
        if asset.asset_id in asset_ids:
            errors.append(f"duplicate asset_id: {asset.asset_id}")
        object_ids.add(asset.object_id)
        asset_ids.add(asset.asset_id)
        if not asset.asset_type.strip():
            errors.append(f"asset_type is empty for {asset.asset_id}")

    zone_ids = {zone.zone_id for zone in pack.workspace.zones}
    station_ids = {station.station_id for station in pack.workspace.stations}
    for station in pack.workspace.stations:
        if station.zone_id not in zone_ids:
            errors.append(f"station {station.station_id} references unknown zone {station.zone_id}")

    for step in pack.process.steps:
        if step.required_zone and step.required_zone not in zone_ids:
            errors.append(f"step {step.step_id} references unknown zone {step.required_zone}")
        if step.required_station and step.required_station not in station_ids:
            errors.append(f"step {step.step_id} references unknown station {step.required_station}")
        for required_asset in step.required_assets:
            if required_asset not in asset_ids:
                errors.append(f"step {step.step_id} references unknown asset {required_asset}")

    return errors
