"""Native SDXL/Anima weighting, with sampler-local NegPiP conditioning.

The native encoder owns empty-prompt interpolation, pooling and CLIP options.
Only token coefficients and the K/V transport are implemented here.
"""
import math
import torch
from .config import EmphasisError, active_strength, AUTO_NEGPIP

SIGN = "moss_emphasis_anima_sign"
PATCH = "moss_emphasis_auto"
FORBIDDEN = {"hooks", "start_percent", "end_percent", "clip_start_percent", "clip_end_percent",
             "area", "mask", "control", "reference_latents", "concat_latent_image"}


def model_family(model, clip):
    from comfy import model_base, sdxl_clip
    from comfy.text_encoders.anima import AnimaTokenizer, AnimaTEModel
    if type(model.model) is model_base.SDXL:
        family, tokenizer, encoder = "sdxl", sdxl_clip.SDXLTokenizer, sdxl_clip.SDXLClipModel
    elif type(model.model) is model_base.Anima:
        family, tokenizer, encoder = "anima", AnimaTokenizer, AnimaTEModel
    else:
        raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "Use native MOSS-Image, SDXL/Illustrious or Anima, or disable MOSS Emphasis.")
    if type(clip.tokenizer) is not tokenizer or not isinstance(clip.cond_stage_model, encoder):
        raise EmphasisError("ENCODER_MODEL_MISMATCH", f"Use the native {family} MODEL and CLIP combination.")
    return family


def check_patches(model, clip, negpip):
    for owner in (model, clip.patcher):
        if any(key.startswith("ppm_negpip") or key == PATCH for key in owner.model_options):
            raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "Disable the upstream prompt weighting patch.")
    if any("encode_token_weights" in key for key in clip.patcher.object_patches):
        raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "An upstream CLIP weighting patch is active.")
    if clip.patcher.forced_hooks is not None:
        raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Scheduled CLIP hooks are unsupported.")
    if negpip:
        options = model.model_options.get("transformer_options", {})
        if (options.get("patches", {}).get("attn2_patch") or
                options.get("patches_replace", {}).get("attn2")):
            raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "An upstream cross-attention patch is active.")


def weighted_tokens(tokens, keys, strength, negpip):
    """Copy only the token lists we change; retain token IDs and auxiliary fields."""
    result = dict(tokens)
    for key in keys:
        sections = []
        for section in tokens[key]:
            updated = []
            for token, weight, *rest in section:
                value = 1 + strength * ((abs(weight) if negpip else weight) - 1)
                if not math.isfinite(weight) or not math.isfinite(value):
                    raise EmphasisError("INVALID_WEIGHT", "Token weights and computed coefficients must be finite.")
                updated.append((token, value, *rest))
            sections.append(updated)
        result[key] = sections
    return result


def plain_conditioning(cond):
    if len(cond) != 1 or cond[0][0].ndim != 3 or FORBIDDEN.intersection(cond[0][1]):
        raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Use a single ordinary text conditioning without regions, schedules or control patches.")
    return cond[0]


def interleave(key, value):
    return torch.stack((key, value), dim=2).flatten(1, 2)


def split_sdxl(q, k, v, extra_options):
    if k.shape[1] % 2 or v.shape[1] != k.shape[1]:
        raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "NegPiP K/V conditioning was modified after encoding.")
    return q, k[:, ::2], v[:, 1::2]


def sdxl_conditioning(cond, tokens, clip, effect):
    key, metadata = plain_conditioning(cond)
    value = key.clone()
    offset = 0
    # CLIP-L and G have independent token positions, followed by channel concatenation.
    for name in ("l", "g"):
        width = getattr(clip.cond_stage_model, "clip_" + name).transformer.text_model.final_layer_norm.weight.numel()
        weights = [w for section in tokens[name] for _, w, *_ in section][:key.shape[1]]
        if len(weights) != key.shape[1]:
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "CLIP token/chunk alignment changed.")
        signs = key.new_tensor([1 - 2 * effect if w < 0 else 1 for w in weights])
        value[..., offset:offset + width] *= signs[None, :, None]
        offset += width
    if offset != key.shape[-1]:
        raise EmphasisError("ENCODER_MODEL_MISMATCH", "Unexpected SDXL CLIP channel layout.")
    return [[interleave(key, value), dict(metadata)]]


