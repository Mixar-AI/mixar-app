# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Route table for the MCP bridge HTTP API.

Every handler takes the parsed JSON body (dict) and returns a
JSON-serializable dict with a top-level `success` flag. Routing is data
driven so the surface is trivially testable outside Blender.
"""

from typing import Callable, Dict

from mixar.config.logging_config import get_logger

from . import executor_bridge, services_bridge

logger = get_logger(__name__)


def _handle_execute(params: dict) -> dict:
    return executor_bridge.execute_script(
        script=params.get("script", ""),
        params=params.get("params"),
        push_undo=params.get("push_undo", True),
        timeout=params.get("timeout"),
    )


def _handle_tool(params: dict) -> dict:
    return executor_bridge.run_local_tool(
        domain=params.get("domain", ""),
        name=params.get("name", ""),
        params=params.get("params"),
        timeout=params.get("timeout"),
    )


def _handle_generation_enqueue(params: dict) -> dict:
    return services_bridge.generation_enqueue(
        service=params.get("service", ""),
        model=params.get("model", ""),
        payload=params.get("payload") or {},
    )


def _handle_generation_status(params: dict) -> dict:
    return services_bridge.generation_job_status(params.get("job_id", ""))


def _handle_generation_cancel(params: dict) -> dict:
    return services_bridge.generation_job_cancel(params.get("job_id", ""))


def _handle_generation_catalog(params: dict) -> dict:
    return services_bridge.generation_catalog(
        capability=params.get("capability"),
        service=params.get("service"),
    )


def _handle_byok_status(params: dict) -> dict:
    return services_bridge.byok_status()


def _handle_byok_models(params: dict) -> dict:
    return services_bridge.byok_models()


def _handle_byok_set(params: dict) -> dict:
    return services_bridge.byok_set(
        provider=params.get("provider", ""),
        model=params.get("model", ""),
        api_key=params.get("api_key", ""),
    )


def _handle_byok_remove(params: dict) -> dict:
    return services_bridge.byok_remove()


ROUTES: Dict[str, Callable[[dict], dict]] = {
    "/execute": _handle_execute,
    "/tool": _handle_tool,
    "/generation/enqueue": _handle_generation_enqueue,
    "/generation/status": _handle_generation_status,
    "/generation/cancel": _handle_generation_cancel,
    "/generation/catalog": _handle_generation_catalog,
    "/byok/status": _handle_byok_status,
    "/byok/models": _handle_byok_models,
    "/byok/set": _handle_byok_set,
    "/byok/remove": _handle_byok_remove,
}


def route_request(path: str, params: dict) -> dict:
    """Dispatch a POST request to its handler.

    Unknown paths return an error envelope listing the available routes so
    MCP-side mistakes are self-diagnosing.
    """
    handler = ROUTES.get(path)
    if handler is None:
        return {
            "success": False,
            "error": "Unknown endpoint: {0}".format(path),
            "available": sorted(ROUTES),
        }
    if not isinstance(params, dict):
        return {"success": False, "error": "Request body must be a JSON object"}
    return handler(params)
