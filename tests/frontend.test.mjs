import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { VERSION, Controller, normalize, executionSettings, shouldApply, hideRuntime, RUNTIME, RUNTIME_V2, RUNTIME_V3, FORGE, IDS } from "../web/controller.js";

function fixture(raw = {}) {
  const graph = { extra: { moss_emphasis: normalize(raw) }, beforeChange(){}, afterChange(){}, change(){} };
  const store = { values:{}, async set(k,v){this.values[k]=v;} };
  const calls=[];
  const api = { async queuePrompt(...args){ calls.push(args); return "queued"; },
    async fetchApi(_url,opts){ const body=JSON.parse(opts.body); return {ok:true,async json(){return {prompt:{...body.prompt,internal:{}},settings:body.settings,targets:[],warnings:[]};}}; } };
  const app = { rootGraph: graph, extensionManager:{setting:store},async graphToPrompt(){return {output:{n:1},workflow:{extra:structuredClone(graph.extra)}};} };
  const notices=[]; const c = new Controller(app,api,m=>notices.push(m));
  c.installQueue(); return {c,api,app,calls,notices,store};
}

test("off: no prepare request; original arguments preserved",async()=>{
 const {api,calls}=fixture();api.fetchApi=()=>{throw Error("must not call");};const data={output:{a:1},workflow:{}};const options={partialExecutionTargets:["1"]};
 await api.queuePrompt(-1,data,options);assert.equal(calls[0][1],data);assert.equal(calls[0][2],options);assert.equal(calls[0][0],-1);
});
test("strength zero is complete bypass",async()=>{
 const {api,app}=fixture({enabled:true,strength:0});api.fetchApi=()=>{throw Error("must not call");};await api.queuePrompt(0,await app.graphToPrompt());
});
test("enabled queue prepares output without modifying editor workflow",async()=>{
 const {api,app,calls}=fixture({enabled:true});const data=await app.graphToPrompt();const old=structuredClone(data);await api.queuePrompt(0,data);
 assert.deepEqual(data,old);assert.ok(calls[0][1].output.internal);assert.deepEqual(calls[0][1].workflow,data.workflow);
});
test("prepare failure never calls original queue",async()=>{
 const {api,app,calls,notices}=fixture({enabled:true});api.fetchApi=async()=>({ok:false,json:async()=>({error:{code:"BROKEN",message:"unsupported"}})});
 await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/BROKEN/);assert.equal(calls.length,0);assert.equal(notices.length,1);
});
test("network failure never queues",async()=>{
 const {api,app,calls}=fixture({enabled:true});api.fetchApi=async()=>{throw Error("offline");};await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()));assert.equal(calls.length,0);
});
test("queued snapshot survives changing active tab",async()=>{
 const {c,api,app,calls}=fixture({enabled:true,strength:.5});const old=await app.graphToPrompt();app.rootGraph={extra:{moss_emphasis:normalize({enabled:true,strength:1.5})}};
 await api.queuePrompt(0,old);assert.equal(calls[0][1].workflow.extra.moss_emphasis.strength,.5);
});
test("settings are workflow scoped",async()=>{
 const {c,app}=fixture();await c.restore();c.change("strength",.75);c.change("enabled",true);assert.equal(app.rootGraph.extra.moss_emphasis.strength,.75);assert.equal(app.rootGraph.extra.moss_emphasis.enabled,true);
});
test("restore suppresses onChange side effects",async()=>{
 const {c,app,store}=fixture({enabled:true});const original=structuredClone(app.rootGraph.extra);store.set=async function(k,v){c.change(k===IDS.enabled?"enabled":"strength",v);};await c.restore();assert.deepEqual(app.rootGraph.extra,original);
});
test("new workflow defaults OFF even if previous UI was ON",async()=>{
 const {c,app,store}=fixture({enabled:true});await c.restore();app.rootGraph={extra:{}};await c.restore();assert.equal(store.values[IDS.enabled],false);
});
test("hide internal node in both node definition forms",()=>{
 const dict={[RUNTIME]:{},Other:{}};hideRuntime(dict);assert.deepEqual(Object.keys(dict),["Other"]);const list=[{name:RUNTIME},{name:"Other"}];hideRuntime(list);assert.equal(list.length,1);
});
test("invalid settings fail validation",()=>{
 for(const value of [{enabled:1},{strength:NaN},{strength:-1},{version:"wrong"}])assert.throws(()=>normalize(value));
});
test("API export contains prepared prompt and original workflow",async()=>{
 const {c}=fixture({enabled:true});const result=await c.exportApi();assert.ok(result.prompt.internal);assert.equal(result.extra_data.extra_pnginfo.workflow.extra.moss_emphasis.enabled,true);
});
test("queue installed only once",()=>{const {c,api}=fixture();const fn=api.queuePrompt;c.installQueue();assert.equal(fn,api.queuePrompt);});
test("server cannot change the settings snapshot",async()=>{
 const {api,app,calls}=fixture({enabled:true});api.fetchApi=async()=>({ok:true,json:async()=>({prompt:{},targets:[],settings:normalize({enabled:true,strength:2})})});await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/mismatch/);assert.equal(calls.length,0);
});

