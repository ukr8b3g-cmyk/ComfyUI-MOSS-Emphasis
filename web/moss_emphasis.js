import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { Controller, IDS, hideRuntime, normalize, isNegPiP } from "./controller.js";

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
        input.disabled = !controller.ready || !config.enabled || isNegPiP(config) !== (name === "negpip_strength");
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
function statusRenderer() {
  const element = document.createElement("span");
  const update = () => {
    const ja = String(controller.store?.get?.("Comfy.Locale") ?? "").startsWith("ja");
    try {
      if (controller.restoreError) throw controller.restoreError;
      const config = normalize(controller.graph?.extra?.moss_emphasis);
      const neg = isNegPiP(config);
      const strength = neg ? config.negpip_strength : config.strength;
      element.textContent = !config.enabled || strength === 0 ? (ja ? "無効（完全バイパス）" : "OFF (complete bypass)") :
        (neg ? "NegPiP" : "Emphasis") + " / " + strength +
        (config.schema_version === 3 ? (ja ? "（モデル自動判定）" : " (auto model)") : (ja ? "（旧MOSS方式）" : " (legacy MOSS)"));
    } catch { element.textContent = ja ? "設定エラー：設定をリセットして復旧" : "Invalid settings: reset to recover"; }
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
      tooltip: "Current workflow only. Uses ordinary CLIP Text Encode / Text Multiline. Saved with this workflow; new workflows start OFF.",
      onChange: value => controller.change("enabled", value) },
    { id: IDS.strength, name: "Strength", category: ["MOSS Emphasis", "General", "Strength"],
      sortOrder: 90,
      type: strengthRenderer("strength", 4), defaultValue: 1,
      tooltip: "1 = KJ equations for MOSS; native token weighting for SDXL/Illustrious and Anima. 0 bypasses this extension; native prompt weighting still applies. Above 1 increases both emphasis and suppression.",
      onChange: value => controller.change("strength", value) },
    { id: IDS.negpip, name: "Use NegPiP", category: ["MOSS Emphasis", "General", "NegPiP"],
      sortOrder: 80,
      type: "boolean", defaultValue: false,
      tooltip: "ON selects model-specific PPM-reference NegPiP; OFF selects normal emphasis. MODEL and CLIP select MOSS, SDXL/Illustrious or native Anima automatically. Negative retains its native meaning. Changing weighting settings upgrades a legacy workflow to auto model mode.",
      onChange: value => controller.change("negpip", value) },
    { id: IDS.negpip_strength, name: "NegPiP effect", category: ["MOSS Emphasis", "General", "NegPiPStrength"],
      sortOrder: 70,
      type: strengthRenderer("negpip_strength", 1), defaultValue: 1,
      tooltip: "1 = reference equations; 0 = complete bypass including syntax. At 0.5 negative tokens have zero Value, but are not deleted. This effect control is an independent extension.",
      onChange: value => controller.change("negpip_strength", value) },
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
