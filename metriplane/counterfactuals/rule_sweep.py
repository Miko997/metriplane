# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.counterfactuals.models import CounterfactualTransform


def parse_sweep(spec: str) -> tuple[str, str, list[float]]:
    """
    Parse a sweep spec of the form 'rule_id.field=start:stop:step'.

    Returns (rule_id, field, values). Range is inclusive of stop (within float eps).
    """
    if "=" not in spec:
        raise ValueError(f"invalid sweep spec (missing '='): {spec!r}")
    lhs, rhs = spec.split("=", 1)
    if "." not in lhs:
        raise ValueError(f"invalid sweep target (expected rule_id.field): {lhs!r}")
    rule_id, field = lhs.rsplit(".", 1)
    parts = rhs.split(":")
    if len(parts) != 3:
        raise ValueError(f"invalid sweep range (expected start:stop:step): {rhs!r}")
    try:
        start, stop, step = (float(p) for p in parts)
    except ValueError as e:
        raise ValueError(f"invalid sweep numbers: {rhs!r}") from e
    if step <= 0:
        raise ValueError(f"sweep step must be > 0: {step}")
    values: list[float] = []
    v = start
    while v <= stop + 1e-9 and len(values) < 1000:
        values.append(round(v, 6))
        v += step
    return rule_id, field, values


def sweep_transforms(spec: str) -> list[CounterfactualTransform]:
    rule_id, field, values = parse_sweep(spec)
    return [
        CounterfactualTransform(
            type="rule_threshold_sweep",
            target=rule_id,
            params={"field": field, "value": v},
        )
        for v in values
    ]
