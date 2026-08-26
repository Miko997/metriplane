# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations


def precision_recall_f1(expected: list[str], observed: list[str]) -> dict:
    """Set-based precision/recall/F1 over rule-id labels."""
    exp = set(expected)
    obs = set(observed)
    tp = len(exp & obs)
    fp = len(obs - exp)
    fn = len(exp - obs)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def compare_incidents(expected: list[dict], observed: list[dict]) -> dict:
    """Compare incidents by rule_id (precision/recall/f1)."""
    exp = [e.get("rule_id", "") for e in expected]
    obs = [o.get("rule_id", "") for o in observed]
    return precision_recall_f1(exp, obs)


def compare_replay_hash(hash_a: str, hash_b: str) -> bool:
    return hash_a == hash_b


def latency_summary(samples: list[float]) -> dict:
    if not samples:
        return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "mean_ms": 0.0, "n": 0}
    s = sorted(samples)

    def pct(q: float) -> float:
        idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
        return s[idx]

    return {
        "p50_ms": round(pct(0.50), 6),
        "p95_ms": round(pct(0.95), 6),
        "p99_ms": round(pct(0.99), 6),
        "mean_ms": round(sum(s) / len(s), 6),
        "n": len(s),
    }
