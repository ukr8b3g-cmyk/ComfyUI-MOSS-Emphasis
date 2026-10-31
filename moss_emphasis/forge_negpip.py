# SPDX-License-Identifier: AGPL-3.0-only
# Portions adapted from flyfront/sd-forge-negpip, 0570f23d (lib_negpip/moss.py),
# and Haoming02/sd-webui-forge-classic, 2d79fc2f (backend/text_processing/parsing.py).
# Copyright (C) 2023 AUTOMATIC1111; 2024 lllyasviel; 2025 Haoming02
# Copyright (C) 2025 hako-mikan; 2026 Haoming02
# Modifications (2026): native ComfyUI token transport, finite checks, independent
# Positive/Negative routing and model-local Attention. See NOTICE.md and LICENSE-AGPL-3.0.
"""Forge Original-style NegPiP; no Forge imports or global hooks."""
import json
import logging
import math
import re
import torch
from .config import EmphasisError, MAX_TEXT
from .tokens import PREFIX, SUFFIX
from .engine import KEY, is_native_moss, patch_joint, check_joint_patches

ATTENTION = re.compile(r"\\\(|\\\)|\\\[|\\\]|\\\\|\\|\(|\[|:\s*([+-]?[.\d]+)\s*\)|\)|\]|[^\\()\[\]:]+|:")
BREAK = re.compile(r"\s*\bBREAK\b\s*", re.S)
FORBIDDEN = {"hooks", "start_percent", "end_percent", "clip_start_percent", "clip_end_percent",
             "reference_latents", "concat_latent_image", "area", "mask", "control"}


def parse_segments(text):
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise EmphasisError("SYNTAX_LIMIT", "Forge text must be a string within the prompt length limit.")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            layout, _ = json.JSONDecoder().raw_decode(stripped)
        except ValueError:
            layout = None
        if isinstance(layout, dict):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Forge mode does not yet support Layout JSON; select an existing method.")
    result, rounds, squares = [], [], []

    def multiply(start, amount):
        for item in result[start:]:
            item[1] *= amount
            if not math.isfinite(item[1]):
                raise EmphasisError("INVALID_WEIGHT", "Explicit and nested weights must be finite.")

    for match in ATTENTION.finditer(text):
        token, number = match.group(0), match.group(1)
        if token.startswith("\\"):
            result.append([token[1:], 1.0])
        elif token in ("(", "["):
            (rounds if token == "(" else squares).append(len(result))
            if len(rounds) + len(squares) > 16:
                raise EmphasisError("SYNTAX_LIMIT", "Parenthesis nesting exceeds 16 levels.")
        elif number is not None and rounds:
            try:
                value = float(number)
            except ValueError as exc:
                raise EmphasisError("INVALID_WEIGHT", "Invalid explicit Forge weight.") from exc
            multiply(rounds.pop(), value)
        elif token == ")" and rounds:
            multiply(rounds.pop(), 1.1)
        elif token == "]" and squares:
            multiply(squares.pop(), 1 / 1.1)
        else:
            for index, part in enumerate(BREAK.split(token)):
                if index:
                    result.append(["BREAK", -1.0])
                result.append([part, 1.0])
    for start in rounds:
        multiply(start, 1.1)
    for start in squares:
        multiply(start, 1 / 1.1)
    merged = []
    for segment, weight in result or [["", 1.0]]:
        if merged and merged[-1][1] == weight:
            merged[-1][0] += segment
        else:
            merged.append([segment, weight])
    return [(" BREAK ", 1.0) if segment == "BREAK" and weight == -1 else (segment, weight)
            for segment, weight in merged]


def coefficient_values(weights, scale):
    fade = min(scale, 1.0)
    encoder, image, sign = [], [], []
    for weight in weights:
        if not math.isfinite(weight):
            raise EmphasisError("INVALID_WEIGHT", "Forge token weights must be finite.")
        q = -1.0 if weight < 0 else 1.0
        try:
            a = abs(weight) + (1 - abs(weight)) * fade if fade < 1 else 1.0
            value = q * max(abs(weight), 1e-4) ** scale if scale > 0 else q
        except OverflowError as exc:
            raise EmphasisError("INVALID_WEIGHT", "Forge weighting coefficient overflowed.") from exc
        if not math.isfinite(a) or not math.isfinite(value):
            raise EmphasisError("INVALID_WEIGHT", "Forge weighting coefficient overflowed.")
        encoder.append(a); image.append(value); sign.append(q)
    return tuple(encoder), tuple(image), tuple(sign)


