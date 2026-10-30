# ComfyUI-MOSS-Emphasis v0.10.0

[日本語](README_JA.md) · [Validation](docs/VALIDATION.md) · [Attribution](NOTICE.md)

Prompt weighting and **NegPiP** from **Settings → MOSS Emphasis**, using ordinary **CLIP Text Encode**. No prompt-weight node needs to be placed on the canvas.

**v0.10.0 includes NegPiP** for three model families: **native MOSS-Image, SDXL / Illustrious, and native Anima**. In auto model mode, **every other architecture automatically bypasses this extension**, including Qwen-Image, FLUX, SD1.5, SD3, Krea2 and SDXL Refiner; ordinary generation continues. These are CPU-tested experimental features. GPU quality, speed and VRAM for the new adapters have not been tested. [Release notes](docs/RELEASE_NOTES_0.10.0.md).

## Install / update

Run in ComfyUI's `custom_nodes` directory:

```sh
git clone https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis.git
```

For an existing installation, update the repository, **restart ComfyUI itself**, then reload the browser. A browser refresh alone cannot load new Python code. No additional pip dependencies, PPM/KJNodes installation or model downloads are required. Use a recent ComfyUI with native support for the selected model and the V3 node API; see the tested version in [Validation](docs/VALIDATION.md).

## Choose a method

Keep your normal model, positive and negative wiring. Open **Settings → MOSS Emphasis**:

| Setting | Meaning |
|---|---|
| Enable prompt weighting | Master switch, saved per workflow. New workflows start OFF. |
| Strength | Normal emphasis only, 0–4; start at 1. |
| Use NegPiP | OFF = normal emphasis; ON = model-specific NegPiP. The methods are exclusive. |
| NegPiP effect | NegPiP only, 0–1; start at 1. |
| Current method | Shows the method and auto model / legacy MOSS mode. |

In auto mode, actual **MODEL and CLIP types** select the adapter; checkpoint filenames do not. There is no model selection menu. Use NegPiP does not activate anything while the master switch is OFF. The inactive strength is retained but ignored.

The selected strength/effect at **0**, or master OFF, bypasses the extension completely. **Native SDXL/Anima weighting still applies to the original text.** Extension OFF does not disable a model's built-in weighting.

![Earlier MOSS Emphasis Settings UI](docs/images/moss-emphasis-settings.webp)

*This image predates NegPiP controls. Current order: Enable → Strength → Use NegPiP → NegPiP effect → Current method. ComfyUI's Japanese locale translates labels and hover help; persisted IDs stay unchanged.*

## Model support

| Model | Normal emphasis | NegPiP at effect 1 | Status |
|---|---|---|---|
| Native MOSS-Image Base / SFT | Existing KJ-style Value scaling / attention bias | PPM-reference log-absolute-weight bias and Value sign | Existing arithmetic preserved; CPU regressions |
| Native SDXL Base / Illustrious | Native CLIP-L/G weighting | Absolute CLIP weights, separate Key/Value; negative weights reverse Value | CPU tokenization, encoding, batching and real attention-module tests |
| Native Anima | Native T5 token weights after the Qwen adapter | Absolute T5 weights and negative-token Value sign | CPU preprocessing, deferred forward, padding, batching and real attention-module tests |
| Qwen-Image, FLUX, SD1.5, SD3, Krea2, SDXL Refiner, all other architectures | Automatically bypassed | Automatically bypassed | Ordinary model processing continues |

In auto model mode, unsupported architectures skip this extension's weighting and attention patches, preserving the original text, MODEL and Negative. The saved ON/OFF and method settings stay intact; switching back to a supported model activates the selected method again. The server log records the bypass. A supported MODEL with the wrong CLIP still produces a mismatch error. Graph/conditioning compatibility checks still apply; automatic model bypass does not add support for integrated custom samplers or unsupported graph layouts.

Qwen-Image here means the image-generation architecture. MOSS and Anima may use a Qwen text encoder; the encoder name alone does not make them unsupported.

Illustrious uses the native SDXL architecture route, not a filename allowlist. No Illustrious/Anima checkpoint was loaded for these tests. Anima uses existing T5 **tokenizer metadata**; this extension does not load a T5 encoder model. MODEL and CLIP must be a matching native pair.

**Positive weighting is the scope.** Negative retains its native numerical meaning, including native weights it already contains. SDXL NegPiP internally transports identical K/V copies of Negative to compensate for the attention split; it does not reinterpret Negative with NegPiP.

