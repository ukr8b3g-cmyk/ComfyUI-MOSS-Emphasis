"""CPU contracts for the new mode; legacy engine tests remain separate."""
import copy
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import torch
from moss_emphasis.config import VERSION, FORGE, RUNTIME_V3, EmphasisError, canonical, settings, should_apply
from moss_emphasis.forge_negpip import parse_segments, coefficient_values, tokenize, ForwardState, run_attention
from moss_emphasis.runtime import RuntimeV3
from moss_emphasis.graph import prepare
from moss_emphasis.api import corresponding_source
from test_core import graph
from test_engine import Clip, FakeHF, Container, Patcher, modules

ON = {"schema_version": 4, "engine": FORGE, "enabled": True}


class HF(FakeHF):
    def encode(self, text, add_special_tokens=False):
        return super().encode(text)


class ForgeClip(Clip):
    def __init__(self):
        super().__init__()
        self.hf = HF(); self.tokenizer.qwen35_9b.tokenizer = self.hf
        self.cond_stage_model = type("MOSSImageTEModel", (), {"__module__": "comfy.text_encoders.moss_image"})()
        self.calls, self.received = 0, []

    def encode_from_tokens_scheduled(self, tokens):
        self.calls += 1; self.received.append(copy.deepcopy(tokens))
        ids, scales = zip(*tokens["qwen35_9b"][0])
        value = torch.tensor(ids, dtype=torch.float64)[None, :, None].repeat(1, 1, 4)
        scale = torch.tensor(scales, dtype=value.dtype)[None, :, None]
        return [[(value - .25) * scale + .25, {"pooled_output": torch.ones(1, 4)}]]


