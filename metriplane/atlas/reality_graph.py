# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections import OrderedDict

from metriplane.atlas.models import (
    AssetRegistryModel,
    AtlasEvent,
    AtlasIncident,
    Edge,
    Entity,
    ProcessModel,
    RealityGraphExport,
    WorkspaceModel,
)


def stable_edge_id(edge_type: str, source_id: str, target_id: str, suffix: str = "") -> str:
    raw = f"{edge_type}:{source_id}:{target_id}:{suffix}"
    return raw.replace(" ", "_").replace("/", "_")


class RealityGraph:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._entities: OrderedDict[str, Entity] = OrderedDict()
        self._edges: OrderedDict[str, Edge] = OrderedDict()

    def add_entity(self, entity: Entity) -> None:
        self._entities[entity.id] = entity

    def add_edge(self, edge: Edge) -> None:
        self._edges[edge.id] = edge

    def bootstrap(
        self,
        assets: AssetRegistryModel,
        workspace: WorkspaceModel,
        process: ProcessModel,
        work_order_ids: list[str],
    ) -> None:
        for asset in sorted(assets.assets, key=lambda item: item.asset_id):
            self.add_entity(Entity(
                id=f"asset:{asset.asset_id}",
                type="asset",
                label=asset.label,
                properties={
                    "asset_type": asset.asset_type,
                    "object_id": asset.object_id,
                    "work_order_id": asset.work_order_id,
                },
            ))
        for zone in sorted(workspace.zones, key=lambda item: item.zone_id):
            self.add_entity(Entity(
                id=f"zone:{zone.zone_id}",
                type="zone",
                label=zone.label or zone.zone_id,
                properties={"zone_type": zone.zone_type},
            ))
        for station in sorted(workspace.stations, key=lambda item: item.station_id):
            self.add_entity(Entity(
                id=f"station:{station.station_id}",
                type="station",
                label=station.label,
                properties={"zone_id": station.zone_id},
            ))
            self.add_edge(Edge(
                id=stable_edge_id("station_in_zone", f"station:{station.station_id}", f"zone:{station.zone_id}"),
                type="station_in_zone",
                source_id=f"station:{station.station_id}",
                target_id=f"zone:{station.zone_id}",
            ))
        for step in sorted(process.steps, key=lambda item: item.step_id):
            self.add_entity(Entity(
                id=f"step:{step.step_id}",
                type="process_step",
                label=step.label,
                properties={
                    "required_station": step.required_station,
                    "required_zone": step.required_zone,
                    "required_assets": list(step.required_assets),
                },
            ))
            for asset_id in step.required_assets:
                self.add_edge(Edge(
                    id=stable_edge_id("asset_required_for_step", f"asset:{asset_id}", f"step:{step.step_id}"),
                    type="asset_required_for_step",
                    source_id=f"asset:{asset_id}",
                    target_id=f"step:{step.step_id}",
                ))
        for work_order_id in sorted(work_order_ids):
            self.add_entity(Entity(
                id=f"work_order:{work_order_id}",
                type="work_order",
                label=work_order_id,
            ))

    def add_observation(self, asset_id: str, zone_id: str | None, station_id: str | None, ts: float) -> None:
        if zone_id:
            self.add_edge(Edge(
                id=stable_edge_id("asset_in_zone", f"asset:{asset_id}", f"zone:{zone_id}", f"{ts:.3f}"),
                type="asset_in_zone",
                source_id=f"asset:{asset_id}",
                target_id=f"zone:{zone_id}",
                ts_start=ts,
            ))
        if station_id:
            self.add_edge(Edge(
                id=stable_edge_id("asset_at_station", f"asset:{asset_id}", f"station:{station_id}", f"{ts:.3f}"),
                type="asset_at_station",
                source_id=f"asset:{asset_id}",
                target_id=f"station:{station_id}",
                ts_start=ts,
            ))

    def add_event(self, event: AtlasEvent) -> None:
        self.add_entity(Entity(
            id=f"event:{event.event_id}",
            type="event",
            label=event.event_type,
            properties={"severity": event.severity, "message": event.message},
        ))
        if event.asset_id:
            self.add_edge(Edge(
                id=stable_edge_id("event_involves_asset", f"event:{event.event_id}", f"asset:{event.asset_id}"),
                type="event_involves_asset",
                source_id=f"event:{event.event_id}",
                target_id=f"asset:{event.asset_id}",
                ts_start=event.ts,
            ))
        if event.process_step_id:
            self.add_edge(Edge(
                id=stable_edge_id("event_about_step", f"event:{event.event_id}", f"step:{event.process_step_id}"),
                type="event_about_step",
                source_id=f"event:{event.event_id}",
                target_id=f"step:{event.process_step_id}",
                ts_start=event.ts,
            ))

    def add_incident(self, incident: AtlasIncident) -> None:
        self.add_entity(Entity(
            id=f"incident:{incident.incident_id}",
            type="incident",
            label=incident.title,
            properties={"severity": incident.severity, "summary": incident.summary},
        ))
        for event_id in incident.event_ids:
            self.add_edge(Edge(
                id=stable_edge_id("incident_has_event", f"incident:{incident.incident_id}", f"event:{event_id}"),
                type="incident_has_event",
                source_id=f"incident:{incident.incident_id}",
                target_id=f"event:{event_id}",
            ))

    def export(self) -> RealityGraphExport:
        return RealityGraphExport(
            graph_id=f"graph_{self.run_id}",
            run_id=self.run_id,
            entities=list(self._entities.values()),
            edges=list(self._edges.values()),
        )
