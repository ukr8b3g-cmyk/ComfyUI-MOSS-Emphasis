/* Settings are a workflow editor, never process-global execution state. */
export const VERSION = "0.9.0";
export const RUNTIME = "_MossEmphasisRuntimeV1";
export const IDS = Object.freeze({
  enabled: "MOSSEmphasis.General.Enabled",
  strength: "MOSSEmphasis.General.Strength",
  diagnostic: "MOSSEmphasis.Advanced.Diagnostic",
  tools: "MOSSEmphasis.Tools.Action",
});

export function normalize(raw = {}) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid MOSS Emphasis settings.");
  const expected = { schema_version: 1, engine: "kj_dit_v1", parser_version: 1, version: VERSION };
  for (const [key, value] of Object.entries(expected)) {
    if (raw[key] !== undefined && raw[key] !== value) throw new Error(`Unsupported MOSS Emphasis ${key}.`);
  }
  const enabled = raw.enabled === undefined ? false : raw.enabled;
  const strength = raw.strength === undefined ? 1 : raw.strength;
  if (typeof enabled !== "boolean" || typeof strength !== "number" || !Number.isFinite(strength) || strength < 0 || strength > 4)
    throw new Error("Strength must be a finite number from 0 to 4.");
  return { ...expected, enabled, strength, diagnostic: raw.diagnostic === true };
}

export function hideRuntime(defs) {
  if (Array.isArray(defs)) {
    for (let i = defs.length - 1; i >= 0; i--) if ((defs[i].name ?? defs[i].node_id) === RUNTIME) defs.splice(i, 1);
  } else if (defs) delete defs[RUNTIME];
}

export class Controller {
  constructor(app, api, notify = console.error) {
    this.app = app; this.api = api; this.notify = notify;
    this.ready = false; this.syncing = 0; this.epoch = 0;
  }
  get graph() { return this.app.rootGraph ?? this.app.graph; }
  get store() { return this.app.extensionManager?.setting; }

  async restore() {
    const epoch = ++this.epoch;
    this.ready = false; this.syncing++;
    try {
      let snapshot;
      try { snapshot = normalize(this.graph?.extra?.moss_emphasis); }
      catch (error) { this.notify(error.message); snapshot = normalize(); }
      if (!this.store?.set) throw new Error("INCOMPATIBLE_FRONTEND: Settings API is unavailable.");
      for (const name of ["enabled", "strength", "diagnostic"]) {
        if (epoch !== this.epoch) return;
        await this.store.set(IDS[name], snapshot[name]);
      }
    } finally {
      this.syncing--;
      if (epoch === this.epoch) this.ready = true;
    }
  }

  change(name, value) {
    if (!this.ready || this.syncing || !this.graph) return;
    const graph = this.graph;
    const snapshot = normalize({ ...(graph.extra?.moss_emphasis ?? {}), [name]: value });
    graph.beforeChange?.();
    graph.extra = { ...(graph.extra ?? {}), moss_emphasis: snapshot };
    graph.afterChange?.();
    graph.change?.();
  }

  async prepare(data) {
    // Snapshot the serialized workflow, not whichever tab happens to be active later.
    const snapshot = normalize(data.workflow?.extra?.moss_emphasis);
    if (!snapshot.enabled || snapshot.strength === 0) return data;
    const frozenWorkflow = structuredClone(data.workflow);
    const frozenPrompt = structuredClone(data.output);
    const response = await this.api.fetchApi("/moss_emphasis/prepare", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schema_version: 1, prompt: frozenPrompt, settings: snapshot, diagnostic: snapshot.diagnostic }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(`[${result.error?.code ?? "PREPARE_FAILED"}] ${result.error?.message ?? "Preparation failed. Nothing was queued."}`);
    if (!result.prompt || typeof result.prompt !== "object" || !Array.isArray(result.targets)) throw new Error("Invalid prepare response. Nothing was queued.");
    const returned = normalize(result.settings);
    for (const key of ["enabled", "strength", "engine", "version", "schema_version", "parser_version"])
      if (returned[key] !== snapshot[key]) throw new Error("Prepare settings mismatch. Nothing was queued.");
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
