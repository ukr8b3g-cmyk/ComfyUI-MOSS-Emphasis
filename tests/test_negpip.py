import json
import math
import sys
import unittest
from unittest.mock import patch as mock_patch
import torch
# Profiler lazily imports Dynamo. Load it before the existing sys.modules
# contract mocks, so their restoration cannot discard a registered torch library.
import torch._dynamo
from test_engine import modules, Patcher, Clip, Container, attention_pytorch
from test_core import graph
from moss_emphasis.config import settings, canonical, active_strength, ENGINE, NEGPIP, EmphasisError
from moss_emphasis.negpip import negpip_coefficients, compact_mask, MASK_CACHE_KEY
from moss_emphasis.engine import patch, KEY
from moss_emphasis.runtime import Runtime
from moss_emphasis.graph import prepare

ON = {'schema_version': 2, 'enabled': True, 'engine': NEGPIP}


class NegPiPTests(unittest.TestCase):
    def setUp(self):
        self.modules = modules()
        self.mock = mock_patch.dict(sys.modules, self.modules)
        self.mock.start()
        torch.manual_seed(15)

    def tearDown(self):
        self.mock.stop()

    def test_legacy_migration(self):
        for version in ('0.9.0', '0.9.1'):
            old = settings({'version': version, 'enabled': True, 'strength': .7})
            self.assertEqual((old['engine'], old['strength'], old['schema_version']), ('kj_dit_v1', .7, 2))
            self.assertEqual(settings(old), old)

    def test_invalid_settings(self):
        for key, values in [('negpip_strength', [-1, 1.1, True, None, math.inf, math.nan]),
                            ('engine_version', [True, 2]), ('schema_version', [True, 3])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(EmphasisError):
                    settings({**ON, key: value})

    def test_strength_selection(self):
        self.assertEqual(active_strength(settings({**ON, 'strength': 0})), 1)
        self.assertEqual(active_strength(settings({**ON, 'strength': 4, 'negpip_strength': 0})), 0)
        self.assertNotEqual(canonical(ON), canonical({**ON, 'negpip_strength': .5}))

    def test_coefficients(self):
        weights = [-10, -5, -2, -1, -.5, 0, .5, 1, 2, 4, 5, 10]
        for t in (.25, .5, .75, 1):
            pairs = negpip_coefficients(weights, t)
            self.assertEqual(pairs[0][0], 1 - 2*t)
            absolute = torch.tensor(weights, dtype=torch.float64).abs().clamp_min(1e-4)
            expected = (absolute / absolute.mean()).log() * t
            torch.testing.assert_close(torch.tensor([v[1] for v in pairs], dtype=torch.float64), expected, atol=1e-12, rtol=1e-12)
        for weight in (0, .5, 1, 2):
            self.assertEqual(negpip_coefficients([weight]*3, 1), ((1., 0.),)*3)

    def test_extreme_finite_negpip_coefficients(self):
        maximum = sys.float_info.max
        pairs = negpip_coefficients([-maximum, 0, maximum, 1], 1)
        self.assertTrue(all(math.isfinite(value) for pair in pairs for value in pair))
        self.assertEqual(pairs[0][0], -1)
        self.assertAlmostEqual(pairs[0][1], math.log(2), places=12)
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(EmphasisError):
                negpip_coefficients([value, 1], 1)

    def test_unbounded_runtime_weights_both_engines_and_dtypes(self):
        for engine in (ENGINE, NEGPIP):
          for dtype in (torch.float64, torch.float32, torch.float16, torch.bfloat16):
            with self.subTest(engine=engine, dtype=dtype):
                original, clip = Patcher(), Clip()
                model, cond = Runtime().execute(original, clip, 'a (x:-5) (y:10)',
                                               json.dumps({**ON, 'engine': engine}))
                self.assertEqual(clip.last_text, 'a x y')
                self.assertEqual(original.objects, {})
                context = cond[0][0].to(dtype)
                n_text = context.shape[1]
                state = model.wrapper(lambda x,t,c,o:o, torch.zeros(1,128,1,2), None,
                                      context, {'cond_or_uncond':[0]})
                pairs = model.wrapper.weights
                if engine == ENGINE:
                    self.assertIn((-5., 0.), pairs)
                    self.assertIn((1., 18.), pairs)
                else:
                    self.assertEqual(sum(value < 0 for value,bias in pairs), 1)
                    self.assertTrue(any(bias > 0 for value,bias in pairs))
                q,k,v = [torch.randn(1,2+n_text,4,dtype=dtype) for _ in range(3)]
                before = v.clone()
                out = model.objects['diffusion_model.layers.0.comfy_attention'].run(q,k,v,1,transformer_options=state)
                self.assertEqual(out.dtype, dtype)
                self.assertTrue(torch.isfinite(out).all())
                self.assertTrue(torch.equal(v, before))
                if engine == NEGPIP:
                    torch.testing.assert_close(out[:,2:], attention_pytorch(q[:,2:],k,v,1))

    def test_legacy_overflow_checks_use_computed_coefficients_and_dtype(self):
        ref = torch.ones(2,4)
        with self.assertRaisesRegex(EmphasisError, 'overflowed'):
            patch(Patcher(), [[ref[None],{}]], [-sys.float_info.max,1], 4)
        model = patch(Patcher(), [[ref[None],{}]], [-100000,1], 1)
        with self.assertRaisesRegex(EmphasisError, 'float16'):
            model.wrapper(lambda x,t,c,o:o, torch.zeros(1,128,1,2), None,
                          ref[None].half(), {'cond_or_uncond':[0]})
        state = model.wrapper(lambda x,t,c,o:o, torch.zeros(1,128,1,2), None,
                              ref[None], {'cond_or_uncond':[0]})
        self.assertEqual(state[KEY][2][0], -100000)

    def test_query_split_batch_dtype_and_ownership(self):
        for dtype in (torch.float64, torch.float32, torch.float16, torch.bfloat16):
          for layout in ([0], [1, 0], [0, 1], [0, 0, 1]):
           for wrapped in (False, True):
            with self.subTest(dtype=dtype, layout=layout, wrapped=wrapped):
                b, image, text, heads, dim = len(layout), 3, 4, 2, 8
                weights = [-1, 0, .5, 2]
                ref = torch.ones(text, dim, dtype=dtype)
                model = patch(Patcher(), [[ref[None], {}]], weights, 1, engine=NEGPIP)
                state = model.wrapper(lambda x,t,c,o: o, torch.zeros(b,128,1,image), None,
                                      ref[None].repeat(b,1,1), {'cond_or_uncond':layout})
                q,k,v = [torch.randn(b,image+text,dim,dtype=dtype) for _ in range(3)]
                original = v.clone()
                inp = [Container(x) for x in (q,k,v)] if wrapped else [q,k,v]
                out = model.objects['diffusion_model.layers.0.comfy_attention'].run(*inp, heads, transformer_options=state)
                plain = attention_pytorch(q,k,v,heads)
                for row, kind in enumerate(layout):
                    if kind == 1:
                        torch.testing.assert_close(out[row], plain[row])
                    else:
                        torch.testing.assert_close(out[row,image:], plain[row,image:])
                        absw=torch.tensor(weights,dtype=torch.float64).abs().clamp_min(1e-4)
                        bias=torch.zeros(1,1,1,image+text,dtype=dtype)
                        bias[...,image:] = (absw/absw.mean()).log().to(dtype)
                        vv=v[row:row+1].clone();vv[:,image] *= -1
                        expected=attention_pytorch(q[row:row+1,:image],k[row:row+1],vv,heads,mask=bias)
                        torch.testing.assert_close(out[row:row+1,:image],expected)
                self.assertEqual(out.dtype, dtype)
                self.assertTrue(torch.equal(v, original))
                if wrapped:
                    for c in inp:
                        with self.assertRaises(RuntimeError): c.peek()

    def test_masks(self):
        q=torch.ones(2,5,4)
        mask=torch.tensor([[[[True,False,True,True,True]]]])
        old=mask.clone(); m=compact_mask(mask,q,1,5)
        self.assertTrue(torch.isneginf(m[...,1]).all());self.assertTrue(torch.equal(mask,old))
        for bad in (torch.zeros(2,5), torch.zeros(1,1,5,5), torch.ones(1,1,1,5)*float('nan'),
                    torch.full((1,1,1,5), -math.inf), torch.full((1,1,1,5), math.inf)):
            with self.assertRaises(EmphasisError):compact_mask(bad,q,1,5)

    def test_kitchen_container_calls_and_exception_recovery(self):
        att=self.modules['comfy.ldm.modules.attention'];calls=[]
        def kitchen(q,k,v,h,**kwargs):
            self.assertTrue(all(isinstance(t,Container) for t in (q,k,v)))
            calls.append((q.peek().shape[1],v.peek().dtype))
            return attention_pytorch(q,k,v,h,**kwargs)
        kitchen.container_function=lambda:None
        att.optimized_attention=att.attention_comfy_kitchen_int8=kitchen
        ref=torch.ones(2,4)
        model=patch(Patcher(),[[ref[None],{}]],[-1,2],.75,engine=NEGPIP)
        state=model.wrapper(lambda x,t,c,o:o,torch.zeros(1,128,1,3),None,ref[None],{'cond_or_uncond':[0]})
        fn=model.objects['diffusion_model.layers.0.comfy_attention'].run
        with self.assertRaises(EmphasisError):
            fn(*[Container(torch.ones(1,6,4)) for _ in range(3)],1,transformer_options=state)
        fn(*[Container(torch.ones(1,5,4)) for _ in range(3)],1,transformer_options=state)
        self.assertEqual(calls,[(3,torch.float32),(2,torch.float32)])
        self.assertFalse(any(isinstance(v,torch.Tensor) for v in vars(model.objects['diffusion_model.layers.0.comfy_attention']).values()))

    def test_runtime_and_bypass(self):
        for config in ({**ON,'negpip_strength':0},{**ON,'enabled':False}):
            clip=Clip();model=Patcher()
            out,_=Runtime().execute(model,clip,'(red:-1)',json.dumps(config))
            self.assertIs(out,model);self.assertEqual(clip.last_text,'(red:-1)')
        clip=Clip();model=Patcher()
        out,_=Runtime().execute(model,clip,'(red:-1)',json.dumps({**ON,'strength':0}))
        self.assertIsNot(out,model);self.assertEqual(clip.last_text,'red')
        clip=Clip();model=Patcher();model.diffusion=object()
        with self.assertRaises(EmphasisError):Runtime().execute(model,clip,'red',json.dumps(ON))

    def test_graph_roundtrip_and_conflicts(self):
        g=graph();first=prepare(g,{**ON,'strength':0})
        self.assertTrue(first['targets'])
        self.assertEqual(prepare(first['prompt'],{**ON,'negpip_strength':0})['prompt'],g)
        for config in (ON, {'enabled':True}):
            g=graph();g['2']['class_type']='CLIPNegPip'
            with self.assertRaises(EmphasisError):prepare(g,config)
        g=graph();g['unused']={'class_type':'CLIPNegPip','inputs':{}}
        self.assertTrue(prepare(g,ON)['targets'])

    def test_duplicate_clip_marker(self):
        clip=Clip();clip.patcher=type('P',(),{'model_options':{'ppm_negpip':True}})()
        with self.assertRaises(EmphasisError):Runtime().execute(Patcher(),clip,'(red:-1)',json.dumps(ON))

    def attention_fixture(self):
        ref = torch.ones(2,4)
        model = patch(Patcher(), [[ref[None],{}]], [-.5,2], 1, engine=NEGPIP)
        def forward():
            return model.wrapper(lambda x,t,c,o:o, torch.zeros(1,128,1,3), None, ref[None], {'cond_or_uncond':[0]})
        return model, forward, [torch.randn(1,5,4) for _ in range(3)]

    def test_generated_bias_has_no_host_scalar_reads_across_42_blocks(self):
        from torch.profiler import profile, ProfilerActivity
        model, forward, tensors = self.attention_fixture()
        opts = forward()
        with profile(activities=[ProfilerActivity.CPU]) as p:
            for i in range(42):
                model.objects[f'diffusion_model.layers.{i}.comfy_attention'].run(*tensors,1,transformer_options=opts)
        self.assertEqual(sum(e.count for e in p.key_averages() if e.key=='aten::_local_scalar_dense'),0)

    def test_external_mask_validation_shared_only_within_forward(self):
        model, forward, tensors = self.attention_fixture()
        opts = forward(); mask = torch.zeros(1,1,1,5); mask[...,0] = -math.inf
        original = mask.clone()
        with mock_patch('moss_emphasis.negpip.compact_mask',wraps=compact_mask) as check:
            for i in range(42):
                out = model.objects[f'diffusion_model.layers.{i}.comfy_attention'].run(*tensors,1,mask=mask,transformer_options=dict(opts))
            self.assertEqual(check.call_count,2)  # input and combined mask, once each
        self.assertTrue(torch.equal(mask,original));self.assertTrue(torch.isfinite(out).all())
        next_opts=forward();self.assertIsNot(next_opts[MASK_CACHE_KEY],opts[MASK_CACHE_KEY])
        self.assertEqual(next_opts[MASK_CACHE_KEY],{})
        with mock_patch('moss_emphasis.negpip.compact_mask',wraps=compact_mask) as check:
            model.objects['diffusion_model.layers.0.comfy_attention'].run(*tensors,1,mask=mask,transformer_options=next_opts)
            self.assertEqual(check.call_count,2)
        self.assertNotIn(MASK_CACHE_KEY,vars(model.wrapper))

    def test_different_mask_or_bias_invalidates_forward_cache(self):
        model, forward, tensors = self.attention_fixture(); opts=forward()
        run=model.objects['diffusion_model.layers.0.comfy_attention'].run
        valid=torch.zeros(1,1,1,5);run(*tensors,1,mask=valid,transformer_options=opts)
        for invalid in (torch.full_like(valid,math.nan),torch.full_like(valid,-math.inf),torch.full_like(valid,math.inf)):
            with self.assertRaises(EmphasisError):run(*tensors,1,mask=invalid,transformer_options=opts)
        fresh=valid.clone()
        with mock_patch('moss_emphasis.negpip.compact_mask',wraps=compact_mask) as check:
            run(*tensors,1,mask=fresh,transformer_options=opts);self.assertEqual(check.call_count,2)
        fresh[...,0] = math.nan
        with self.assertRaises(EmphasisError):run(*tensors,1,mask=fresh,transformer_options=opts)
        fresh.zero_()
        run(*tensors,1,mask=fresh,transformer_options=opts)
        rows,start,factors,bias=opts[KEY];opts[KEY]=(rows,start,factors,bias.clone())
        with mock_patch('moss_emphasis.negpip.compact_mask',wraps=compact_mask) as check:
            run(*tensors,1,mask=fresh,transformer_options=opts);self.assertEqual(check.call_count,2)

    def test_mask_dtype_overflow_is_still_rejected(self):
        model, forward, tensors = self.attention_fixture();opts=forward()
        # A finite FP32 mask outside the FP16 range must remain an error.
        tensors=[t.half() for t in tensors]
        mask=torch.full((1,1,1,5),1e10)
        with self.assertRaises(EmphasisError):
            model.objects['diffusion_model.layers.0.comfy_attention'].run(*tensors,1,mask=mask,transformer_options=opts)
