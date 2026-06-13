from __future__ import annotations

from metriplane.forecasting.velocity import MAX_SPEED_MPS, VelocityEstimator


def test_estimates_velocity_from_two_points():
    est = VelocityEstimator()
    est.observe("a", 0.0, (0.0, 0.0))
    est.observe("a", 1.0, (2.0, 0.0))
    v = est.estimate("a", None)
    assert v.vx == 2.0
    assert v.vy == 0.0
    assert v.source == "trace"
    assert v.n_points == 2


def test_prefers_trace_over_vel_world():
    est = VelocityEstimator()
    est.observe("a", 0.0, (0.0, 0.0))
    est.observe("a", 1.0, (1.0, 0.0))
    v = est.estimate("a", (9.0, 9.0))
    assert v.source == "trace"
    assert v.vx == 1.0


def test_falls_back_to_vel_world():
    est = VelocityEstimator()
    est.observe("a", 0.0, (0.0, 0.0))  # only one point → no trace velocity
    v = est.estimate("a", (1.5, 0.0))
    assert v.source == "vel_world"
    assert v.confidence == 0.4


def test_no_velocity_without_data():
    est = VelocityEstimator()
    v = est.estimate("a", None)
    assert v.source == "none"
    assert v.speed == 0.0
    assert v.confidence == 0.0


def test_ignores_missing_position():
    est = VelocityEstimator()
    est.observe("a", 0.0, None)
    est.observe("a", 1.0, None)
    assert est.n_points("a") == 0


def test_zero_dt_safe():
    est = VelocityEstimator()
    est.observe("a", 1.0, (0.0, 0.0))
    est.observe("a", 1.0, (5.0, 0.0))  # same timestamp
    v = est.estimate("a", None)
    # dt == 0 → cannot derive trace velocity, no vel_world → none
    assert v.source == "none"


def test_velocity_clamped():
    est = VelocityEstimator()
    est.observe("a", 0.0, (0.0, 0.0))
    est.observe("a", 0.001, (100.0, 0.0))  # absurd jump
    v = est.estimate("a", None)
    assert v.speed <= MAX_SPEED_MPS + 1e-6


def test_confidence_tiers():
    est = VelocityEstimator()
    est.observe("a", 0.0, (0.0, 0.0))
    est.observe("a", 1.0, (1.0, 0.0))
    assert est.estimate("a", None).confidence == 0.6
    est.observe("a", 2.0, (2.0, 0.0))
    assert est.estimate("a", None).confidence == 0.8
