/* Settings are a workflow editor, never process-global execution state. */
export const VERSION = "0.11.0";
export const RUNTIME = "_MossEmphasisRuntimeV1";
export const RUNTIME_V2 = "_MossEmphasisRuntimeV2";
export const RUNTIME_V3 = "_MossEmphasisRuntimeV3";
export const FORGE = "forge_negpip_moss_v1";
export const isNegPiP = config => ["ppm_negpip_moss_v1", "negpip_auto_v1", FORGE].includes(config.engine);
export const isForge = config => config.engine === FORGE;
export const shouldApply = config => config.enabled && (isForge(config) || (isNegPiP(config) ? config.negpip_strength : config.strength) !== 0);
export const IDS = Object.freeze({
  enabled: "MOSSEmphasis.General.Enabled",
  strength: "MOSSEmphasis.General.Strength",
  negpip: "MOSSEmphasis.General.NegPiP",
  negpip_strength: "MOSSEmphasis.General.NegPiPStrength",
  negpip_implementation: "MOSSEmphasis.General.NegPiPImplementation",
  v_scaling_enabled: "MOSSEmphasis.General.VScaling",
  v_scaling_strength: "MOSSEmphasis.General.VScalingStrength",
  status: "MOSSEmphasis.General.Status",
  diagnostic: "MOSSEmphasis.Advanced.Diagnostic",
  tools: "MOSSEmphasis.Tools.Action",
});

export function normalize(raw = {schema_version: 3, engine: "native_auto_v1"}) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid MOSS Emphasis settings.");
  const schema = raw.schema_version === undefined ? 1 : raw.schema_version, engine = raw.engine === undefined ? "kj_dit_v1" : raw.engine;
  const engines = {1: ["kj_dit_v1"], 2: ["kj_dit_v1", "ppm_negpip_moss_v1"], 3: ["native_auto_v1", "negpip_auto_v1"], 4: [FORGE]};
  if (!Number.isInteger(schema) || !engines[schema]?.includes(engine))
    throw new Error("Unsupported MOSS Emphasis schema or engine.");
  for (const field of ["parser_version", "engine_version"])
    if (raw[field] !== undefined && raw[field] !== 1) throw new Error("Unsupported MOSS Emphasis " + field);
  if (raw.version !== undefined && !["0.9.0", "0.9.1", "0.10.0", "0.10.1", VERSION].includes(raw.version)) throw new Error("Unsupported MOSS Emphasis version.");
  const enabled = raw.enabled === undefined ? false : raw.enabled, strength = raw.strength === undefined ? 1 : raw.strength, neg = raw.negpip_strength === undefined ? 1 : raw.negpip_strength;
  if (typeof enabled !== "boolean" || typeof strength !== "number" || !Number.isFinite(strength) || strength < 0 || strength > 4 ||
      typeof neg !== "number" || !Number.isFinite(neg) || neg < 0 || neg > 1)
    throw new Error("Invalid MOSS Emphasis strength or enabled value.");
  const method = raw.negpip_implementation === undefined ? (engine === FORGE ? "Forge compatible" : "PPM reference") : raw.negpip_implementation;
  const vEnabled = raw.v_scaling_enabled === undefined ? false : raw.v_scaling_enabled;
  const vStrength = raw.v_scaling_strength === undefined ? 1 : raw.v_scaling_strength;
  if (!["PPM reference", "Forge compatible"].includes(method) || typeof vEnabled !== "boolean" ||
      typeof vStrength !== "number" || !Number.isFinite(vStrength) || vStrength < 0 || vStrength > 2)
    throw new Error("Invalid MOSS Emphasis Forge preferences.");
  if (engine === FORGE && method !== "Forge compatible") throw new Error("Forge engine and implementation differ.");
  return { schema_version: Math.max(2, schema), engine, engine_version: 1, parser_version: 1, version: VERSION,
           enabled, strength, negpip_strength: neg, negpip_implementation: method,
           v_scaling_enabled: vEnabled, v_scaling_strength: vStrength, diagnostic: raw.diagnostic === true };
}

