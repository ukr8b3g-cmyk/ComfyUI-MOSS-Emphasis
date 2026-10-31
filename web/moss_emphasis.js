import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { Controller, IDS, hideRuntime, normalize, isNegPiP, isForge, shouldApply } from "./controller.js";

function notify(detail) {
  const toast = app.extensionManager?.toast;
  if (toast?.add) toast.add({ severity: "error", summary: "MOSS Emphasis", detail, life: 12000 });
  else app.ui?.dialog?.show?.(String(detail));
  console.error("[MOSS Emphasis]", detail);
}
const controller = new Controller(app, api, notify);
const views = new Set();
controller.refreshUI = () => {
  for (const view of views) {
    if (view.connected && !view.element.isConnected) { views.delete(view); continue; }
    view.connected ||= view.element.isConnected;
    view.update();
  }
};
function strengthRenderer(name, max) {
  return (_label, setter, value) => {
    const input = document.createElement("input");
    input.type = "number"; input.min = "0"; input.max = String(max); input.step = "0.05";
    input.style.width = "7em"; input.value = String(value);
    const update = () => {
      try {
        const config = normalize(controller.graph?.extra?.moss_emphasis);
        input.value = String(config[name]);
        const active = name === "v_scaling_strength" ? isForge(config) && config.v_scaling_enabled :
          name === "negpip_strength" ? isNegPiP(config) && !isForge(config) : !isNegPiP(config);
        input.disabled = !controller.ready || !config.enabled || !active;
      } catch { input.disabled = true; }
    };
    input.addEventListener("change", () => {
      const number = input.valueAsNumber;
      if (!Number.isFinite(number) || number < 0 || number > max) { update(); return; }
      setter(number);
    });
    views.add({element: input, update}); update(); return input;
  };
}
function forgeRenderer(name) {
  return (_label, setter) => {
    const choice = name === "negpip_implementation";
    const input = document.createElement(choice ? "select" : "input");
    if (choice) for (const value of ["PPM reference", "Forge compatible"]) {
      const option = document.createElement("option"); option.value = value; option.textContent = value; input.append(option);
    }
    else input.type = "checkbox";
    const update = () => {
      try {
        const config = normalize(controller.graph?.extra?.moss_emphasis);
        if (choice) input.value = config[name]; else input.checked = config[name];
        input.disabled = !controller.ready || !config.enabled || !isNegPiP(config) || (!choice && !isForge(config));
      } catch { input.disabled = true; }
    };
    input.addEventListener("change", () => setter(choice ? input.value : input.checked));
    views.add({element: input, update}); update(); return input;
  };
}
function statusRenderer() {
  const element = document.createElement("span");
  const update = () => {
    const ja = String(controller.store?.get?.("Comfy.Locale") ?? "").startsWith("ja");
    try {
      if (controller.restoreError) throw controller.restoreError;
      const config = normalize(controller.graph?.extra?.moss_emphasis);
      const neg = isNegPiP(config);
      const strength = neg ? config.negpip_strength : config.strength;
      element.textContent = !shouldApply(config) ? (ja ? "無効（完全バイパス）" : "OFF (complete bypass)") :
        isForge(config) ? "Forge NegPiP / V-Scaling " + (config.v_scaling_enabled ? config.v_scaling_strength : 0) +
          (ja ? "（MOSS以外は自動無効）" : " (auto bypass outside MOSS)") :
          (neg ? "PPM NegPiP" : "Emphasis") + " / " + strength +
          (config.schema_version === 3 ? (ja ? "（モデル自動判定）" : " (auto model)") : (ja ? "（旧MOSS方式）" : " (legacy MOSS)"));
    } catch { element.textContent = ja ? "設定エラー：設定をリセットして復旧" : "Invalid settings: reset to recover"; }
    const source = document.createElement("a");
    source.href = api.apiURL("/moss_emphasis/source");
    source.textContent = ja ? "実行中の版の対応ソース（GPL/AGPL）" : "Corresponding source of this installed version (GPL/AGPL)";
    source.style.display = "block"; element.append(source);
  };
  views.add({element, update}); update(); return element;
}


