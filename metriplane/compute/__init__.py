"""metriplane.compute

M9.6: Optional GPU compute backends.

This package provides a small compute backend abstraction used by fusion code
to offload heavy arithmetic to GPU (CuPy) when available.
"""

from metriplane.compute.interface import FusionComputeBackend
from metriplane.compute.select import select_fusion_backend

__all__ = ["FusionComputeBackend", "select_fusion_backend"]