export function executionSettings(raw) {
  const config = normalize(raw);
  const {diagnostic, negpip_implementation, v_scaling_enabled, v_scaling_strength, ...result} = config;
  if (isForge(config)) Object.assign(result, {strength: 1, negpip_strength: 1,
    v_scaling_enabled: v_scaling_enabled && v_scaling_strength > 0,
    v_scaling_strength: v_scaling_enabled ? v_scaling_strength : 0});
  return result;
}

export function hideRuntime(defs) {
  if (Array.isArray(defs)) {
    for (let i = defs.length - 1; i >= 0; i--) if ([RUNTIME, RUNTIME_V2, RUNTIME_V3].includes(defs[i].name ?? defs[i].node_id)) defs.splice(i, 1);
  } else if (defs) { delete defs[RUNTIME]; delete defs[RUNTIME_V2]; delete defs[RUNTIME_V3]; }
}

export class Controller {
  constructor(app, api, notify = console.error) {
    this.app = app; this.api = api; this.notify = notify;
    this.ready = false; this.epoch = 0; this.restoreTail = Promise.resolve();
    this.restoreStates = new WeakMap();
  }
  get graph() { return this.app.rootGraph ?? this.app.graph; }
  get store() { return this.app.extensionManager?.setting; }
  get restoreError() { return this.restoreStates.get(this.graph)?.error; }

  restore() {
    const epoch = ++this.epoch;
    const graph = this.graph;
    const state = { pending: true, error: null };
    this.restoreStates.set(graph, state);
    this.ready = false;
    let snapshot;
    const failed = error => {
      state.pending = false; state.error = error;
      if (epoch === this.epoch) {
        this.ready = false; this.notify(error.message); this.refreshUI?.();
      }
    };
    try { snapshot = normalize(graph?.extra?.moss_emphasis); }
    catch (error) { failed(error); return; }

    // Serialize Settings writes: an older in-flight set() must finish before
    // the newest workflow can apply its values.
    const apply = async () => {
      if (epoch !== this.epoch) return;
      if (!this.store?.set) throw new Error("INCOMPATIBLE_FRONTEND: Settings API is unavailable.");
      for (const name of ["enabled", "strength", "negpip", "negpip_implementation", "negpip_strength", "v_scaling_enabled", "v_scaling_strength", "diagnostic"]) {
        if (epoch !== this.epoch) return;
        await this.store.set(IDS[name], name === "negpip" ? isNegPiP(snapshot) : snapshot[name]);
      }
      if (epoch === this.epoch) {
        state.pending = false;
        this.ready = true;
        this.refreshUI?.();
      }
    };
    const pending = this.restoreTail.then(apply).catch(error => { failed(error); throw error; });
    // Keep later restores runnable even if an earlier Settings write failed.
    this.restoreTail = pending.catch(() => {});
    return pending;
  }

  change(name, value) {
    if (!this.ready || !this.graph) return;
    const graph = this.graph;
    const previous = normalize(graph.extra?.moss_emphasis);
    const method = name === "negpip" ? value : isNegPiP(previous);
    const migrate = ["enabled", "strength", "negpip", "negpip_strength"].includes(name) ||
      (name === "negpip_implementation" && method) || (["v_scaling_enabled", "v_scaling_strength"].includes(name) && isForge(previous));
    const update = name === "negpip" ? {} : { [name]: value };
    const forge = method && (update.negpip_implementation ?? previous.negpip_implementation) === "Forge compatible";
    const snapshot = normalize({ ...previous, ...update, ...(migrate ? {
      schema_version: forge ? 4 : 3, engine: forge ? FORGE : method ? "negpip_auto_v1" : "native_auto_v1"
    } : {}) });
    graph.beforeChange?.();
    graph.extra = { ...(graph.extra ?? {}), moss_emphasis: snapshot };
    graph.afterChange?.();
    graph.change?.();
    this.refreshUI?.();
  }

