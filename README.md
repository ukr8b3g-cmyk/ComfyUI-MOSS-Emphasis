# ComfyUI-MOSS-Emphasis

**MOSS Emphasis 0.9 — experimental beta.** Use explicit `(phrase:weight)` syntax in ordinary **CLIP Text Encode** or upstream **Text Multiline** nodes. Configure it in **Settings → MOSS Emphasis**. No prompt-weight node needs to be placed on the canvas.

[日本語の説明](README_JA.md) · [0.9 release notes](docs/RELEASE_NOTES_0.9.md) · [Validation and limitations](docs/VALIDATION.md)

> CPU unit/contract tests are included. Real MOSS Base/SFT GPU generation and the actual ComfyUI browser UI have **not** been verified for this release. This is not a production-certified release.

## Install

From your existing ComfyUI `custom_nodes` folder:

```sh
git clone https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis.git
```

Or extract the release ZIP so `ComfyUI/custom_nodes/ComfyUI-MOSS-Emphasis/__init__.py` exists. Restart ComfyUI and reload the browser. **No additional pip dependencies, model downloads, KJNodes installation or LLM are required.** Uses PyTorch and aiohttp already provided by ComfyUI.

Requires **native ComfyUI MOSS-Image support**, its MOSS Qwen3.5 tokenizer, `ComfyAttention` / `AttentionTensorContainer`, and the documented extension Settings API. The standalone OpenMOSS HF-loader plugin is not an adapter supported by 0.9.

## Use

Keep your normal positive/negative/model wiring. In Settings → MOSS Emphasis:

- **Enable prompt weighting:** ON for the current workflow. New workflows default to OFF.
- **Strength:** start at 1.00. Both OFF and Strength 0 completely bypass rewriting, including syntax removal.
- **Diagnostic logging:** optional settings/target-ID logging. Full prompt text is not logged.

For example, in the normal positive field:

```text
portrait, (big eyes:0.5), (long hair:1.2), soft lighting
```

A STRING from Text Multiline, concatenation, or CSV nodes works when it reaches ordinary `CLIPTextEncode.text`. Base and SFT use the same native architecture adapter; there is no Base/SFT switch. Negative is left on its original path, and negative-field weighting is not added.

The Settings values belong to the **workflow**, not a live server-global switch. They are stored at `workflow.extra.moss_emphasis`. Each queued job captures its own values. PNG restoration works through the original workflow metadata when your image saver already saves that metadata; the extension does not force metadata saving on.

## Syntax

| Input | Meaning |
|---|---|
| `(phrase:0.5)` | Reduce the phrase's Value contribution |
| `(phrase:1)` | Remove explicit syntax; ordinary strength |
| `(phrase:1.5)` | Increase attention logit bias |
| `(phrase:0)` / `(phrase:-1)` | Zero / reverse Value at Strength 1; **not guaranteed concept removal** |
| `saber (fate)` | Literal parentheses, not implicit emphasis |
| `(saber (fate):1.2)` | Weight the name while preserving its inner parentheses |
| `((red hair:1.2):1.1)` | Multiply explicit nested weights: 1.32 |

Explicit and effective weights must be finite decimals within -2..4; maximum 128 weighted groups and 16 nesting levels. Escape literal parentheses/colons with backslashes when they would otherwise look like weight syntax. Weights affect only the marked occurrence, not every identical phrase. Boundary tokens use non-whitespace UTF-8 byte coverage.

**MOSS Layout JSON:** only `summary.caption` and `items[].caption` are interpreted. `items[].text`, boxes, labels and palettes are protected. Do not weight an entire JSON object. Krea2 JSON conversion is not part of this extension.

## 0.9 compatibility boundary

Supported execution contracts:

- `CLIPTextEncode → KSampler` or `KSamplerAdvanced`.
- `CLIPTextEncode → CFGGuider → SamplerCustomAdvanced`.
- Native MOSS-Image architecture and native MOSS Qwen3.5 CLIP.
- PyTorch/basic attention contracts; ordinary ModelSamplingSD3 and official SLG wiring are preserved. **Real SLG GPU parity is still unverified.**

Intentionally rejected rather than silently changed: configured INT8/SOL attention (`_attn` checkpoints), Sage/Flash overrides, torch.compile, Spectrum/TeaCache/NAG, MOSS Edit/reference/control/video paths, condition averaging/concatenation/regions/schedules, unknown guiders and integrated custom pipelines. Quantized *weights* are different from quantized *attention*: an otherwise native model with ordinary attention can pass the adapter, but real quantized-model generation remains unverified.

Turn the extension OFF for unsupported workflows. It never changes CFG, steps, seed, sampler, scheduler, Shift, model files or ComfyUI source files. Ordinary non-MOSS model paths pass through at runtime without stripping the text.

## API and transparency

The visible editor graph stays unchanged. A **private runtime node is added to a copy of the execution graph**, so it does appear in API execution records. Runtime inputs include versioned settings, which participate in ComfyUI's cache; changing Strength invalidates the correct computation. Existing KJ or independent MOSS weight nodes on the same path are rejected to avoid double weighting.

Use Settings → MOSS Emphasis → API export → **Export execution API JSON**, or call:

```json
POST /moss_emphasis/prepare
{"schema_version":1,"prompt":{...},"settings":{"enabled":true,"strength":1.0,"engine":"kj_dit_v1"}}
```

Send the returned `prompt` to the standard `/prompt` endpoint. Preparation errors never fall back to unweighted queueing. Ordinary ComfyUI API export does **not** necessarily include the runtime transformation. Exported prepared API JSON requires this extension; editable workflow JSON uses ordinary nodes and can be opened without it (weighting then requires reinstalling the extension).

## Tests and design

```sh
python -m unittest discover -s tests -v
node --test tests/frontend.test.mjs
```

The full Python suite needs the existing ComfyUI dependencies `torch` and `aiohttp`; tests are skipped if those packages are absent. No GPU weights are downloaded by the tests. See [implementation design](docs/SPEC_0.9.md).

GPL-3.0-only. [Attribution / upstream interfaces](NOTICE.md). KJ equations are used as the numerical basis, **not a promise of identical generated images**. The parser and workflow integration deliberately differ.
