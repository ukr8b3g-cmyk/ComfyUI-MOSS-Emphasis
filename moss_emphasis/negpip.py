"""MOSS-only NegPiP equations and query split; no PPM runtime dependency.

Reference equations: pamparamm/ComfyUI-ppm, 926e8bb5, moss_negpip.py.
The parser and model-local integration belong to MOSS Emphasis.
"""
import math
import torch
from .config import EmphasisError

MASK_CACHE_KEY = "moss_emphasis.negpip_masks"


def negpip_coefficients(weights, strength):
    if not weights or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise EmphasisError("INVALID_SETTINGS", "Invalid NegPiP strength or empty weights.")
    if any(not math.isfinite(w) for w in weights):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Invalid NegPiP token weights.")
    # Python double arithmetic keeps log/normalization out of FP16/BF16.
    logs = [math.log(max(abs(w), 1e-4)) for w in weights]
    peak = max(logs)
    norm = peak + math.log(math.fsum(math.exp(v - peak) for v in logs) / len(logs))
    return tuple((1 - 2 * strength if w < 0 else 1.0, strength * (v - norm))
                 for w, v in zip(weights, logs))


def compact_mask(mask, q, heads, length):
    if mask is None:
        return None
    if (mask.ndim != 4 or mask.device != q.device or mask.shape[-2:] != (1, length)
            or mask.shape[0] not in (1, q.shape[0]) or mask.shape[1] not in (1, heads)):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "NegPiP requires a compact [batch, heads, 1, keys] mask.")
    if mask.dtype == torch.bool:
        mask = torch.zeros_like(mask, dtype=q.dtype).masked_fill(~mask, -math.inf)
    elif not mask.is_floating_point():
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Expected a boolean or floating attention mask.")
    if torch.isnan(mask).any() or torch.isposinf(mask).any() or torch.isneginf(mask).all(-1).any():
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Invalid or fully blocked attention mask.")
    converted = mask.to(dtype=q.dtype)
    if (torch.isfinite(mask) & ~torch.isfinite(converted)).any():
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Attention mask exceeds the backend dtype range.")
    return converted


def run_attention(backend, container, q, k, v, heads, rows, start, length,
                  factors, bias, args, mask, options, kwargs):
    if kwargs.get("skip_reshape"):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Unexpected pre-reshaped NegPiP input.")
    wrapped = isinstance(q, container)
    if any(isinstance(t, container) != wrapped for t in (k, v)):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Mixed attention tensor ownership.")
    q, k, v = [t.take() if wrapped else t for t in (q, k, v)]
    if (any(t.ndim != 3 or t.shape != q.shape or t.device != q.device or t.dtype != q.dtype for t in (q, k, v))
            or q.shape[1] != start + length or start <= 0 or length <= 0):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Expected native image+text Q/K/V without reference keys.")
    positive = list(rows)
    negative = [i for i in range(q.shape[0]) if i not in rows]
    query_axis = 2 if kwargs.get("skip_output_reshape") else 1

    def select_mask(value, indices):
        return value if value is None or value.shape[0] == 1 else value[indices]

    def call(qpart, kpart, vpart, m):
        inputs = [container(t) for t in (qpart, kpart, vpart)] if wrapped else (qpart, kpart, vpart)
        return backend(*inputs, heads, *args, mask=m, transformer_options=options, **kwargs)

    qp, kp, vp = q[positive], k[positive], v[positive]
    original_mask = select_mask(mask, positive)
    weighted = vp
    if factors is not None:
        weighted = vp.clone()
        # Preserve the model's Value dtype before multiplication and quantization.
        weighted[:, start:] *= factors.to(device=v.device, dtype=v.dtype)[None, :, None]
    cache = options.get(MASK_CACHE_KEY, {})
    # Native MOSS inference masks are immutable within a forward. For ordinary
    # tensors also invalidate after in-place updates, without device readback.
    versions = tuple(t._version if t is not None and not t.is_inference() else None for t in (mask, bias))
    signature = (q.shape[0], heads, start + length, q.dtype, q.device, tuple(rows), versions)
    if cache.get("signature") == signature and cache.get("source_mask") is mask and cache.get("source_bias") is bias:
        image_mask = cache["image_mask"]
    else:
        image_mask = select_mask(compact_mask(mask, q, heads, start + length), positive)
        if bias is not None:
            # Generated coefficients are finite/bounded by negpip_coefficients on
            # CPU (finite double weights, floor 1e-4, effect 0..1). No device readback is
            # needed to revalidate this same bias in each of the 42 blocks.
            addition = select_mask(bias, positive).to(device=q.device, dtype=q.dtype)
            image_mask = addition if image_mask is None else compact_mask(image_mask + addition, qp, heads, start + length)
        cache.update(signature=signature, source_mask=mask, source_bias=bias, image_mask=image_mask)
    image = call(qp[:, :start], kp, weighted, image_mask)
    text = call(qp[:, start:], kp, vp, original_mask)
    pos = torch.cat((image, text), dim=query_axis)
    if not negative:
        return pos
    neg = call(q[negative], k[negative], v[negative], select_mask(mask, negative))
    out = pos.new_empty((q.shape[0], *pos.shape[1:]))
    out[positive], out[negative] = pos, neg
    return out