test("in-flight workflow metadata is frozen at submission",async()=>{
 const {api,app,calls}=fixture({enabled:true,strength:.5});const data=await app.graphToPrompt();let release;
 api.fetchApi=async(_url,options)=>{const body=JSON.parse(options.body);await new Promise(r=>release=r);return {ok:true,json:async()=>({prompt:body.prompt,settings:body.settings,targets:[]})};};
 const pending=api.queuePrompt(0,data);data.workflow.extra.moss_emphasis.strength=3;release();await pending;
 assert.equal(calls[0][1].workflow.extra.moss_emphasis.strength,.5);
});

test("saved 0.9.0 workflow settings migrate without dropping enabled state", () => {
 const old = normalize({ version:"0.9.0", enabled:true, strength:1.3 });
 assert.equal(old.version,VERSION);assert.equal(old.enabled,true);assert.equal(old.strength,1.3);
});

test("version upgrade preserves old NegPiP mode and auto scope",()=>{
 for(const version of ["0.9.1","0.10.0","0.10.1"]) for(const [schema,engine] of [[2,"kj_dit_v1"],[2,"ppm_negpip_moss_v1"],[3,"native_auto_v1"],[3,"negpip_auto_v1"]]){
   const old={version,schema_version:schema,engine,enabled:true,strength:.7,negpip_strength:.4};
   const value=normalize(old);assert.equal(value.version,VERSION);
   for(const key of ["schema_version","engine","enabled","strength","negpip_strength"])assert.equal(value[key],old[key]);
 }
});
test("older running backend version rejection gives restart instructions",async()=>{
 const {api,app,calls}=fixture({schema_version:3,engine:"negpip_auto_v1",enabled:true});
 api.fetchApi=async()=>({ok:false,json:async()=>({error:{code:"INVALID_SETTINGS",message:`Unsupported version: '${VERSION}'.`}})});
 await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/BACKEND_RESTART_REQUIRED/);assert.equal(calls.length,0);
});

test("NegPiP selected strength controls preparation and full bypass",async()=>{
 const {api,app,calls}=fixture({schema_version:2,engine:"ppm_negpip_moss_v1",enabled:true,strength:0});
 await api.queuePrompt(0,await app.graphToPrompt());assert.ok(calls[0][1].output.internal);
 app.rootGraph.extra.moss_emphasis.negpip_strength=0;
 api.fetchApi=()=>{throw Error("must bypass");};await api.queuePrompt(0,await app.graphToPrompt());
});
test("engine toggle retains both strengths",async()=>{
 const {c,app,store}=fixture({enabled:true,strength:0.7});await c.restore();
 c.change("negpip",true);c.change("negpip_strength",0.45);c.change("negpip",false);c.change("negpip",true);
 const value=app.rootGraph.extra.moss_emphasis;
 assert.equal(value.engine,"negpip_auto_v1");assert.equal(value.schema_version,3);assert.equal(value.strength,.7);assert.equal(value.negpip_strength,.45);
 await c.restore();assert.equal(store.values[IDS.negpip],true);
});

