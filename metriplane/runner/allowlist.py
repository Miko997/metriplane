# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Command allowlist for the local Metriplane runner

Defines safe, pre-approved commands that can be executed via the dashboard.
No arbitrary command execution allowed.
"""

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import List, Optional

_RUNS_DIR = str(Path.home() / "metriplane-runs")
_ATLAS_UI_RUN = "web/dashboard/atlas_run"
_ATLAS_UI_BUNDLE_DIR = f"{_ATLAS_UI_RUN}/evidence_bundles/INC-0001"
_ATLAS_UI_BUNDLE = f"{_ATLAS_UI_RUN}/evidence_bundles/INC-0001.zip"
_ATLAS_UI_REGRESSION = f"{_ATLAS_UI_RUN}/regression_tests/INC-0001.yaml"
_PYTHON = sys.executable


@dataclass
class AllowedCommand:
    """Definition of an allowlisted command"""
    id: str
    title: str
    description: str
    command: List[str]  # Command as argument list (not shell string)
    enabled: bool
    disabled_reason: Optional[str]
    timeout_s: int
    requires_gpu: bool = False
    requires_cameras: bool = False


# Hardcoded allowlist - no dynamic construction
ALLOWLIST: List[AllowedCommand] = [
    # Runnable commands
    AllowedCommand(
        id="run-demo-replay",
        title="Run Demo Replay",
        description="Build the camera-free demo replay, Command Center sample, evidence workspace, and USD export",
        command=[_PYTHON, "tools/run_ui_demo_replay.py"],
        enabled=True,
        disabled_reason=None,
        timeout_s=120,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="doctor",
        title="Doctor",
        description="Run health diagnostics across 8 system checks",
        command=[_PYTHON, "-m", "metriplane.cli", "doctor"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30
    ),
    AllowedCommand(
        id="preflight",
        title="Preflight",
        description="Check system dependencies and configuration",
        command=["./tools/mp.sh", "preflight"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30
    ),
    AllowedCommand(
        id="deterministic-replay",
        title="Deterministic Replay",
        description="M9.1: Verify bit-exact reproducibility across runs",
        command=["./tools/mp.sh", "deterministic-replay"],
        enabled=True,
        disabled_reason=None,
        timeout_s=120
    ),
    AllowedCommand(
        id="backpressure",
        title="Backpressure Test",
        description="M9.2: Test graceful degradation under synthetic load",
        command=["./tools/mp.sh", "backpressure"],
        enabled=True,
        disabled_reason=None,
        timeout_s=60
    ),
    AllowedCommand(
        id="gpu-smoke",
        title="GPU Smoke Test",
        description="M9.6: Verify CuPy and CUDA device availability",
        command=["./tools/mp.sh", "gpu-smoke"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_gpu=True
    ),
    AllowedCommand(
        id="gpu-benchmark",
        title="GPU Benchmark",
        description="M9.6: Compare CPU vs GPU compute backend performance",
        command=["./tools/mp.sh", "gpu-benchmark"],
        enabled=True,
        disabled_reason=None,
        timeout_s=60,
        requires_gpu=True
    ),
    
    # Disabled commands (not runnable yet)
    AllowedCommand(
        id="health-degrade-cam1",
        title="Health Degradation",
        description="M9.3: Simulate camera failure",
        command=["./tools/mp.sh", "health-degrade-cam1"],
        enabled=False,
        disabled_reason="Requires second capture-capable camera",
        timeout_s=60,
        requires_cameras=True
    ),
    AllowedCommand(
        id="gpu-equivalence",
        title="GPU Equivalence Test",
        description="M9.6: CPU vs GPU output comparison",
        command=["./tools/mp.sh", "gpu-equivalence"],
        enabled=False,
        disabled_reason="Requires visible ArUco markers in test session",
        timeout_s=60,
        requires_gpu=True
    ),
    AllowedCommand(
        id="run-fusion",
        title="Run Fusion",
        description="Start fusion pipeline with live cameras",
        command=["./tools/mp.sh", "run-fusion", "cpu", "60", "test"],
        enabled=False,
        disabled_reason="Hardware/configuration dependent - use CLI directly",
        timeout_s=300,
        requires_cameras=True
    ),
    # Operator workflow commands
    AllowedCommand(
        id="provenance",
        title="Provenance Check",
        description="M9.4: Verify run_id, config_hash, and git commit stamping without opening cameras",
        command=["./tools/mp.sh", "provenance"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_cameras=False
    ),
    AllowedCommand(
        id="timing-breakdown",
        title="Camera-Free Latency Check",
        description="Measure replay/rule-engine latency without opening local cameras",
        command=[_PYTHON, "tools/run_ui_timing_check.py"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False
    ),
    AllowedCommand(
        id="list-cameras",
        title="List Cameras",
        description="Discover available v4l2 camera devices (JSON output)",
        command=[_PYTHON, "tools/list_cameras.py"],
        enabled=True,
        disabled_reason=None,
        timeout_s=20,
        requires_cameras=False
    ),
    # Command Center sample: one-click replay that populates the incident view.
    AllowedCommand(
        id="sentinel-demo",
        title="Build Command Center Sample",
        description="Run the camera-free incident sample and write a run the Command Center can display",
        command=[_PYTHON, "-m", "metriplane.cli", "sentinel", "run",
                 "--config", "configs/sentinel_operator_demo.yaml",
                 "--run-id", "metriplane_demo", "--runs-dir", _RUNS_DIR],
        enabled=True,
        disabled_reason=None,
        timeout_s=60,
        requires_cameras=False
    ),
    # Metriplane evidence actions. These write only generated,
    # gitignored dashboard artifacts under web/dashboard/atlas_run.
    AllowedCommand(
        id="atlas-validate-pack",
        title="Validate Evidence Rules",
        description="Validate the checked-in assembly-cell evidence rules",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "validate-pack",
                 "configs/domain_packs/assembly_cell"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-demo",
        title="Build Evidence Sample",
        description="Run the Metriplane evidence workflow over the assembly-cell sample and publish local dashboard artifacts",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "run",
                 "--session-jsonl", "datasets/demo/atlas/assembly_cell_missing_tool.jsonl",
                 "--pack", "configs/domain_packs/assembly_cell",
                 "--out", _ATLAS_UI_RUN,
                 "--run-id", "metriplane_sample"],
        enabled=True,
        disabled_reason=None,
        timeout_s=90,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-verify-demo",
        title="Verify Incident Archive",
        description="Verify checksums and required contents for the generated incident evidence archive",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "bundle", "verify",
                 _ATLAS_UI_BUNDLE],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-regression-demo",
        title="Replay Evidence Regression",
        description="Replay the generated physical regression spec for the incident",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "test",
                 _ATLAS_UI_REGRESSION, "--json"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-query-demo-events",
        title="Query Event Ledger",
        description="Return the run's physical event ledger as JSON",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "query", "events",
                 "--run-dir", _ATLAS_UI_RUN, "--json"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-lake-build",
        title="Build Evidence Index",
        description="Index generated manifests, incidents, and events into a local SQLite evidence index",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "lake", "build",
                 "--root", _ATLAS_UI_RUN,
                 "--db", f"{_ATLAS_UI_RUN}/evidence_lake.sqlite"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-protocol-export",
        title="Export Protocol Files",
        description="Write local protocol schema/index artifacts for external interchange",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "protocol", "export",
                 "--out", f"{_ATLAS_UI_RUN}/protocol"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-pilot-kit",
        title="Create Field Review Kit",
        description="Create external review checklist, script, and review templates",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "pilot", "kit",
                 "--out", f"{_ATLAS_UI_RUN}/pilot_kit"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-freeze-build",
        title="Build Audit Snapshot",
        description="Build a local evidence audit and review-note snapshot",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "freeze", "build",
                 "--root", ".",
                 "--out", f"{_ATLAS_UI_RUN}/evidence_freeze"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="atlas-edge-doctor",
        title="Run Edge Readiness",
        description="Check generated evidence storage and edge-appliance readiness signals",
        command=[_PYTHON, "-m", "metriplane.cli", "atlas", "edge", "doctor",
                 "--runs-root", _ATLAS_UI_RUN,
                 "--min-free-mb", "64"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="integration-omniverse-export",
        title="Export Omniverse USD Replay",
        description="Write a USD replay scene from the current Metriplane evidence run",
        command=[_PYTHON, "-m", "integrations.omniverse.metriplane_usd_replay",
                 "--run-dir", _ATLAS_UI_BUNDLE_DIR,
                 "--out", f"{_ATLAS_UI_RUN}/omniverse/metriplane_replay.usda"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="integration-isaac-export",
        title="Export Isaac USD Replay",
        description="Write a USD replay scene compatible with Isaac Sim",
        command=[_PYTHON, "-m", "integrations.isaac.metriplane_to_usd",
                 "--run-dir", _ATLAS_UI_BUNDLE_DIR,
                 "--out", f"{_ATLAS_UI_RUN}/isaac/metriplane_replay.usda"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="integration-ros2-check",
        title="Check ROS 2 Bridge Adapters",
        description="Run ROS-free checks for the Metriplane ROS 2 message adapters",
        command=[_PYTHON, "tools/check_ros2_adapters.py"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="docker-check",
        title="Check Docker",
        description="Check whether Docker is available for the local demo container path",
        command=["docker", "--version"],
        enabled=True,
        disabled_reason=None,
        timeout_s=20,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="docker-demo-up",
        title="Start Docker Demo",
        description="Start the camera-free Docker demo if Docker is installed",
        command=["./tools/docker_demo_up.sh"],
        enabled=True,
        disabled_reason=None,
        timeout_s=120,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="docker-stop",
        title="Stop Docker Demo",
        description="Stop local Metriplane Docker demo containers",
        command=["./tools/docker_stop.sh"],
        enabled=True,
        disabled_reason=None,
        timeout_s=60,
        requires_cameras=False,
    ),
    AllowedCommand(
        id="cleanup",
        title="Check Stale Processes",
        description="Runner-safe cleanup check that keeps the active UI stack online",
        command=[_PYTHON, "tools/ui_safe_cleanup.py"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_cameras=False,
    ),
]


def get_command(command_id: str) -> Optional[AllowedCommand]:
    """Get command by ID from allowlist"""
    for cmd in ALLOWLIST:
        if cmd.id == command_id:
            return cmd
    return None


def validate_command_id(command_id: str) -> bool:
    """Check if command_id exists in allowlist (security check)"""
    # Reject suspicious patterns
    if not command_id.replace('-', '').replace('_', '').isalnum():
        return False
    if '..' in command_id or '/' in command_id:
        return False
    return get_command(command_id) is not None