## Prompt weights and zero

```text
1girl, (red hair:1.2), (realistic:-5)
```

A negative number is interpreted within the selected method; it does not automatically switch to NegPiP. Prompt weights have no fixed min/max. Non-finite values, overflowing coefficients and unrepresentable conditioning are rejected. Larger magnitudes do not guarantee stronger visual suppression.

| Model, strength/effect = 1 | Weight 0 | Weight 1 |
|---|---|---|
| MOSS normal | Value multiplier 0; Key remains | Ordinary weight |
| MOSS NegPiP | Absolute weight floored to 1e-4 for bias; positive Value sign | Relative weight 1; normalized with other tokens |
| SDXL normal / NegPiP | Empty-prompt-reference embedding; positive NegPiP sign | Native embedding |
| Anima normal / NegPiP | Corresponding adapted context multiplied by 0; positive NegPiP sign | Native weight |

None guarantees concept deletion. `(realistic:1)` is ordinary weighting, not a special realism boost.

**Syntax differs by model:** MOSS preserves explicit decimal syntax, literal unweighted parentheses, nested products, 128-group/16-level limits and character-position mapping. Its Layout JSON protection applies only to `summary.caption` / `items[].caption`. SDXL/Anima use their **native tokenizer's** parentheses, escaping, nesting and token weights. MOSS JSON protection does not apply to them; this is not an A1111/Compel normalization mode.

For SDXL/Anima normal emphasis, Strength `s` maps token weight `w` to `1+s*(w-1)`. NegPiP effect `t` uses `1+t*(abs(w)-1)` and negative Value multiplier `1-2*t`. Effect **1** is the pinned PPM equation comparison point; intermediate effects are extension-specific. At **0.5**, negative-token Value becomes zero but the token remains. MOSS retains its log-bias interpolation.

## Workflows and compatibility

Supported: ordinary `CLIPTextEncode → KSampler / KSamplerAdvanced`, or `CLIPTextEncode → CFGGuider → SamplerCustomAdvanced`. Text Multiline/CSV/concatenation can feed `CLIPTextEncode.text`. Standard LoRA and CLIP skip stay on the native encoder path.

Initial scope excludes `CLIPTextEncodeSDXL`, Advanced CLIP, regional/scheduled/combined conditioning, ControlNet/IPAdapter, Refiner, standalone HF loaders and integrated custom samplers. Upstream weighting/attn2 replacement patches are rejected. Use OFF for unsupported workflows.

MOSS retains its existing backend boundary: PyTorch/basic, native global Comfy Kitchen INT8 (`--use-ck-attention`) integration and official SLG callbacks; no Sage/Flash/SOL override or configured per-layer INT8. Real Kitchen/SLG GPU operation remains unverified. SDXL/Anima use native hooks and retain the selected kernel; CPU tests do not certify every GPU backend.

Saved **schema 1/2** workflows retain their old MOSS-only behavior. Loading them does not silently activate weighting on other models. To enable auto model mode, explicitly change a weighting setting (e.g. master OFF then ON), then save. Status changes from **legacy MOSS** to **auto model**. Diagnostic logging alone does not migrate the workflow. Both strengths survive method changes and tab switches.

Private runtime nodes are inserted only into a copy of the execution graph; editor wiring stays intact. Each job captures its settings, which participate in caching. No global tokenizer/attention replacement, model-file changes or ComfyUI source modifications. CFG, sampler and scheduler stay unchanged.

## API and tests

Use **Settings → MOSS Emphasis → API export → Export execution API JSON**, or prepare an actual API graph with:

```json
POST /moss_emphasis/prepare
{"schema_version":1,"prompt":{},"settings":{"schema_version":3,"enabled":true,"engine":"negpip_auto_v1","strength":1,"negpip_strength":1}}
```

Replace `prompt` with the actual graph, then send the returned `prompt` to `/prompt`. Preparation failures never queue an unweighted fallback. The prepare envelope stays version 1; workflow settings use schema 3. Prepared graphs require this extension. Ordinary ComfyUI API export may omit the transformation.

```sh
python -m unittest discover -s tests -v
node --test tests/frontend.test.mjs tests/locales.test.mjs
python -B tests/native_contract.py --comfy-root /path/to/ComfyUI
```

[Validation](docs/VALIDATION.md) separates unit tests, real CPU module contracts and unperformed GPU/UI checks. GPL-3.0-only; [NOTICE](NOTICE.md) lists PPM/KJ/native references. No promise of identical generated images.