test("legacy restore does not upgrade; only an explicit weighting change does",async()=>{
 const {c,app}=fixture({schema_version:2,engine:"ppm_negpip_moss_v1",enabled:true,strength:.6,negpip_strength:.4});
 const original=structuredClone(app.rootGraph.extra);await c.restore();assert.deepEqual(app.rootGraph.extra,original);
 c.change("diagnostic",true);assert.equal(app.rootGraph.extra.moss_emphasis.schema_version,2);
 c.change("enabled",false);const value=app.rootGraph.extra.moss_emphasis;
 assert.equal(value.schema_version,3);assert.equal(value.engine,"negpip_auto_v1");assert.equal(value.strength,.6);assert.equal(value.negpip_strength,.4);
});
test("new workflow uses auto model mode OFF and hides both runtimes",()=>{
 assert.equal(normalize().schema_version,3);assert.equal(normalize().enabled,false);
 const defs={[RUNTIME]:{},[RUNTIME_V2]:{},Other:{}};hideRuntime(defs);assert.deepEqual(Object.keys(defs),["Other"]);
});
test("auto mode API export round trips without selecting a concrete model",async()=>{
 const {c}=fixture({schema_version:3,engine:"negpip_auto_v1",enabled:true,strength:0,negpip_strength:.5});
 await c.restore();const result=await c.exportApi();const value=result.extra_data.extra_pnginfo.workflow.extra.moss_emphasis;
 assert.equal(value.schema_version,3);assert.equal(value.engine,"negpip_auto_v1");assert.equal(value.negpip_strength,.5);
});
test("schema3 sent to schema2 backend requires restart, without downgrade",async()=>{
 const {api,app,calls}=fixture({schema_version:3,engine:"native_auto_v1",enabled:true});
 api.fetchApi=async()=>({ok:false,json:async()=>({error:{code:"INVALID_SETTINGS",message:"Unsupported schema or engine."}})});
 await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/BACKEND_RESTART_REQUIRED/);assert.equal(calls.length,0);
});
test("invalid raw workflow is preserved and blocks queue until explicit recovery",async()=>{
 const {c,app,api,calls}=fixture();const invalid={schema_version:999,enabled:true};app.rootGraph.extra.moss_emphasis=invalid;
 await c.restore();assert.equal(c.ready,false);assert.equal(app.rootGraph.extra.moss_emphasis,invalid);
 await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()));assert.equal(calls.length,0);
 await c.resetSettings();assert.equal(c.ready,true);assert.equal(app.rootGraph.extra.moss_emphasis.enabled,false);
});
test("unknown/null fields reject consistently with Python settings",()=>{
 for(const value of [{schema_version:null},{engine:null},{enabled:null},{strength:null},{negpip_strength:null},{engine_version:2},{negpip_strength:1.1}])
   assert.throws(()=>normalize(value));
});
test("restores serialize writes across workflow switches",async()=>{
 const {c,app,store}=fixture({enabled:true});let release;const original=store.set.bind(store);let first=true;
 store.set=async(k,v)=>{if(first){first=false;await new Promise(r=>release=r);}await original(k,v);};
 const a=c.restore();await Promise.resolve();app.rootGraph={extra:{moss_emphasis:normalize({schema_version:2,engine:"ppm_negpip_moss_v1",enabled:true,negpip_strength:.25})}};
 const b=c.restore();release();await Promise.all([a,b]);
 assert.equal(store.values[IDS.negpip],true);assert.equal(store.values[IDS.negpip_strength],.25);assert.equal(c.ready,true);
});
test("NegPiP API export restores an identical settings snapshot",async()=>{
 const {c,app}=fixture({schema_version:2,engine:"ppm_negpip_moss_v1",enabled:true,negpip_strength:.75});
 const saved=await c.exportApi();assert.deepEqual(saved.extra_data.extra_pnginfo.workflow.extra.moss_emphasis,app.rootGraph.extra.moss_emphasis);
});

