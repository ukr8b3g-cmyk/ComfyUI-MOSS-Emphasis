"""Internal execution node. No dependency on KJNodes or the independent node."""
import json
import logging
from .config import EmphasisError, settings
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
        ordinary = lambda: (model, clip.encode_from_tokens_scheduled(clip.tokenize(text)))
        if not config["enabled"] or config["strength"] == 0 or not is_native_moss(model):
            return ordinary()
        tokenizer_type = type(clip.tokenizer)
        if (tokenizer_type.__module__, tokenizer_type.__name__) != ("comfy.text_encoders.moss_image", "MOSSImageTokenizer"):
            raise EmphasisError("ENCODER_MODEL_MISMATCH", "Use the native MOSS-Image Qwen3.5 CLIP loader.", source)
        parsed = parse(text)
        if not parsed.groups:
            return ordinary()
        tokens, weights = tokenize(clip, parsed)
        cond = clip.encode_from_tokens_scheduled(tokens)
        if len(cond) != 1 or cond[0][0].ndim != 3 or cond[0][0].shape[0] != 1 or cond[0][0].shape[1] != len(weights):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Expected a single unmodified full-length text conditioning.", source)
        forbidden = {"start_percent", "end_percent", "hooks", "reference_latents", "concat_latent_image", "area", "mask"}
        if forbidden.intersection(cond[0][1]):
            raise EmphasisError("UNSUPPORTED_CONDITIONING_PATH", "Scheduled/region/edit conditioning is unsupported.", source)
        if all(w == 1 for w in weights):
            return model, cond
        weighted_model = patch(model, cond, weights, config["strength"])
        logging.info("[MOSS Emphasis] applied engine=%s strength=%s groups=%s weighted_tokens=%s source=%s",
                     config["engine"], config["strength"], parsed.groups, sum(w != 1 for w in weights), source)
        return weighted_model, cond
