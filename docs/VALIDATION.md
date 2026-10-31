# Validation — v0.10.1 (2026-10-31)

Version 0.10.1 includes the audit fixes below. The published v0.10.0 ZIP/tag remains unchanged. Prior 0.9.0/0.9.1/0.10.0 settings preserve their selected method, strengths and model scope when loaded by the new backend/frontend.

CPU verification on Windows, installed ComfyUI **0.43.0**, commit `426f5eea52a7ece1dd599fff4cb6cd1f352ddd24`. No checkpoints were loaded or downloaded for these tests.

| Gate | Result |
|---|---|
| Python unit/regression suite | 127 passed, including legacy MOSS, overflow regressions, transactional schema-3 graphs and prior-version settings |
| Frontend/locale suite | 43 passed; workflow restoration, method changes, migration, queue/export and stale backend handling |
| Real ComfyUI CPU contracts | 14 passed; native SDXL/Anima tokenizers and token-weight encoders, ModelPatcher clone/hooks, conditioning batching, V3 node registration, real small attention modules and unsupported-model bypass |
| Pinned PPM SDXL comparison | 6 prompts, including empty, unit/zero/negative/large weights, nested syntax and multiple CLIP chunks; K/V and pooled agree at float64 tolerance 1e-12 |
| Pinned PPM Anima comparison | 4 prompts × 2 preprocessing routes; context and Value-sign metadata agree exactly after matching dtype |
| MOSS pinned PPM comparison | 48 cases; maximum absolute error 4.45e-16 |
| Saved original MOSS engine | 48 cases bit-exact |

The native contracts use actual installed ComfyUI modules with small deterministic encoder/adapter stand-ins instead of checkpoint weights. SDXL BasicTransformerBlock and Anima/Cosmos Attention execute on CPU. Tests cover original Negative numerics, pooled/mask/IDs preservation, different CLIP chunk lengths, reversed CFG row order, positive-only and negative-only calls, batch size 2, Anima length above 512, deferred and inference preprocessing, FP64/FP32/FP16/BF16 Value dtype, coefficient overflow, duplicate patch rejection and input/options ownership. Illustrious is covered through its native SDXL architecture contract, not checkpoint generation.

Model-auto settings use schema 3 and a private V3-API runtime. Old schema 1/2 and runtime V1 remain supported. Tests assert that loading an old workflow does not upgrade its model scope; an explicit weighting-setting change does. The MOSS attention arithmetic is retained.

### External audit follow-up

- Reproduced NUM-01 before editing: finite FP16 weight -60000 and Value 2 produced infinity; finite mask 40000 plus bias 40000 also overflowed. The new regressions cover FP16/BF16/FP32/FP64, Tensor/container inputs, dtype conversion, legal -inf mask blocking and unchanged input/unselected rows. Finite output arithmetic is unchanged; invalid results now raise `INVALID_WEIGHT`, with no clipping or fixed weight cap.
- MOSS decides whether a Value multiplier can amplify from CPU coefficient metadata. Nonamplifying multipliers and the ordinary no-existing-mask path add no finite-check readback. Amplification needs a result check in each affected block; an existing mask combined with bias is also checked. No GPU speed/VRAM benefit is claimed.
- Reproduced Anima's analogous product overflow using native preprocessing and a tiny constant adapter, in both deferred and inference preprocessing and both methods. A model-local `preprocess_text_embeds` guard is installed only for amplifying weights, checking after native multiplication rather than in each attention block. Native Negative, finite results, original model ownership and patch removal are covered.
- Reproduced UI-01 before editing: schema-3 rejection remained a generic settings error. Rejections matching the submitted supported schema (2 or 3) now give localized backend-restart instructions, stop queue/export and retain workflow settings. Other invalid settings/errors do not become restart messages.
- The audit's optional all-Positive Q/K/V copy optimization was not needed to fix either defect and is unchanged. Real browser/GPU gates remain open.

### Reproduce

