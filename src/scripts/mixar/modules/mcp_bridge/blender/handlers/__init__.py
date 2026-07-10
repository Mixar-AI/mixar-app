"""
Request router for Blender MCP Bridge.
Maps URL paths (/api/{category}/{action}) to handler functions.
All handlers are executed via the command queue to ensure thread safety.
"""

from ..utils.queue import enqueue_command
from ..utils.response import error_response

# Handler registry: (category, action) → handler_func
_handlers = {}


def register_handler(category, action, handler_func):
    """
    Register a handler function for a given category/action pair.

    Args:
        category: The URL category (e.g., "file", "object", "scene")
        action: The URL action (e.g., "info", "create", "delete")
        handler_func: Callable(params) → response dict. Will be executed on the main thread.
    """
    key = (category.lower(), action.lower())
    _handlers[key] = handler_func


def route_request(path, params):
    """
    Route an HTTP request to the appropriate handler.

    Args:
        path: The URL path (e.g., "/api/file/info")
        params: The parsed JSON body parameters

    Returns:
        Response dict from the handler, or error response if not found.
    """
    # Parse path: /api/{category}/{action}
    parts = path.strip("/").split("/")

    if len(parts) < 3 or parts[0] != "api":
        return error_response(f"Invalid path format: {path}. Expected /api/{{category}}/{{action}}")

    category = parts[1].lower()
    action = parts[2].lower()

    key = (category, action)
    handler_func = _handlers.get(key)

    if handler_func is None:
        available = [f"/api/{c}/{a}" for (c, a) in sorted(_handlers.keys())]
        return error_response(
            f"No handler for /api/{category}/{action}. "
            f"Available routes: {', '.join(available) if available else 'none'}"
        )

    # Execute via command queue (ensures main thread execution)
    route = f"{category}/{action}"
    try:
        result = enqueue_command(handler_func, params, route=route)
        return result
    except TimeoutError as e:
        return error_response(f"Handler timeout: {e}")
    except Exception as e:
        return error_response(f"Handler error: {type(e).__name__}: {e}")


# ─── Register handlers ───
# Import handlers here to trigger their registration.
# Each handler module calls register_handler() at import time.

from . import file  # noqa: E402, F401 — registers file handlers
from . import scene  # noqa: E402, F401
from . import object  # noqa: E402, F401
from . import collection  # noqa: E402, F401
from . import material  # noqa: E402, F401
from . import modifier  # noqa: E402, F401
from . import mesh  # noqa: E402, F401
from . import render  # noqa: E402, F401
from . import animation  # noqa: E402, F401
from . import export_import  # noqa: E402, F401 — registers export/fbx, export/gltf, import/file
from . import reference  # noqa: E402, F401 — registers reference/execute-recipe
from . import advanced  # noqa: E402, F401 — registers all advanced handlers
