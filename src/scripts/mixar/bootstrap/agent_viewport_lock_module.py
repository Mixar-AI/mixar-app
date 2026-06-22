# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Viewport Lock — bootstrap.

Wires the "agent is working" viewport treatment:

  * A breathing green inner-glow halo on the 3D viewport
    (core.halo_renderer — a POST_PIXEL draw handler).
  * An input-block modal that stops canvas editing while allowing
    camera navigation (ui.operators.viewport_block_op — auto-
    registered by the UI loader).

This module owns the lifecycle: it installs the halo draw handler and
runs a light poll tick. While the agent is executing (BUSY /
MODIFYING) the tick (a) ensures the block modal is running and (b)
tags the viewport for redraw so the halo breathes. When the agent
isn't executing the tick idles cheaply and nothing is drawn or
blocked.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.agent_viewport_lock.constants import (
    HALO_TICK_ACTIVE_S,
    HALO_TICK_IDLE_S,
)
from mixar.modules.agent_viewport_lock.core import halo_renderer
from mixar.modules.agent_viewport_lock.core.state_probe import (
    is_agent_executing,
)

logger = get_logger(__name__)


def _ensure_modal_running() -> None:
    """Start the input-block modal if the agent is executing and it
    isn't already running. Invoked from the poll tick."""
    try:
        from mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op import (
            is_running,
        )
    except Exception:
        # UI operator module not registered yet (early startup) — the
        # next tick will retry.
        return
    if is_running():
        return

    op = getattr(getattr(bpy.ops, "mixar", None), "agent_viewport_block", None)
    if op is None:
        return

    # Attach the modal to a window that actually contains a 3D viewport.
    # A modal operator only receives events for the window it's added to,
    # and the block only consumes input over a VIEW_3D region — so binding
    # to a viewport-less window (e.g. the agent bubble) would let clicks
    # through. Falls back to the first window if none has a viewport.
    wm = bpy.context.window_manager
    win = None
    if wm and wm.windows:
        for candidate in wm.windows:
            screen = candidate.screen
            if screen is not None and any(
                area.type == 'VIEW_3D' for area in screen.areas
            ):
                win = candidate
                break
        if win is None:
            win = wm.windows[0]
    if win is None:
        return
    try:
        with bpy.context.temp_override(window=win):
            op('INVOKE_DEFAULT')
    except Exception as exc:  # noqa: BLE001 — never break the tick
        logger.debug("Agent viewport lock: modal start failed: %s", exc)


_was_executing = False


def _lock_tick():
    """Persistent timer: drive halo redraw + keep the block modal alive
    while the agent is executing. Must never raise."""
    global _was_executing
    try:
        if is_agent_executing():
            _was_executing = True
            _ensure_modal_running()
            halo_renderer.tag_view3d_redraw()
            return HALO_TICK_ACTIVE_S
        if _was_executing:
            # The agent just went idle. The draw callback now early-outs,
            # but the last halo frame stays on screen until the viewport
            # repaints — without this final tag it would only clear on
            # user interaction (e.g. a click).
            _was_executing = False
            halo_renderer.tag_view3d_redraw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Agent viewport lock tick error: %s", exc)
    return HALO_TICK_IDLE_S


@persistent
def _on_load_post(_dummy_arg) -> None:
    """Re-arm the lock after open / new-file.

    A .blend load tears down the running block modal (modal operators
    never survive a file load) while the halo draw handler — registered
    on the SpaceView3D class — keeps rendering. That mismatch is the
    "halo shows but clicks aren't blocked on a new file" bug. Reset the
    stale running guard so the tick re-invokes the modal, and make sure
    the tick timer is alive (belt-and-suspenders — it's registered
    persistent below, but re-register defensively if it ever isn't)."""
    try:
        from mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op import (
            reset_running_guard,
        )
        reset_running_guard()
    except Exception as exc:  # noqa: BLE001 — never break file load
        logger.debug("agent_viewport_lock: guard reset failed: %s", exc)
    if not bpy.app.timers.is_registered(_lock_tick):
        try:
            bpy.app.timers.register(_lock_tick, first_interval=1.0, persistent=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("agent_viewport_lock: timer re-register failed: %s", exc)


def register() -> None:
    logger.info("agent_viewport_lock: register()")
    halo_renderer.install_draw_handler()
    if not bpy.app.timers.is_registered(_lock_tick):
        # Slight delay so the UI loader has registered the block
        # operator before the first tick tries to invoke it.
        # persistent=True so the tick keeps running across file loads —
        # otherwise the lock never re-arms on a newly-opened file.
        bpy.app.timers.register(_lock_tick, first_interval=1.0, persistent=True)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    halo_renderer.remove_draw_handler()
    if _on_load_post in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(_on_load_post)
        except Exception as exc:  # noqa: BLE001
            logger.debug("agent_viewport_lock: load handler remove failed: %s", exc)
    if bpy.app.timers.is_registered(_lock_tick):
        try:
            bpy.app.timers.unregister(_lock_tick)
        except Exception as exc:  # noqa: BLE001
            logger.debug("agent_viewport_lock: timer unregister failed: %s", exc)
