# MOSS Emphasis 0.10.1 (Beta)

Fixes numerical overflow protection and update-time restart instructions found in the v0.10.0 audit.

- **Numerical protection:** finite coefficients can still overflow when multiplied by model Values. MOSS Value multiplication, existing mask conversion/composition and Anima post-adapter multiplication now raise `INVALID_WEIGHT` on invalid results. Intentional mask blocking with `-inf` remains valid. No fixed prompt-weight cap, clamping or automatic method switch was added; finite arithmetic and native Negative handling are preserved.
- **Scoped checks:** MOSS checks amplified Values; nonamplifying multipliers and the ordinary no-existing-mask path add no finite-check readback. Anima checks at native preprocessing only when weights can amplify, covering both preprocessing routes. No GPU performance improvement is claimed.
- **Update guidance:** old backends rejecting the submitted supported schema 2 or 3 now produce Japanese/English `BACKEND_RESTART_REQUIRED` instructions. Queue/API export stops and saved settings remain intact. Other invalid settings retain their own errors.
- **Compatibility:** settings from 0.9.0, 0.9.1 and 0.10.0 retain their method, strengths and model scope. Native MOSS-Image, SDXL/Illustrious and Anima support, unsupported-model auto bypass, and exclusive normal/NegPiP selection remain unchanged. No new dependencies.

**Update:** restart ComfyUI itself after updating, then reload the browser. Browser refresh alone does not load new Python code.

**Validation:** 127 Python regressions, 43 frontend/locale checks and 14 real ComfyUI CPU contract tests passed. Saved original MOSS results remain bit-exact across 48 conditions; 48 pinned PPM MOSS comparisons and native SDXL/Anima reference comparisons also pass. CPU contracts use small encoder/adapter stand-ins, not loaded checkpoints. GPU generation, live UI, Kitchen/SLG GPU behavior and GPU speed/VRAM remain unverified.

[README](https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis/blob/v0.10.1/README.md) · [Validation](https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis/blob/v0.10.1/docs/VALIDATION.md)

## 日本語

v0.10.0の監査で見つかった、数値保護と更新時の再起動案内を修正したBeta版です。

- **数値保護：** 係数自体が有限でも乗算結果はoverflowする場合があります。MOSSのValue乗算、既存maskの型変換・合成、Animaのadapter後の乗算で不正な結果を検出すると、`INVALID_WEIGHT`で停止します。maskの意図した`-inf`による遮断は維持します。固定重み上限・丸め込み・方式の自動変更は追加せず、有限結果の計算と通常のNegative処理を保ちます。
- **検査負荷：** MOSSはValueを増幅する場合に結果を検査し、増幅しない係数や通常の既存maskなし経路には有限性検査の読戻しを追加しません。Animaは増幅重みの場合だけnative前処理で検査し、通常／遅延の両経路に対応します。GPUでの高速化は主張していません。
- **再起動案内：** 起動中の旧バックエンドが送信したschema 2／3を拒否した場合、日本語／英語で`BACKEND_RESTART_REQUIRED`を案内します。Queue/API exportを停止し、保存設定を保持します。その他の設定エラーは再起動扱いにしません。
- **互換性：** 0.9.0・0.9.1・0.10.0の保存設定は、方式・強さ・対象モデル範囲を保って読み込めます。対応3系統、未対応モデルの自動バイパス、通常方式／NegPiPの排他切り替えは維持します。追加依存はありません。

**更新後はComfyUI本体を再起動し、ブラウザーを再読み込みしてください。** Python127件・画面側43件・実ComfyUI CPU契約14件が成功し、旧MOSS48条件のbit一致と固定PPM比較を確認しました。実checkpointを使うGPU生成・実画面・Kitchen/SLGのGPU動作・速度/VRAMは未検証です。

[日本語README](https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis/blob/v0.10.1/README_JA.md)