def tokenize(clip, text, scale):
    parsed = parse_segments(text)
    outer = clip.tokenizer
    inner = getattr(outer, getattr(outer, "clip", ""), None)
    hf = getattr(inner, "tokenizer", None)
    if hf is None:
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Cannot locate the native MOSS Qwen tokenizer.")
    special = set(getattr(hf, "all_special_tokens", ()))
    special.update(getattr(hf, "get_added_vocab", lambda: {})())
    if any(marker and marker in text for marker in special):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Forge mode accepts plain text, without chat/vision special tokens or custom templates.")
    native = clip.tokenize(text)
    if not isinstance(native, dict) or len(native) != 1:
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Expected one native MOSS token stream.")
    name, sections = next(iter(native.items()))
    if len(sections) != 1 or any(type(item[0]) is not int for item in sections[0]):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Multiple token chunks or image embeddings are unsupported.")
    ids = [item[0] for item in sections[0]]
    # SDTokenizer unescapes parentheses even with disable_weights=True. Check
    # the template with plain probe text, not a false raw-body ID equivalence.
    probe = "moss template check"
    probe_tokens = clip.tokenize(probe)
    expected = list(hf.encode(PREFIX + probe + SUFFIX, add_special_tokens=False))
    if (list(probe_tokens) != [name] or len(probe_tokens[name]) != 1
            or [item[0] for item in probe_tokens[name][0]] != expected):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Native MOSS tokenizer/template differs from the supported plain-text contract.")
    if all(weight == 1 for _, weight in parsed):
        weights = [1.0] * len(ids)
    else:
        texts = [part for part, _ in parsed]
        texts[0] = texts[0].lstrip()
        texts[-1] = texts[-1].rstrip()
        for index in range(len(texts) - 1):
            trimmed = texts[index].rstrip()
            texts[index + 1] = texts[index][len(trimmed):] + texts[index + 1]
            texts[index] = trimmed
        ids = list(hf.encode(PREFIX, add_special_tokens=False))
        weights = [1.0] * len(ids)
        for part, (_, weight) in zip(texts, parsed):
            part_ids = list(hf.encode(part, add_special_tokens=False)) if part else []
            ids.extend(part_ids); weights.extend([weight] * len(part_ids))
        suffix = list(hf.encode(SUFFIX, add_special_tokens=False))
        ids.extend(suffix); weights.extend([1.0] * len(suffix))
    if len(ids) > 4096:
        raise EmphasisError("WEIGHTED_SPAN_TRUNCATED", "Forge prompts are limited to 4096 tokens including the template.")
    encoder, image, sign = coefficient_values(weights, scale)
    return {name: [list(zip(ids, encoder))]}, image, sign


def encode(clip, text, scale):
    tokenizer_type = type(clip.tokenizer)
    encoder_types = type(getattr(clip, "cond_stage_model", None)).__mro__
    if ((tokenizer_type.__module__, tokenizer_type.__name__) != ("comfy.text_encoders.moss_image", "MOSSImageTokenizer")
            or not any((base.__module__, base.__name__) == ("comfy.text_encoders.moss_image", "MOSSImageTEModel") for base in encoder_types)):
        raise EmphasisError("ENCODER_MODEL_MISMATCH", "Forge mode requires the native MOSS-Image Qwen3.5 CLIP loader.")
    patcher = getattr(clip, "patcher", None)
    if getattr(patcher, "forced_hooks", None) is not None:
        raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Scheduled CLIP hooks are unsupported in Forge mode.")
    options = getattr(patcher, "model_options", {})
    patches = getattr(patcher, "object_patches", {})
    if any(key.startswith("ppm_negpip") for key in options) or any("encode_token_weights" in key for key in patches):
        raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "Disable the upstream CLIP weighting patch.")
    tokens, image, sign = tokenize(clip, text, scale)
    cond = clip.encode_from_tokens_scheduled(tokens)
    if (len(cond) != 1 or cond[0][0].ndim != 3 or tuple(cond[0][0].shape[:2]) != (1, len(image))
            or FORBIDDEN.intersection(cond[0][1])):
        raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Expected one unmodified, full-length native MOSS conditioning.")
    if not torch.isfinite(cond[0][0]).all():
        raise EmphasisError("INVALID_WEIGHT", "Weighted encoding exceeds the working dtype; reduce the weight.")
    return cond, image, sign


def execute(model, positive_clip, positive_text, negative_clip, negative_text, config):
    if not config["enabled"] or not is_native_moss(model, strict=False):
        if config["enabled"]:
            logging.info("[MOSS Emphasis] Forge mode bypassed: this model is not native MOSS-Image; saved settings retained.")
        # No cross-branch reuse: avoid assuming hooks/LoRA/options match on bypass.
        return (model, positive_clip.encode_from_tokens_scheduled(positive_clip.tokenize(positive_text)),
                negative_clip.encode_from_tokens_scheduled(negative_clip.tokenize(negative_text)))
    if any(key.startswith("ppm_negpip") for key in model.model_options):
        raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "Disable the upstream MODEL weighting patch.")
    wrappers = getattr(model, "wrappers", {})
    if any(KEY in group for group in wrappers.values()):
        raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "MOSS Emphasis is already applied to this MODEL.")
    if any(wrappers.values()):
        raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Another model execution wrapper is active; disable it for Forge mode.")
    scale = config["v_scaling_strength"]
    positive = encode(positive_clip, positive_text, scale)
    # Encode independently. No cache or object-equivalence heuristics are needed.
    negative = encode(negative_clip, negative_text, scale)
    if all(value == 1 for branch in (positive, negative) for values in branch[1:] for value in values):
        check_joint_patches(model)
        return model, positive[0], negative[0]
    weighted = patch_joint(model, lambda: ForwardState(positive, negative, scale), attention=run_attention)
    return weighted, positive[0], negative[0]


