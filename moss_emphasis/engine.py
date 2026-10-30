"""Model-local DiT-only KJ-equation engine. No global attention replacement."""
from __future__ import annotations
import torch
import sys
import types
from pathlib import Path
import logging
import math
from .config import EmphasisError, coefficients, ENGINE, NEGPIP
from .negpip import negpip_coefficients, run_attention, MASK_CACHE_KEY

KEY = "moss_emphasis.v1"


# ComfyUI 0.42.x loads its official SLG file using the absolute filepath as
# module name (nodes.load_custom_node); do not compare __module__ to a constant.
# Resolve the already-loaded official class and compare the EXACT nested code
# object, not a spoofable filename suffix or broad module prefix.
_OFFICIAL_SLG_CALLBACKS = {
    "block": {
        "SkipLayerGuidanceDiT": "skip",
        "SkipLayerGuidanceDiTSimple": "skip",
    },
    "sampler_post_cfg_function": {"SkipLayerGuidanceDiT": "post_cfg_function"},
    "sampler_calc_cond_batch_function": {"SkipLayerGuidanceDiTSimple": "calc_cond_batch_function"},
}


def is_official_slg_callback(fn, slot):
    accepted = _OFFICIAL_SLG_CALLBACKS.get(slot, {})
    if not accepted or not isinstance(fn, types.FunctionType):
        return False
    try:
        import nodes
        official_file = (Path(nodes.__file__).resolve().parent / "comfy_extras" / "nodes_slg.py").resolve(strict=True)
        source_module = sys.modules.get(fn.__module__)
        if source_module is None or not hasattr(source_module, "__file__"):
            return False
        if Path(source_module.__file__).resolve(strict=True) != official_file:
            return False
        if Path(fn.__code__.co_filename).resolve(strict=True) != official_file:
            return False
        if fn.__globals__ is not vars(source_module):
            return False
        for class_name, nested_name in accepted.items():
            cls = getattr(source_module, class_name, None)
            method = getattr(cls, "execute", None)
            code = getattr(getattr(method, "__func__", method), "__code__", None)
            if code is None:
                continue
            for const in code.co_consts:
                if isinstance(const, types.CodeType) and const.co_name == nested_name and fn.__code__ is const:
                    return True
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        pass
    return False


def select_attention_backend(attn):
    """Never change the user-selected backend or a model's per-layer kernel."""
    backend = attn.optimized_attention
    if backend is getattr(attn, "attention_pytorch", None) or backend is getattr(attn, "attention_basic", None):
        return backend, "native_pytorch_basic"
    if backend is getattr(attn, "attention_comfy_kitchen_int8", None):
        if not callable(getattr(backend, "container_function", None)):
            raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Comfy Kitchen INT8 requires ComfyUI's container/prequantized attention path.")
        return backend, "comfy_kitchen_int8"
    raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Supported global backends: PyTorch/basic and native --use-ck-attention. Sage/Flash/SOL/custom overrides are not enabled or silently replaced.")




def combine_mask(mask, bias):
    if bias is None:
        return mask
    if mask is None:
        return bias
    if mask.device != bias.device or mask.shape[-1] != bias.shape[-1] or mask.ndim not in (2, 3, 4):
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Unsupported existing attention-mask shape/device.")
    if mask.dtype == torch.bool:
        mask = torch.zeros_like(mask, dtype=bias.dtype).masked_fill(~mask, float("-inf"))
    else:
        mask = mask.to(bias.dtype)
    if mask.ndim == 2:
        mask = mask[:, None, None, :]
    elif mask.ndim == 3:
        mask = mask[:, None, :, :]
    # Never allocate a new sequence-by-sequence mask just for emphasis.
    if mask.shape[-2] != 1:
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Dense/query-dependent masks are unsupported in 0.9.")
    return mask + bias


