# MOSS Emphasis 0.10.0 (Beta)

Adds **NegPiP** and model-aware prompt weighting for **native MOSS-Image, SDXL / Illustrious, and native Anima**.

- Use **Settings → MOSS Emphasis → Enable prompt weighting**, then choose normal emphasis or **Use NegPiP**. The methods are exclusive and keep separate strengths.
- In auto model mode, **every unsupported architecture automatically bypasses the extension** and continues native generation: Qwen-Image, FLUX, SD1.5, SD3, Krea2, SDXL Refiner and other models. Saved settings stay intact; a supported model reactivates the selected method. A supported MODEL with a mismatched CLIP still errors. Existing graph/conditioning restrictions remain.
- SDXL preserves native Negative semantics while carrying separate Key/Value; Anima uses native T5 token metadata and Value signs. Existing MOSS arithmetic is retained. No extra dependency or model download.
- Prompt weights have no fixed min/max; finite/dtype constraints remain. Intermediate NegPiP effects are extension-specific. Strength/effect 0 bypasses the extension, while native encoder weighting may still apply.
- 0.9.0 / 0.9.1 settings remain loadable. Old schema 1/2 workflows retain MOSS-only scope until an explicit weighting setting change upgrades them to auto mode.

**Update:** install/update the extension, restart ComfyUI itself, and reload the browser. For an old workflow, toggle weighting OFF then ON and save to enter auto model mode. Read [model support and limitations](../README.md#model-support).

**Validation:** 122 Python regressions, 42 frontend/locale checks, 12 real ComfyUI CPU contract tests, pinned PPM comparisons and 48 bit-exact legacy MOSS comparisons. CPU contracts use native modules with small deterministic stand-ins, not loaded checkpoints. GPU image quality, speed/VRAM and real Settings rendering remain unverified. This is a beta release; see [validation](VALIDATION.md).

## 日本語

**NegPiP搭載版 v0.10.0**です。対応は**標準MOSS-Image、SDXL／Illustrious、標準Animaの3系統**です。

- 設定 → MOSS Emphasisで全体を有効化し、「NegPiP方式を使用」で通常方式と切り替えます。重ね掛けはせず、各方式の強さを別々に保持します。
- 自動判定モードでは、**それ以外のモデルは拡張を自動で無効化して標準生成へ戻します**。Qwen-Image・FLUX・SD1.5・SD3・Krea2・SDXL Refinerなども同様です。設定値は消さず、対応モデルへ戻すと再適用します。MODELとCLIPの不一致や未対応配線のチェックは残ります。
- 通常のNegativeの意味と、既存MOSS方式の計算を維持します。追加依存やモデルのダウンロードは不要です。
- プロンプト重みに固定の上下限はありません。有限数・dtypeの制約は残ります。NegPiPの中間効果は独自機能です。
- 旧0.9系の設定を読み込めます。旧ワークフローは重み設定をOFF→ONにして保存するとモデル自動判定へ移行します。

**ComfyUI本体を再起動し、ブラウザーを再読み込みしてください。** CPU検証済みですが、GPU画質・速度・VRAMと実画面確認は未実施です。詳しくは[日本語README](../README_JA.md)を参照してください。