  async resetSettings() {
    this.graph.beforeChange?.();
    this.graph.extra = { ...(this.graph.extra ?? {}), moss_emphasis: normalize() };
    this.graph.afterChange?.(); this.graph.change?.();
    this.refreshUI?.();
    await this.restore();
  }

  async prepare(data) {
    const graph = this.graph;
    const state = this.restoreStates.get(graph);
    // Admission belongs to the workflow being submitted, not a later active tab.
    const sameWorkflow = !data.workflow?.id || !graph?.id || data.workflow.id === graph.id;
    if (sameWorkflow && (state?.pending || state?.error))
      throw new Error(state.error
        ? "MOSS Emphasis settings restoration failed. Restore or reset this workflow before queue/export."
        : "MOSS Emphasis settings are still restoring. Retry after restoration completes.");
    // Snapshot the serialized workflow, not whichever tab happens to be active later.
    const snapshot = normalize(data.workflow?.extra?.moss_emphasis);
    if (!shouldApply(snapshot)) return data;
    const execution = executionSettings(snapshot);
    const frozenWorkflow = structuredClone(data.workflow);
    const frozenPrompt = structuredClone(data.output);
    const response = await this.api.fetchApi("/moss_emphasis/prepare", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schema_version: 1, prompt: frozenPrompt, settings: execution, diagnostic: snapshot.diagnostic }),
    });
    const result = await response.json();
    if (!response.ok && result.error?.code === "INVALID_SETTINGS" &&
        (result.error?.message === `Unsupported schema_version: ${snapshot.schema_version}.` ||
         result.error?.message === `Unsupported version: '${VERSION}'.` ||
         ([3, 4].includes(snapshot.schema_version) && result.error?.message === "Unsupported schema or engine."))) {
      const ja = String(this.store?.get?.("Comfy.Locale") ?? "").startsWith("ja");
      throw new Error(ja
        ? "[BACKEND_RESTART_REQUIRED] 画面は新版ですが、起動中のPython側が旧版です。ComfyUI本体を再起動し、ブラウザーを再読み込みしてください。生成は投入していません。"
        : "[BACKEND_RESTART_REQUIRED] The browser has the new settings format, but the running Python backend is older. Restart ComfyUI itself, then reload the browser. Nothing was queued.");
    }
    if (!response.ok) throw new Error(`[${result.error?.code ?? "PREPARE_FAILED"}] ${result.error?.message ?? "Preparation failed. Nothing was queued."}`);
    if (!result.prompt || typeof result.prompt !== "object" || !Array.isArray(result.targets)) throw new Error("Invalid prepare response. Nothing was queued.");
    const returned = executionSettings(result.settings);
    for (const key of Object.keys(execution))
      if (returned[key] !== execution[key]) throw new Error("Prepare settings mismatch. Nothing was queued.");
    if (snapshot.diagnostic) console.info("[MOSS Emphasis]", { settings: snapshot, targets: result.targets, warnings: result.warnings });
    return { ...data, output: result.prompt, workflow: frozenWorkflow };
  }

  installQueue() {
    const api = this.api, controller = this;
    if (typeof api.queuePrompt !== "function" || typeof api.fetchApi !== "function")
      throw new Error("INCOMPATIBLE_FRONTEND: queuePrompt/fetchApi unavailable.");
    if (api.queuePrompt.mossEmphasisV1) return;
    const original = api.queuePrompt;
    async function queue(number, data, options) {
      let prepared;
      try { prepared = await controller.prepare(data); }
      catch (error) { controller.notify(error.message); throw error; }
      return original.call(this, number, prepared, options);
    }
    queue.mossEmphasisV1 = true;
    api.queuePrompt = queue;
  }

  async exportApi() {
    const original = await this.app.graphToPrompt();
    const data = await this.prepare(original);
    return { prompt: data.output, extra_data: { extra_pnginfo: { workflow: data.workflow } } };
  }
}
