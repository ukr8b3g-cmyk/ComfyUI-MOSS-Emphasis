"""Transactional API graph rewriting; the editor graph never reaches this code."""
from __future__ import annotations
import copy
import hashlib
import json
import re
from .config import EmphasisError, RUNTIME, RUNTIME_V2, settings, canonical, active_strength

TARGETS = {"KSampler", "KSamplerAdvanced", "CFGGuider"}
CONFLICTS = {"MossImagePromptWeight", "MOSSImagePromptWeight", "CLIPNegPip"}
FORBIDDEN = ("torchcompile", "teacache", "spectrum", "normalizedattentionguidance", "mossimagecontrol", "textencodemossimageedit")
# Match the NAG acronym as a node-name component, not inside words like "Manager".
NAG_MARKER = re.compile(r"NAG|Nag|(?:^|[^A-Za-z])nag")


def link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int and value[1] >= 0


def _validate(prompt):
    if not isinstance(prompt, dict) or len(prompt) > 10000:
        raise EmphasisError("INVALID_GRAPH", "Expected an API graph with at most 10000 nodes.")
    for key, node in prompt.items():
        if not isinstance(key, str) or not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise EmphasisError("INVALID_GRAPH", "Invalid node definition.", str(key))
    # Iterative topological validation, including disconnected components.
    parents, children = {}, {key: [] for key in prompt}
    for key, node in prompt.items():
        deps = {v[0] for v in node["inputs"].values() if link(v)}
        for dep in deps:
            if dep not in prompt:
                raise EmphasisError("INVALID_GRAPH", "Input links to a missing node.", key)
            children[dep].append(key)
        parents[key] = len(deps)
    pending = [key for key, count in parents.items() if not count]
    visited = 0
    while pending:
        visited += 1
        for key in children[pending.pop()]:
            parents[key] -= 1
            if not parents[key]:
                pending.append(key)
    if visited != len(prompt):
        raise EmphasisError("CYCLIC_GRAPH", "The execution graph contains a cycle.")


def _restore(prompt):
    for key in list(prompt):
        node = prompt[key]
        if node["class_type"] not in (RUNTIME, RUNTIME_V2):
            continue
        inp = node["inputs"]
        try:
            source = json.loads(inp["source"])
            encoder, target = source["encoder"], source["target"]
            enc = prompt[encoder]
            dest = prompt[target]["inputs"]
            if enc["class_type"] != "CLIPTextEncode" or dest["model"] != [key, 0] or dest["positive"] != [key, 1]:
                raise ValueError("links")
            if enc["inputs"]["clip"] != inp["clip"] or enc["inputs"]["text"] != inp["text"]:
                raise ValueError("source changed")
            if node["class_type"] == RUNTIME_V2:
                if dest["negative"] != [key, 2] or inp["negative"] != source["negative"]:
                    raise ValueError("negative changed")
                dest["negative"] = inp["negative"]
            for other, data in prompt.items():
                for v in data["inputs"].values():
                    if link(v) and v[0] == key and other != target:
                        raise ValueError("shared runtime")
            settings(json.loads(inp["settings_json"]))
            dest["model"], dest["positive"] = inp["model"], [encoder, 0]
            del prompt[key]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmphasisError("PREPARED_GRAPH_CHANGED", "Cannot safely reconstruct the original graph; export it again from the editor.", key) from exc


def _ancestors(prompt, start):
    stack, seen = [start], set()
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        yield key, prompt[key]
        stack.extend(v[0] for v in prompt[key]["inputs"].values() if link(v))


def prepare(prompt: dict, config: dict) -> dict:
    snapshot = settings(config)
    _validate(prompt)
    result = copy.deepcopy(prompt)
    _restore(result)
    if not snapshot["enabled"] or active_strength(snapshot) == 0:
        return {"prompt": result, "settings": snapshot, "targets": [], "warnings": []}
    targets = []
    auto = snapshot["schema_version"] == 3
    for key, node in list(result.items()):
        kind, inputs = node["class_type"], node["inputs"]
        unsupported = (kind not in TARGETS and (("sampler" in kind.lower() and ("positive" in inputs or "pipe" in inputs)) or "guider" in kind.lower()))
        if kind == "SamplerCustomAdvanced":
            guider = inputs.get("guider")
            if not link(guider) or result[guider[0]]["class_type"] != "CFGGuider":
                raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "SamplerCustomAdvanced requires ordinary CFGGuider.", key)
        if unsupported:
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "This sampler/guider is not supported in 0.9; disable MOSS Emphasis for this workflow.", key)
        if kind not in TARGETS:
            continue
        for name in (("model", "positive", "negative") if auto else ("model", "positive")):
            if not link(inputs.get(name)):
                raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", f"Expected a {name} link.", key)
            for upstream, data in _ancestors(result, inputs[name][0]):
                if data["class_type"] in CONFLICTS:
                    raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "An existing prompt-weight node is on this execution path.", upstream)
                upstream_kind = data["class_type"]
                if any(word in upstream_kind.lower() for word in FORBIDDEN) or NAG_MARKER.search(upstream_kind):
                    raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Edit/control/compile/acceleration/NAG combinations are not supported in 0.9.", upstream)
        encoder = inputs["positive"][0]
        enc = result[encoder]
        if enc["class_type"] != "CLIPTextEncode" or inputs["positive"][1] != 0:
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Positive must connect directly to ordinary CLIP Text Encode.", key)
        ein = enc["inputs"]
        if not link(ein.get("clip")) or not (isinstance(ein.get("text"), str) or link(ein.get("text"))):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "CLIP Text Encode needs clip and text inputs.", encoder)
        runtime_id = "_moss_emphasis_" + hashlib.sha256(key.encode()).hexdigest()[:16]
        if runtime_id in result:
            raise EmphasisError("NODE_ID_COLLISION", "Internal ID already exists.", key)
        source = {"encoder": encoder, "target": key}
        if auto:
            source["negative"] = copy.deepcopy(inputs["negative"])
        result[runtime_id] = {"class_type": RUNTIME_V2 if auto else RUNTIME, "inputs": {
            "model": copy.deepcopy(inputs["model"]), "clip": copy.deepcopy(ein["clip"]), "text": copy.deepcopy(ein["text"]),
            "settings_json": canonical(snapshot), "source": json.dumps(source, sort_keys=True)}}
        if auto:
            result[runtime_id]["inputs"]["negative"] = copy.deepcopy(inputs["negative"])
            inputs["negative"] = [runtime_id, 2]
        inputs["model"], inputs["positive"] = [runtime_id, 0], [runtime_id, 1]
        targets.append({"target": key, "encoder": encoder, "runtime": runtime_id})
    if not targets:
        raise EmphasisError("NO_SUPPORTED_SAMPLER", "No supported KSampler/KSamplerAdvanced/CFGGuider path found. Disable the extension for other workflows.")
    _validate(result)
    return {"prompt": result, "settings": snapshot, "targets": targets, "warnings": []}
