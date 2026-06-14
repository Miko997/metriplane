# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import math
from dataclasses import dataclass, field

from metriplane.camera_trust.models import (
    CameraTrustReportModel,
    CameraTrustScoreModel,
    ZoneCoverageScoreModel,
)
from metriplane.camera_trust.recommendations import build_recommendations
from metriplane.schema import FrameStateModel


@dataclass
class CameraTrustConfig:
    disagreement_warn_m: float = 0.02
    disagreement_fail_m: float = 0.05
    dropout_warn_rate: float = 0.10
    dropout_fail_rate: float = 0.30
    min_frames_for_score: int = 1


@dataclass
class _CamAgg:
    frames_with_detection: int = 0
    detections_total: int = 0
    disagreements: list[float] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)


@dataclass
class _ZoneAgg:
    frames_with_objects: int = 0
    camera_counts: dict[str, int] = field(default_factory=dict)


class CameraTrustAnalyzer:
    """Aggregates per-camera dropout, multi-camera disagreement, and zone coverage."""

    def __init__(self, config: CameraTrustConfig | None = None):
        self.config = config or CameraTrustConfig()
        self.run_id: str | None = None
        self._total_frames = 0
        self._cams: dict[str, _CamAgg] = {}
        self._zones: dict[str, _ZoneAgg] = {}

    def update(self, frame: FrameStateModel) -> None:
        if frame.run_id and not self.run_id:
            self.run_id = frame.run_id
        self._total_frames += 1

        fused = {str(o.id): o for o in (frame.fused or frame.objects)}

        # zone coverage from fused objects
        for o in (frame.fused or frame.objects):
            if o.zone:
                za = self._zones.setdefault(o.zone, _ZoneAgg())
                za.frames_with_objects += 1

        if not frame.raw_per_camera:
            return

        for cam in frame.raw_per_camera:
            cid = str(cam.camera_id)
            agg = self._cams.setdefault(cid, _CamAgg())
            objs = cam.objects or []
            if objs:
                agg.frames_with_detection += 1
            agg.detections_total += len(objs)
            for o in objs:
                if o.confidence is not None:
                    agg.confidences.append(float(o.confidence))
                # disagreement vs fused position of same object id
                fo = fused.get(str(o.id))
                if (fo is not None and fo.pos_world is not None
                        and o.pos_world is not None):
                    d = math.hypot(o.pos_world[0] - fo.pos_world[0],
                                   o.pos_world[1] - fo.pos_world[1])
                    agg.disagreements.append(d)
                # zone coverage per camera
                if o.zone:
                    za = self._zones.setdefault(o.zone, _ZoneAgg())
                    za.camera_counts[cid] = za.camera_counts.get(cid, 0) + 1

    def _score_camera(self, cid: str, agg: _CamAgg) -> CameraTrustScoreModel:
        cfg = self.config
        total = max(1, self._total_frames)
        dropout = 1.0 - (agg.frames_with_detection / total)
        mean_dis = (sum(agg.disagreements) / len(agg.disagreements)
                    if agg.disagreements else None)
        p95_dis = _p95(agg.disagreements) if agg.disagreements else None
        mean_conf = (sum(agg.confidences) / len(agg.confidences)
                     if agg.confidences else None)

        score = 1.0
        notes: list[str] = []
        # dropout penalty
        if dropout >= cfg.dropout_fail_rate:
            score -= 0.5
            notes.append(f"high dropout {dropout:.2f}")
        elif dropout >= cfg.dropout_warn_rate:
            score -= 0.2
            notes.append(f"elevated dropout {dropout:.2f}")
        # disagreement penalty
        if mean_dis is not None:
            if mean_dis >= cfg.disagreement_fail_m:
                score -= 0.4
                notes.append(f"large disagreement {mean_dis*100:.1f}cm")
            elif mean_dis >= cfg.disagreement_warn_m:
                score -= 0.15
                notes.append(f"moderate disagreement {mean_dis*100:.1f}cm")
        # low confidence penalty
        if mean_conf is not None and mean_conf < 0.5:
            score -= 0.1
            notes.append(f"low mean confidence {mean_conf:.2f}")

        score = max(0.0, min(1.0, score))
        status = "OK" if score >= 0.80 else ("DEGRADED" if score >= 0.50 else "FAILED")
        return CameraTrustScoreModel(
            camera_id=cid, score=round(score, 3), status=status,
            frames_seen=agg.frames_with_detection,
            detections_total=agg.detections_total,
            dropout_rate=round(dropout, 3),
            mean_disagreement_m=round(mean_dis, 4) if mean_dis is not None else None,
            p95_disagreement_m=round(p95_dis, 4) if p95_dis is not None else None,
            mean_confidence=round(mean_conf, 3) if mean_conf is not None else None,
            notes=notes,
        )

    def _score_zone(self, zone: str, agg: _ZoneAgg) -> ZoneCoverageScoreModel:
        n_cams = len(agg.camera_counts)
        score = 1.0 if n_cams >= 2 else (0.6 if n_cams == 1 else 0.2)
        weak = sorted(c for c, n in agg.camera_counts.items()
                      if n < max(agg.camera_counts.values(), default=1) * 0.5)
        notes = []
        if n_cams <= 1:
            notes.append("single-camera coverage (no redundancy)")
        return ZoneCoverageScoreModel(
            zone=zone, score=round(score, 3),
            frames_with_objects=agg.frames_with_objects,
            camera_observation_counts=dict(sorted(agg.camera_counts.items())),
            weak_cameras=weak, notes=notes,
        )

    def report(self) -> CameraTrustReportModel:
        cam_scores = {cid: self._score_camera(cid, agg)
                      for cid, agg in sorted(self._cams.items())}
        zone_scores = {z: self._score_zone(z, agg)
                       for z, agg in sorted(self._zones.items())}
        recs = build_recommendations(cam_scores, zone_scores, self.config)
        return CameraTrustReportModel(
            run_id=self.run_id,
            frames_analyzed=self._total_frames,
            camera_scores=cam_scores,
            zone_scores=zone_scores,
            recommendations=recs,
        )


def _p95(values: list[float]) -> float:
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(0.95 * (len(s) - 1)))))
    return s[idx]


def analyze_session(session_path, config: CameraTrustConfig | None = None
                    ) -> CameraTrustReportModel:
    from metriplane.sentinel.engine import iter_frames
    analyzer = CameraTrustAnalyzer(config)
    for frame in iter_frames(session_path):
        analyzer.update(frame)
    return analyzer.report()