Unsupported-model regression: both auto engines bypass Krea2, SDXL Refiner and unknown native model types, including an unrecognized MOSS diffusion implementation. Original MODEL/Negative identity and native positive/pooled values are preserved, existing patches remain untouched, and saved settings are unchanged. Returning to a supported model resumes the selected method; a wrong CLIP for a supported MODEL still fails explicitly. Legacy schema 1/2 behavior and execution-graph restrictions are unchanged.

```sh
python -B -m unittest discover -s tests
node --test tests/frontend.test.mjs tests/locales.test.mjs
python -B tests/native_contract.py --comfy-root /path/to/ComfyUI
```

For independent PPM comparisons, optionally pass `--reference-dir /path/to/external/references` containing unmodified `src/negpip/unet_negpip.py` and `anima_negpip.py` from commit `926e8bb5f3c4b652e5b42a451d76cb3dc1d4df73`, named `ppm_unet_926e8bb5.py` / `ppm_anima_926e8bb5.py`. References are not bundled or downloaded by tests. Without them the two PPM comparison tests are explicitly skipped. The separate MOSS differential harness was run locally; the shipped MOSS regression tests also exercise its equations.

### Unperformed gates

New-adapter checkpoint loading, GPU image/quality comparison, real GPU backend speed/VRAM, installed browser Settings rendering and live workflow tab/PNG restoration. Unit/frontend doubles and real CPU module contracts do not establish these results. No GPU generation or service restart is performed by the tests. Version 0.10.1 packages these changes; previous releases/tags are retained and Registry publishing is separate.

## Historical validation report — 0.9

Executed in an isolated build container on 2026-10-24.

- Python: 3.13.5.
- PyTorch: 2.10.0+cpu; CUDA available: False.
- aiohttp: 3.13.3.
- Node.js: v22.16.0.

## Executed

- `python -m unittest discover -s tests -v`: **76 tests passed**, including actual CPU tensor arithmetic and a local aiohttp prepare endpoint.
- `node --test tests/frontend.test.mjs`: **15 tests passed**, using mocked ComfyUI contracts.
- Python compileall and JavaScript syntax checks: passed.

Coverage includes OFF/zero bypass, explicit/nested weights, duplicate occurrences, Unicode byte-BPE alignment, protected JSON fields, transactional graph transformation, deterministic IDs, repeated prepare, cache settings, preserved negative links, duplicate-engine rejection, positive-only tensor modification, compact mask preservation, backend rejection, exception isolation, Settings restoration, frozen queue snapshots and prepare failures that prevent queueing.

The engine tests use small tensors and interface doubles with 42 joint-block slots, **not loaded MOSS weights**. The SLG check verifies preserved hooks/wiring, **not real SLG generation**. The tokenizer tests use synthetic byte-BPE pieces, **not downloaded Qwen weights/tokenizer assets**.

## Not executed / not claimed

Actual ComfyUI installation/browser UI, real workflow tab switching and PNG restoration, native tokenizer/model loading, Base/SFT GPU generation, KJ image parity, actual SLG parity, quantized model generation, GPU timing/VRAM and live cancellation cleanup. The user's local Windows environment has not been modified.

This beta release does not close the original V1 real-browser/GPU acceptance gates. Tests must not be presented as proof of image quality or complete platform compatibility.

## Japanese locale and settings help (post-release `main` documentation update)

ComfyUI's native `custom_nodes/<extension>/locales/ja/main.json` and `locales/ja/settings.json` load through `CustomNodeManager.build_translations()`, and Vue's Settings UI translates category headings, names, help tooltips and combo option labels by setting ID. The values saved in the workflow remain the original stable IDs and English combo option values.

`node --test tests/*.test.mjs` now includes additional static locale-contract checks for all four settings, the General / Advanced / Tools headings and both API export options. **A real running Japanese ComfyUI browser UI has not yet been observed or validated by this test.** The attached screenshot is the English UI supplied by the project user, reproduced as a compressed WebP image.


## 0.9.1 SLG and Comfy Kitchen INT8 patch (CPU tests)