def apply_values(v, rows, start, factors):
    if v.ndim != 3 or start + len(factors) != v.shape[1]:
        raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Expected [batch, image+text, channels] value vectors.")
    out = v.clone()
    for row in rows:
        out[row, start:] *= factors.to(device=v.device, dtype=v.dtype)[:, None]
    return out


class ForwardState:
    """One reference and at most one device copy; owned by a cloned ModelPatcher."""
    def __init__(self, reference, weights, strength, engine=ENGINE):
        self.reference = reference.detach().cpu().clone()
        self.weights = negpip_coefficients(weights, strength) if engine == NEGPIP else tuple(coefficients(w, strength) for w in weights)
        if any(not math.isfinite(value) for pair in self.weights for value in pair):
            raise EmphasisError("INVALID_WEIGHT", "Computed weighting coefficients overflowed; reduce the prompt weight or strength.")
        self.max_coefficient = max(abs(value) for pair in self.weights for value in pair)
        self.device_reference = None
        self.negpip = engine == NEGPIP

    def __call__(self, executor, x, timestep, context, transformer_options=None, **kwargs):
        options = dict(transformer_options or {})
        if self.negpip:
            # Owned by this forward only; shallow per-block option copies share it.
            options[MASK_CACHE_KEY] = {}
        layout = options.get("cond_or_uncond")
        if not isinstance(layout, (list, tuple)) or not layout or any(type(v) is not int or v not in (0, 1) for v in layout) or x.shape[0] % len(layout):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Cannot identify positive/negative batch rows.")
        if any(kwargs.get(k) is not None and (not isinstance(kwargs[k], (list, tuple)) or len(kwargs[k])) for k in ("ref_latents", "ref_kv")):
            raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Reference image/edit conditioning is unsupported.")
        chunk = x.shape[0] // len(layout)
        rows = [i for i in range(x.shape[0]) if layout[i // chunk] == 0]
        options.pop(KEY, None)
        if rows:
            if context.ndim != 3 or context.shape[0] != x.shape[0] or tuple(context.shape[1:]) != tuple(self.reference.shape):
                raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Positive conditioning shape changed after encoding.")
            if self.device_reference is None or self.device_reference.device != context.device or self.device_reference.dtype != context.dtype:
                self.device_reference = self.reference.to(context)
            if any(not torch.equal(context[i], self.device_reference) for i in rows):
                raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Positive conditioning was modified after encoding.")
            start, length = x.shape[-2] * x.shape[-1], context.shape[1]
            if self.max_coefficient > torch.finfo(context.dtype).max:
                raise EmphasisError("INVALID_WEIGHT", f"Computed weighting coefficients exceed {context.dtype}; reduce the prompt weight or strength.")
            factors = torch.tensor([p[0] for p in self.weights], device=context.device, dtype=context.dtype)
            biases = torch.tensor([p[1] for p in self.weights], device=context.device, dtype=context.dtype)
            additive = None
            if any(p[1] != 0 for p in self.weights):
                additive = torch.zeros((x.shape[0], 1, 1, start + length), device=context.device, dtype=context.dtype)
                additive[rows, 0, 0, start:] = biases
            options[KEY] = (tuple(rows), start, factors if any(p[0] != 1 for p in self.weights) else None, additive)
        return executor(x, timestep, context, options, **kwargs)


def is_native_moss(model):
    diffusion = model.get_model_object("diffusion_model")
    cls = type(diffusion)
    if cls.__module__ == "comfy.ldm.moss_image.model" and cls.__name__ == "MOSSImage":
        return True
    if "moss" in (cls.__module__ + "." + cls.__name__).lower():
        raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Use ComfyUI's native MOSS-Image loader; this MOSS implementation is unsupported.")
    return False


def patch(model, conditioning, weights, strength, engine=ENGINE):
    from comfy.ldm.modules import attention as attn
    from comfy.patcher_extension import WrappersMP
    diffusion = model.get_model_object("diffusion_model")
    options = model.model_options.get("transformer_options", {})
    if options.get(KEY) or any(k in str(options.get("wrappers", {})) for k in ("MossImagePromptWeight", "moss_prompt_weight", KEY)):
        raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "A prompt-weight patch is already active.")
    if options.get("optimized_attention_override") or options.get("wrappers"):
        raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Another attention/execution override is active; disable it for 0.9.")
    for group in options.get("patches_replace", {}).values():
        for func in group.values():
            if not is_official_slg_callback(func, "block"):
                raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Unsupported block replacement patch.")
    for key in ("sampler_cfg_function", "model_function_wrapper", "denoise_mask_function"):
        if model.model_options.get(key):
            raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", f"Unsupported model option: {key}.")
    for key in ("sampler_post_cfg_function", "sampler_calc_cond_batch_function", "sampler_pre_cfg_function"):
        funcs = model.model_options.get(key, [])
        if not isinstance(funcs, (list, tuple)):
            funcs = [funcs]
        if any(not is_official_slg_callback(fn, key) for fn in funcs):
            raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", f"Unsupported guidance patch: {key}.")
    backend, backend_kind = select_attention_backend(attn)
    if len(getattr(diffusion, "layers", [])) != 42 or not hasattr(diffusion, "text_embedder"):
        raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Expected the native 42-block MOSS-Image architecture.")

    class LocalAttention(attn.ComfyAttention):
        def __init__(self, original):
            super().__init__()
            self.config, self.method = original.config, getattr(original, "method", None)
            self.function = self.run

        def run(self, q, k, v, heads, *args, mask=None, transformer_options=None, **kwargs):
            opts = transformer_options or {}
            if opts.get("optimized_attention_override"):
                raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "A late attention override would bypass emphasis.")
            if backend_kind == "comfy_kitchen_int8" and kwargs.get("low_precision_attention", True) is False:
                qt = q.peek() if isinstance(q, attn.AttentionTensorContainer) else q
                if qt.dtype == torch.float32:
                    raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Comfy Kitchen would fall back to PyTorch for float32 + low_precision_attention=False; no silent fallback.")
            state = opts.get(KEY)
            if state:
                rows, start, factors, bias = state
                if engine == NEGPIP:
                    return run_attention(backend, attn.AttentionTensorContainer, q, k, v, heads,
                                         rows, start, len(weights), factors, bias, args, mask, opts, kwargs)
                if kwargs.get("skip_reshape"):
                    raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Unexpected pre-reshaped attention input.")
                kt = k.peek() if isinstance(k, attn.AttentionTensorContainer) else k
                if kt.ndim != 3 or (bias is not None and kt.shape[1] != bias.shape[-1]):
                    raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Unexpected key/reference token layout.")
                if factors is not None:
                    if isinstance(v, attn.AttentionTensorContainer):
                        v = attn.AttentionTensorContainer(apply_values(v.take(), rows, start, factors))
                    else:
                        v = apply_values(v, rows, start, factors)
                mask = combine_mask(mask, bias)
            return backend(q, k, v, heads, *args, mask=mask, transformer_options=opts, **kwargs)

    patches = []
    for i in range(len(diffusion.layers)):
        path = f"diffusion_model.layers.{i}.comfy_attention"
        current = model.get_model_object(path)
        if type(current) is not attn.ComfyAttention or current.function is not None or current.config is not None:
            raise EmphasisError("UNSUPPORTED_ATTENTION_BACKEND", "Per-layer INT8/SOL/custom ComfyAttention configurations remain unsupported; use only the global --use-ck-attention path.")
        patches.append((path, LocalAttention(current)))
    cloned = model.clone()
    for path, replacement in patches:
        cloned.add_object_patch(path, replacement)
    cloned.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, KEY, ForwardState(conditioning[0][0][0], weights, strength, engine))
    logging.info("[MOSS Emphasis] selected attention backend=%s (original global kernel retained)", backend_kind)
    return cloned
