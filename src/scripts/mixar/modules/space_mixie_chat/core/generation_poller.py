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
_POLL_MAX_COUNT = 120       # 60s timeout at 0.5s intervals

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

    def _poll_completion():
        poll_count[0] += 1

        if poll_count[0] > _POLL_MAX_COUNT:
            _active_polls.pop(is_generating_attr, None)
            _hide_loader(scene, bubble_id)
            add_agent_message(scene, "Generation timed out. Please try again.")
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
