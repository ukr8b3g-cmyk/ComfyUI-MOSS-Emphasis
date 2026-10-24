# MOSS Emphasis 0.9 — experimental beta

Settings-controlled prompt weighting for ordinary ComfyUI positive prompts. No manually placed prompt-weight node.

- Enable/Strength/diagnostics in **Settings → MOSS Emphasis**, saved per workflow.
- Ordinary CLIP Text Encode and upstream STRING/Text Multiline sources.
- Native MOSS Base/SFT architecture detection, KJ-equation DiT-only weighting.
- Position-aware syntax, nested explicit weights, character-name parentheses and protected MOSS Layout captions.
- Deterministic execution-only graph insertion, cache-aware settings, prepared API export and duplicate-engine detection.
- OFF and Strength 0 are complete bypasses; Negative and sampling parameters stay unchanged.
- No additional runtime pip dependencies or model downloads.

**Validation:** Python CPU/unit/API tests and JavaScript contract tests are included; see `docs/VALIDATION.md` for the exact executed local checks. These are not real-model GPU tests.

**Important 0.9 limitations:** native PyTorch/basic attention only. Configured INT8/SOL `_attn` checkpoints, Sage/Flash overrides, compile, forecasting accelerators, NAG, Edit/control/reference paths and custom conditioning pipelines are deliberately rejected. Real ComfyUI browser behavior and MOSS Base/SFT GPU generation, including SLG and quantized-model parity, are **not verified**.

Install by extracting the ZIP into `ComfyUI/custom_nodes/`, then restart ComfyUI and reload the browser. Enable this per workflow in Settings; new workflows start OFF. Remove existing prompt-weight nodes from the same path before enabling this extension.

---

**日本語:** 普通のPositive欄から重み構文を使い、SettingsのMOSS Emphasisで操作する拡張です。0.9は試験版で、実ComfyUI画面・GPU生成は未検証です。対応外のAttentionや追加パッチは黙って変更せず停止します。詳細はREADME_JA.mdを参照してください。