test("Settings write failure blocks queue and API export even when weighting is OFF",async()=>{
 for (const enabled of [false,true]) {
  const {c,app,api,calls,store}=fixture({enabled});const saved=structuredClone(app.rootGraph.extra);
  store.set=async()=>{throw Error("Settings write failed");};
  await assert.rejects(c.restore(),/Settings write failed/);
  assert.equal(c.ready,false);assert.ok(c.restoreError);
  await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/restoration failed/);
  await assert.rejects(c.exportApi(),/restoration failed/);
  assert.equal(calls.length,0);assert.deepEqual(app.rootGraph.extra,saved);
 }
});
test("missing Settings API blocks admission and successful retry recovers",async()=>{
 const {c,app,api,calls,store}=fixture({enabled:true});app.extensionManager.setting={};
 await assert.rejects(c.restore(),/Settings API/);
 await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/restoration failed/);
 app.extensionManager.setting=store;await c.restore();assert.equal(c.restoreError,null);
 await api.queuePrompt(0,await app.graphToPrompt());assert.equal(calls.length,1);
});
test("partial restore failure blocks until explicit reset succeeds",async()=>{
 const {c,app,api,calls,store}=fixture({enabled:true});const set=store.set.bind(store);let writes=0;
 store.set=async(k,v)=>{if(++writes===3)throw Error("third write failed");await set(k,v);};
 await assert.rejects(c.restore(),/third write/);
 await assert.rejects(c.exportApi(),/restoration failed/);
 store.set=set;await c.resetSettings();assert.equal(app.rootGraph.extra.moss_emphasis.enabled,false);
 await api.queuePrompt(0,await app.graphToPrompt());assert.equal(calls.length,1);
});
test("pending restore rejects admission without retaining the queued request",async()=>{
 const {c,app,api,calls,store}=fixture({enabled:true});let release;const set=store.set.bind(store);let first=true;
 store.set=async(k,v)=>{if(first){first=false;await new Promise(r=>release=r);}await set(k,v);};
 const restoring=c.restore();await Promise.resolve();
 await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/still restoring/);assert.equal(calls.length,0);
 release();await restoring;assert.equal(calls.length,0);
 await api.queuePrompt(0,await app.graphToPrompt());assert.equal(calls.length,1);
});
test("late failure in an old tab does not poison the restored current tab",async()=>{
 const {c,app,api,calls,store}=fixture({enabled:true});const set=store.set.bind(store);let rejectOld;let first=true;
 store.set=async(k,v)=>{if(first){first=false;await new Promise((_,reject)=>rejectOld=reject);}await set(k,v);};
 const oldGraph=app.rootGraph;const old=c.restore();await Promise.resolve();
 app.rootGraph={extra:{moss_emphasis:normalize({enabled:false})}};const current=c.restore();
 rejectOld(Error("old tab failed"));await assert.rejects(old,/old tab/);await current;
 assert.equal(c.ready,true);assert.equal(c.restoreError,null);
 await api.queuePrompt(0,await app.graphToPrompt());assert.equal(calls.length,1);
 app.rootGraph=oldGraph;await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/restoration failed/);
});
test("already admitted submission keeps its snapshot when a later tab restore fails",async()=>{
 const {c,app,api,calls,store}=fixture({enabled:true});await c.restore();let release;
 api.fetchApi=async(_url,options)=>{const body=JSON.parse(options.body);await new Promise(r=>release=r);return {ok:true,json:async()=>({prompt:body.prompt,settings:body.settings,targets:[]})};};
 const pending=api.queuePrompt(0,await app.graphToPrompt());
 app.rootGraph={extra:{moss_emphasis:normalize({enabled:false})}};store.set=async()=>{throw Error("new tab failed");};
 await assert.rejects(c.restore(),/new tab/);release();await pending;
 assert.equal(calls.length,1);assert.equal(calls[0][1].workflow.extra.moss_emphasis.enabled,true);
});

