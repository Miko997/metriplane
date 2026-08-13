# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Bounded ROS 2/MCAP recorded-state adapter."""

from .core import AdapterError, convert, inspect_source
from .finalize import FinalizationError, finalize_conversion_equivalence
from .generator import generate_source

__all__ = [
    "AdapterError",
    "FinalizationError",
    "convert",
    "finalize_conversion_equivalence",
    "generate_source",
    "inspect_source",
]
