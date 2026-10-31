"""CPU-only native MOSS integration and optional pinned Forge differential tests.

--comfy-root PATH [--reference-dir PATH]; no checkpoints or network access.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import types
import unittest
import traceback
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--comfy-root", required=True)
parser.add_argument("--reference-dir")
args = parser.parse_args()
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), args.comfy_root]
sys.argv = [sys.argv[0], "--cpu", "--use-pytorch-cross-attention"]
import comfy.options
comfy.options.enable_args_parsing()
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["HIP_VISIBLE_DEVICES"] = "-1"
import torch
import comfy.ops
from comfy.text_encoders.moss_image import MOSSImageTokenizer, MOSSImageTEModel
from comfy.sd1_clip import ClipTokenWeightEncoder
from comfy.model_patcher import ModelPatcher
from comfy.patcher_extension import WrappersMP, merge_nested_dicts
from comfy.ldm.moss_image.model import MOSSImage
from comfy.ldm.modules import attention as attn
from moss_emphasis.config import FORGE, RUNTIME_V3, EmphasisError, canonical
from moss_emphasis.runtime import RuntimeV3
from moss_emphasis.forge_negpip import parse_segments, tokenize, coefficient_values

torch.set_num_threads(1)
CPU = torch.device("cpu")
TOKENIZER = MOSSImageTokenizer()
ON = {"schema_version": 4, "engine": FORGE, "enabled": True}
CUDA_CALLS = []
REFERENCE_STATS = {"text_cases": 0, "token_coefficient_cases": 0, "mask_max_abs_error": 0.0}


def forbid_cuda(*args, **kwargs):
    CUDA_CALLS.append("".join(traceback.format_stack(limit=9)))
    raise AssertionError("CUDA initialization is forbidden in CPU tests")


class TinyEncoder(torch.nn.Module, ClipTokenWeightEncoder):
    def __init__(self, dtype):
        super().__init__(); self.dtype = dtype
        self.special_tokens = {"pad": 248044}
        self.calls = 0

    def encode(self, tokens):
        self.calls += 1
        ids = torch.tensor(tokens, dtype=torch.float64)
        channels = torch.arange(1, 9, dtype=torch.float64)
        result = torch.sin(ids[..., None] * .0001 + channels * .2).to(self.dtype)
        return result, result.mean(1), {"attention_mask": torch.ones(ids.shape, dtype=torch.int64)}


class Clip:
    def __init__(self, dtype=torch.float64):
        self.tokenizer = TOKENIZER
        self.cond_stage_model = MOSSImageTEModel.__new__(MOSSImageTEModel)
        torch.nn.Module.__init__(self.cond_stage_model)
        self.cond_stage_model.clip_name = self.cond_stage_model.clip = "qwen35_9b"
        self.cond_stage_model.qwen35_9b = TinyEncoder(dtype)
        self.patcher = ModelPatcher(self.cond_stage_model, CPU, CPU)
        self.calls = 0

    def tokenize(self, text):
        return self.tokenizer.tokenize_with_weights(text)

    def encode_from_tokens_scheduled(self, tokens):
        self.calls += 1
        result = self.cond_stage_model.encode_token_weights(tokens)
        return [[result[0], {"pooled_output": result[1], **result[2]}]]


def model():
    diffusion = MOSSImage(dim=32, ffn_dim=64, num_heads=2, num_layers=42, text_dim=8,
                          latent_channels=4, dtype=torch.float32, operations=comfy.ops.manual_cast)
    with torch.no_grad():
        for name, parameter in diffusion.named_parameters():
            if "norm" in name and parameter.ndim == 1: parameter.fill_(1)
            else: parameter.normal_(std=.02)
    base = torch.nn.Module(); base.diffusion_model = diffusion
    return ModelPatcher(base, CPU, CPU)


def run(m, p, positive, n, negative, scale=0):
    return RuntimeV3().execute(m, p, positive, n, negative,
                              canonical({**ON, "v_scaling_enabled": True, "v_scaling_strength": scale}))


def forge_reference(directory):
    root = Path(directory)
    sources = {
        "forge_moss_0570f23d.py": "f3f404aaf65ad076978eb6947f53dac8d224d2a603971aa765aa08384e14e975",
        "forge_parsing_2d79fc2f.py": "dbb0e18c48d1e7460a115afa758aa7dc1afa5f1cf118f3a9c7f861cccd7d4613",
    }
    for name, expected in sources.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise AssertionError("Pinned Forge reference changed: " + name)
    parsing = types.ModuleType("fixed_forge_parsing")
    exec(compile((root / "forge_parsing_2d79fc2f.py").read_text(encoding="utf-8"), "fixed_forge_parsing", "exec"), vars(parsing))
    tree = ast.parse((root / "forge_moss_0570f23d.py").read_text(encoding="utf-8"))
    names = {"_parse_attention", "_tokenize_line_negpip", "_weight_masks"}
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    reference = {"torch": torch, "parsing": parsing, "_Backend": object}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "fixed_forge_moss", "exec"), reference)
    reference["_parse_line"] = lambda backend, line, mode: reference["_parse_attention"](line, mode)
    return reference


REFERENCE = forge_reference(args.reference_dir) if args.reference_dir else None


class NativeForgeContracts(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42)
        self.cuda = patch.object(torch.cuda, "_lazy_init", forbid_cuda); self.cuda.start()

    def tearDown(self):
        self.cuda.stop()

    def test_real_native_unit_prompt_and_empty_are_bit_identical(self):
        clip, m = Clip(), model()
        for text in ("", " ", "plain text", "(word:1)", r"\(word\)", "は\u3099"):
            plain = clip.encode_from_tokens_scheduled(clip.tokenize(text))
            out, positive, _ = run(m, clip, text, clip, "")
            self.assertIs(out, m)
            torch.testing.assert_close(positive[0][0], plain[0][0], atol=0, rtol=0)
            torch.testing.assert_close(positive[0][1]["pooled_output"], plain[0][1]["pooled_output"], atol=0, rtol=0)

    def test_native_token_weight_encoder_interpolation_dtypes(self):
        for dtype in (torch.float64, torch.float32, torch.float16, torch.bfloat16):
            for scale in (0, .5, 1, 2):
                clip = Clip(dtype)
                tokens, image, sign = tokenize(clip, "a (red:2) (blue:-.5) (cat:0)", scale)
                before = clip.cond_stage_model.qwen35_9b.calls
                _, actual, negative = run(model(), clip, "a (red:2) (blue:-.5) (cat:0)", clip, "(blur:-2)", scale)
                # The native encoder batches the empty reference; no extra CLIP call.
                self.assertEqual(clip.cond_stage_model.qwen35_9b.calls - before, 2)
                pairs = tokens["qwen35_9b"][0]; ids, weights = zip(*pairs)
                raw, _, _ = clip.cond_stage_model.qwen35_9b.encode([list(ids), [248044] * len(ids)])
                expected = raw[:1].clone()
                for index, weight in enumerate(weights):
                    if weight != 1: expected[0, index] = (expected[0, index] - raw[1, index]) * weight + raw[1, index]
                torch.testing.assert_close(actual[0][0], expected, atol=0, rtol=0)
                self.assertEqual(actual[0][0].dtype, dtype)
                self.assertEqual(actual[0][1]["attention_mask"].shape[1], len(image))
                self.assertEqual(len(sign), len(image)); self.assertTrue(torch.isfinite(negative[0][0]).all())

    @unittest.skipUnless(REFERENCE, "Pass --reference-dir for fixed Forge comparison")
    def test_pinned_parser_token_ids_and_masks_against_real_qwen(self):
        clip = Clip()
        hf = TOKENIZER.qwen35_9b.tokenizer
        backend = types.SimpleNamespace(hf_tokenizer=hf, template="<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n<think>\n",
                                       own_template=lambda text: False, max_length=None,
                                       token_ids=lambda line: [t[0] for t in clip.tokenize(line)["qwen35_9b"][0]])
        cases = ["", "plain", "a(red:2)b", "red (hair:1.5)", "(word:1)", "(blue:2)berry", "(sun:2)flower",
                 " ( red :2) ", "(cat:-5) cat", "(赤い髪:1.5) 赤い髪", "は\u3099 (目:-1)", "[cat] ((dog))",
                 r"\(cat\) (dog:2)", "a BREAK b", "(word::2)", "(cat:0)", "(a:-2) (b:.5)", "(word:-0)"]
        for text in cases:
            REFERENCE_STATS["text_cases"] += 1
            with self.subTest(text=text):
                self.assertEqual(parse_segments(text), [tuple(part) for part in REFERENCE["_parse_attention"](text, "Original")])
                ids, multipliers = REFERENCE["_tokenize_line_negpip"](backend, text, "Original")
                for scale in (0, .25, .5, 1, 1.5, 2):
                    tokens, image, sign = tokenize(clip, text, scale)
                    actual_ids, actual_encoder = zip(*tokens["qwen35_9b"][0])
                    expected_encoder, masks = REFERENCE["_weight_masks"](multipliers, scale)
                    self.assertEqual(list(actual_ids), ids)
                    torch.testing.assert_close(torch.tensor(actual_encoder, dtype=torch.float64), torch.tensor(expected_encoder, dtype=torch.float64), atol=1e-12, rtol=1e-12)
                    torch.testing.assert_close(torch.tensor(sign), masks[:, -1], atol=0, rtol=0)
                    torch.testing.assert_close(torch.tensor(image), masks[:, 0], atol=1e-6, rtol=1e-6)
                    REFERENCE_STATS["token_coefficient_cases"] += 1
                    REFERENCE_STATS["mask_max_abs_error"] = max(REFERENCE_STATS["mask_max_abs_error"], (torch.tensor(image) - masks[:, 0]).abs().max().item())
        self.assertEqual(len(REFERENCE["_tokenize_line_negpip"](backend, "a(red:2)b", "Original")[0]), 13)
        self.assertEqual(len(backend.token_ids("aredb")), 12)

    def test_real_42_block_moss_forward_modelpatcher_and_cleanup(self):
        clip, m = Clip(torch.float32), model()
        originals = [layer.comfy_attention for layer in m.model.diffusion_model.layers]
        with torch.inference_mode():
            for scale in (0, 1):
                patched, positive, negative = run(m, clip, "(red:-2)", clip, "(blue:.5)", scale)
                self.assertEqual(len(patched.object_patches), 42); self.assertFalse(m.object_patches)
                options = merge_nested_dicts(patched.model_options["transformer_options"], {"wrappers": patched.wrappers})
                options["cond_or_uncond"] = [1, 0]
                context = torch.cat((negative[0][0], positive[0][0]))
                before = set(options)
                patched.patch_model(load_weights=False)
                try:
                    output = m.model.diffusion_model(torch.randn(2, 4, 1, 3), torch.ones(2), context, transformer_options=options)
                    self.assertEqual(output.shape, (2, 4, 1, 3)); self.assertTrue(torch.isfinite(output).all())
                    self.assertEqual(set(options), before)
                finally:
                    patched.unpatch_model(unpatch_weights=False)
                self.assertTrue(all(layer.comfy_attention is original for layer, original in zip(m.model.diffusion_model.layers, originals)))
            # Real unequal text lengths are processed by separate native forwards.
            patched, pos, neg = run(m, clip, "(red:-1)", clip, "long long (blue:-2) text", 1)
            for role, cond in ((0, pos), (1, neg)):
                options = merge_nested_dicts(patched.model_options["transformer_options"], {"wrappers": patched.wrappers})
                options["cond_or_uncond"] = [role]
                patched.patch_model(load_weights=False)
                try:
                    result = m.model.diffusion_model(torch.randn(1, 4, 1, 3), torch.ones(1), cond[0][0], transformer_options=options)
                    self.assertTrue(torch.isfinite(result).all())
                finally: patched.unpatch_model(unpatch_weights=False)

    def test_internal_v3_node_schema_and_execute(self):
        from aiohttp import web
        from comfy_api.latest import io
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("forge_native_test", root / "__init__.py", submodule_search_locations=[str(root)])
        extension = importlib.util.module_from_spec(spec)
        server = types.ModuleType("server")
        server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=web.RouteTableDef()))
        with patch.dict(sys.modules, {"server": server, "forge_native_test": extension}):
            spec.loader.exec_module(extension)
            cls = extension.NODE_CLASS_MAPPINGS[RUNTIME_V3]
            self.assertTrue(issubclass(cls, io.ComfyNode)); self.assertEqual(len(cls.define_schema().outputs), 3)
            result = cls.execute(model(), Clip(), "(red:-2)", Clip(), "(blue:0)", canonical(ON), "")
            self.assertEqual(len(result.result), 3)

    def test_native_attention_masks_container_ownership_and_output_reshape(self):
        clip = Clip(torch.float32)
        m, pos, neg = run(model(), clip, "(red:-2)", clip, "(blue:.5)", 1)
        state = m.wrappers[WrappersMP.DIFFUSION_MODEL]["moss_emphasis.v1"][0]
        local = m.get_model_object("diffusion_model.layers.0.comfy_attention")
        context = torch.cat((neg[0][0].repeat(2, 1, 1), pos[0][0].repeat(2, 1, 1)))
        length = 3 + context.shape[1]
        q, k, v = [torch.randn(4, length, 8) for _ in range(3)]
        original = [value.clone() for value in (q, k, v)]
        for boolean in (False, True):
            mask = torch.randn(4, 1, length, length) * .1
            if boolean: mask = mask > -.08
            mask[..., 0] = True if boolean else 0
            for reshaped in (False, True):
                def forward(x, t, c, options):
                    values = [attn.AttentionTensorContainer(item) for item in (q, k, v)]
                    out = local.run(*values, 2, mask=mask, transformer_options=options, skip_output_reshape=reshaped)
                    self.assertTrue(all(value.tensor is None for value in values))
                    return out
                actual = state(forward, torch.zeros(4, 4, 1, 3), None, context, {"cond_or_uncond": [1, 0]})
                score = q.reshape(4, length, 2, 4).transpose(1, 2) @ k.reshape(4, length, 2, 4).permute(0, 2, 3, 1) / 2
                score = score.masked_fill(~mask, -math.inf) if boolean else score + mask
                probability = score.softmax(-1)
                expected = []
                for row in range(4):
                    _, image, sign = state.branches[1 if row < 2 else 0]
                    outputs = []
                    for query in range(length):
                        values = v[row].clone()
                        values[3:] *= torch.tensor(image if query < 3 else sign)[:, None]
                        outputs.append((probability[row, :, query, None, :] @ values.reshape(length, 2, 4).transpose(0, 1)).squeeze(1))
                    expected.append(torch.stack(outputs, dim=1))
                expected = torch.stack(expected)
                if not reshaped: expected = expected.transpose(1, 2).flatten(2)
                torch.testing.assert_close(actual, expected, atol=1e-6, rtol=1e-6)
                for value, before in zip((q, k, v), original): self.assertTrue(torch.equal(value, before))

    def test_native_unsupported_model_and_return_to_moss(self):
        from comfy import model_base
        clip = Clip()
        for cls in (model_base.SDXL, model_base.Anima, model_base.Krea2, model_base.QwenImage, model_base.Flux):
            base = cls.__new__(cls); torch.nn.Module.__init__(base)
            base.diffusion_model = torch.nn.Linear(1, 1)
            m = ModelPatcher(base, CPU, CPU)
            raw = '{"summary":{"caption":"(cat:2)"}}'
            native = clip.encode_from_tokens_scheduled(clip.tokenize(raw))
            out, positive, _ = run(m, clip, raw, clip, "(word:.0.5)")
            self.assertIs(out, m); torch.testing.assert_close(positive[0][0], native[0][0], atol=0, rtol=0)
        m = model(); active, _, _ = run(m, clip, "(cat:-2)", clip, "")
        self.assertIsNot(active, m)
        with self.assertRaisesRegex(EmphasisError, "Layout JSON"):
            run(m, clip, raw, clip, "")

    def test_real_modelpatcher_wrapper_store_rejects_double_application(self):
        clip = Clip()
        m, _, _ = run(model(), clip, "(cat:-2)", clip, "")
        before = clip.calls
        # Native ModelPatcher stores wrappers separately from model_options.
        with self.assertRaisesRegex(EmphasisError, "DUPLICATE_WEIGHT_ENGINE"):
            run(m, clip, "(red:2)", clip, "")
        self.assertEqual(clip.calls, before)
        foreign = model()
        foreign.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, "foreign", lambda *a, **kw: None)
        with self.assertRaisesRegex(EmphasisError, "UNSUPPORTED_MODEL_ADAPTER"):
            run(foreign, clip, "(cat:-1)", clip, "")


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], verbosity=2, exit=False).result
    for stack in CUDA_CALLS: print(stack)
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                      "cuda_initialization_calls": len(CUDA_CALLS), "fixed_forge_reference": bool(REFERENCE),
                      "reference": REFERENCE_STATS, "device": "cpu"}))
    sys.exit(0 if result.wasSuccessful() and not CUDA_CALLS else 1)