test("native Settings sort keeps each enable control before its strength",()=>{
 let extension;
 const app={registerExtension(value){extension=value;}};
 const source=readFileSync(new URL('../web/moss_emphasis.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
 new Function('app','api','Controller','IDS','hideRuntime','normalize',source)(app,{},Controller,IDS,hideRuntime,normalize);
 // Installed SettingDialog sorts descending by sortOrder after flattenTree.
 const general=extension.settings.filter(s=>s.category[1]==='General').reverse().sort((a,b)=>(b.sortOrder??0)-(a.sortOrder??0));
 assert.deepEqual(general.map(s=>s.id),[IDS.enabled,IDS.strength,IDS.negpip,IDS.negpip_implementation,IDS.negpip_strength,IDS.v_scaling_enabled,IDS.v_scaling_strength,IDS.status]);
 assert.equal(extension.settings.find(s=>s.id===IDS.enabled).defaultValue,false);
 assert.equal(extension.settings.find(s=>s.id===IDS.negpip).defaultValue,false);
});
test("old Python schema rejection explains restart in the UI locale and never queues",async()=>{
 for(const locale of ['en','ja']) for(const [schema,engine] of [[2,'ppm_negpip_moss_v1'],[3,'native_auto_v1'],[3,'negpip_auto_v1']]) {
  const {api,c,app,store,calls}=fixture({enabled:true,schema_version:schema,engine});store.get=()=>locale;
  const original=structuredClone(app.rootGraph.extra);
  api.fetchApi=async()=>({ok:false,json:async()=>({error:{code:'INVALID_SETTINGS',message:`Unsupported schema_version: ${schema}.`}})});
  await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),locale==='ja'?/ComfyUI本体を再起動/:/Restart ComfyUI itself/);
  await assert.rejects(c.exportApi(),/BACKEND_RESTART_REQUIRED/);assert.equal(calls.length,0);
  assert.deepEqual(app.rootGraph.extra,original);
 }
});

test("unrelated invalid settings are not classified as backend restart",async()=>{
 for(const [code,message] of [['INVALID_SETTINGS','Unsupported schema_version: 4.'],['INVALID_SETTINGS','Unsupported schema_version: 2.'],['INVALID_SETTINGS','Invalid strength.'],['OTHER','Unsupported schema_version: 3.']]) {
  const {api,app,calls}=fixture({enabled:true,schema_version:3,engine:'negpip_auto_v1'});
  api.fetchApi=async()=>({ok:false,json:async()=>({error:{code,message}})});
  await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),error=>error.message===`[${code}] ${message}`);
  assert.equal(calls.length,0);
 }
});

const forge = extra => ({schema_version:4,engine:FORGE,enabled:true,...extra});

test("local 0.10.1 Forge workflow preserves mode, scale and inactive strengths",()=>{
 const old=forge({version:'0.10.1',strength:0,negpip_strength:.3,v_scaling_enabled:true,v_scaling_strength:1.5});
 const value=normalize(old);assert.equal(value.version,VERSION);
 for(const key of ['engine','schema_version','enabled','strength','negpip_strength','v_scaling_enabled','v_scaling_strength']) assert.equal(value[key],old[key]);
});

