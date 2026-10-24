"""Immutable, versioned execution settings. Never read process-global UI state."""
from __future__ import annotations
import json
import math
from . import VERSION

ENGINE = "kj_dit_v1"
RUNTIME = "_MossEmphasisRuntimeV1"
MAX_TEXT = 262144

class EmphasisError(ValueError):
    def __init__(self, code: str, message: str, node_id: str = ""):
        self.code, self.message, self.node_id = code, message, node_id
        super().__init__(f"MOSS Emphasis [{code}] {message}" + (f" (node {node_id})" if node_id else ""))

    def as_dict(self):
        return {"code": self.code, "message": self.message, "node_id": self.node_id}


def settings(value: dict | None) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise EmphasisError("INVALID_SETTINGS", "Settings must be an object.")
    for field, expected in (("schema_version", 1), ("engine", ENGINE), ("parser_version", 1), ("version", VERSION)):
        if field in value and (type(value[field]) is not type(expected) or value[field] != expected):
            raise EmphasisError("INVALID_SETTINGS", f"Unsupported {field}: {value[field]!r}.")
    enabled, strength = value.get("enabled", False), value.get("strength", 1.0)
    if type(enabled) is not bool or type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 4:
        raise EmphasisError("INVALID_SETTINGS", "enabled must be boolean; strength must be finite and within 0..4.")
    return {"schema_version": 1, "enabled": enabled, "strength": float(strength),
            "engine": ENGINE, "parser_version": 1, "version": VERSION}


def canonical(value: dict) -> str:
    return json.dumps(settings(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def coefficients(weight: float, strength: float) -> tuple[float, float]:
    """Return (value multiplier, additive logit bias), using the KJ equations."""
    return (1.0, 2.0 * strength * (weight - 1.0)) if weight > 1.0 else (1.0 + strength * (weight - 1.0), 0.0)
