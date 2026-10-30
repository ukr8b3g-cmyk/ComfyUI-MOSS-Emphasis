"""Real CPU tensors against small attention-contract doubles, not MOSS GPU tests."""
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch as mock_patch
try:
    import torch
    import torch.distributed.tensor  # Load before sys.modules contract mocks restore imports.
except ImportError:
    torch = None

if torch is not None:
    from moss_emphasis.engine import apply_values, combine_mask, ForwardState, is_native_moss, patch, KEY
    from moss_emphasis.config import EmphasisError, canonical
    from moss_emphasis.runtime import Runtime
    from moss_emphasis.tokens import PREFIX, SUFFIX, byte_decoder

    class Container:
        def __init__(self,t): self.tensor=t
        def peek(self):
            if self.tensor is None: raise RuntimeError("consumed")
            return self.tensor
        def take(self): t=self.peek();self.tensor=None;return t

    class Attention(torch.nn.Module):
        def __init__(self):super().__init__();self.config=None;self.function=None;self.method=None

    def attention_pytorch(q,k,v,heads,mask=None,**kwargs):
        q,k,v=[x.take() if isinstance(x,Container) else x for x in (q,k,v)]
        b,n,d=q.shape
        q,k,v=[x.view(b,-1,heads,d//heads).transpose(1,2) for x in (q,k,v)]
        return torch.nn.functional.scaled_dot_product_attention(q,k,v,attn_mask=mask).transpose(1,2).reshape(b,n,d)

    MOSS = type("MOSSImage",(),{"__module__":"comfy.ldm.moss_image.model"})
    class Patcher:
        def __init__(self):
            self.diffusion=MOSS();self.diffusion.text_embedder=object();self.diffusion.layers=[types.SimpleNamespace(comfy_attention=Attention()) for _ in range(42)]
            self.model_options={};self.objects={};self.wrapper=None
        def get_model_object(self,name):
            if name in self.objects:return self.objects[name]
            if name=="diffusion_model":return self.diffusion
            if name.startswith("diffusion_model.layers."):return self.diffusion.layers[int(name.split('.')[2])].comfy_attention
            raise KeyError(name)
        def clone(self):
            result=copy.copy(self);result.model_options=copy.deepcopy(self.model_options);result.objects=self.objects.copy();return result
        def add_object_patch(self,path,value):self.objects[path]=value
        def add_wrapper_with_key(self,which,key,wrapper):
            self.wrapper=wrapper;self.model_options.setdefault("transformer_options",{}).setdefault("wrappers",{}).setdefault(which,{})[key]=[wrapper]

    class FakeHF:
        all_special_tokens=["<|im_start|>","<|im_end|>"]
        byte_decoder=byte_decoder()
        def __init__(self):self.mapping={};self.rev={}
        def convert_ids_to_tokens(self,ids):return [self.rev[i] for i in ids]
        def get_added_vocab(self):return {k:i for k,i in self.mapping.items() if k in self.all_special_tokens}
        def encode(self,s):
            encoder={v:k for k,v in self.byte_decoder.items()};pieces=[];i=0
            while i<len(s):
                sp=next((t for t in self.all_special_tokens if s.startswith(t,i)),None)
                if sp:pieces.append(sp);i+=len(sp)
                else:pieces.extend(encoder[b] for b in s[i].encode());i+=1
            for p in pieces:
                if p not in self.mapping:
                    index=len(self.mapping);self.mapping[p]=index;self.rev[index]=p
            return [self.mapping[p] for p in pieces]

    Tokenizer=type("MOSSImageTokenizer",(),{"__module__":"comfy.text_encoders.moss_image"})
    class Clip:
        def __init__(self):
            self.hf=FakeHF();self.tokenizer=Tokenizer();self.tokenizer.clip="qwen35_9b";self.tokenizer.qwen35_9b=types.SimpleNamespace(tokenizer=self.hf);self.last_text=None
        def tokenize(self,text):
            self.last_text=text
            return {"qwen35_9b":[[(i,1.0) for i in self.hf.encode(PREFIX+text.strip()+SUFFIX)]]}
        def encode_from_tokens_scheduled(self,tokens):
            ids=[t[0] for t in tokens["qwen35_9b"][0]]
            return [[torch.tensor(ids,dtype=torch.float32)[None,:,None].repeat(1,1,4),{}]]

    def modules():
        comfy=types.ModuleType("comfy");ldm=types.ModuleType("comfy.ldm");mods=types.ModuleType("comfy.ldm.modules");att=types.ModuleType("comfy.ldm.modules.attention");pe=types.ModuleType("comfy.patcher_extension")
        att.ComfyAttention=Attention;att.AttentionTensorContainer=Container;att.optimized_attention=attention_pytorch;att.attention_pytorch=attention_pytorch;att.attention_basic=attention_pytorch
        pe.WrappersMP=types.SimpleNamespace(DIFFUSION_MODEL="diffusion_model")
        comfy.ldm=ldm;ldm.modules=mods;mods.attention=att;comfy.patcher_extension=pe
        return {"comfy":comfy,"comfy.ldm":ldm,"comfy.ldm.modules":mods,"comfy.ldm.modules.attention":att,"comfy.patcher_extension":pe}

@unittest.skipIf(torch is None,"PyTorch not installed in this test environment")
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.modules=modules();self.context=mock_patch.dict(sys.modules,self.modules);self.context.start();torch.manual_seed(0)
    def tearDown(self):self.context.stop()
    def test_value_rows_and_original(self):
        v=torch.ones(2,5,3);old=v.clone();r=apply_values(v,[0],3,torch.tensor([.5,-1.]));self.assertTrue(torch.equal(v,old));self.assertTrue(torch.equal(r[1],v[1]));self.assertEqual(r[0,3,0],.5)
    def test_additive_mask_preserved(self):
        mask=torch.tensor([[0.,-3.,float('-inf')]]);bias=torch.ones(1,1,1,3);r=combine_mask(mask,bias);self.assertEqual(r[0,0,0,1],-2);self.assertTrue(torch.isneginf(r[0,0,0,2]))
    def test_boolean_mask_preserved(self):
        r=combine_mask(torch.tensor([[True,False]]),torch.ones(1,1,1,2));self.assertEqual(r[0,0,0,0],1);self.assertTrue(torch.isneginf(r[0,0,0,1]))
    def test_dense_mask_rejected(self):
        with self.assertRaises(EmphasisError):combine_mask(torch.zeros(1,1,3,3),torch.zeros(1,1,1,3))
    def test_model_guard(self):
        p=Patcher();self.assertTrue(is_native_moss(p));p.diffusion=object();self.assertFalse(is_native_moss(p))
    def test_unknown_moss_rejected(self):
        p=Patcher();p.diffusion=type("OtherMOSS",(),{})()
        with self.assertRaises(EmphasisError):is_native_moss(p)
    def test_only_joint_layers_patched(self):
        p=Patcher();cond=[[torch.ones(1,2,4),{}]];out=patch(p,cond,[.5,1.5],1)
        self.assertEqual(len(out.objects),42);self.assertEqual(p.objects,{});self.assertTrue(all("text_embedder" not in s for s in out.objects))
    def test_context_same_length_different_rejected(self):
        state=ForwardState(torch.ones(2,4),[.5,1],1)
        with self.assertRaises(EmphasisError):state(lambda *a:None,torch.zeros(1,128,1,1),torch.ones(1),torch.zeros(1,2,4),{"cond_or_uncond":[0]})
    def test_negative_unchanged(self):
        state=ForwardState(torch.ones(2,4),[.5,1],1);options={"cond_or_uncond":[1]}
        received=state(lambda x,t,c,o,**k:o,torch.zeros(1,128,1,1),torch.ones(1),torch.zeros(1,7,4),options)
        self.assertNotIn(KEY,received);self.assertEqual(options,{"cond_or_uncond":[1]})
    def test_mixed_attention_matches_manual_math(self):
        reference=torch.ones(2,4);cond=[[reference[None],{}]];p=patch(Patcher(),cond,[.5,1.5],1)
        q,k,v=[torch.randn(2,3,4) for _ in range(3)]
        context=torch.stack([reference,torch.zeros_like(reference)])
        def execute(x,t,c,o):return p.objects['diffusion_model.layers.0.comfy_attention'].function(Container(q.clone()),Container(k.clone()),Container(v.clone()),1,transformer_options=o)
        actual=p.wrapper(execute,torch.zeros(2,128,1,1),torch.ones(2),context,{"cond_or_uncond":[0,1]})
        vv=v.clone();vv[0,1]*=.5;b=torch.zeros(2,1,1,3);b[0,0,0,2]=1
        expected=attention_pytorch(q,k,vv,1,mask=b)
        torch.testing.assert_close(actual,expected,rtol=0,atol=0)
        torch.testing.assert_close(actual[1],attention_pytorch(q[1:2],k[1:2],v[1:2],1)[0])
    def test_missing_batch_labels_rejected(self):
        state=ForwardState(torch.ones(2,4),[.5,1],1)
        with self.assertRaises(EmphasisError):state(lambda *a:None,torch.zeros(1,128,1,1),None,torch.ones(1,2,4),{})
    def test_backend_not_silently_switched(self):
        self.modules['comfy.ldm.modules.attention'].optimized_attention=lambda *a:None
        with self.assertRaisesRegex(EmphasisError,"UNSUPPORTED_ATTENTION_BACKEND"):patch(Patcher(),[[torch.ones(1,2,4),{}]],[.5,1],1)
    def test_configured_kernel_rejected(self):
        p=Patcher();p.diffusion.layers[0].comfy_attention.config={"attention":"comfy_kitchen_int8"}
        with self.assertRaises(EmphasisError):patch(p,[[torch.ones(1,2,4),{}]],[.5,1],1)
    def test_existing_weight_patch_rejected(self):
        p=patch(Patcher(),[[torch.ones(1,2,4),{}]],[.5,1],1)
        with self.assertRaisesRegex(EmphasisError,"DUPLICATE_WEIGHT_ENGINE"):patch(p,[[torch.ones(1,2,4),{}]],[.5,1],1)
    def test_runtime_off_keeps_raw(self):
        p,c=Patcher(),Clip();raw="(big eyes:.5)";out=Runtime().execute(p,c,raw,canonical({}));self.assertIs(out[0],p);self.assertEqual(c.last_text,raw)
    def test_other_families_keep_normal_text_encoding(self):
        for name in ("IllustriousXL", "Anima", "Krea2"):
            with self.subTest(model=name):
                p, c = Patcher(), Clip()
                p.diffusion = type(name, (), {})()
                raw = "portrait, (eyes:0.5), (long hair:1.5)"
                output_model, conditioning = Runtime().execute(p, c, raw, canonical({"enabled": True, "strength": 1.0}))
                self.assertIs(output_model, p)
                self.assertEqual(c.last_text, raw)
                self.assertTrue(conditioning)

    def test_runtime_other_model_keeps_raw(self):
        p,c=Patcher(),Clip();p.diffusion=object();raw="(big eyes:.5)";out=Runtime().execute(p,c,raw,canonical({"enabled":True}));self.assertIs(out[0],p);self.assertEqual(c.last_text,raw)
    def test_runtime_no_weight_no_clone(self):
        p,c=Patcher(),Clip();out=Runtime().execute(p,c,"saber (fate)",canonical({"enabled":True}));self.assertIs(out[0],p)
    def test_runtime_weight_one(self):
        p,c=Patcher(),Clip();out=Runtime().execute(p,c,"(red:1)",canonical({"enabled":True}));self.assertIs(out[0],p);self.assertEqual(c.last_text,"red")
    def test_runtime_weighted_utf8(self):
        p,c=Patcher(),Clip();out=Runtime().execute(p,c,"(赤い髪:.5) 赤い髪",canonical({"enabled":True}));self.assertIsNot(out[0],p);self.assertEqual(c.last_text,"赤い髪 赤い髪");self.assertEqual(sum(v!=1 for v,b in out[0].wrapper.weights),9)
    def test_exception_does_not_modify_options(self):
        state=ForwardState(torch.ones(2,4),[.5,1],1);options={"cond_or_uncond":[0]}
        def fail(*args,**kwargs):raise RuntimeError("cancelled")
        with self.assertRaises(RuntimeError):state(fail,torch.zeros(1,128,1,1),None,torch.ones(1,2,4),options)
        self.assertNotIn(KEY,options)
    def test_slg_module_spoof_rejected(self):
        def untrusted(): pass
        untrusted.__module__ = "comfy_extras.nodes_slg"
        p=Patcher();p.model_options={"sampler_calc_cond_batch_function":untrusted}
        with self.assertRaisesRegex(EmphasisError, "Unsupported guidance patch"):
            patch(p,[[torch.ones(1,2,4),{}]],[.5,1],1)

if __name__=="__main__":unittest.main()
