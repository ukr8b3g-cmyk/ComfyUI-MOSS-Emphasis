# MOSS Emphasis v0.9.1 — SLG provenance + Comfy Kitchen INT8 (Beta)

This patch release addresses two failures reported with **ComfyUI 0.42.1** on Windows:

1. **Official SLG falsely rejected:** `SkipLayerGuidanceDiTSimple` and `SkipLayerGuidanceDiT` can be loaded by ComfyUI as an absolute-path Python module. v0.9 compared `__module__` to a fixed dotted name and incorrectly failed. v0.9.1 recognizes the actual installed official `nodes_slg.py` functions using their loaded module plus original nested code identity. Unknown guidance and block patches remain rejected.
2. **Global `--use-ck-attention` rejected:** v0.9.1 accepts native **Comfy Kitchen INT8 attention** when it is the process-selected global attention kernel, and the original prequantized `AttentionTensorContainer` path is available. 0.5 Value suppression stays unmasked; boosts send additive bias masks to the selected Kitchen backend. Positive/Negative row isolation and non-mutating model clones remain in place. PyTorch/basic remains supported.

**Still unsupported (intentionally):** per-model `ComfyAttention.config` INT8/SOL (`_attn` files), Sage/Flash/custom attention overrides, torch.compile, spectrum/TeaCache, NAG, MOSS Edit or reference control, and unknown custom guider pipelines. No automatic PyTorch fallback is introduced.

**Non-MOSS models:** With ordinary `CLIPTextEncode`→KSampler graphs, Illustrious/SDXL, Anima and Krea2 are passed to their original native encoders without MOSS-specific parsing or model patching. Static checks can still reject unsupported custom sampling graphs while MOSS Emphasis Settings is ON; turn it OFF for other model families to avoid unnecessary constraints.

**Backward compatibility:** Workflow settings written by v0.9.0 are accepted and upgraded to v0.9.1. No ComfyUI core edits or new pip dependencies.

### Validation status

- Local CPU/unit/contract checks: **92 Python tests pass**, plus the existing **21 JavaScript tests** and one added migration test (**22 JavaScript tests**).
- The GitHub CI workflow reruns both test suites and bundles the release.
- **Real Windows ComfyUI 0.42.1 + RTX 5060 Ti + MOSS-Image Base/SFT + Comfy Kitchen GPU generation, SLG video/image quality, speed and VRAM are NOT verified by this release.** This remains a **pre-release beta**, not a production-stable release.

[日本語の使い方・注意事項](https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis/blob/main/README_JA.md)

---

## 日本語

**修正1：** ComfyUI公式 `SkipLayerGuidanceDiTSimple` が絶対パスのモジュール名で読み込まれたときの誤判定を修正しました。ファイル名が似ているだけの未知のコールバックは許可しません。

**修正2：** `--use-ck-attention` の標準Comfy Kitchen INT8に対応しました。抑制（Value操作）と強調（Attention加算マスク）を元のKitchen実装へ渡します。ただし実CUDAカーネルによる画像生成や速度計測は未実施です。モデル内部で指定されたINT8/SOL、Sage/Flashなどは引き続き対象外です。

**その他：** Illustrious／Anima／Krea2の通常ワークフローではMOSSの重み処理を適用せず、各モデルの標準プロンプト処理を保持します。v0.9.0の設定をv0.9.1で読み込めます。今回のテストはCPUベースであり、実際のMOSS GPU生成は未検証です。
