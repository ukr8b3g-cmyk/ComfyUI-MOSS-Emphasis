# MOSS Emphasis 0.9 implementation contract

This is the implementation of the 2026-10-24 V1 design, released as a **0.9 beta**, not as completion of the real-browser/GPU acceptance gates.

## Execution architecture

The visible graph remains standard nodes. `workflow.extra.moss_emphasis` is authoritative. Settings is only its UI editor. `api.queuePrompt` is wrapped once; a submitted workflow/prompt snapshot is frozen before awaiting `/moss_emphasis/prepare`. The original queue method receives the prepared API graph and unchanged queue options only after successful preparation. OFF/Strength 0 makes no prepare request. Global fetch/tokenizer/sampler monkey patches are not used.

Preparation copies and validates the API graph, identifies standard positive encoder paths, creates deterministic internal runtime IDs, and rewires only the supported target's MODEL and positive CONDITIONING inputs. Other consumers and Negative keep their original links. Repeated preparation reconstructs the original from checked runtime provenance; modified provenance, cycles, collisions and duplicate weighting fail closed. `settings_json` contains schema, engine, parser and implementation versions plus enabled/strength, but not timestamps, client IDs or diagnostic flags.

Internal runtime definitions are removed from the frontend node-add lists, not from the backend registry. They remain visible in execution JSON. API export explicitly prepares the graph and includes the original editable workflow. Prepared JSON requires the extension; editable workflows remain loadable without it.

## Parser/token contract

Only explicit finite decimal weights are supported. Individual and nested effective weights: -2..4. Nesting: 16. Weighted groups: 128. Input length: 262144 characters. A prompt with no weight processing is returned exactly as received; it is not reformatted or normalized by this extension. ON with `(x:1)` removes the syntax. OFF/Strength 0 does not.

Positions, not repeated phrase searches, determine weights. Explicit nested weights multiply. Literal character-name parentheses survive. MOSS Layout JSON edits only `summary.caption` and `items[].caption`, preserving other strings/values and unedited source formatting. Unweighted text is not reserialized.

The runtime uses actual Qwen byte-BPE token pieces and verifies the complete native chat-template bytes. It does not guess offsets from a phrase search. Non-whitespace UTF-8 coverage averages a token spanning different weights. Chat/vision special tokens, multiple token chunks, custom embeddings, ambiguous normalization, unexpected conditioning lengths and truncation fail rather than partially weighting. Weighted prompts are limited to 4096 tokens including the template.

## Engine contract

For phrase weight w and Strength s:

- w <= 1: Value multiplier = 1 + s * (w - 1), logit bias = 0.
- w > 1: Value multiplier = 1, logit bias = 2 * s * (w - 1).

A cloned ModelPatcher receives local wrappers for native MOSS's 42 joint-attention blocks. Qwen, the two text refinement blocks, RoPE, projections, MLP, latent format and sampling settings are not changed. The reference positive tensor and actual cond/uncond row layout are checked. A same-length but different conditioning is not accepted. State is per model clone and per forward, never process-global.

Value tensors are copied before modification; existing compact additive/bool masks are combined, not overwritten. No full sequence-by-sequence mask is allocated for emphasis. At most one device copy of the positive reference is retained per clone; standard ComfyUI cache lifetime applies. No forced cache clearing.

0.9 supports native PyTorch/basic attention only. Configured INT8/SOL attention and attention overrides are refused rather than silently replacing optimized kernels. Quantized *weight* paths may satisfy the adapter but are not GPU-certified. ModelSamplingSD3 and official SLG hooks are preserved by the contract; their actual GPU interaction remains a required future acceptance gate.

## Scope

Standard CLIPTextEncode feeding KSampler/KSamplerAdvanced/CFGGuider is supported; CFGGuider may feed SamplerCustomAdvanced. STRING producers are not modified. Native Base/SFT share the adapter. Ordinary non-MOSS models pass through at runtime without parsing the text. Unknown integrated paths still require OFF; static graph preparation cannot infer arbitrary custom pipelines.

No Qwen encoder intervention, Negative-field weighting, Native Log engine, Krea2 conversion, Edit/reference/control/video, arbitrary conditional composition, NAG, torch.compile or forecasting acceleration in 0.9. Existing prompt-weight engines on the same path are an error, not chained.

## Acceptance still outstanding

Actual ComfyUI Settings rendering, PNG load-back, multiple real browser tabs, native tokenizer/model loading, Base/SFT generation, OFF equivalence on GPU, KJ single-phrase comparison, quantized models, real SLG parity, cancellation cleanup and real GPU memory/performance must be tested separately. No inference quality/speed guarantee is made by the CPU tests.
