import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { Controller, IDS, hideRuntime } from "./controller.js";

function notify(detail) {
  const toast = app.extensionManager?.toast;
  if (toast?.add) toast.add({ severity: "error", summary: "MOSS Emphasis", detail, life: 12000 });
  else app.ui?.dialog?.show?.(String(detail));
  console.error("[MOSS Emphasis]", detail);
}
const controller = new Controller(app, api, notify);

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
      type: "boolean", defaultValue: false,
      tooltip: "Current workflow only. Uses ordinary CLIP Text Encode / Text Multiline. Saved with this workflow; new workflows start OFF.",
      onChange: value => controller.change("enabled", value) },
    { id: IDS.strength, name: "Strength", category: ["MOSS Emphasis", "General", "Strength"],
      type: "number", defaultValue: 1, attrs: { min: 0, max: 4, step: 0.05, minFractionDigits: 2, maxFractionDigits: 2 },
      tooltip: "1.00 = KJ-equation strength. 0 = complete bypass, including syntax. Above 1 strengthens both emphasis and suppression, including negative values.",
      onChange: value => controller.change("strength", value) },
    { id: IDS.diagnostic, name: "Diagnostic logging", category: ["MOSS Emphasis", "Advanced", "Diagnostic"],
      type: "boolean", defaultValue: false,
      tooltip: "Log settings and target IDs; does not log full prompts. Does not change the image cache key.",
      onChange: value => controller.change("diagnostic", value) },
    { id: IDS.tools, name: "API export", category: ["MOSS Emphasis", "Tools", "Export"],
      type: "combo", defaultValue: "Select action", options: ["Select action", "Export execution API JSON"],
      tooltip: "Prepared API JSON includes internal runtime nodes. Ordinary ComfyUI API export may not include weighting.",
      onChange: value => { if (controller.ready && value === "Export execution API JSON") void exportApi(); } },
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