test("Forge old strengths zero and V OFF/zero still prepare basic NegPiP",async()=>{
 for(const config of [forge({strength:0,negpip_strength:0}),forge({v_scaling_enabled:true,v_scaling_strength:0})]) {
  const {api,app,calls}=fixture(config);
  await api.queuePrompt(0,await app.graphToPrompt());assert.ok(calls[0][1].output.internal);
  assert.equal(shouldApply(normalize(config)),true);
 }
});
test("Forge execution omits inactive preferences and normalizes OFF and ON+0",()=>{
 const a=executionSettings(forge({strength:0,negpip_strength:0,v_scaling_strength:2}));
 const b=executionSettings(forge({strength:4,negpip_strength:1,v_scaling_enabled:true,v_scaling_strength:0}));
 assert.deepEqual(a,b);assert.equal(a.v_scaling_strength,0);assert.equal(a.strength,1);
 assert.equal(Object.hasOwn(a,'diagnostic'),false);assert.equal(Object.hasOwn(a,'negpip_implementation'),false);
 const old=executionSettings({schema_version:2,engine:'ppm_negpip_moss_v1',enabled:true,v_scaling_enabled:true,v_scaling_strength:2});
 assert.equal(Object.hasOwn(old,'v_scaling_strength'),false);assert.equal(old.schema_version,2);
});
test("Forge mode and all saved strengths survive switch, restore and API export",async()=>{
 const {c,app,store}=fixture({schema_version:2,engine:'ppm_negpip_moss_v1',enabled:true,strength:.7,negpip_strength:.3});
 await c.restore();c.change('negpip_implementation','Forge compatible');c.change('v_scaling_enabled',true);c.change('v_scaling_strength',1.5);
 assert.equal(app.rootGraph.extra.moss_emphasis.engine,FORGE);
 c.change('negpip',false);assert.equal(app.rootGraph.extra.moss_emphasis.engine,'native_auto_v1');
 c.change('negpip',true);assert.equal(app.rootGraph.extra.moss_emphasis.engine,FORGE);
 c.change('negpip_implementation','PPM reference');assert.equal(app.rootGraph.extra.moss_emphasis.schema_version,3);
 c.change('negpip_implementation','Forge compatible');await c.restore();
 assert.equal(store.values[IDS.v_scaling_strength],1.5);assert.equal(store.values[IDS.negpip_implementation],'Forge compatible');
 const result=await c.exportApi();const config=result.extra_data.extra_pnginfo.workflow.extra.moss_emphasis;
 assert.equal(config.strength,.7);assert.equal(config.negpip_strength,.3);assert.equal(config.v_scaling_enabled,true);
 assert.equal(config.v_scaling_strength,1.5);assert.equal(config.engine,FORGE);
});
test("inactive Forge preferences do not migrate a legacy ordinary engine",async()=>{
 const {c,app}=fixture({schema_version:2,engine:'kj_dit_v1',enabled:true});await c.restore();
 const before=executionSettings(app.rootGraph.extra.moss_emphasis);
 c.change('negpip_implementation','Forge compatible');c.change('v_scaling_strength',2);
 assert.deepEqual(executionSettings(app.rootGraph.extra.moss_emphasis),before);
 c.change('negpip',true);assert.equal(app.rootGraph.extra.moss_emphasis.engine,FORGE);
});
test("schema4 old backend requires localized restart without downgrade",async()=>{
 for(const locale of ['ja','en']) {
  const {api,c,app,store,calls}=fixture(forge({}));store.get=()=>locale;await c.restore();
  const before=structuredClone(app.rootGraph.extra);
  api.fetchApi=async()=>({ok:false,json:async()=>({error:{code:'INVALID_SETTINGS',message:'Unsupported schema or engine.'}})});
  await assert.rejects(c.exportApi(),locale==='ja'?/ComfyUI本体を再起動/:/Restart ComfyUI itself/);
  assert.equal(calls.length,0);assert.deepEqual(app.rootGraph.extra,before);
 }
});
test("backend cannot change the Forge effective scale",async()=>{
 const {api,app,calls}=fixture(forge({v_scaling_enabled:true,v_scaling_strength:.5}));
 api.fetchApi=async(_url,options)=>{const body=JSON.parse(options.body);return {ok:true,json:async()=>({prompt:body.prompt,targets:[],settings:{...body.settings,v_scaling_strength:1}})};};
 await assert.rejects(api.queuePrompt(0,await app.graphToPrompt()),/mismatch/);assert.equal(calls.length,0);
});
test("Forge submission freezes effective scale and editor preferences across tabs",async()=>{
 const {api,app,calls}=fixture(forge({v_scaling_enabled:true,v_scaling_strength:.5,strength:.8}));
 const data=await app.graphToPrompt();let release;
 api.fetchApi=async(_url,options)=>{const body=JSON.parse(options.body);await new Promise(r=>release=r);return {ok:true,json:async()=>({prompt:body.prompt,settings:body.settings,targets:[]})};};
 const pending=api.queuePrompt(0,data);data.workflow.extra.moss_emphasis.v_scaling_strength=2;
 app.rootGraph={extra:{moss_emphasis:normalize()}};release();await pending;
 assert.equal(calls[0][1].workflow.extra.moss_emphasis.v_scaling_strength,.5);
 assert.equal(calls[0][1].workflow.extra.moss_emphasis.strength,.8);
});
test("new preferences validate types and hide the third runtime",()=>{
 for(const extra of [{v_scaling_enabled:1},{v_scaling_strength:NaN},{v_scaling_strength:2.1},{negpip_implementation:null},{negpip_implementation:'other'}])
  assert.throws(()=>normalize(forge(extra)));
 const dict={[RUNTIME_V3]:{},Other:{}};hideRuntime(dict);assert.deepEqual(Object.keys(dict),['Other']);
 const list=[{name:RUNTIME_V3},{name:'Other'}];hideRuntime(list);assert.equal(list.length,1);
});
