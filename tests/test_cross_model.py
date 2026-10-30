"""Graph/legacy regressions. Real ComfyUI contracts run in native_contract.py."""
import copy
import json
import math
import sys
import unittest
from unittest.mock import patch
import torch
from test_core import graph
from test_engine import Patcher, Clip, modules
from moss_emphasis.config import (settings, canonical, ENGINE, NEGPIP, AUTO_ENGINE,
                                 AUTO_NEGPIP, RUNTIME, RUNTIME_V2, EmphasisError)
from moss_emphasis.graph import prepare
from moss_emphasis.runtime import Runtime, RuntimeV2
from moss_emphasis.adapters import weighted_tokens, interleave, split_sdxl, anima_attention, SIGN

ON = {"schema_version": 3, "engine": AUTO_NEGPIP, "enabled": True}


class AutoGraphTests(unittest.TestCase):
    def test_roundtrip_multiple_samplers_and_shared_negative(self):
        for kind in ("KSampler", "KSamplerAdvanced", "CFGGuider"):
            g = graph(kind)
            g["5"]["inputs"]["negative"] = ["3", 0]
            g["6"] = copy.deepcopy(g["5"])
            original = copy.deepcopy(g)
            result = prepare(g, ON)
            self.assertEqual(g, original)
            self.assertEqual(prepare(result["prompt"], ON), result)
            self.assertEqual(prepare(result["prompt"], {})["prompt"], g)
            for target in result["targets"]:
                node = result["prompt"][target["runtime"]]
                self.assertEqual(node["class_type"], RUNTIME_V2)
                self.assertEqual(node["inputs"]["negative"], ["3", 0])
            legacy = prepare(result["prompt"], {"enabled": True})
            self.assertTrue(all(legacy["prompt"][t["runtime"]]["class_type"] == RUNTIME for t in legacy["targets"]))

    def test_changed_negative_or_shared_runtime_is_rejected(self):
        for mode in ("source", "target", "shared"):
            result = prepare(graph(), ON)
            r = result["targets"][0]["runtime"]
            g = result["prompt"]
            if mode == "source":
                g[r]["inputs"]["negative"] = ["3", 0]
            elif mode == "target":
                g["5"]["inputs"]["negative"] = ["4", 0]
            else:
                g["6"] = {"class_type": "Consumer", "inputs": {"cond": [r, 2]}}
            with self.assertRaisesRegex(EmphasisError, "PREPARED_GRAPH_CHANGED"):
                prepare(g, ON)

    def test_negative_upstream_conflicts_checked_only_for_auto(self):
        g = graph()
        g["4"]["class_type"] = "CLIPNegPip"
        with self.assertRaisesRegex(EmphasisError, "DUPLICATE_WEIGHT_ENGINE"):
            prepare(g, ON)
        prepare(g, {"enabled": True})

    def test_schema_and_cache_keys(self):
        for engine in (AUTO_ENGINE, AUTO_NEGPIP):
            config = settings({**ON, "engine": engine})
            self.assertEqual(config, settings(config))
            self.assertNotEqual(canonical(config), canonical({"enabled": True}))
        for bad in ({**ON, "engine": NEGPIP}, {**ON, "schema_version": 2}, {**ON, "schema_version": 4}):
            with self.assertRaises(EmphasisError): settings(bad)

    def test_moss_auto_dispatch_keeps_legacy_results(self):
        with patch.dict(sys.modules, modules()):
            for auto, legacy in ((AUTO_ENGINE, ENGINE), (AUTO_NEGPIP, NEGPIP)):
                for strength in (0, .5, 1):
                    cfg = {**ON, "engine": auto, "strength": strength, "negpip_strength": strength}
                    old = {**cfg, "schema_version": 2, "engine": legacy}
                    negative = [[torch.randn(1, 2, 4), {}]]
                    m1, c1 = Runtime().execute(Patcher(), Clip(), "(red:-5)", json.dumps(old))
                    m2, c2, neg = RuntimeV2().execute(Patcher(), Clip(), "(red:-5)", json.dumps(cfg), negative)
                    self.assertTrue(torch.equal(c1[0][0], c2[0][0]))
                    self.assertIs(neg, negative)
                    if strength: self.assertEqual(m1.wrapper.weights, m2.wrapper.weights)

    def test_off_bypass_allows_other_models_and_untouched_text(self):
        for cfg in ({**ON, "enabled": False}, {**ON, "negpip_strength": 0}):
            clip, model, negative = Clip(), object(), []
            out, _, neg = RuntimeV2().execute(model, clip, "(red:-5)", json.dumps(cfg), negative)
            self.assertIs(out, model); self.assertIs(neg, negative)
            self.assertEqual(clip.last_text, "(red:-5)")


class TokenAndAttentionTests(unittest.TestCase):
    def test_coefficients_and_token_ownership(self):
        weights = [0, 1, .5, -.5, -1, -5, 5, 10]
        tokens = {"l": [[(i, w, i) for i, w in enumerate(weights)]], "other": [[(4, .1)]]}
        old = copy.deepcopy(tokens)
        for neg in (False, True):
            for strength in (.5, 1, 2) if not neg else (.5, 1):
                result = weighted_tokens(tokens, ("l",), strength, neg)
                expected = [1 + strength * ((abs(w) if neg else w) - 1) for w in weights]
                self.assertEqual([t[1] for t in result["l"][0]], expected)
                self.assertIs(result["other"], tokens["other"])
        self.assertEqual(tokens, old)
        for w in (math.nan, math.inf, -math.inf, -sys.float_info.max):
            with self.assertRaises(EmphasisError): weighted_tokens({"l": [[(0, w)]]}, ("l",), 4, False)

    def test_sdxl_identity_negative_batch_order_and_dtype(self):
        for dtype in (torch.float64, torch.float32, torch.float16, torch.bfloat16):
            positive, negative = torch.randn(2, 6, 8).to(dtype), torch.randn(2, 3, 8).to(dtype)
            for rows in ((0,), (1,), (0, 1), (1, 0), (0, 0, 1)):
                identity = interleave(negative, negative).repeat(1, 2, 1)
                carrier = torch.cat([interleave(positive, -positive) if row == 0 else identity for row in rows])
                before = carrier.clone()
                q = torch.randn(len(rows) * 2, 2, 8).to(dtype)
                _, k, v = split_sdxl(q, carrier, carrier, {})
                for i, row in enumerate(rows):
                    expected = positive if row == 0 else negative.repeat(1, 2, 1)
                    torch.testing.assert_close(k[i*2:i*2+2], expected, rtol=0, atol=0)
                    torch.testing.assert_close(v[i*2:i*2+2], -positive if row == 0 else expected, rtol=0, atol=0)
                self.assertTrue(torch.equal(carrier, before))

    def test_anima_dtype_ownership_and_bad_alignment(self):
        for dtype in (torch.float64, torch.float32, torch.float16, torch.bfloat16):
            v = torch.randn(2, 5, 4).to(dtype); old = v.clone()
            signs = torch.tensor([[-1., 0., 1., 1., 1.], [1., 1., 1., 1., 1.]], dtype=torch.float64)[..., None]
            out = anima_attention(v, v, v, extra_options={SIGN: signs})
            self.assertEqual(out["v"].dtype, dtype)
            self.assertTrue(torch.equal(v, old))
            self.assertTrue(torch.equal(out["v"][1], v[1]))
            self.assertTrue(torch.equal(out["v"][0, 1], torch.zeros(4, dtype=dtype)))
        with self.assertRaises(EmphasisError): anima_attention(v, v, v, extra_options={SIGN: signs[:, :2]})
