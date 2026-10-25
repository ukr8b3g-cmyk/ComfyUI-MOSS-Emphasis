import test from "node:test";
import assert from "node:assert/strict";
import { Controller, normalize, hideRuntime, RUNTIME, IDS } from "../web/controller.js";

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
 assert.equal(old.version,"0.9.1");assert.equal(old.enabled,true);assert.equal(old.strength,1.3);
});

test("an obsolete Settings restore cannot overwrite the active workflow", async () => {
  const { c, app, store } = fixture({ enabled: true, strength: 1 });
  const write = store.set.bind(store);
  let started, resume;
  const firstWriteStarted = new Promise(resolve => { started = resolve; });
  const firstWriteGate = new Promise(resolve => { resume = resolve; });
  let delayed = false;
  store.set = async (id, value) => {
    if (!delayed && id === IDS.enabled && value === true) {
      delayed = true;
      started();
      await firstWriteGate;
    }
    return write(id, value);
  };

  const earlier = c.restore();
  await firstWriteStarted;
  app.rootGraph = { extra: { moss_emphasis: normalize({ enabled: false, strength: 2 }) } };
  const later = c.restore();
  assert.equal(c.ready, false);
  resume();
  await Promise.all([earlier, later]);

  assert.equal(store.values[IDS.enabled], false);
  assert.equal(store.values[IDS.strength], 2);
  assert.equal(store.values[IDS.diagnostic], false);
  assert.equal(c.ready, true);
});

test("failed Settings restore leaves controller read-only until a successful retry", async () => {
  const { c, app, store } = fixture({ enabled: true, strength: 1.5 });
  const write = store.set.bind(store);
  store.set = async (id, value) => {
    if (id === IDS.strength) throw new Error("Settings write failed");
    return write(id, value);
  };

  await assert.rejects(c.restore(), /Settings write failed/);
  assert.equal(c.ready, false);
  c.change("enabled", false);
  assert.equal(app.rootGraph.extra.moss_emphasis.enabled, true);

  store.set = write;
  await c.restore();
  assert.equal(c.ready, true);
  assert.equal(store.values[IDS.enabled], true);
  assert.equal(store.values[IDS.strength], 1.5);
});
