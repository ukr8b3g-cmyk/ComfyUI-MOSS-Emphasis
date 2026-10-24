# Validation report — 0.9

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
