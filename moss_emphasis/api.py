"""Explicit prepare endpoint: failures never fall through to /prompt."""
import logging
import io
import os
from pathlib import Path
import zipfile
from .config import EmphasisError
from .graph import prepare


def corresponding_source():
    """Archive this installed extension only; never the package/user/model trees."""
    root = Path(__file__).resolve().parents[1]
    top = {"__init__.py", "LICENSE", "LICENSE-AGPL-3.0", "NOTICE.md", "README.md", "README_JA.md",
           "VERSION", "RELEASE_TAG", "pyproject.toml", "package.json"}
    directories = {"moss_emphasis": {".py"}, "web": {".js"}, "locales": {".json"},
                   "tests": {".py", ".mjs"}, "scripts": {".py"}, "docs": {".md"}}
    paths = [root / name for name in top]
    for name in sorted(directories):
        directory = root / name
        if directory.is_symlink() or not directory.resolve().is_relative_to(root):
            continue
        for parent, children, files in os.walk(directory, followlinks=False):
            parent = Path(parent)
            children[:] = [child for child in children if not child.startswith(".") and child != "__pycache__"
                           and not (parent / child).is_symlink() and (parent / child).resolve().is_relative_to(root)]
            paths.extend(parent / file for file in files if not file.startswith(".") and Path(file).suffix in directories[name])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            relative = path.relative_to(root)
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            archive.writestr("ComfyUI-MOSS-Emphasis/" + relative.as_posix(), path.read_bytes())
    return output.getvalue()


def install_routes():
    from aiohttp import web
    from server import PromptServer
    server = PromptServer.instance
    if getattr(server, "_moss_emphasis_routes_v1", False):
        return

    @server.routes.post("/moss_emphasis/prepare")
    async def prepare_route(request):
        try:
            if request.content_length and request.content_length > 8 * 1024 * 1024:
                raise EmphasisError("INVALID_GRAPH", "Prepare payload exceeds 8 MiB.")
            body = await request.json()
            if not isinstance(body, dict) or type(body.get("schema_version")) is not int or body.get("schema_version") != 1:
                raise EmphasisError("INVALID_SETTINGS", "schema_version=1 is required.")
            result = prepare(body.get("prompt"), body.get("settings"))
            if body.get("diagnostic") is True:
                logging.info("[MOSS Emphasis] prepare targets=%s settings=%s", result["targets"], result["settings"])
            return web.json_response(result)
        except EmphasisError as exc:
            return web.json_response({"error": exc.as_dict()}, status=400)
        except (ValueError, TypeError, KeyError):
            return web.json_response({"error": {"code": "INVALID_REQUEST", "message": "Malformed prepare request."}}, status=400)
        except Exception:
            logging.exception("[MOSS Emphasis] prepare failed")
            return web.json_response({"error": {"code": "PREPARE_FAILED", "message": "Preparation failed; nothing has been queued. See the server log."}}, status=500)

    @server.routes.get("/moss_emphasis/source")
    async def source_route(request):
        return web.Response(body=corresponding_source(), content_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="ComfyUI-MOSS-Emphasis-source.zip"',
                                     "Cache-Control": "no-store"})

    server._moss_emphasis_routes_v1 = True
