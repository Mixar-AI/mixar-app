# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lifecycle of the backend procedural-material catalog (non-blocking).

The library is served by the backend; no material scripts ship with the app.
The fetch starts at paint UI register, but a user who logs in after launch has
no token then, so the post-login auth hook and the agent's material tools call
:func:`ensure_server_catalog` to (re)start it. State is main-thread only:
every entry point runs on the main thread (UI register, a ``bpy.app.timers``
callback, the agent executor), and the worker thread only fills a queue.

States: ``idle`` (never fetched, or registry cleared) → ``loading`` →
``loaded`` | ``failed``. ``failed`` (including "not authenticated") is retried
by the next ``ensure_server_catalog``. Only the worker reads credentials;
callers never probe the system credential store before starting a fetch.
"""

import os
import queue as _queue
import threading

import bpy

from ....config.logging_config import get_logger
from . import material_registry as _mr

logger = get_logger(__name__)

IDLE = "idle"
LOADING = "loading"
LOADED = "loaded"
FAILED = "failed"

SERVER_SOURCE = "server"

_state = {"status": IDLE, "retry": False}


def is_server_material(material) -> bool:
    return getattr(material, "source", "") == SERVER_SOURCE


def catalog_status() -> str:
    return _state["status"]


def reset_server_catalog() -> None:
    """Forget the catalog state (the registry was cleared)."""
    _state["status"] = IDLE
    _state["retry"] = False


def is_script_available(material_id: str) -> bool:
    """True when the material's script is already in the local disk cache."""
    try:
        return os.path.exists(os.path.join(_mr._get_cache_dir(), f"{material_id}.py"))
    except Exception:
        return False


def ensure_server_catalog() -> str:
    """Start the catalog fetch if it never succeeded; check auth on the worker.

    Idempotent: a no-op while loaded; while loading it only asks for one more
    fetch if the one in flight fails (it may have started before login).
    Returns the status after the call.
    """
    status = _state["status"]
    if status == LOADED:
        return status
    if status == LOADING:
        _state["retry"] = True
        return status
    load_server_catalog()
    return _state["status"]


def load_server_catalog() -> None:
    """Fetch the material catalog from the server in a daemon thread.

    The user's own AI-generated materials (stored in the user data dir) are
    registered immediately so they are available offline and while the server
    request is in flight, and again after the server catalog lands.
    """
    _mr._load_local_matgen()
    if _state["status"] in (LOADING, LOADED):
        return
    _state["status"] = LOADING
    _state["retry"] = False

    result_queue = _queue.Queue()

    def _fetch():
        token = _mr._get_auth_token()
        base_url = _mr._get_base_url()
        if not token or not base_url:
            result_queue.put({"ok": False, "error": "not authenticated"})
            return
        try:
            from .matgen_client import fetch_catalog_async
            fetch_catalog_async(token, base_url, result_queue)
        except Exception as exc:
            result_queue.put({"ok": False, "error": str(exc)})

    threading.Thread(target=_fetch, daemon=True).start()
    bpy.app.timers.register(
        lambda: _poll(result_queue), first_interval=0.5
    )


def _poll(result_queue):
    if not hasattr(bpy.types.WindowManager, 'mixar_matgen_status'):
        return 0.5  # WM props not ready yet — reschedule instead of dying
    try:
        result = result_queue.get_nowait()
    except _queue.Empty:
        return 0.5  # reschedule
    _apply_result(result)
    return None  # unregister timer


def _apply_result(result: dict) -> None:
    ok = False
    try:
        if result.get("ok"):
            materials = result.get("materials", [])
            for item in materials:
                material = _mr.ProceduralMaterial(
                    material_id=item["material_id"],
                    name=item["name"],
                    category=item["category"],
                    thumbnail_url=item.get("thumbnail_url"),
                    node_group_name=item["name"],
                )
                # Tagged here, the one place server entries are built: local
                # materials (generated, layered-build) may carry script text
                # only, so "no script_path" does not mean "server".
                material.source = SERVER_SOURCE
                _mr.register_material(material)
            ok = True
            logger.info("Loaded %d materials from server catalog", len(materials))
        else:
            logger.warning("Server catalog unavailable (%s)", result.get("error"))
    except Exception:
        logger.exception("Error processing server catalog result")

    retry = _state["retry"]
    _state["status"] = LOADED if ok else FAILED
    _state["retry"] = False

    # Overlay user-generated AI materials on top of the server catalog.
    _mr._load_local_matgen()

    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass

    if not ok and retry:
        # A login landed while this fetch was in flight without a token.
        ensure_server_catalog()
