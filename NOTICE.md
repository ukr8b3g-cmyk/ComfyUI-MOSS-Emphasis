# Attribution and upstream interface references

Existing ComfyUI-MOSS-Emphasis files are GPL-3.0-only. Copyright (C) 2026 ComfyUI-MOSS-Emphasis contributors.
The Forge-derived `moss_emphasis/forge_negpip.py` is AGPL-3.0-only; see the additional notice below.

The numerical design follows Kijai's MOSS/Krea2 prompt weighting equations. The independently structured parser, graph preparation, Settings controller and guarded runtime in this repository were written for this extension. No KJNodes or independent PromptWeight installation is required.

References used during design/interface review (not bundled dependencies):

- Kijai / ComfyUI-KJNodes, GPL-3.0, `eaa8fee753faf37d1539804d89a46d3e0f40963d`, `nodes/model_optimization_nodes.py`:
  https://github.com/kijai/ComfyUI-KJNodes
- levzzz5154 / ComfyUI-MOSS-PromptWeight, GPL-3.0, `3802c2c601f19e0b97d4c151e520f0bbc7e2e471`:
  https://github.com/levzzz5154/ComfyUI-MOSS-PromptWeight
- ComfyUI native MOSS, attention containers, patcher and SLG contracts, reviewed at `7cebca52227c63b4180ceed448cbd7ad22903b6d`:
  https://github.com/Comfy-Org/ComfyUI
- ComfyUI frontend queue/extension interfaces, reviewed at `48880f80a404e9b84a62a089a83e11885ad03fa1`:
  https://github.com/Comfy-Org/ComfyUI_frontend
- Official extension Settings documentation:
  https://docs.comfy.org/custom-nodes/js/javascript_settings

These references identify reviewed contracts, not a claim of end-to-end execution against those repositories. In particular the independent node's Qwen encoder patches and Linear/Log modes are NOT included. Model weights and upstream code/assets are not distributed here.

## NegPiP and cross-model numerical references

- pamparamm / ComfyUI-ppm, AGPL-3.0, pinned commit `926e8bb5f3c4b652e5b42a451d76cb3dc1d4df73`:
  [MOSS](https://github.com/pamparamm/ComfyUI-ppm/blob/926e8bb5f3c4b652e5b42a451d76cb3dc1d4df73/src/negpip/moss_negpip.py),
  [SDXL](https://github.com/pamparamm/ComfyUI-ppm/blob/926e8bb5f3c4b652e5b42a451d76cb3dc1d4df73/src/negpip/unet_negpip.py),
  [Anima](https://github.com/pamparamm/ComfyUI-ppm/blob/926e8bb5f3c4b652e5b42a451d76cb3dc1d4df73/src/negpip/anima_negpip.py).
- Original NegPiP lineage: [laksjdjf/cd-tuner_negpip-ComfyUI](https://github.com/laksjdjf/cd-tuner_negpip-ComfyUI/blob/938b838546cf774dc8841000996552cef52cccf3/negpip.py).
- Native ComfyUI `sd1_clip`, `sdxl_clip`, `text_encoders/anima`, `model_base.Anima`, `ldm/anima/model`, `ldm/cosmos/predict2` and ModelPatcher contracts.

PPM is a numerical/interface reference, not a bundled dependency. These adapters reuse ComfyUI's native encoders and implement their own token-coefficient/conditioning transport; they do not vendor PPM's encoder or wrapper implementations. Fixed upstream source used for differential tests remains outside this distribution under its upstream terms. Tests optionally load those external files via `--reference-dir`, without automatic downloads. Intermediate effect, workflow-scoped selection, original Negative preservation and legacy schema handling are extension-specific.

## Forge-compatible implementation (added in 0.11.0)

`moss_emphasis/forge_negpip.py` adapts the Original prompt parser from
[Haoming02/sd-webui-forge-classic, 2d79fc2ffefa63f4429c4abe35324e66977983d5](https://github.com/Haoming02/sd-webui-forge-classic/blob/2d79fc2ffefa63f4429c4abe35324e66977983d5/backend/text_processing/parsing.py)
and segment tokenization / encoder-Value coefficient splitting from
[flyfront/sd-forge-negpip, 0570f23d3f2505e40937a1e4290ec1e533debb6d](https://github.com/flyfront/sd-forge-negpip/blob/0570f23d3f2505e40937a1e4290ec1e533debb6d/lib_negpip/moss.py).
The Forge repository's LICENSE credits AUTOMATIC1111 (2023), lllyasviel (2024), Haoming02 (2025).
The NegPiP package header credits hako-mikan (2025), Haoming02 (2026), under AGPL version 3 or later; this adaptation uses version 3.
The new module is AGPL-3.0-only, with the license in `LICENSE-AGPL-3.0`.
2026 changes: native ComfyUI token/conditioning transport, bounds and finite checks,
independent Positive/Negative routing, model-local Attention and no global Forge hooks.
Original reference files and Forge/PPM runtimes are not bundled dependencies.

GPLv3 section 13 and AGPLv3 section 13 permit this combination. Existing GPL files retain
their license; AGPL section 13's remote-network source requirements apply to the combination.
The Settings status includes a prominent corresponding-source link to `/moss_emphasis/source`,
which supplies the actual installed code, tests, build script, documentation and both licenses,
including local modifications. It does not substitute the older public GitHub release for this source.
Redistributors must retain the notices, applicable license terms and corresponding source of their modified version.
