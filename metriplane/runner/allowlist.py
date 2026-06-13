"""
Command allowlist for Dashboard V2 Runner

Defines safe, pre-approved commands that can be executed via the dashboard.
No arbitrary command execution allowed.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_RUNS_DIR = str(Path.home() / "metriplane-runs")


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
        id="doctor",
        title="Doctor",
        description="Run health diagnostics across 8 system checks",
        command=["python", "-m", "metriplane.cli", "doctor"],
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
        description="M9.4: Verify run_id, config_hash, and git commit stamping",
        command=["./tools/mp.sh", "provenance"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
        requires_cameras=True
    ),
    AllowedCommand(
        id="timing-breakdown",
        title="Timing Breakdown",
        description="M9.5: Measure per-stage latencies across pipeline",
        command=["./tools/mp.sh", "timing-breakdown"],
        enabled=True,
        disabled_reason=None,
        timeout_s=45,
        requires_cameras=True
    ),
    AllowedCommand(
        id="list-cameras",
        title="List Cameras",
        description="Discover available v4l2 camera devices (JSON output)",
        command=["python", "tools/list_cameras.py"],
        enabled=True,
        disabled_reason=None,
        timeout_s=20,
        requires_cameras=False
    ),
    # Sentinel command-center: one-click demo that populates the Command Center.
    AllowedCommand(
        id="sentinel-demo",
        title="Run Sentinel Demo",
        description="Run the Sentinel shadow-auditor demo (replay, no camera) and write a "
                    "run the Command Center can display",
        command=["python", "-m", "metriplane.cli", "sentinel", "run",
                 "--config", "configs/sentinel_operator_demo.yaml",
                 "--run-id", "sentinel_demo", "--runs-dir", _RUNS_DIR],
        enabled=True,
        disabled_reason=None,
        timeout_s=60,
        requires_cameras=False
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