def anima_attention(q, k, v, pe=None, attn_mask=None, extra_options=None):
    signs = (extra_options or {}).get(SIGN)
    if signs is None or signs.shape[1] != v.shape[1] or signs.shape[0] != v.shape[0]:
        raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Anima NegPiP token/batch alignment changed.")
    return {"q": q, "k": k, "v": v * signs.to(v), "pe": pe}


def anima_forward(executor, x, timesteps, context, *args, **kwargs):
    signs = kwargs.pop(SIGN)
    options = dict(kwargs.get("transformer_options", {}))
    options[SIGN] = signs.to(context)
    return executor(x, timesteps, context, *args, **{**kwargs, "transformer_options": options})


def patch_anima(model):
    from comfy.conds import CONDRegular
    from comfy.patcher_extension import WrappersMP
    previous = model.get_model_object("extra_conds")
    def extra_conds(**kwargs):
        signs = kwargs.pop(SIGN, None)
        result = previous(**kwargs)
        context = result["c_crossattn"].cond
        # The non-preprocessed native path supplies T5 IDs to diffusion forward.
        length = max(512, result["t5xxl_ids"].cond.shape[-1]) if "t5xxl_ids" in result else context.shape[1]
        if signs is None:
            signs = context.new_ones((context.shape[0], length, 1))
        else:
            if signs.shape[1] > length:
                raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Anima sign sequence exceeds the adapted context.")
            signs = torch.nn.functional.pad(signs.to(context), (0, 0, 0, length - signs.shape[1]), value=1)
        result[SIGN] = CONDRegular(signs)
        return result
    model.add_object_patch("extra_conds", extra_conds)
    model.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, PATCH, anima_forward)
    model.set_model_attn2_patch(anima_attention)


def encode_native(model, clip, text, negative, config):
    family = model_family(model, clip)
    negpip = config["engine"] == AUTO_NEGPIP
    strength = active_strength(config)
    check_patches(model, clip, negpip)
    tokens = clip.tokenize(text)
    keys = ("l", "g") if family == "sdxl" else ("t5xxl",)
    transformed = weighted_tokens(tokens, keys, strength, negpip)
    if family == "anima":
        # Native Anima stores weights in float32, then casts them for the adapter.
        limit = min(torch.finfo(torch.float32).max, torch.finfo(model.model.get_dtype_inference()).max)
        if any(abs(w) > limit for section in transformed["t5xxl"] for _, w, *_ in section):
            raise EmphasisError("INVALID_WEIGHT", "Anima weights exceed the working dtype; reduce the weight or strength.")
    positive = clip.encode_from_tokens_scheduled(transformed)
    context, metadata = plain_conditioning(positive)
    # Once at encode time, never a host scalar read in each attention block.
    limit = torch.finfo(model.model.get_dtype_inference()).max
    if not torch.isfinite(context).all() or (context.abs() > limit).any():
        raise EmphasisError("INVALID_WEIGHT", "Weighted conditioning exceeds the working dtype; reduce the weight or strength.")
    if not negpip:
        return model, positive, negative
    plain_conditioning(negative)
    patched = model.clone()
    patched.model_options[PATCH] = family
    if family == "sdxl":
        positive = sdxl_conditioning(positive, tokens, clip, strength)
        tensor, info = negative[0]
        negative = [[interleave(tensor, tensor), dict(info)]]
        patched.set_model_attn2_patch(split_sdxl)
    else:
        weights = tokens["t5xxl"]
        if len(weights) != 1 or metadata["t5xxl_ids"].numel() != len(weights[0]):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Use native Anima T5 token metadata.")
        signs = context.new_tensor([1 - 2 * strength if w < 0 else 1 for _, w, *_ in weights[0]])[None, :, None]
        positive = [[context, {**metadata, SIGN: signs}]]
        patch_anima(patched)
    return patched, positive, negative
