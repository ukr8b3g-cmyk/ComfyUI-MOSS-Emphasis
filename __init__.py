"""ComfyUI-MOSS-Emphasis 0.10.0: Settings UI, no manually placed prompt node."""
from .moss_emphasis.config import RUNTIME, RUNTIME_V2
from .moss_emphasis.runtime import Runtime, RuntimeV2
from .moss_emphasis.api import install_routes
from comfy_api.latest import io


class RuntimeV2Node(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id=RUNTIME_V2, category="MOSS Emphasis/internal",
            description="Internal execution node inserted by MOSS Emphasis. Do not add manually.",
            inputs=[io.Model.Input("model"), io.Clip.Input("clip"),
                    io.String.Input("text", multiline=True), io.String.Input("settings_json"),
                    io.Conditioning.Input("negative"), io.String.Input("source")],
            outputs=[io.Model.Output(), io.Conditioning.Output(), io.Conditioning.Output()],
        )

    @classmethod
    def execute(cls, model, clip, text, settings_json, negative, source=""):
        return io.NodeOutput(*RuntimeV2().execute(model, clip, text, settings_json, negative, source))


NODE_CLASS_MAPPINGS = {RUNTIME: Runtime, RUNTIME_V2: RuntimeV2Node}
NODE_DISPLAY_NAME_MAPPINGS = {name: "MOSS Emphasis internal runtime" for name in NODE_CLASS_MAPPINGS}
WEB_DIRECTORY = "./web"
install_routes()
