"""Standalone CPU contracts against an installed ComfyUI (no model downloads).

python -B tests/native_contract.py --comfy-root PATH [--reference-dir PATH]
Real tokenizers, token encoders, ModelPatcher, conditioning batching and attention
modules run with small deterministic tensors in place of checkpoint weights.
Keep this process separate from the legacy suite's sys.modules doubles.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--comfy-root", required=True)
parser.add_argument("--reference-dir")
args = parser.parse_args()
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), args.comfy_root]
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import torch
import comfy.model_base as mb
import comfy.sdxl_clip as sx
from comfy.sd1_clip import ClipTokenWeightEncoder
from comfy.text_encoders.anima import AnimaTokenizer, AnimaTEModel
from comfy.model_patcher import ModelPatcher
from comfy.conds import CONDCrossAttn
from comfy.ldm.modules.attention import BasicTransformerBlock
from comfy.ldm.cosmos.predict2 import Attention
from comfy.ldm.anima.model import Anima as AnimaDiffusion
from comfy.patcher_extension import merge_nested_dicts
from moss_emphasis.config import AUTO_ENGINE, AUTO_NEGPIP, EmphasisError
from moss_emphasis.runtime import RuntimeV2
from moss_emphasis.adapters import SIGN, PATCH, model_family


def reference(name):
    path = Path(args.reference_dir) / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ppm_sdxl = reference("ppm_unet_926e8bb5.py") if args.reference_dir else None
ppm_anima = reference("ppm_anima_926e8bb5.py") if args.reference_dir else None
SDXL_TOKENIZER = sx.SDXLTokenizer()
ANIMA_TOKENIZER = AnimaTokenizer()
CPU = torch.device("cpu")
ON = {"schema_version": 3, "engine": AUTO_NEGPIP, "enabled": True}


class TinyEncoder(torch.nn.Module, ClipTokenWeightEncoder):
    def __init__(self, width, dtype=torch.float64, mask=False):
        super().__init__()
        self.width, self.dtype, self.mask = width, dtype, mask
        self.special_tokens = {"start": 49406, "end": 49407, "pad": 0}
        self.transformer = torch.nn.Module()
        self.transformer.text_model = torch.nn.Module()
        self.transformer.text_model.final_layer_norm = torch.nn.LayerNorm(width, dtype=dtype)

    def encode(self, tokens):
        ids = torch.tensor(tokens, dtype=torch.float64)
        channels = torch.arange(1, self.width + 1, dtype=torch.float64)
        out = torch.sin(ids[..., None] * .0001 + channels * .2).to(self.dtype)
        result = (out, out.mean(1))
        if self.mask:
            result += ({"attention_mask": torch.ones(ids.shape, dtype=torch.int64)},)
        return result


class Clip:
    def __init__(self, family="sdxl", dtype=torch.float64):
        self.tokenizer = SDXL_TOKENIZER if family == "sdxl" else ANIMA_TOKENIZER
        cls = sx.SDXLClipModel if family == "sdxl" else AnimaTEModel
        self.cond_stage_model = cls.__new__(cls)
        torch.nn.Module.__init__(self.cond_stage_model)
        if family == "sdxl":
            self.cond_stage_model.clip_l = TinyEncoder(4, dtype)
            self.cond_stage_model.clip_g = TinyEncoder(8, dtype)
        else:
            self.cond_stage_model.clip_name = self.cond_stage_model.clip = "qwen3_06b"
            self.cond_stage_model.qwen3_06b = TinyEncoder(8, dtype, mask=True)
        self.patcher = ModelPatcher(self.cond_stage_model, CPU, CPU)

    def tokenize(self, text):
        return self.tokenizer.tokenize_with_weights(text)

    def encode_from_tokens_scheduled(self, tokens):
        result = self.cond_stage_model.encode_token_weights(tokens)
        return [[result[0], {"pooled_output": result[1], **(result[2] if len(result) > 2 else {})}]]


class TinyAdapter(torch.nn.Module):
    def forward(self, context, ids):
        return context.mean(1, keepdim=True).expand(-1, ids.shape[1], -1) + ids[..., None].to(context) * .0001


def model(family="sdxl", dtype=torch.float64):
    cls = mb.SDXL if family == "sdxl" else mb.Anima
    base = cls.__new__(cls)
    torch.nn.Module.__init__(base)
    base.concat_keys = ()
    base.manual_cast_dtype = None
    if family == "sdxl":
        base.diffusion_model = torch.nn.Linear(1, 1, dtype=dtype)
        base.diffusion_model.dtype = dtype
    else:
        diffusion = AnimaDiffusion.__new__(AnimaDiffusion)
        torch.nn.Module.__init__(diffusion)
        diffusion.llm_adapter = TinyAdapter()
        diffusion.dtype = dtype
        base.diffusion_model = diffusion
    return ModelPatcher(base, CPU, CPU)


def run(m, clip, text, config=None, negative=None):
    if negative is None:
        negative = clip.encode_from_tokens_scheduled(clip.tokenize("bad (blur:-0.5)"))
    return RuntimeV2().execute(m, clip, text, json.dumps(config or ON), negative)


def extra(patcher, cond):
    return patcher.get_model_object("extra_conds")(
        cross_attn=cond[0][0], device=CPU, **cond[0][1])


class NativeContracts(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42)

    def test_native_model_detection_and_wrong_clip(self):
        for family in ("sdxl", "anima"):
            self.assertEqual(model_family(model(family), Clip(family)), family)
            with self.assertRaisesRegex(EmphasisError, "ENCODER_MODEL_MISMATCH"):
                model_family(model(family), Clip("anima" if family == "sdxl" else "sdxl"))
        # SDXL-family checkpoint names do not participate in detection.
        for unsupported in (mb.SDXLRefiner, mb.Krea2, mb.BaseModel):
            native = unsupported.__new__(unsupported); torch.nn.Module.__init__(native)
            with self.assertRaisesRegex(EmphasisError, "UNSUPPORTED_MODEL_ADAPTER"):
                model_family(ModelPatcher(native, CPU, CPU), Clip())

    def test_v3_registration_and_prepared_execution_contract(self):
        from aiohttp import web
        from comfy_api.latest import io
        from moss_emphasis.graph import prepare
        from moss_emphasis.config import RUNTIME, RUNTIME_V2
        from test_core import graph
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("moss_native_test", root / "__init__.py", submodule_search_locations=[str(root)])
        extension = importlib.util.module_from_spec(spec)
        server = types.ModuleType("server")
        server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=web.RouteTableDef()))
        with patch.dict(sys.modules, {"server":server, "moss_native_test":extension}):
            spec.loader.exec_module(extension)
            cls = extension.NODE_CLASS_MAPPINGS[RUNTIME_V2]
            self.assertTrue(issubclass(cls, io.ComfyNode))
            self.assertEqual(len(cls.define_schema().outputs), 3)
            self.assertEqual(extension.NODE_CLASS_MAPPINGS[RUNTIME].RETURN_TYPES, ("MODEL", "CONDITIONING"))
            prepared = prepare(graph(), ON)
            inputs = prepared["prompt"][prepared["targets"][0]["runtime"]]["inputs"]
            c = Clip(); negative = c.encode_from_tokens_scheduled(c.tokenize("bad"))
            result = cls.execute(model(), c, inputs["text"], inputs["settings_json"], negative, inputs["source"])
            self.assertEqual(len(result.result), 3)

    def test_effect_half_zero_and_dtype_overflow(self):
        for family in ("sdxl", "anima"):
            c, m = Clip(family), model(family)
            text = "(red:-5) blue"
            _, cond, _ = run(m, c, text, {**ON, "negpip_strength": .5})
            if family == "sdxl":
                # Negative token Value is zero in each encoder's own token positions.
                tokens = c.tokenize(text)
                for key, start, width in (("l",0,4),("g",4,8)):
                    for i, (_, w, *_) in enumerate(tokens[key][0]):
                        if w < 0: self.assertTrue(torch.all(cond[0][0][:, 2*i+1, start:start+width] == 0))
            else:
                self.assertTrue(torch.any(cond[0][1][SIGN] == 0))
            native = c.encode_from_tokens_scheduled(c.tokenize(text))
            out, bypass, _ = run(m, c, text, {**ON, "negpip_strength": 0})
            self.assertIs(out, m)
            torch.testing.assert_close(bypass[0][0], native[0][0], rtol=0, atol=0)
            # The error concerns representability, not an arbitrary prompt-weight cap.
            with self.assertRaisesRegex(EmphasisError, "INVALID_WEIGHT"):
                run(model(family, torch.float16), Clip(family), "(red:-100000000)")

    def test_anima_long_context_and_native_deferred_preprocessing(self):
        c = Clip("anima")
        text = "cat " * 520 + "(red:-5)"
        for inference in (False, True):
            with torch.inference_mode(inference):
                m = model("anima"); patched, pos, _ = run(m, c, text)
                data = extra(patched, pos)
                count = pos[0][1]["t5xxl_ids"].numel()
                self.assertGreater(count, 512)
                self.assertEqual(data[SIGN].cond.shape[1], count)
                options = merge_nested_dicts(patched.model_options["transformer_options"], {"wrappers": patched.wrappers})
                def capture(self, x, t, context, fps, padding_mask, transformer_options):
                    return context, transformer_options[SIGN]
                m.model.diffusion_model._forward = types.MethodType(capture, m.model.diffusion_model)
                values = {k:v.process_cond(2).cond for k,v in data.items()}
                context = values.pop("c_crossattn")
                adapted, signs = m.model.diffusion_model(torch.zeros(2,1), None, context, transformer_options=options, **values)
                self.assertEqual(adapted.shape[:2], signs.shape[:2])
                self.assertEqual(adapted.shape[1], count)
                expected = m.model.diffusion_model.preprocess_text_embeds(pos[0][0], pos[0][1]["t5xxl_ids"][None], pos[0][1]["t5xxl_weights"][None,:,None])
                torch.testing.assert_close(adapted, expected.repeat(2,1,1))

    def test_sdxl_standard_is_native_and_pooling_unchanged(self):
        c, m = Clip(), model()
        for text in ("", "red", "(red:-5) red (blue:0)", "((cat:2):0.5)", r"\(red\) [blue]", "cat " * 90):
            native = c.encode_from_tokens_scheduled(c.tokenize(text))
            output, cond, _ = run(m, c, text, {**ON, "engine": AUTO_ENGINE})
            self.assertIs(output, m)
            torch.testing.assert_close(cond[0][0], native[0][0], rtol=0, atol=0)
            torch.testing.assert_close(cond[0][1]["pooled_output"], native[0][1]["pooled_output"], rtol=0, atol=0)

    @unittest.skipUnless(ppm_sdxl, "Supply pinned PPM reference directory")
    def test_sdxl_negpip_matches_pinned_ppm_kv_and_pool(self):
        c = Clip()
        for text in ("", "red", "(red:-5) red (blue:0)", "(a:-1) (b:.5) (c:10)", "((cat:2):-0.5)", "cat " * 90 + "(red:-5)"):
            tokens = c.tokenize(text)
            _, cond, _ = run(model(), c, text)
            parts = [ppm_sdxl.encode_token_weights_negpip(getattr(c.cond_stage_model, "clip_" + key), tokens[key]) for key in ("l", "g")]
            length = min(part[0].shape[1] for part in parts)
            expected = torch.cat([part[0][:, :length] for part in parts], -1)
            torch.testing.assert_close(cond[0][0], expected, atol=1e-12, rtol=1e-12)
            torch.testing.assert_close(cond[0][1]["pooled_output"], parts[1][1], atol=0, rtol=0)

    def test_sdxl_real_attention_cfg_batch_and_chunk_repeat(self):
        c = Clip()
        neg = c.encode_from_tokens_scheduled(c.tokenize("(bad:-.5)"))
        base = model(); patched, pos, converted = run(base, c, "cat " * 90 + "(red:-5)", negative=neg)
        self.assertFalse(base.model_options["transformer_options"].get("patches"))
        block = BasicTransformerBlock(8, 2, 4, context_dim=12, dtype=torch.float64, operations=torch.nn)
        expected_options = {"patches": {"attn2_patch": [lambda q,k,v,o: (q,k[:,:k.shape[1]//2],k[:,k.shape[1]//2:])]}}
        for order in ((0,), (1,), (0, 1), (1, 0)):
            selected = [pos if i == 0 else converted for i in order]
            conds = [CONDCrossAttn(p[0][0]).process_cond(2) for p in selected]
            carrier = conds[0].concat(conds[1:])
            x = torch.randn(len(order)*2, 3, 8, dtype=torch.float64)
            actual = block(x, carrier, transformer_options=patched.model_options["transformer_options"])
            manual = torch.cat((carrier[:, ::2], carrier[:, 1::2]), 1)
            torch.testing.assert_close(actual, block(x, manual, transformer_options=expected_options), atol=1e-12, rtol=1e-12)
            for row, kind in enumerate(order):
                if kind == 1:
                    native = block(x[row*2:row*2+2], neg[0][0].repeat(2, 1, 1))
                    torch.testing.assert_close(actual[row*2:row*2+2], native, atol=1e-12, rtol=1e-12)

    def test_anima_native_normal_and_metadata_preservation(self):
        c, m = Clip("anima"), model("anima")
        for strength in (.5, 1, 2):
            text = "red (blue:-5) (cat:0)"
            native = c.encode_from_tokens_scheduled(c.tokenize(text))
            _, positive, negative = run(m, c, text, {**ON, "engine": AUTO_ENGINE, "strength": strength})
            torch.testing.assert_close(positive[0][0], native[0][0], rtol=0, atol=0)
            torch.testing.assert_close(positive[0][1]["t5xxl_weights"], 1 + strength*(native[0][1]["t5xxl_weights"]-1))
            for key in ("t5xxl_ids", "attention_mask", "pooled_output"):
                torch.testing.assert_close(positive[0][1][key], native[0][1][key], rtol=0, atol=0)

    @unittest.skipUnless(ppm_anima, "Supply pinned PPM reference directory")
    def test_anima_ppm_reference_preprocess_and_forward_routes(self):
        c = Clip("anima")
        for inference in (False, True):
            for text in ("", "red", "(red:-5) (blue:0) (cat:10)", "((cat:2):-0.5)"):
                with torch.inference_mode(inference):
                    m = model("anima")
                    original = c.encode_from_tokens_scheduled(c.tokenize(text))
                    patched, pos, negative = run(m, c, text)
                    out = extra(patched, pos)
                    expected = ppm_anima.anima_extra_conds_negpip_wrapper(m.get_model_object("extra_conds"))(
                        cross_attn=original[0][0], device=CPU, **original[0][1])
                    torch.testing.assert_close(out["c_crossattn"].cond, expected["c_crossattn"].cond, atol=0, rtol=0)
                    torch.testing.assert_close(out[SIGN].cond, expected[ppm_anima.COND_NEGPIP_MASK_KEY].cond.to(out[SIGN].cond), atol=0, rtol=0)
                    # Native Negative is an independent oracle, including its negative weights.
                    uncond = extra(patched, negative); plain = extra(m, negative)
                    torch.testing.assert_close(uncond["c_crossattn"].cond, plain["c_crossattn"].cond, atol=0, rtol=0)
                    self.assertTrue(torch.all(uncond[SIGN].cond == 1))

    def test_anima_real_attention_batch_dtype_and_no_option_leak(self):
        for dtype in (torch.float64, torch.float32, torch.float16, torch.bfloat16):
            with torch.inference_mode():
                c, m = Clip("anima", dtype), model("anima", dtype)
                patched, pos, neg = run(m, c, "red (blue:-5)")
                att = Attention(8, 8, n_heads=2, head_dim=4, dtype=dtype, operations=torch.nn)
                cp, cn = extra(patched, pos), extra(patched, neg)
                for order in ((cp,), (cn,), (cp, cn), (cn, cp)):
                    conds = [{k:v.process_cond(2) for k,v in data.items()} for data in order]
                    merged = {k:conds[0][k].concat([d[k] for d in conds[1:]]) for k in conds[0]}
                    context = merged["c_crossattn"]
                    options = merge_nested_dicts(patched.model_options["transformer_options"], {"wrappers": patched.wrappers})
                    before_keys = set(options)
                    q = torch.randn(context.shape[0], 3, 8, dtype=dtype)
                    def forward(self, x, t, ctx, fps, padding_mask, transformer_options):
                        self_test.assertEqual(fps, 24)
                        self_test.assertIs(padding_mask, marker)
                        return att(x, ctx, transformer_options=transformer_options)
                    self_test, marker = self, object()
                    diffusion = m.model.diffusion_model
                    diffusion._forward = types.MethodType(forward, diffusion)
                    actual = diffusion(q, None, context, fps=24, padding_mask=marker,
                                       transformer_options=options, **{SIGN:merged[SIGN]})
                    expected_options = {"patches": {"attn2_patch": [lambda q,k,v,**kw: {"v":v*merged[SIGN].to(v)}]}}
                    expected = att(q, context, transformer_options=expected_options)
                    torch.testing.assert_close(actual, expected, atol=0, rtol=0)
                    self.assertEqual(actual.dtype, dtype)
                    self.assertEqual(set(options), before_keys)
                    self.assertNotIn(SIGN, options)

    def test_conflicts_fail_without_changing_original(self):
        for family in ("sdxl", "anima"):
            for conflict in ("attn2", "replace", "clip", "ppm"):
                c, m = Clip(family), model(family)
                if conflict == "attn2": m.set_model_attn2_patch(lambda *a: a)
                elif conflict == "replace": m.model_options["transformer_options"]["patches_replace"]={"attn2":{0:lambda *a:a}}
                elif conflict == "clip": c.patcher.add_object_patch("encode_token_weights", lambda *a:a)
                else: m.model_options["ppm_negpip"] = True
                before = copy.deepcopy(m.model_options)
                with self.assertRaisesRegex(EmphasisError, "DUPLICATE_WEIGHT_ENGINE"):
                    run(m, c, "(red:-1)")
                self.assertEqual(m.model_options, before)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