async function exportApi() {
  try {
    const data = await controller.exportApi();
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "moss-emphasis-api.json";
    a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { notify(error.message); }
  finally { await controller.store?.set(IDS.tools, "Select action"); }
}

app.registerExtension({
  name: "ukr8b3g.MOSSEmphasis",
  settings: [
    { id: IDS.enabled, name: "Enable prompt weighting", category: ["MOSS Emphasis", "General", "Enabled"],
      sortOrder: 100,
      type: "boolean", defaultValue: false,
      tooltip: "Current workflow only. Uses ordinary CLIP Text Encode / Text Multiline. Forge mode weights both Positive and Negative; existing methods preserve Negative. New workflows start OFF.",
      onChange: value => controller.change("enabled", value) },
    { id: IDS.strength, name: "Strength", category: ["MOSS Emphasis", "General", "Strength"],
      sortOrder: 90,
      type: strengthRenderer("strength", 4), defaultValue: 1,
      tooltip: "1 = KJ equations for MOSS; native token weighting for SDXL/Illustrious and Anima. 0 bypasses this extension; native prompt weighting still applies. Above 1 increases both emphasis and suppression.",
      onChange: value => controller.change("strength", value) },
    { id: IDS.negpip, name: "Use NegPiP", category: ["MOSS Emphasis", "General", "NegPiP"],
      sortOrder: 80,
      type: "boolean", defaultValue: false,
      tooltip: "ON uses the selected NegPiP implementation; OFF keeps normal emphasis. PPM supports MOSS, SDXL/Illustrious and Anima. Forge supports native MOSS only and weights both Positive and Negative. Other models bypass Forge weighting.",
      onChange: value => controller.change("negpip", value) },
    { id: IDS.negpip_implementation, name: "NegPiP implementation", category: ["MOSS Emphasis", "General", "NegPiPImplementation"],
      sortOrder: 75,
      type: forgeRenderer("negpip_implementation"), defaultValue: "PPM reference",
      tooltip: "PPM reference preserves the existing method. Forge compatible uses segment tokenization, empty-encoding interpolation and signed Values. Native MOSS only; Layout JSON and processed conditioning are unsupported.",
      onChange: value => controller.change("negpip_implementation", value) },
    { id: IDS.negpip_strength, name: "NegPiP effect", category: ["MOSS Emphasis", "General", "NegPiPStrength"],
      sortOrder: 70,
      type: strengthRenderer("negpip_strength", 1), defaultValue: 1,
      tooltip: "1 = reference equations; 0 = complete bypass including syntax. At 0.5 negative tokens have zero Value, but are not deleted. This effect control is an independent extension.",
      onChange: value => controller.change("negpip_strength", value) },
    { id: IDS.v_scaling_enabled, name: "Use V-Scaling", category: ["MOSS Emphasis", "General", "VScaling"],
      sortOrder: 68,
      type: forgeRenderer("v_scaling_enabled"), defaultValue: false,
      tooltip: "Forge only. OFF retains basic NegPiP: encoder magnitude and Value sign. ON transfers magnitude towards the Values read by image queries. This is not the PPM effect control.",
      onChange: value => controller.change("v_scaling_enabled", value) },
    { id: IDS.v_scaling_strength, name: "V-Scaling Strength", category: ["MOSS Emphasis", "General", "VScalingStrength"],
      sortOrder: 66,
      type: strengthRenderer("v_scaling_strength", 2), defaultValue: 1,
      tooltip: "Forge only, 0..2. 0 is basic NegPiP, not complete bypass. 1 uses signed prompt magnitudes on image-query Values; above 1 increases their exponent. Text queries read sign-only Values. Master OFF bypasses weighting.",
      onChange: value => controller.change("v_scaling_strength", value) },
    { id: IDS.status, name: "Current method", category: ["MOSS Emphasis", "General", "Status"],
      sortOrder: 60,
      type: statusRenderer, defaultValue: "",
      tooltip: "Read-only status derived from this workflow. An invalid saved configuration must be explicitly reset before use." },
    { id: IDS.diagnostic, name: "Diagnostic logging", category: ["MOSS Emphasis", "Advanced", "Diagnostic"],
      type: "boolean", defaultValue: false,
      tooltip: "Log settings and target IDs; does not log full prompts. Does not change the image cache key.",
      onChange: value => controller.change("diagnostic", value) },
    { id: IDS.tools, name: "API export", category: ["MOSS Emphasis", "Tools", "Export"],
      type: "combo", defaultValue: "Select action", options: ["Select action", "Export execution API JSON", "Reset workflow settings"],
      tooltip: "Prepared API JSON includes internal runtime nodes. Ordinary ComfyUI API export may not include weighting.",
      onChange: value => { if (controller.ready && value === "Export execution API JSON") void exportApi();
        if (value === "Reset workflow settings") void controller.resetSettings().then(() => controller.store?.set(IDS.tools, "Select action")); } },
  ],
  addCustomNodeDefs: hideRuntime,
  beforeRegisterVueAppNodeDefs: hideRuntime,
  beforeConfigureGraph() { controller.ready = false; },
  async afterConfigureGraph() { await controller.restore(); },
  async afterLoadGraph() { await controller.restore(); },
  async setup() {
    try { controller.installQueue(); await controller.restore(); }
    catch (error) { notify(error.message); }
  },
});
