# MOSS Emphasis 0.11.0 (Beta)

Adds an optional **Forge-compatible NegPiP / V-Scaling mode for native MOSS-Image** and plain-language English/Japanese documentation. Existing normal and PPM-reference modes remain available with their original arithmetic and model scope.

- **Select it explicitly:** Settings → MOSS Emphasis → enable prompt weighting → Use NegPiP → `Forge compatible`. Existing workflows do not switch methods automatically. V-Scaling defaults OFF; strength defaults to 1, range 0..2.
- **OFF and zero:** V-Scaling OFF or ON with strength 0 uses basic Forge NegPiP, including negative weights. It does not disable NegPiP. Master OFF bypasses the extension. The old normal Strength and PPM effect are retained but ignored in Forge mode; their own zero-bypass behavior is unchanged in the existing modes.
- **Different weighting path:** Forge-style segment tokenization, native empty-encoding interpolation and signed Attention Values. At V strength 1, magnitudes act on image-query Values while text queries read sign-only Values. Positive and Negative are processed independently; Negative stays the negative CFG branch. No guaranteed “double negative” interpretation or visual improvement is claimed.
- **Compatibility:** native MOSS only for Forge; every non-MOSS model automatically bypasses that mode with original text and retained settings. Existing normal/PPM SDXL/Illustrious and Anima support is unchanged. New mode excludes Layout JSON, custom templates, image references and processed/region/scheduled conditioning. Conflicting weighting/execution patches are rejected, including native ModelPatcher's separate wrapper store.
- **Preserved settings:** versions 0.9.0, 0.9.1, 0.10.0 and 0.10.1, including prior local Forge settings, remain readable. Runtime V1/V2 and schema 1/2/3 contracts remain; Forge uses private Runtime V3 / schema 4. Old-backend rejection stops queue/export and asks for a full restart. No new dependency or model download.
- **Documentation and licenses:** README comparison tables explain normal/PPM/Forge, V ON/OFF/0, prompt weight zero and Negative. Existing files retain GPL-3.0-only; the new Forge-derived module is AGPL-3.0-only, with attribution and both license texts. The Settings status links to the corresponding source of the actual installed version at `/moss_emphasis/source`; see [NOTICE](../NOTICE.md).

**Update:** restart ComfyUI itself, then reload the browser. A browser refresh alone cannot load the new Python code.

**Validation:** 143 Python tests, 52 frontend/locale tests, 14 existing native CPU contracts and 8 new native MOSS CPU contracts passed. Fixed Forge comparison covers 18 text cases / 108 token-and-coefficient cases with real Qwen tokenization (max float32 mask difference 1.1920928955078125e-7, tolerance 1e-6). Legacy MOSS remains bit-exact across 48 conditions; 48 PPM comparisons pass. Native CPU tests use small synthetic encoders/weights, not checkpoints; the new CPU process records zero CUDA initialization attempts. GPU generation, live Settings UI, Kitchen INT8 GPU behavior, image quality, speed and VRAM remain unverified. See [validation](VALIDATION.md).

[English README](../README.md) · [日本語README](../README_JA.md)

## 日本語

**標準MOSS-Image向けのForge互換NegPiP／V-Scaling**を追加したBeta版です。従来の通常／PPM方式と、その計算・対応モデル範囲は維持します。

- **明示的に選択：** 設定 → MOSS Emphasisで全体とUse NegPiPをONにし、`Forge compatible`を選択します。旧ワークフローは勝手に切り替わりません。V-Scalingは初期OFF、強度は初期1（0～2）です。
- **OFF／0の意味：** V OFFとV ON＋強度0は、負の重みも働く基本Forge NegPiPです。NegPiP全体の無効化ではありません。完全バイパスは全体OFFです。旧通常強度・PPM効果は保持してForgeでは使いません。従来方式での「強度／効果0＝バイパス」は維持します。
- **処理の違い：** 区間ごとのトークン化・標準の空埋め込み補間・符号付きValueを使用します。V強度1では重みの大きさを絵に反映する側へ移し、文章側は符号だけを反映します。Positive／Negativeを独立に処理しますが、NegativeはCFGの負側のままです。マイナス同士で必ず強調に戻る、画質が必ず上がるという意味ではありません。
- **対応範囲：** Forgeは標準MOSSのみ。他モデルでは原文の標準処理へ自動バイパスし、設定を保持します。従来のSDXL／Illustrious・Anima対応は維持します。新方式のLayout JSON・独自template・画像参照・加工済み／領域／時間指定の条件は初期対応外です。実ModelPatcherのwrapper storeを含む二重適用・競合を検出します。
- **保存互換：** 0.9.0・0.9.1・0.10.0・0.10.1と先行ローカルForge設定を読み込めます。旧V1/V2・schema1/2/3は維持し、Forgeだけ内部V3／schema4を使います。旧backendが新版設定を拒否すると投入を止めて再起動を案内します。追加依存・モデルダウンロードはありません。
- **説明・ライセンス：** 日英READMEに平易な比較表、V ON/OFF/0とプロンプト内の重み0、Negativeの違いを記載。既存GPLを維持し、新しいForge由来モジュールはAGPLv3で扱います。両LICENSE・出典と、実際の導入版の対応ソースを取得するSettingsリンクを含みます。

**更新後はComfyUI本体を再起動し、ブラウザーを再読み込みしてください。** Python143件・画面側52件・既存native CPU14件・新native CPU8件が成功。Forge108条件比較・旧MOSS48条件bit一致・PPM48条件比較を確認しました。実checkpointによるGPU生成、実画面、Kitchen INT8のGPU動作・画質・速度・VRAMは未検証です。
