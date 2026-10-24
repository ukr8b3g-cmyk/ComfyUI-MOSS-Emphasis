"""CPU contract tests for official SLG provenance and native CK INT8 forwarding.

No CUDA or actual MOSS weights are used here. A Kitchen stand-in records the
attention tensors handed to the kernel, after emphasis/mask preparation.
"""
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

try:
    import torch
except ImportError:
    torch = None

if torch is not None:
    from moss_emphasis.engine import (is_official_slg_callback, select_attention_backend,
                                      patch, ForwardState, combine_mask, KEY)
    from moss_emphasis.config import EmphasisError
    from test_engine import (Container, Attention, Patcher, attention_pytorch, modules)


@unittest.skipIf(torch is None, "torch needed")
class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "nodes.py").touch()
        file = root / "comfy_extras" / "nodes_slg.py"
        file.parent.mkdir()
        file.write_text("# official-file placeholder\n")
        # Comfy 0.42.x registers a module under its full absolute path stem.
        name = str(file.with_suffix(""))
        m = types.ModuleType(name)
        m.__file__ = str(file)
        source = '''
class SkipLayerGuidanceDiTSimple:
    @classmethod
    def execute(cls):
        def skip(args, extra_args):
            return args
        def calc_cond_batch_function(args):
            return args
        return skip, calc_cond_batch_function
class SkipLayerGuidanceDiT:
    @classmethod
    def execute(cls):
        def skip(args, extra_args):
            return args
        def post_cfg_function(args):
            return args
        return skip, post_cfg_function
'''
        exec(compile(source, str(file), "exec"), m.__dict__)
        self.nm = types.ModuleType("nodes")
        self.nm.__file__ = str(root / "nodes.py")
        self.module = m
        self.loaded = mock_patch.dict(sys.modules, {"nodes": self.nm, name: m})
        self.loaded.start()
        self.addCleanup(self.loaded.stop)

    def test_real_import_layout(self):
        simple_skip, simple_cb = self.module.SkipLayerGuidanceDiTSimple.execute()
        complex_skip, complex_cb = self.module.SkipLayerGuidanceDiT.execute()
        self.assertTrue(is_official_slg_callback(simple_cb, "sampler_calc_cond_batch_function"))
        self.assertTrue(is_official_slg_callback(complex_cb, "sampler_post_cfg_function"))
        self.assertTrue(is_official_slg_callback(simple_skip, "block"))
        self.assertTrue(is_official_slg_callback(complex_skip, "block"))
        self.assertFalse(is_official_slg_callback(simple_cb, "sampler_post_cfg_function"))

    def test_patch_preserves_registered_official_callback(self):
        _, fn = self.module.SkipLayerGuidanceDiTSimple.execute()
        p = Patcher()
        p.model_options["sampler_calc_cond_batch_function"] = fn
        mods = modules()
        with mock_patch.dict(sys.modules, mods):
            weighted = patch(p, [[torch.ones(1,2,4), {}]], [.5, 1.5], 1)
        self.assertIs(weighted.model_options["sampler_calc_cond_batch_function"], fn)
        self.assertIs(p.model_options["sampler_calc_cond_batch_function"], fn)

    def test_official_dit_block_replacement_preserved(self):
        skip, _ = self.module.SkipLayerGuidanceDiTSimple.execute()
        p = Patcher()
        p.model_options["transformer_options"] = {"patches_replace": {"dit": {("single_block", 22): skip}}}
        with mock_patch.dict(sys.modules, modules()):
            weighted = patch(p, [[torch.ones(1,2,4), {}]], [.5, 1.5], 1)
        self.assertIs(weighted.model_options["transformer_options"]["patches_replace"]["dit"][("single_block", 22)], skip)

    def test_official_post_cfg_preserved(self):
        _, fn = self.module.SkipLayerGuidanceDiT.execute()
        p = Patcher()
        p.model_options["sampler_post_cfg_function"] = [fn]
        with mock_patch.dict(sys.modules, modules()):
            weighted = patch(p, [[torch.ones(1,2,4), {}]], [.5, 1.5], 1)
        self.assertEqual(weighted.model_options["sampler_post_cfg_function"], [fn])

    def test_rejects_untrusted_same_basename(self):
        fake = types.ModuleType("custom_nodes.nodes_slg")
        fake.__file__ = str(Path(self.tmp.name) / "custom_nodes" / "nodes_slg.py")
        def bogus(args): return args
        bogus.__module__ = fake.__name__
        with mock_patch.dict(sys.modules, {fake.__name__: fake}):
            self.assertFalse(is_official_slg_callback(bogus, "sampler_calc_cond_batch_function"))

    def test_rejects_forged_module_property(self):
        _, legitimate = self.module.SkipLayerGuidanceDiTSimple.execute()
        def spoof(args):return args
        spoof.__module__ = legitimate.__module__
        self.assertFalse(is_official_slg_callback(spoof, "sampler_calc_cond_batch_function"))

    def test_rejects_unregistered_custom_guidance(self):
        def outsider(args): return args
        p = Patcher()
        p.model_options["sampler_calc_cond_batch_function"] = outsider
        with mock_patch.dict(sys.modules, modules()):
            with self.assertRaisesRegex(EmphasisError, "Unsupported guidance patch"):
                patch(p, [[torch.ones(1,2,4), {}]], [.5, 1.5], 1)


