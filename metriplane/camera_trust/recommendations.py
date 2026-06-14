# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metriplane.camera_trust.models import (
        CameraTrustScoreModel,
        ZoneCoverageScoreModel,
    )


def build_recommendations(camera_scores: dict, zone_scores: dict, config) -> list[str]:
    """Turn metrics into qualitative operator recommendations (no exact placement)."""
    recs: list[str] = []
    for cid, cs in sorted(camera_scores.items()):
        if cs.dropout_rate is not None and cs.dropout_rate >= config.dropout_warn_rate:
            recs.append(
                f"{cid} has high dropout ({cs.dropout_rate:.0%}); check cable, focus, "
                f"occlusion, or device index.")
        if (cs.mean_disagreement_m is not None
                and cs.mean_disagreement_m >= config.disagreement_warn_m):
            recs.append(
                f"{cid} disagrees with the fused estimate by "
                f"{cs.mean_disagreement_m*100:.1f} cm; re-run calibration / alignment "
                f"validation.")
        if cs.mean_confidence is not None and cs.mean_confidence < 0.5:
            recs.append(
                f"{cid} has low mean confidence ({cs.mean_confidence:.2f}); improve "
                f"lighting, marker size, or focus.")
    for zone, zs in sorted(zone_scores.items()):
        if zs.score < 0.7:
            weak = f" (weak: {', '.join(zs.weak_cameras)})" if zs.weak_cameras else ""
            recs.append(
                f"Zone {zone} has weak coverage{weak}; adjust a camera viewpoint or add a "
                f"camera for redundancy.")
    if not recs:
        recs.append("No camera trust issues detected.")
    return recs
