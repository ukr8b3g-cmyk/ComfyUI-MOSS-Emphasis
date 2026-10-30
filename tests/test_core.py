import copy
import json
import math
import unittest
from moss_emphasis.config import EmphasisError, RUNTIME, settings, canonical, coefficients
from moss_emphasis.parser import parse
from moss_emphasis.graph import prepare
from moss_emphasis.tokens import PREFIX, SUFFIX, align, byte_decoder, normalize

ON = {"enabled": True, "strength": 1.0}

def graph(kind="KSampler"):
    return {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "moss.safetensors"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"type": "moss_image"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "a (red hat:0.5)"}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "bad anatomy"}},
            "5": {"class_type": kind, "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "seed": 12}}}

class SettingsTests(unittest.TestCase):
    def test_defaults(self): self.assertFalse(settings({})["enabled"])
    def test_range(self):
        for v in [-1, 4.1, True, "1", math.inf, math.nan]:
            with self.subTest(v=v), self.assertRaises(EmphasisError): settings({"strength": v})
    def test_legacy_version_migrates(self):
        self.assertEqual(settings({"version": "0.9.0", "enabled": True})["version"], "0.10.0")
        self.assertEqual(settings({"version": "0.9.1", "enabled": True})["version"], "0.10.0")

    def test_prior_auto_and_negpip_settings_keep_scope_on_version_upgrade(self):
        for schema, engine in ((2, "ppm_negpip_moss_v1"), (3, "negpip_auto_v1")):
            old = {"version": "0.9.1", "schema_version": schema, "engine": engine,
                   "enabled": True, "strength": .7, "negpip_strength": .4}
            migrated = settings(old)
            self.assertEqual(migrated["version"], "0.10.0")
            for key in ("schema_version", "engine", "enabled", "strength", "negpip_strength"):
                self.assertEqual(migrated[key], old[key])

    def test_version(self):
        for v in [{"version": "other"}, {"engine": "log"}, {"schema_version": 3}, {"enabled": 1}]:
            with self.subTest(v=v), self.assertRaises(EmphasisError): settings(v)
    def test_diagnostic_does_not_invalidate(self): self.assertEqual(canonical(ON), canonical({**ON, "diagnostic": True}))
    def test_strength_invalidates(self): self.assertNotEqual(canonical(ON), canonical({**ON, "strength": .5}))
    def test_equations(self):
        for s, scale in [(.5,.75),(1,.5),(1.5,.25),(2,0)]: self.assertEqual(coefficients(.5,s), (scale,0))
        self.assertEqual(coefficients(1.5,1), (1,1))
        self.assertEqual(coefficients(-1,1), (-1,0))

class ParserTests(unittest.TestCase):
    def test_plain_preserved(self):
        for s in ["saber (fate)","hello :) ","A (B) C", "は\u3099",r"\(12:30\)"]:
            with self.subTest(s=s): self.assertEqual(parse(s).text,s)
    def test_basic(self):
        p=parse("a (big eyes:0.5), long hair"); self.assertEqual(p.text,"a big eyes, long hair")
        self.assertEqual(p.weights[2:5],(.5,.5,.5)); self.assertEqual(p.groups,1)
    def test_repeated(self):
        p=parse("(red:0.5) red"); self.assertEqual(p.weights, (.5,.5,.5,1,1,1,1))
    def test_character_parentheses(self): self.assertEqual(parse("(saber (fate):1.2)").text,"saber (fate)")
    def test_nested(self):
        p=parse("((red:1.2):1.1)"); self.assertAlmostEqual(p.weights[0],1.32)
    def test_one_cleans(self):
        p=parse("(red:1)"); self.assertEqual(p.text,"red"); self.assertEqual(p.weights,(1,1,1))
    def test_negative_zero(self):
        self.assertEqual(parse("(x:-1)").weights,(-1,)); self.assertEqual(parse("(x:0)").weights,(0,))
    def test_escape(self): self.assertEqual(parse(r"(saber \(fate\):1.2)").text,"saber (fate)")
    def test_invalid(self):
        for s in ["(x:NaN)","(x:Infinity)","(x:1e2)","(:1)","(x:abc)","(x:.0.5)"]:
            with self.subTest(s=s), self.assertRaises(EmphasisError): parse(s)
    def test_finite_weights_have_no_numeric_bounds(self):
        for value in (-1000000, -10, -5, -2, -.5, 0, 4, 5, 10, 1000000):
            with self.subTest(value=value):
                self.assertEqual(parse(f"(x:{value})").weights, (value,))
        self.assertEqual(parse("((x:-5):3)").weights, (-15,))
        self.assertEqual(parse("((x:5):3)").weights, (15,))
    def test_nonfinite_and_nested_overflow_still_rejected(self):
        for text in (f"(x:{'9'*400})", f"((x:{'9'*200}):{'9'*200})"):
            with self.subTest(text_length=len(text)), self.assertRaisesRegex(EmphasisError, "finite"):
                parse(text)
    def test_unbounded_layout_caption_weights_preserve_other_fields(self):
        data={"summary":{"caption":"(x:-5)"},"items":[{"caption":"(y:10)","text":"(z:-99)","bbox":[0,0,10,20]}]}
        parsed=parse(json.dumps(data)); actual=json.loads(parsed.text)
        self.assertEqual(actual["summary"]["caption"],"x")
        self.assertEqual(actual["items"][0]["caption"],"y")
        self.assertEqual(actual["items"][0]["text"],data["items"][0]["text"])
        self.assertEqual(actual["items"][0]["bbox"],data["items"][0]["bbox"])
        self.assertIn(-5,parsed.weights); self.assertIn(10,parsed.weights)
    def test_unclosed_weight(self):
        with self.assertRaises(EmphasisError): parse("(red:1.5")
    def test_nonweight_json_like_prose(self):
        for text in ["{broken", '{"hello":1}', "hello (fate)"]:
            self.assertEqual(parse(text).text,text)
    def test_limits(self):
        for s in ["("*17+"x:1.2"+")"*17, "(x:1)"*129, "x"*262145]:
            with self.subTest(n=len(s)), self.assertRaises(EmphasisError): parse(s)
    def test_json_protection(self):
        data={"summary":{"caption":"(soft light:1.2)"},"items":[{"caption":"(big eyes:0.5)","text":"(12:30)","bbox":[-10,0,20,30],"tags":["(red:2)"]}]}
        p=parse(json.dumps(data,indent=2)); actual=json.loads(p.text)
        self.assertEqual(actual["items"][0]["text"],"(12:30)"); self.assertEqual(actual["items"][0]["bbox"],data["items"][0]["bbox"])
        self.assertEqual(actual["items"][0]["tags"],data["items"][0]["tags"]); self.assertEqual(p.groups,2)
        start=p.text.index("12:30"); self.assertTrue(all(w==1 for w in p.weights[start:start+5]))
    def test_json_no_reformat(self):
        s=' { "summary": {"caption":"plain"}, "items": [] }\n'; self.assertEqual(parse(s).text,s)
    def test_json_escapes(self):
        p=parse(json.dumps({"summary":{"caption":"(赤い髪:1.5)\n\"soft\""},"items":[]})); self.assertEqual(json.loads(p.text)["summary"]["caption"],'赤い髪\n"soft"')
    def test_json_invalid(self):
        for s in ['{"summary":"(x:2)"', '{"summary":{},"summary":{"caption":"(x:2)"},"items":[]}', '({"summary":{},"items":[]}:2)']:
            with self.subTest(s=s), self.assertRaises(EmphasisError): parse(s)

class GraphTests(unittest.TestCase):
    def test_off(self): self.assertEqual(prepare(graph(),{})["prompt"],graph())
    def test_zero(self): self.assertEqual(prepare(graph(),{**ON,"strength":0})["prompt"],graph())
    def test_input_unchanged(self):
        g=graph(); old=copy.deepcopy(g); prepare(g,ON); self.assertEqual(g,old)
    def test_sampler_paths(self):
        for kind in ["KSampler","KSamplerAdvanced","CFGGuider"]:
            with self.subTest(kind=kind):
                r=prepare(graph(kind),ON); self.assertEqual(len(r["targets"]),1); self.assertEqual(r["prompt"]["5"]["inputs"]["negative"],["4",0])
    def test_string_link(self):
        g=graph();g["6"]={"class_type":"TextMultiline","inputs":{"text":"x"}};g["3"]["inputs"]["text"]=["6",0]
        r=prepare(g,ON); n=r["targets"][0]["runtime"];self.assertEqual(r["prompt"][n]["inputs"]["text"],["6",0])
    def test_shared_negative(self):
        g=graph();g["5"]["inputs"]["negative"]=["3",0];r=prepare(g,ON); self.assertEqual(r["prompt"]["5"]["inputs"]["negative"],["3",0])
    def test_multiple(self):
        g=graph();g["7"]=copy.deepcopy(g["5"]);r=prepare(g,ON);self.assertEqual(len(r["targets"]),2);self.assertNotEqual(r["targets"][0]["runtime"],r["targets"][1]["runtime"])
    def test_idempotent(self):
        r=prepare(graph(),ON);self.assertEqual(prepare(r["prompt"],ON),r)
    def test_reconfigure(self):
        r=prepare(graph(),ON); new=prepare(r["prompt"],{**ON,"strength":.5});self.assertEqual(new,prepare(graph(),{**ON,"strength":.5}))
    def test_restore_off(self): self.assertEqual(prepare(prepare(graph(),ON)["prompt"],{})["prompt"],graph())
    def test_collision(self):
        r=prepare(graph(),ON);g=graph();key=r["targets"][0]["runtime"];g[key]={"class_type":"Text","inputs":{}}
        with self.assertRaises(EmphasisError):prepare(g,ON)
    def test_duplicate(self):
        for kind in ["MossImagePromptWeight","MOSSImagePromptWeight"]:
            g=graph();g["3"]["class_type"]=kind
            with self.subTest(kind=kind),self.assertRaisesRegex(EmphasisError,"DUPLICATE_WEIGHT_ENGINE"):prepare(g,ON)
    def test_unsupported(self):
        for kind in ["ConditioningConcat","ConditioningAverage","TextEncodeMOSSImageEdit"]:
            g=graph();g["3"]["class_type"]=kind
            with self.subTest(kind=kind),self.assertRaises(EmphasisError):prepare(g,ON)
    def test_cycle(self):
        g=graph();g["1"]["inputs"]["model"]=["5",0]
        with self.assertRaisesRegex(EmphasisError,"CYCLIC_GRAPH"):prepare(g,ON)
    def test_missing(self):
        g=graph();del g["2"]
        with self.assertRaises(EmphasisError):prepare(g,ON)
    def test_slg_preserved(self):
        g=graph();g["6"]={"class_type":"SkipLayerGuidanceDiTSimple","inputs":{"model":["1",0],"single_layers":"22"}};g["5"]["inputs"]["model"]=["6",0]
        r=prepare(g,ON);self.assertEqual(r["prompt"]["6"],g["6"])
    def test_diagnostic_cache(self):self.assertEqual(prepare(graph(),ON),prepare(graph(),{**ON,"diagnostic":True}))
    def test_malformed_restored(self):
        r=prepare(graph(),ON)["prompt"];r["3"]["inputs"]["text"]="changed"
        with self.assertRaisesRegex(EmphasisError,"PREPARED_GRAPH_CHANGED"):prepare(r,ON)
    def test_unknown_sampler_rejected(self):
        g=graph();g["7"]={"class_type":"CustomUnknownSampler","inputs":{"positive":["3",0],"model":["1",0]}}
        with self.assertRaises(EmphasisError):prepare(g,ON)
    def test_custom_advanced_guider(self):
        g=graph("CFGGuider");g["7"]={"class_type":"SamplerCustomAdvanced","inputs":{"guider":["5",0]}}
        self.assertEqual(len(prepare(g,ON)["targets"]),1)
    def test_no_target(self):
        with self.assertRaisesRegex(EmphasisError,"NO_SUPPORTED_SAMPLER"):prepare({},ON)

class TokenTests(unittest.TestCase):
    def pieces(self,text):
        enc={b:c for c,b in byte_decoder().items()}; result=[];i=0
        specials={"<|im_start|>","<|im_end|>"}
        while i<len(text):
            special=next((s for s in specials if text.startswith(s,i)),None)
            if special: result.append(special);i+=len(special)
            else:
                result.extend(enc[b] for b in text[i].encode());i+=1
        return result,specials
    def test_utf8_bytes(self):
        p=parse("(赤い髪:1.5) 赤い髪");pieces,special=self.pieces(PREFIX+p.text+SUFFIX);w=align(p,list(range(len(pieces))),pieces,special)
        self.assertEqual(sum(x==1.5 for x in w),9)
    def test_boundary_average(self):
        p=parse("(red:0)blue");pieces,special=self.pieces(PREFIX+p.text+SUFFIX)
        i=len(self.pieces(PREFIX)[0]);pieces[i:i+7]=["redblue"]
        w=align(p,list(range(len(pieces))),pieces,special);self.assertAlmostEqual(w[i],4/7)
    def test_template_specials_unweighted(self):
        p=parse("(x:2)");ps,sp=self.pieces(PREFIX+p.text+SUFFIX);w=align(p,list(range(len(ps))),ps,sp)
        self.assertTrue(all(v==1 for v,s in zip(w,ps) if s in sp))
    def test_trim(self):
        p=parse("  (x:2) \n");ps,sp=self.pieces(PREFIX+"x"+SUFFIX);self.assertIn(2,align(p,list(range(len(ps))),ps,sp))
    def test_truncation(self):
        p=parse("(x:2)");ps,sp=self.pieces(PREFIX+p.text+SUFFIX)
        with self.assertRaisesRegex(EmphasisError,"WEIGHTED_SPAN_TRUNCATED"):align(p,list(range(len(ps)-3)),ps[:-3],sp)
    def test_mismatch(self):
        p=parse("(x:2)");ps,sp=self.pieces(PREFIX+"y"+SUFFIX)
        with self.assertRaisesRegex(EmphasisError,"TOKEN_ALIGNMENT_FAILED"):align(p,list(range(len(ps))),ps,sp)
    def test_nfc(self):self.assertEqual(normalize(parse("(は\u3099:2)"))[0],"ば")

if __name__ == "__main__":unittest.main()