class ForwardState:
    def __init__(self, positive, negative, scale):
        self.branches = tuple((cond[0][0][0].detach().cpu().clone(), image, sign)
                              for cond, image, sign in (positive, negative))
        self.scale = scale

    def __call__(self, executor, x, timestep, context, transformer_options=None, **kwargs):
        options = dict(transformer_options or {})
        layout = options.get("cond_or_uncond")
        if (not isinstance(layout, (tuple, list)) or not layout or x.shape[0] % len(layout)
                or any(type(role) is not int or role not in (0, 1) for role in layout)):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Cannot identify Forge Positive/Negative batch rows.")
        if any(kwargs.get(key) is not None and (not isinstance(kwargs[key], (tuple, list)) or len(kwargs[key]))
               for key in ("ref_latents", "ref_kv")):
            raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Reference/edit conditioning is unsupported in Forge mode.")
        if context.ndim != 3 or context.shape[0] != x.shape[0]:
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Forge context batch changed after encoding.")
        chunk = x.shape[0] // len(layout)
        images, signs = [], []
        for role in layout:
            reference, image, sign = self.branches[role]
            if tuple(context.shape[1:]) != tuple(reference.shape):
                raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Forge conditioning length changed; batch the branches separately.")
            actual = reference.to(context)
            index = len(images) * chunk
            if any(not torch.equal(row, actual) for row in context[index:index + chunk]):
                raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Forge conditioning was modified after encoding.")
            images.append(image); signs.append(sign)
        # Everything below is owned by this forward, including any dtype-specific masks.
        amplifies = any(abs(value) > 1 for values in images for value in values)
        options[KEY] = (x.shape[-2] * x.shape[-1], context.shape[1], chunk, tuple(images), tuple(signs), self.scale, amplifies, {})
        return executor(x, timestep, context, options, **kwargs)


def run_attention(backend, container, q, k, v, heads, state, args, mask, options, kwargs):
    if kwargs.get("skip_reshape"):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Unexpected pre-reshaped Forge Attention input.")
    wrapped = isinstance(q, container)
    if any(isinstance(item, container) != wrapped for item in (k, v)):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Mixed Attention tensor ownership.")
    q, k, v = [item.take() if wrapped else item for item in (q, k, v)]
    start, length, chunk, images, signs, scale, amplifies, cache = state
    if (any(item.ndim != 3 or item.shape != q.shape or item.dtype != q.dtype or item.device != q.device for item in (q, k, v))
            or q.shape[1] != start + length or q.shape[0] != chunk * len(images) or start <= 0):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Expected native image+text Forge Q/K/V layout.")
    signature = (v.device, v.dtype)
    if signature not in cache:
        sign_factor = torch.tensor(signs, device=v.device, dtype=v.dtype).repeat_interleave(chunk, dim=0)
        image_factor = sign_factor if scale == 0 else torch.tensor(images, device=v.device, dtype=v.dtype).repeat_interleave(chunk, dim=0)
        factors = (image_factor, sign_factor)
        if any(not torch.isfinite(factor).all() for factor in factors):
            raise EmphasisError("INVALID_WEIGHT", "Forge Value coefficient exceeds the working dtype.")
        cache[signature] = factors
    image_factor, sign_factor = cache[signature]
    signed = v.clone()
    signed[:, start:] *= sign_factor[:, :, None]

    def call(query, values, current_mask):
        inputs = [container(item) for item in (query, k, values)] if wrapped else (query, k, values)
        return backend(*inputs, heads, *args, mask=current_mask, transformer_options=options, **kwargs)

    if scale == 0:
        return call(q, signed, mask)
    weighted = v.clone()
    weighted[:, start:] *= image_factor[:, :, None]
    if amplifies and not torch.isfinite(weighted[:, start:]).all():
        raise EmphasisError("INVALID_WEIGHT", "Forge weighted Value exceeds the working dtype; reduce the weight or V-Scaling strength.")
    image_mask, text_mask = mask, mask
    if mask is not None and mask.ndim >= 3 and mask.shape[-2] != 1:
        if mask.shape[-2] != q.shape[1]:
            raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Unexpected query-dependent Attention mask.")
        image_mask, text_mask = mask[..., :start, :], mask[..., start:, :]
    image = call(q[:, :start], weighted, image_mask)
    text = call(q[:, start:], signed, text_mask)
    return torch.cat((image, text), dim=2 if kwargs.get("skip_output_reshape") else 1)