@unittest.skipIf(torch is None, "torch needed")
class KitchenContractTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(619)
        self.stub = modules()
        self.ctx = mock_patch.dict(sys.modules, self.stub)
        self.ctx.start()
        self.addCleanup(self.ctx.stop)
        self.attn = self.stub["comfy.ldm.modules.attention"]
        self.calls = []
        calls = self.calls
        def ck_int8(q,k,v,heads,*a,mask=None,**kwargs):
            if isinstance(q, Container):
                return ck_int8.container_function(q,k,v,heads,*a,mask=mask,**kwargs)
            return attention_pytorch(q,k,v,heads,mask=mask,**kwargs)
        def container(q,k,v,heads,*a,mask=None,**kwargs):
            q,k,v = q.take(),k.take(),v.take()
            calls.append({"q":q.clone(),"k":k.clone(),"v":v.clone(),
                          "mask": None if mask is None else mask.clone(),
                          "requested_backend":"comfy_kitchen_int8_prequantized"})
            return attention_pytorch(q,k,v,heads,mask=mask,**kwargs)
        ck_int8.container_function = container
        self.attn.attention_comfy_kitchen_int8 = ck_int8
        self.attn.optimized_attention = ck_int8

    def _execute(self, weights):
        p = Patcher()
        context1 = torch.randn(2,4)
        output = patch(p, [[context1[None],{}]], weights, 1)
        q,k,v = [torch.randn(2,3,4) for _ in range(3)]
        original = v.clone()
        context = torch.stack([context1,torch.zeros_like(context1)])
        Q,K,V=Container(q),Container(k),Container(v)
        def execute(x,t,c,o):
            return output.objects["diffusion_model.layers.0.comfy_attention"].function(Q,K,V,1,transformer_options=o)
        result = output.wrapper(execute,torch.zeros(2,128,1,1),torch.ones(2),context,{"cond_or_uncond":[0,1]})
        return result,q,k,original,(Q,K,V)

    def test_supported_backend_is_original(self):
        kernel, label = select_attention_backend(self.attn)
        self.assertIs(kernel, self.attn.attention_comfy_kitchen_int8)
        self.assertEqual(label,"comfy_kitchen_int8")

    def test_suppression_keeps_unmasked_kitchen_and_negative_untouched(self):
        output,q,k,v,containers=self._execute([.5,1])
        self.assertEqual(len(self.calls),1)
        call=self.calls[0]
        self.assertEqual(call["requested_backend"],"comfy_kitchen_int8_prequantized")
        self.assertIsNone(call["mask"])
        torch.testing.assert_close(call["v"][0,1,:],v[0,1,:]*.5)
        torch.testing.assert_close(call["v"][1,:,:],v[1,:,:])
        torch.testing.assert_close(output[1],attention_pytorch(q[1:],k[1:],v[1:],1,mask=None)[0],rtol=0,atol=0)
        self.assertTrue(all(x.tensor is None for x in containers))

    def test_boost_uses_additive_mask_with_kitchen_without_fallback(self):
        _,_,_,v,_=self._execute([1,1.5])
        call=self.calls[0]
        self.assertEqual(call["mask"].shape,(2,1,1,3))
        self.assertEqual(call["mask"][0,0,0,2],1)
        self.assertEqual(call["mask"][1].abs().sum(),0)
        torch.testing.assert_close(call["v"],v)

    def test_mixed_boost_and_suppression(self):
        _,_,_,v,_=self._execute([.5,1.5])
        c=self.calls[0]
        self.assertEqual(c["mask"][0,0,0,2],1)
        self.assertEqual(c["mask"][1].abs().sum(),0)
        torch.testing.assert_close(c["v"][0,1,:],v[0,1,:]*.5)
        torch.testing.assert_close(c["v"][1],v[1])

    def test_unavailable_container_contract_is_rejected(self):
        self.attn.attention_comfy_kitchen_int8.container_function = None
        with self.assertRaisesRegex(EmphasisError,"container/prequantized"):
            patch(Patcher(),[[torch.ones(1,2,4),{}]],[1.5,1],1)

    def test_model_configured_int8_still_rejected(self):
        p=Patcher()
        p.diffusion.layers[0].comfy_attention.config = {"attention":"comfy_kitchen_int8"}
        with self.assertRaisesRegex(EmphasisError,"Per-layer INT8/SOL"):
            patch(p,[[torch.ones(1,2,4),{}]],[1.5,1],1)

    def test_float32_forced_pytorch_fallback_rejected(self):
        p=patch(Patcher(),[[torch.ones(1,2,4),{}]],[1.5,1],1)
        q,k,v=[Container(torch.randn(1,2,4)) for _ in range(3)]
        with self.assertRaisesRegex(EmphasisError,"would fall back"):
            p.objects["diffusion_model.layers.0.comfy_attention"].function(q,k,v,1,
                transformer_options={},low_precision_attention=False)
        self.assertTrue(all(x.tensor is not None for x in (q,k,v)))

if __name__=="__main__": unittest.main()
