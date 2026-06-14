# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.camera_trust.models import CameraTrustReportModel


def export_camera_trust_report(path: str | Path, report: CameraTrustReportModel) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report.model_dump(), indent=2))
    return p


def read_camera_trust_report(path: str | Path) -> CameraTrustReportModel:
    return CameraTrustReportModel.model_validate_json(Path(path).read_text())