- Official SLG provenance logic now checks the real ComfyUI `nodes.py` sibling `comfy_extras/nodes_slg.py`, the loaded module object and the nested `execute` code object. It supports absolute-filepath module names while rejecting an unrelated file merely named `nodes_slg.py`.
- Comfy Kitchen global INT8 is allowed only if selected as the original `optimized_attention` and the original callable has a working `container_function` (prequantized path). Positive-only value scaling and additive masks are forwarded without swapping to PyTorch. Configured per-layer INT8/SOL remains rejected. Sage/Flash/custom overrides remain rejected.
- CPU stand-ins assert selected backend, positive/negative isolation, no-mask 0.5, biased-mask 1.5, mixed weights, container consumed once, SLG functions preserved, unknown callbacks refused and no silent float32 fallback.
- Backward compatibility: 0.9.0 persisted settings are accepted by 0.9.1 backend and UI.
- **Execution gate:** Python unittest suite now has 92 tests, but **real ComfyUI 0.42.1 MOSS Base/SFT and global Kitchen GPU generation remain unverified**. A simulated kernel receiving tensors is not a real INT8 GPU invocation.
# Forge-compatible implementation — v0.11.0 Beta, 2026-11-01

Reference: specification revision 1.1; Forge NegPiP `0570f23d`, Forge parser `2d79fc2f`.
Version markers are 0.11.0. This section records local validation; GitHub CI and public artifact verification are separate publication checks.

- Baseline before editing: Python 127, frontend/locale 43, native ComfyUI CPU 14 passed.
- Feature implementation: Python **142**, frontend/locale **51**, existing native CPU **14** and new native MOSS CPU **8** passed before versioning. Release validation also covers 0.10.1 legacy and local Forge settings migration; see the 0.11.0 release notes for final totals.
- Fixed external Forge reference: **18** text cases / **108** token-and-coefficient cases, using the real native Qwen tokenizer. Token IDs match the segment reference; maximum float32 Value-mask difference **1.1920928955078125e-7** (declared atol/rtol 1e-6). FP64 encoder-scale reference uses 1e-12. Native empty/unit prompts retain ComfyUI results bit-exactly, including its parenthesis unescaping; this does not claim all Forge empty/template conventions are identical.
- Independent Attention tests cover FP64/FP32/FP16/BF16, both CFG orders, Positive-only and Negative-only forwards, batch 1/2, masks, Container single ownership, output reshape and overflow. Small-tensor dtype tolerances were fixed before comparisons (1e-12 / 1e-6 / .004 / .04 for the independent double softmax comparison); existing mode tolerances were not relaxed.
- Real ComfyUI ModelPatcher, wrappers, native token-weight encoder and a **42-block MOSS structure with small synthetic weights** execute on CPU. The actual checkpoint/text model is not loaded. The new standalone CPU process hides CUDA/HIP devices; a guard recorded **0 CUDA initialization attempts**. Kitchen's unmodified hardware probe was identified while setting up that fixture; no core or user startup settings were changed.
- Legacy MOSS **48 conditions bit-exact**; fixed PPM **48 conditions**, max absolute difference **4.440892098500626e-16**. Existing SDXL/Illustrious and Anima CPU contracts pass. Old parser, token alignment, PPM equations and model adapters remain unchanged.
- Final audit added a native ModelPatcher wrapper-store check in Forge mode: an already weighted MODEL or a foreign execution wrapper is rejected before encoding, including the encoder-only path. The regression uses the real wrapper store, not only model_options doubles.
- License policy: existing GPL-3.0-only files retained; Forge-derived module AGPL-3.0-only with full license and attribution. The installed source ZIP endpoint and Settings link are tested; personal settings, workflow JSON, Git data and external references are excluded.

実GPU生成、実際のSettings画面、Kitchen INT8のGPU完走・速度・VRAM・画質は未検証です。ComfyUI_testへの配置はローカル作業記録で照合し、利用には本体再起動とブラウザー再読み込みが必要です。他の導入先・設定・workflow・公開版は変更しません。

