"""Immutable, versioned execution settings. Never read process-global UI state."""
from __future__ import annotations
import json
import math
from . import VERSION

ENGINE = "kj_dit_v1"
NEGPIP = "ppm_negpip_moss_v1"
RUNTIME = "_MossEmphasisRuntimeV1"
RUNTIME_V2 = "_MossEmphasisRuntimeV2"
AUTO_ENGINE = "native_auto_v1"
AUTO_NEGPIP = "negpip_auto_v1"
FORGE = "forge_negpip_moss_v1"
RUNTIME_V3 = "_MossEmphasisRuntimeV3"
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
    # Retain saved v0.9 settings while snapshotting the current code version.
    schema = value.get("schema_version", 1)
    engine = value.get("engine", ENGINE)
    engines = {1: (ENGINE,), 2: (ENGINE, NEGPIP), 3: (AUTO_ENGINE, AUTO_NEGPIP), 4: (FORGE,)}
    if type(schema) is not int or schema not in engines or engine not in engines[schema]:
        raise EmphasisError("INVALID_SETTINGS", "Unsupported schema or engine.")
    for field, expected in (("parser_version", 1), ("engine_version", 1)):
        if field in value and (type(value[field]) is not type(expected) or value[field] != expected):
            raise EmphasisError("INVALID_SETTINGS", f"Unsupported {field}: {value[field]!r}.")
    if "version" in value and (type(value["version"]) is not str or value["version"] not in ("0.9.0", "0.9.1", "0.10.0", "0.10.1", VERSION)):
        raise EmphasisError("INVALID_SETTINGS", f"Unsupported version: {value['version']!r}.")
    enabled, strength = value.get("enabled", False), value.get("strength", 1.0)
    if type(enabled) is not bool or type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 4:
        raise EmphasisError("INVALID_SETTINGS", "enabled must be boolean; strength must be finite and within 0..4.")
    neg = value.get("negpip_strength", 1.0)
    if type(neg) not in (int, float) or not math.isfinite(neg) or not 0 <= neg <= 1:
        raise EmphasisError("INVALID_SETTINGS", "NegPiP strength must be finite and within 0..1.")
    result = {"schema_version": max(2, schema), "enabled": enabled, "strength": float(strength),
            "engine": engine, "negpip_strength": float(neg), "engine_version": 1,
            "parser_version": 1, "version": VERSION}
    if engine == FORGE:
        active, scale = value.get("v_scaling_enabled", False), value.get("v_scaling_strength", 1.0)
        if type(active) is not bool or type(scale) not in (int, float) or not math.isfinite(scale) or not 0 <= scale <= 2:
            raise EmphasisError("INVALID_SETTINGS", "V-Scaling must be boolean; strength must be finite and within 0..2.")
        # Inactive preferences never become execution inputs or cache dependencies.
        result.update(strength=1.0, negpip_strength=1.0,
                      v_scaling_enabled=active and scale > 0, v_scaling_strength=float(scale) if active else 0.0)
    return result


def active_strength(config):
    return config["negpip_strength"] if config["engine"] in (NEGPIP, AUTO_NEGPIP) else config["strength"]


def should_apply(config):
    return config["enabled"] and (config["engine"] == FORGE or active_strength(config) != 0)


def canonical(value: dict) -> str:
    return json.dumps(settings(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def coefficients(weight: float, strength: float) -> tuple[float, float]:
    """Return (value multiplier, additive logit bias), using the KJ equations."""
    return (1.0, 2.0 * strength * (weight - 1.0)) if weight > 1.0 else (1.0 + strength * (weight - 1.0), 0.0)
