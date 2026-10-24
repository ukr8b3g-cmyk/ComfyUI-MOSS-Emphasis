"""Explicit prepare endpoint: failures never fall through to /prompt."""
import logging
from .config import EmphasisError
from .graph import prepare


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

    server._moss_emphasis_routes_v1 = True
