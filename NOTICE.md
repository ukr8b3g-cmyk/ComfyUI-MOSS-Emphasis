# Attribution and upstream interface references

ComfyUI-MOSS-Emphasis is GPL-3.0-only. Copyright (C) 2026 ComfyUI-MOSS-Emphasis contributors.

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
