# Historical MOSS-only NegPiP implementation notes

This records the earlier schema-2 local stage. Current schema-3 SDXL/Anima behavior is in [README](../README.md), [日本語README](../README_JA.md) and [Validation](VALIDATION.md). Statements below describe that earlier stage, not the current complete model scope.

Based on MOSS Emphasis 0.9.1; includes the later main controller restore serialization and scoped NAG detection. Public version/release metadata remains unchanged. Settings schema is 2; prepare API envelope stays 1.

## Use / 使い方

In ComfyUI Settings → MOSS Emphasis, enable prompt weighting and turn **Use NegPiP** ON. OFF keeps the existing MOSS Emphasis method. The two methods are exclusive. Separate strengths are retained when switching; only the selected method's strength controls execution.

設定 → MOSS Emphasisで「プロンプトの重み付けを有効化」と「NegPiP方式を使用」をONにします。NegPiPをOFFにすると従来方式です。「重み付け強度」は従来方式、「NegPiP効果」は新方式専用です。使わない強さは非活性表示になります。

Positive text example: `a person wearing a (red:-1) hat`. The Negative field is not processed. Ordinary parentheses and protected JSON fields retain the existing parser behavior. Negative numbers alone do not switch engines.

Prompt weights have no fixed numeric lower or upper bound in either method: `(red:-5)` and `(blue:10)` are valid. This is separate from the Settings controls (existing Emphasis strength 0..4; NegPiP effect 0..1), whose ranges are unchanged. Only finite decimal weights are supported; non-finite nested products and coefficients that overflow the working dtype are rejected. The former -2..4 prompt-weight bounds were local MOSS Emphasis validation, not a PPM/NegPiP requirement.

両方式ともプロンプト内の重みに固定の下限・上限はありません。`(red:-5)`、`(blue:10)` が使用できます。Settingsの「重み付け強度」0〜4／「NegPiP効果」0〜1とは別の値で、そちらの範囲は従来どおりです。以前の-2〜4制限はMOSS Emphasis独自の入力チェックで、PPMの仕様ではありません。NegPiPは負の語のValueの符号を反転し、絶対値をAttention配分へ反映します。絶対値を大きくしても、画像の抑制効果が単純に比例するとは限りません。

NegPiP effect: 1 uses the PPM-reference equations; 0 bypasses parsing and patching completely. At 0.5, negative token Value is zero, but the token is not removed. Intermediate effect values are an independent extension, not an upstream PPM control. Zero and a small positive effect can produce different input text because zero retains the original syntax.

NegPiP効果は1が参照数式、0が原文を含む完全バイパスです。0.5では負の語のValue倍率が0になりますが、KeyやAttentionの分母には残ります。概念の完全除去は保証しません。

Old 0.9.0/0.9.1 workflow settings migrate in memory to the existing method. Saved configuration is changed only on an explicit edit. Invalid saved settings block preparation; use **Reset workflow settings** to explicitly recover to OFF. Use the dedicated **Export execution API JSON** action for weighted API workflows.

## Implementation and limits

- Only native MOSS's 42 joint attention blocks are patched; the shared CLIP and text embedder are not patched. Positive image queries use modified Value and bias; text queries use original Value/mask. Negative rows retain the original calculation.
- Coefficients and logarithms use Python double precision. Value factors are converted to Value dtype before multiplication. Mask additions use the query dtype; invalid or overflowing masks are rejected. Existing method arithmetic is unchanged.
- Input containers are consumed once. Each split backend call receives fresh containers; modified Values reach Kitchen before quantization. No additional dense Q×K mask is allocated.
- Initial masks: none or unambiguous rank-4 compact `[B or 1, H or 1, 1, K]`. Ambiguous lower-rank, query-dependent and fully blocked masks are rejected.
- Existing backend, model, reference-image, region and conditioning restrictions remain. This is not full PPM parser/model support.
- CPU tests only at this stage. Real tokenizer, UI, GPU images, native Kitchen INT8 kernel performance/VRAM and GPU SLG remain unverified. Kitchen support is **HOLD pending real GPU validation**.

Reference: [PPM MOSS implementation, fixed 926e8bb5](https://github.com/pamparamm/ComfyUI-ppm/blob/926e8bb5f3c4b652e5b42a451d76cb3dc1d4df73/src/negpip/moss_negpip.py). The extension does not require or bundle PPM. The local external reference used for tests is outside this distribution. Existing license/NOTICE remains in force; publication review is a separate step.

Local installation requires a ComfyUI restart and browser refresh before the running application loads the changed Python/JS. Neither is performed automatically.

## 2026-10-31 audit fixes (local)

Settings restoration failures (including missing Settings API and partial writes) now block queue/API export for that workflow until restoration or explicit reset succeeds. Pending restoration also blocks admission. A later tab's failure does not cancel a submission already being prepared.

NegPiP-generated bias is bounded/validated by the CPU coefficient calculation and no longer undergoes per-block host scalar reads. External compact masks and their combined bias are checked once per forward for the same input/layout/dtype; replacement inputs and ordinary-tensor in-place updates invalidate that result. Native inference masks are immutable during a MOSS forward. Cache lifetime is one forward, not model/global state. Legacy weighting arithmetic is unchanged.

設定の復元中・復元失敗中は、そのワークフローのQueueと専用API出力を停止します。復元成功または明示的な設定リセット後に再開できます。NegPiPの生成biasについて42ブロックで繰り返していた検査を省き、外部maskの検査結果は1回のforward内でのみ共有します。GPU速度の実測は未実施です。
