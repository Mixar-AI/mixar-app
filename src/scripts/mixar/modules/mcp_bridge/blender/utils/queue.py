# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar-adapted command queue for the vendored Blender handlers.

The standalone Blender MCP plugin runs its own command queue drained by a
50ms bpy timer to hop bpy calls onto the main thread. Inside Mixar we already
have that machinery: ``executor_bridge.run_on_main_thread_sync`` marshals a
callable onto Blender's main thread, waits for the result, serializes with
``mixar_execute_script`` (shared ``_EXEC_LOCK``), and clears the shutdown
latch. So this shim keeps the plugin's ``enqueue_command`` contract but routes
through that single path — no always-on idle timer, one serialized main-thread
queue for the whole bridge.

The public surface matches the original module (``enqueue_command``,
``RESULT_TIMEOUT``, ``LONG_OPERATION_TIMEOUT``, ``process_queue``) so the
vendored router and handlers import it unchanged.
"""

from typing import Callable, Optional

# Kept for parity with the original module / handler expectations.
RESULT_TIMEOUT = 120.0
LONG_OPERATION_TIMEOUT = 300.0

# Route prefixes that qualify for the longer timeout. Derived from the actual
# registered handler routes, not guessed: render, physics (incl. bake/free-bake),
# export, texture bake, animation bake (anim/bake), and the offscreen viewport
# render preview — all can run well past the default 120s on heavy scenes.
_LONG_OPERATION_PREFIXES = (
    "render/",
    "physics/",
    "export/",
    "texture/bake",
    "anim/bake",
    "viewport/render-preview",
)


def _select_timeout(route: Optional[str]) -> float:
    if route and any(route.startswith(p) for p in _LONG_OPERATION_PREFIXES):
        return LONG_OPERATION_TIMEOUT
    return RESULT_TIMEOUT


def enqueue_command(handler_func: Callable[[dict], dict], params: dict, route: Optional[str] = None) -> dict:
    """Run a Blender handler on the main thread and return its response dict.

    Delegates to Mixar's ``executor_bridge.run_on_main_thread_sync`` so bpy
    access is serialized with the rest of the bridge. Handler exceptions are
    turned into an error envelope by that helper (it never raises), matching
    the original queue's behavior.
    """
    # Lazy import avoids a module-load cycle (executor_bridge does not import
    # the blender package, but keep the boundary clean).
    from ...core.executor_bridge import run_on_main_thread_sync

    timeout = _select_timeout(route)
    return run_on_main_thread_sync(lambda: handler_func(params), timeout=timeout)


def process_queue():
    """No-op for API parity.

    The original plugin registered this on a bpy timer to drain its queue.
    The Mixar shim executes handlers synchronously in ``enqueue_command``, so
    there is nothing to drain here. Kept so any caller importing it still
    resolves.
    """
    return None
