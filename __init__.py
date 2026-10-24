"""ComfyUI-MOSS-Emphasis 0.9: Settings UI, no manually placed prompt node."""
from .moss_emphasis.config import RUNTIME
from .moss_emphasis.runtime import Runtime
from .moss_emphasis.api import install_routes

NODE_CLASS_MAPPINGS = {RUNTIME: Runtime}
NODE_DISPLAY_NAME_MAPPINGS = {RUNTIME: "MOSS Emphasis internal runtime"}
WEB_DIRECTORY = "./web"
install_routes()
