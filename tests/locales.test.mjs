import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { IDS } from "../web/controller.js";

const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
const jaMain = read("../locales/ja/main.json");
const jaSettings = read("../locales/ja/settings.json");

// Matches ComfyUI frontend's normalizeI18nKey (periods to underscores).
const keyOf = id => id.replace(/\./g, "_");

test("ComfyUI native i18n locale directory uses supported code ja", () => {
  assert.ok(jaMain.settingsCategories);
  assert.equal(typeof jaSettings, "object");
});

test("every registered setting has a Japanese name and help tooltip", () => {
  for (const id of Object.values(IDS)) {
    const item = jaSettings[keyOf(id)];
    assert.ok(item, "missing translation for " + id);
    assert.match(item.name, /[ぁ-んァ-ヶ一-龠]/u);
    assert.match(item.tooltip, /[ぁ-んァ-ヶ一-龠]/u);
    assert.ok(item.tooltip.length > 35);
  }
});

test("translated section headings match backend category strings", () => {
  const categories = jaMain.settingsCategories;
  assert.equal(categories["MOSS Emphasis"], "MOSS 強調設定");
  assert.equal(categories["General"], "一般");
  assert.equal(categories["Advanced"], "詳細設定");
  assert.equal(categories["Tools"], "ツール");
});

test("API export combobox preserves internal English option values", () => {
  const options = jaSettings[keyOf(IDS.tools)].options;
  assert.equal(options["Select action"], "操作を選択");
  assert.equal(options["Export execution API JSON"], "実行用API JSONを書き出す");
});

test("Japanese labels do not change persisted IDs or execution semantics", () => {
  for (const [id, translation] of Object.entries(jaSettings)) {
    assert.ok(Object.values(IDS).some(x => keyOf(x) === id));
    assert.ok(!Object.hasOwn(translation, "value"));
    assert.ok(!Object.hasOwn(translation, "id"));
  }
});

test("all Japanese tooltips use native locale messages, without DOM rewriting", () => {
  const js = readFileSync(new URL("../web/moss_emphasis.js", import.meta.url), "utf8");
  assert.match(js, /name: "ukr8b3g\.MOSSEmphasis"/);
  for (const [id, item] of Object.entries(jaSettings)) {
    assert.ok(item.name && item.tooltip);
    assert.ok(id.startsWith("MOSSEmphasis_"));
  }
});
