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
    if not rows:
        raise ValueError(f"work_orders.csv must contain at least one work order: {path}")
    return rows


def load_domain_pack(path: str | Path) -> DomainPack:
    root = Path(path)
    assets = AssetRegistryModel.model_validate(_read_yaml(root / "assets.yaml"))
    workspace = WorkspaceModel.model_validate(_read_yaml(root / "workspace.yaml"))
    process = ProcessModel.model_validate(_read_yaml(root / "process.yaml"))
    if not process.steps:
        raise ValueError(f"process must contain at least one step: {root / 'process.yaml'}")
    work_orders = _read_work_orders(root / "work_orders.csv", process.process_id)
    for work_order in work_orders:
        if work_order.process_id != process.process_id:
            raise ValueError(
                f"work order {work_order.work_order_id} references process "
                f"{work_order.process_id}, expected {process.process_id}"
            )
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

    zone_ids: set[str] = set()
    for zone in pack.workspace.zones:
        if zone.zone_id in zone_ids:
            errors.append(f"duplicate zone_id: {zone.zone_id}")
        zone_ids.add(zone.zone_id)

    station_ids: set[str] = set()
    for station in pack.workspace.stations:
        if station.station_id in station_ids:
            errors.append(f"duplicate station_id: {station.station_id}")
        station_ids.add(station.station_id)
        if station.zone_id not in zone_ids:
            errors.append(f"station {station.station_id} references unknown zone {station.zone_id}")

    for asset in pack.assets.assets:
        for zone_id in asset.expected_zones:
            if zone_id not in zone_ids:
                errors.append(f"asset {asset.asset_id} references unknown expected zone {zone_id}")
        for station_id in asset.expected_stations:
            if station_id not in station_ids:
                errors.append(
                    f"asset {asset.asset_id} references unknown expected station {station_id}"
                )

    step_ids: set[str] = set()
    for step in pack.process.steps:
        if step.step_id in step_ids:
            errors.append(f"duplicate step_id: {step.step_id}")
        step_ids.add(step.step_id)
        if step.required_zone and step.required_zone not in zone_ids:
            errors.append(f"step {step.step_id} references unknown zone {step.required_zone}")
        if step.required_station and step.required_station not in station_ids:
            errors.append(f"step {step.step_id} references unknown station {step.required_station}")
        for required_asset in step.required_assets:
            if required_asset not in asset_ids:
                errors.append(f"step {step.step_id} references unknown asset {required_asset}")
        if step.max_wait_s is not None and step.max_wait_s < 0:
            errors.append(f"step {step.step_id} has negative max_wait_s")

    work_order_ids: set[str] = set()
    for work_order in pack.work_orders:
        if work_order.work_order_id in work_order_ids:
            errors.append(f"duplicate work_order_id: {work_order.work_order_id}")
        work_order_ids.add(work_order.work_order_id)

    if pack.contracts_path is not None:
        errors.extend(
            _validate_contracts(
                pack.contracts_path,
                step_ids=step_ids,
                asset_ids=asset_ids,
                station_ids=station_ids,
                zone_ids=zone_ids,
            )
        )

    return errors


def _validate_contracts(
    path: Path,
    *,
    step_ids: set[str],
    asset_ids: set[str],
    station_ids: set[str],
    zone_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    try:
        data = _read_yaml(path)
    except ValueError as exc:
        return [str(exc)]
    if data.get("schema_version") != "metriplane.atlas.contracts.v1":
        errors.append(f"unsupported contracts schema_version in {path}")
    contracts = data.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        return errors + [f"contracts must be a nonempty list in {path}"]

    contract_ids: set[str] = set()
    references = (
        ("process_step_id", step_ids, "step"),
        ("required_asset_id", asset_ids, "asset"),
        ("station_id", station_ids, "station"),
        ("zone_id", zone_ids, "zone"),
    )
    for index, contract in enumerate(contracts, start=1):
        if not isinstance(contract, dict):
            errors.append(f"contract {index} must be a mapping in {path}")
            continue
        contract_id = contract.get("contract_id")
        kind = contract.get("kind")
        if not isinstance(contract_id, str) or not contract_id.strip():
            errors.append(f"contract {index} has no contract_id in {path}")
            continue
        if contract_id in contract_ids:
            errors.append(f"duplicate contract_id: {contract_id}")
        contract_ids.add(contract_id)
        if not isinstance(kind, str) or not kind.strip():
            errors.append(f"contract {contract_id} has no kind")
        for field, known, label in references:
            value = contract.get(field)
            if value is not None and value not in known:
                errors.append(
                    f"contract {contract_id} references unknown {label} {value}"
                )
        max_wait = contract.get("max_wait_s")
        if max_wait is not None and (
            isinstance(max_wait, bool)
            or not isinstance(max_wait, (int, float))
            or max_wait < 0
        ):
            errors.append(f"contract {contract_id} has invalid max_wait_s")
    return errors
