"""Internal execution node. No dependency on KJNodes or the independent node."""
import json
import logging
from .config import EmphasisError, settings, active_strength, ENGINE, NEGPIP, AUTO_NEGPIP
from .parser import parse
from .tokens import tokenize

class Runtime:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "clip": ("CLIP",),
                "text": ("STRING", {"multiline": True}), "settings_json": ("STRING",), "source": ("STRING",)}}

    RETURN_TYPES = ("MODEL", "CONDITIONING")
    FUNCTION = "execute"
    CATEGORY = "MOSS Emphasis/internal"
    DESCRIPTION = "Internal runtime inserted by MOSS Emphasis. Do not add manually."

    def execute(self, model, clip, text, settings_json, source=""):
        from .engine import is_native_moss, patch
        config = settings(json.loads(settings_json))
        if config["schema_version"] == 3:
            raise EmphasisError("INVALID_SETTINGS", "Model-auto settings require runtime V2.", source)
        ordinary = lambda: (model, clip.encode_from_tokens_scheduled(clip.tokenize(text)))
        if not config["enabled"] or active_strength(config) == 0:
            return ordinary()
        if not is_native_moss(model):
            if config["engine"] == NEGPIP:
                raise EmphasisError("UNSUPPORTED_MODEL_ADAPTER", "NegPiP requires native MOSS-Image.", source)
            return ordinary()
        for owner in (model, getattr(clip, "patcher", None)):
            options = getattr(owner, "model_options", {})
            if any(key in options for key in ("ppm_negpip", "ppm_negpip_moss")):
                raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "Disable the upstream PPM MODEL/CLIP patch.", source)
        patches = getattr(getattr(clip, "patcher", None), "object_patches", {})
        if any("encode_token_weights" in key for key in patches):
            raise EmphasisError("DUPLICATE_WEIGHT_ENGINE", "An upstream CLIP weighting patch is active.", source)
        tokenizer_type = type(clip.tokenizer)
        if (tokenizer_type.__module__, tokenizer_type.__name__) != ("comfy.text_encoders.moss_image", "MOSSImageTokenizer"):
            raise EmphasisError("ENCODER_MODEL_MISMATCH", "Use the native MOSS-Image Qwen3.5 CLIP loader.", source)
        parsed = parse(text)
        if not parsed.groups:
            return ordinary()
        tokens, weights = tokenize(clip, parsed)
        if config["engine"] == NEGPIP:
            tokens = {key: [[(token, 1.0, *rest) for token, weight, *rest in section] for section in sections]
                      for key, sections in tokens.items()}
        cond = clip.encode_from_tokens_scheduled(tokens)
        if len(cond) != 1 or cond[0][0].ndim != 3 or cond[0][0].shape[0] != 1 or cond[0][0].shape[1] != len(weights):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Expected a single unmodified full-length text conditioning.", source)
        forbidden = {"start_percent", "end_percent", "hooks", "reference_latents", "concat_latent_image", "area", "mask"}
        if forbidden.intersection(cond[0][1]):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Scheduled/region/edit conditioning is unsupported.", source)
        if all(w == 1 for w in weights):
            return model, cond
        weighted_model = patch(model, cond, weights, active_strength(config), engine=config["engine"])
        logging.info("[MOSS Emphasis] applied engine=%s strength=%s groups=%s weighted_tokens=%s source=%s",
                     config["engine"], active_strength(config), parsed.groups, sum(w != 1 for w in weights), source)
        return weighted_model, cond


class RuntimeV2(Runtime):
    """Keep the V1 contract intact; V2 also owns sampler-local Negative conversion."""
    def execute(self, model, clip, text, settings_json, negative, source=""):
        from .engine import is_native_moss
        from .adapters import encode_native
        config = settings(json.loads(settings_json))
        if config["schema_version"] != 3:
            raise EmphasisError("INVALID_SETTINGS", "Runtime V2 requires model-auto settings.", source)
        if not config["enabled"] or active_strength(config) == 0:
            return model, clip.encode_from_tokens_scheduled(clip.tokenize(text)), negative
        if is_native_moss(model):
            legacy = {**config, "schema_version": 2,
                      "engine": NEGPIP if config["engine"] == AUTO_NEGPIP else ENGINE}
            weighted_model, cond = super().execute(model, clip, text, json.dumps(legacy), source)
            return weighted_model, cond, negative
        return encode_native(model, clip, text, negative, config)