class ForgeTests(unittest.TestCase):
    def test_saved_local_forge_settings_upgrade_without_changing_effective_scale(self):
        original = {**ON, "version": "0.10.1", "v_scaling_enabled": True, "v_scaling_strength": .5}
        upgraded = settings(original)
        self.assertEqual(upgraded["version"], VERSION)
        for key in ("engine", "schema_version", "enabled", "v_scaling_enabled", "v_scaling_strength"):
            self.assertEqual(upgraded[key], original[key])

    def setUp(self):
        self.comfy = patch.dict("sys.modules", modules()); self.comfy.start()
        torch.manual_seed(42)

    def tearDown(self):
        self.comfy.stop()

    def test_settings_and_zero_bypass_contract(self):
        for scale in (0, .5, 1, 2):
            for enabled in (False, True):
                config = settings({**ON, "strength": 0, "negpip_strength": 0,
                                   "v_scaling_enabled": enabled, "v_scaling_strength": scale})
                self.assertTrue(should_apply(config))
                self.assertEqual(config["v_scaling_strength"], scale if enabled else 0)
        self.assertEqual(canonical(ON), canonical({**ON, "strength": 0, "negpip_strength": 0, "v_scaling_strength": 2}))
        self.assertEqual(canonical(ON), canonical({**ON, "v_scaling_enabled": True, "v_scaling_strength": 0}))
        self.assertFalse(should_apply(settings({**ON, "enabled": False})))
        for field, values in (("v_scaling_enabled", (1, "true", None)),
                              ("v_scaling_strength", (-1, 2.01, True, None, math.nan, math.inf))):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(EmphasisError):
                    settings({**ON, field: value})

    def test_fp64_coefficients_independent_formula(self):
        for scale in (0, .25, .5, 1, 1.5, 2):
            for weight in (-5, -2, -1, -.5, 0, .5, 1, 1.5, 2, 5):
                encoder, image, sign = coefficient_values([weight], scale)
                q = -1 if weight < 0 else 1
                self.assertAlmostEqual(encoder[0], (1 - min(scale, 1)) * abs(weight) + min(scale, 1), places=12)
                self.assertAlmostEqual(image[0], q * math.exp(scale * math.log(max(abs(weight), .0001))) if scale else q, places=12)
                self.assertEqual(sign[0], q)
        for weight in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(EmphasisError, "INVALID_WEIGHT"):
                coefficient_values([weight], 1)
        with self.assertRaisesRegex(EmphasisError, "overflow"):
            coefficient_values([1e300], 2)

    def test_original_parser_boundaries_and_limits(self):
        cases = {"(word)": [("word", 1.1)], "((word))": [("word", 1.21)],
                 "[word]": [("word", 1 / 1.1)], "(word:-5)": [("word", -5)],
                 "(word:1)": [("word", 1)], r"\(word\)": [("(word)", 1)],
                 "x BREAK y": [("x", 1), (" BREAK ", 1), ("y", 1)]}
        for text, expected in cases.items():
            actual = parse_segments(text)
            self.assertEqual([s for s, _ in actual], [s for s, _ in expected])
            for (_, a), (_, b) in zip(actual, expected): self.assertAlmostEqual(a, b)
        for text in ("(word:.0.5)", "(word:" + "9" * 400 + ")", "(" * 17 + "word"):
            with self.assertRaises(EmphasisError): parse_segments(text)
        with self.assertRaisesRegex(EmphasisError, "Layout JSON"):
            parse_segments('{"summary":{"caption":"(word:2)"}}')

    def test_unit_weight_keeps_original_and_template_once(self):
        clip = ForgeClip()
        for text in ("plain", "(word:1)", "", "は\u3099", r"\(word\)"):
            tokens, image, sign = tokenize(clip, text, 0)
            self.assertEqual(tokens, clip.tokenize(text))
            self.assertTrue(all(value == 1 for value in image + sign))
        tokens, _, _ = tokenize(clip, " ( red :2) ", 0)
        pieces = clip.hf.convert_ids_to_tokens([i for i, _ in tokens["qwen35_9b"][0]])
        self.assertEqual(pieces.count("<|im_start|>"), 2)
        with self.assertRaisesRegex(EmphasisError, "special tokens"):
            tokenize(clip, "<|im_start|>user", 1)
        with self.assertRaisesRegex(EmphasisError, "4096"):
            tokenize(clip, "a" * 4100, 1)

    def test_runtime_weights_both_branches_once_even_with_old_zero_strengths(self):
        clip, other = ForgeClip(), ForgeClip()
        result = RuntimeV3().execute(Patcher(), clip, "(red:2)", other, "(blue:-5)", canonical({**ON, "strength": 0, "negpip_strength": 0}))
        self.assertEqual((clip.calls, other.calls), (1, 1))
        self.assertEqual(len(result[0].objects), 42)
        self.assertTrue(any(w == 2 for _, w in clip.received[0]["qwen35_9b"][0]))
        self.assertTrue(any(w == 5 for _, w in other.received[0]["qwen35_9b"][0]))
        self.assertTrue(any(value < 0 for value in result[0].wrapper.branches[1][2]))

    def test_no_unsafe_encode_sharing(self):
        for same_clip, same_text in ((True, False), (False, True), (True, True)):
            clip = ForgeClip(); negative = clip if same_clip else ForgeClip()
            RuntimeV3().execute(Patcher(), clip, "(red:2)", negative, "(red:2)" if same_text else "(blue:-1)", canonical(ON))
            self.assertEqual(clip.calls + (negative.calls if negative is not clip else 0), 2)

    def test_nonmoss_and_off_return_original_text_without_parsing(self):
        for enabled in (False, True):
            for name in ("SDXL", "Anima", "Krea2", "QwenImage", "Flux", "OtherMOSS"):
                model = Patcher(); model.diffusion = type(name, (), {})()
                clip, neg = ForgeClip(), ForgeClip()
                out = RuntimeV3().execute(model, clip, '{"a":1}', neg, "(bad:.0.5)", canonical({**ON, "enabled": enabled}))
                self.assertIs(out[0], model)
                self.assertEqual(clip.last_text, '{"a":1}'); self.assertEqual(neg.last_text, "(bad:.0.5)")
                self.assertEqual((clip.calls, neg.calls), (1, 1))

    def test_wrong_clip_and_existing_patch_rejected(self):
        clip = ForgeClip(); clip.tokenizer = object()
        with self.assertRaisesRegex(EmphasisError, "ENCODER_MODEL_MISMATCH"):
            RuntimeV3().execute(Patcher(), clip, "text", clip, "", canonical(ON))
        clip = ForgeClip(); clip.cond_stage_model = object()
        with self.assertRaisesRegex(EmphasisError, "ENCODER_MODEL_MISMATCH"):
            RuntimeV3().execute(Patcher(), clip, "text", ForgeClip(), "", canonical(ON))
        model = Patcher(); model.model_options["ppm_negpip_moss"] = True
        with self.assertRaisesRegex(EmphasisError, "DUPLICATE"):
            RuntimeV3().execute(model, ForgeClip(), "text", ForgeClip(), "", canonical(ON))
        model = Patcher(); model.model_options["transformer_options"] = {"wrappers": {"diffusion_model": {"moss_emphasis.v1": [object()]}}}
        with self.assertRaisesRegex(EmphasisError, "DUPLICATE"):
            RuntimeV3().execute(model, ForgeClip(), "(red:2)", ForgeClip(), "", canonical(ON))

    def test_graph_roundtrip_without_old_negative_dependency(self):
        original = graph(); before = copy.deepcopy(original)
        original["6"] = {"class_type": "String", "inputs": {"text": "weighted"}}
        original["4"]["inputs"]["text"] = ["6", 0]
        original["7"] = {"class_type": "OtherConsumer", "inputs": {"cond": ["4", 0]}}
        before = copy.deepcopy(original)
        first = prepare(original, ON); internal = first["targets"][0]["runtime"]
        self.assertEqual(original, before)
        self.assertEqual(first["prompt"][internal]["class_type"], RUNTIME_V3)
        inp = first["prompt"][internal]["inputs"]
        self.assertNotIn("negative", inp)
        self.assertEqual(inp["negative_text"], ["6", 0])
        self.assertEqual(first["prompt"]["7"], original["7"])
        self.assertEqual(prepare(first["prompt"], {"enabled": False})["prompt"], original)
        self.assertEqual(prepare(first["prompt"], ON)["prompt"], first["prompt"])
        changed = copy.deepcopy(first["prompt"]); changed[internal]["inputs"]["model"] = ["2", 0]
        with self.assertRaisesRegex(EmphasisError, "PREPARED_GRAPH_CHANGED"):
            prepare(changed, ON)

    def test_graph_rejects_modified_negative_transactionally(self):
        for kind in ("ConditioningZeroOut", "ConditioningConcat", "CustomEncode"):
            source = graph(); source["4"]["class_type"] = kind; before = copy.deepcopy(source)
            with self.assertRaisesRegex(EmphasisError, "UNSUPPORTED_CONDITIONING_PATH"):
                prepare(source, ON)
            self.assertEqual(source, before)

    def test_attention_independent_math_batch_dtypes_and_ownership(self):
        for dtype in (torch.float64, torch.float32, torch.float16, torch.bfloat16):
            for scale in (0, .5, 1, 2):
                for wrapped in (False, True):
                    for order in ([0], [1], [0, 1], [1, 0]):
                        refs = [torch.randn(1, 2, 8, dtype=dtype) for _ in range(2)]
                        weights = [[-2, .5], [0, -1]]
                        branches = [([[ref, {}]], *coefficient_values(w, scale)[1:]) for ref, w in zip(refs, weights)]
                        state = ForwardState(*branches, scale)
                        context = torch.cat([refs[role].repeat(2, 1, 1) for role in order])
                        q, k, v = [torch.randn(len(order) * 2, 5, 8, dtype=dtype) for _ in range(3)]
                        originals = [item.clone() for item in (q, k, v)]
                        mask = torch.ones(q.shape[0], 1, 5, 5, dtype=torch.bool); mask[..., -1] = False
                        count = []
                        def backend(qq, kk, vv, heads, *args, mask=None, **kwargs):
                            count.append(1)
                            qq, kk, vv = [item.take() if isinstance(item, Container) else item for item in (qq, kk, vv)]
                            return torch.nn.functional.scaled_dot_product_attention(
                                qq.reshape(len(qq), -1, 2, 4).transpose(1, 2),
                                kk.reshape(len(kk), -1, 2, 4).transpose(1, 2),
                                vv.reshape(len(vv), -1, 2, 4).transpose(1, 2), attn_mask=mask).transpose(1, 2).flatten(2)
                        def execute(x, timestep, ctx, options):
                            inputs = [Container(item) for item in (q, k, v)] if wrapped else (q, k, v)
                            result = run_attention(backend, Container, *inputs, 2, options["moss_emphasis.v1"], (), mask, options, {})
                            if wrapped: self.assertTrue(all(item.tensor is None for item in inputs))
                            return result
                        options = {"cond_or_uncond": order}
                        actual = state(execute, torch.zeros(len(context), 4, 1, 3), None, context, options)
                        self.assertNotIn("moss_emphasis.v1", options)
                        self.assertEqual(len(count), 1 if scale == 0 else 2)
                        # Dense independent softmax in double, after matching Value dtype rounding.
                        expected = []
                        for row in range(len(q)):
                            role = order[row // 2]
                            _, image, sign = coefficient_values(weights[role], scale)
                            score = q[row].double().reshape(5, 2, 4).transpose(0, 1) @ k[row].double().reshape(5, 2, 4).permute(1, 2, 0) / 2
                            score[..., -1] = -math.inf
                            values = []
                            for query in range(5):
                                vv = v[row].clone()
                                vv[3:] *= torch.tensor(image if query < 3 else sign, dtype=dtype)[:, None]
                                values.append((score[:, query].softmax(-1)[:, None, :] @ vv.double().reshape(5, 2, 4).transpose(0, 1)).flatten())
                            expected.append(torch.stack(values))
                        tol = {torch.float64: 1e-12, torch.float32: 1e-6, torch.float16: .004, torch.bfloat16: .04}[dtype]
                        torch.testing.assert_close(actual.double(), torch.stack(expected), atol=tol, rtol=tol)
                        for value, original in zip((q, k, v), originals): self.assertTrue(torch.equal(value, original))

    def test_attention_value_overflow_and_bad_context(self):
        ref = torch.zeros(1, 1, 4, dtype=torch.float16)
        branch = ([[ref, {}]], (4.,), (1.,))
        state = ForwardState(branch, branch, 2)
        opts = state(lambda x, t, c, o: o, torch.zeros(1, 4, 1, 1), None, ref, {"cond_or_uncond": [1]})
        with self.assertRaisesRegex(EmphasisError, "INVALID_WEIGHT"):
            run_attention(lambda *a, **kw: None, Container, torch.ones(1, 2, 4, dtype=torch.float16),
                          torch.ones(1, 2, 4, dtype=torch.float16), torch.full((1, 2, 4), 60000., dtype=torch.float16),
                          1, opts["moss_emphasis.v1"], (), None, opts, {})
        for context, layout in ((ref + 1, [0]), (torch.zeros(1, 2, 4), [0]), (ref, [])):
            with self.assertRaisesRegex(EmphasisError, "UNSUPPORTED_CONDITIONING_PATH"):
                state(lambda *a: None, torch.zeros(1, 4, 1, 1), None, context, {"cond_or_uncond": layout})

    def test_installed_source_offer_contents(self):
        with zipfile.ZipFile(io.BytesIO(corresponding_source())) as source:
            names = source.namelist()
            for path in ("LICENSE", "LICENSE-AGPL-3.0", "NOTICE.md", "moss_emphasis/forge_negpip.py", "scripts/package.py", "tests/test_forge.py"):
                self.assertIn("ComfyUI-MOSS-Emphasis/" + path, names)
            self.assertFalse(any("/.git/" in path or "__pycache__" in path or "reference/" in path for path in names))
            self.assertIsNone(source.testzip())

    def test_source_offer_excludes_user_files_and_workflows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("VERSION", "web/controller.js", "locales/ja/settings.json", "docs/design.md",
                         "docs/personal-workflow.json", "user/settings.json", ".git/config", "web/.private/file.js"):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("fixture")
            with patch("moss_emphasis.api.__file__", str(root / "moss_emphasis/api.py")):
                with zipfile.ZipFile(io.BytesIO(corresponding_source())) as source:
                    names = {name.removeprefix("ComfyUI-MOSS-Emphasis/") for name in source.namelist()}
                    self.assertEqual(names, {"VERSION", "web/controller.js", "locales/ja/settings.json", "docs/design.md"})


if __name__ == "__main__": unittest.main()
