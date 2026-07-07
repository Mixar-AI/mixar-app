# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Generation Polling Timer Factory.

Replaces 4 near-identical polling timer closures with a single
parameterized factory. Each generation handler registers a poll
that checks a scene boolean, hides the loader, and posts a result.
"""

import bpy
from mixar.config.logging_config import get_logger

from .message_helpers import add_agent_message
from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)

# Polling constants
_POLL_INTERVAL = 0.5        # Check every 0.5s
_POLL_FIRST_INTERVAL = 1.0  # Wait 1s before first poll
_POLL_TIMEOUT_S = 300     # 5 min
_POLL_MAX_COUNT = int(_POLL_TIMEOUT_S / _POLL_INTERVAL)

# Track active poll callbacks so we can cancel duplicates
_active_polls = {}  # is_generating_attr -> poll_callback


def register_generation_poll(scene, bubble_id, is_generating_attr,
                             error_attr, success_message):
    """Register a polling timer that monitors a generation property.

    Polls scene.<is_generating_attr> every 0.5s. When generation completes:
    - Hides the loader on the slot bubble matching bubble_id
    - Posts scene.<error_attr> if set, otherwise success_message

    Args:
        scene: Blender scene with mixie_chat_messages
        bubble_id: ID of the loader bubble to hide on completion
        is_generating_attr: Scene bool property name (e.g. "mixie_lookdev_is_generating")
        error_attr: Scene string property name (e.g. "mixie_lookdev_error")
        success_message: Message to show on success
    """
    # Cancel existing poll for the same attribute to prevent duplicates
    existing = _active_polls.get(is_generating_attr)
    if existing and bpy.app.timers.is_registered(existing):
        bpy.app.timers.unregister(existing)
        logger.debug("Cancelled existing poll for %s", is_generating_attr)

    poll_count = [0]
    # Hold the scene by name, not by reference: the poll can outlive the
    # scene (file load, scene delete), and touching a removed StructRNA
    # raises ReferenceError out of the timer — killing it mid-flight and
    # leaking the _active_polls entry.
    scene_name = scene.name

    def _poll_completion():
        poll_count[0] += 1

        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            _active_polls.pop(is_generating_attr, None)
            logger.debug(
                "Scene %r gone; stopping poll for %s", scene_name, is_generating_attr
            )
            return None

        if poll_count[0] > _POLL_MAX_COUNT:
            # Safety net only (see _POLL_TIMEOUT_S). The job may well still
            # be alive in the queue, so don't claim it failed — point at
            # the Queue panel instead of asking the user to retry.
            _active_polls.pop(is_generating_attr, None)
            _hide_loader(scene, bubble_id)
            add_agent_message(
                scene,
                "Generation may still be running — check the Queue panel for status.",
            )
            redraw_chat_areas()
            return None

        if not getattr(scene, is_generating_attr, False):
            _active_polls.pop(is_generating_attr, None)
            _hide_loader(scene, bubble_id)

            error = getattr(scene, error_attr, "")
            if error:
                add_agent_message(scene, f"Generation failed: {error}")
            else:
                add_agent_message(scene, success_message)

            redraw_chat_areas()
            return None

        return _POLL_INTERVAL

    _active_polls[is_generating_attr] = _poll_completion
    bpy.app.timers.register(_poll_completion, first_interval=_POLL_FIRST_INTERVAL)


def _hide_loader(scene, bubble_id):
    """Hide the loader on the slot bubble matching bubble_id."""
    for msg in scene.mixie_chat_messages:
        if hasattr(msg, 'bubble_id') and msg.bubble_id == bubble_id:
            msg.loader_visible = False
            break
