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

    wm = bpy.context.window_manager
    win = wm.windows[0] if (wm and wm.windows) else None
    if win is None:
        return
    try:
        with bpy.context.temp_override(window=win):
            op('INVOKE_DEFAULT')
    except Exception as exc:  # noqa: BLE001 — never break the tick
        logger.debug("Agent viewport lock: modal start failed: %s", exc)


def _lock_tick():
    """Persistent timer: drive halo redraw + keep the block modal alive
    while the agent is executing. Must never raise."""
    try:
        if is_agent_executing():
            _ensure_modal_running()
            halo_renderer.tag_view3d_redraw()
            return HALO_TICK_ACTIVE_S
    except Exception as exc:  # noqa: BLE001
        logger.debug("Agent viewport lock tick error: %s", exc)
    return HALO_TICK_IDLE_S


def register() -> None:
    logger.info("agent_viewport_lock: register()")
    halo_renderer.install_draw_handler()
    if not bpy.app.timers.is_registered(_lock_tick):
        # Slight delay so the UI loader has registered the block
        # operator before the first tick tries to invoke it.
        bpy.app.timers.register(_lock_tick, first_interval=1.0)


def unregister() -> None:
    halo_renderer.remove_draw_handler()
    if bpy.app.timers.is_registered(_lock_tick):
        try:
            bpy.app.timers.unregister(_lock_tick)
        except Exception as exc:  # noqa: BLE001
            logger.debug("agent_viewport_lock: timer unregister failed: %s", exc)
