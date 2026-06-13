from __future__ import annotations

from metriplane.assistant.models import IntentType

# Ordered: first matching intent wins. Keywords are lowercased substrings.
_INTENT_KEYWORDS: list[tuple[IntentType, tuple[str, ...]]] = [
    ("camera_health", ("camera", "cam0", "cam1", "unreliable", "trust",
                        "calibration", "dropout")),
    ("rule_explanation", ("rule", "contract", "why did", "which rule", "what rule")),
    ("zone_occupancy", ("zone", "exit lane", "exit_lane", "dwell", "blocked",
                        "occupanc")),
    ("object_history", ("object", "cart", "pallet", "human", "path", "where",
                        "trace", "speed", "distance travel")),
    ("incident_search", ("incident", "violation", "happened", "unsafe", "alert",
                         "when was", "how many")),
    ("run_comparison", ("compare", "changed", "before", "after", "difference")),
]

_SUPPORTED = [
    "incident_search — e.g. 'when did an incident happen?'",
    "object_history — e.g. 'where did cart_01 go?'",
    "zone_occupancy — e.g. 'was the exit lane blocked?'",
    "rule_explanation — e.g. 'which rule triggered the incident?'",
    "camera_health — e.g. 'which camera was unreliable?'",
]


def classify(question: str) -> IntentType:
    q = question.lower()
    for intent, keywords in _INTENT_KEYWORDS:
        if any(k in q for k in keywords):
            return intent
    return "unknown"


def supported_questions() -> list[str]:
    return list(_SUPPORTED)
