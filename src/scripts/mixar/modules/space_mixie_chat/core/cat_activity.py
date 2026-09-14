# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Short presentation reactions to real events that can finish between draws.

Main-thread only. These scene-local hints never change chat or step status and
never defer execution. A decimal timestamp survives Python/RNA without the
subsecond loss of a Blender FloatProperty at the current Unix epoch.
"""

import math
import time

from ..constants import CAT_ACTIVITY_HOLD_SECONDS


def clear_activity(scene) -> None:
    if scene is None or not hasattr(scene, 'mixie_chat_cat_activity'):
        return
    scene.mixie_chat_cat_activity = ''
    scene.mixie_chat_cat_activity_until = ''


def _pulse(scene, activity: str) -> None:
    if scene is None or not hasattr(scene, 'mixie_chat_cat_activity'):
        return
    # A late tool/content event cannot animate a paused or disconnected turn.
    if getattr(scene, 'mixie_chat_state', '') != 'BUSY':
        return
    scene.mixie_chat_cat_activity = activity
    scene.mixie_chat_cat_activity_until = repr(time.time() + CAT_ACTIVITY_HOLD_SECONDS)


def note_step_completed(scene, bubble, request_id: str) -> None:
    """Retain the last actual step after RUNNING→DONE in one executor tick."""
    for row in reversed(bubble.step_items):
        if row.item_id == request_id:
            _pulse(scene, 'READING' if row.kind in {'READ', 'SEARCH'} else 'WORKING')
            return


def note_content(scene, content_data: dict) -> None:
    """A fresh response replaces a tool reaction; history does not refresh it."""
    if content_data.get('clear'):
        clear_activity(scene)
    elif content_data.get('set') or content_data.get('append'):
        _pulse(scene, 'RESPONDING')


def note_ephemeral(scene, ephemeral_data: dict) -> None:
    # An end-of-reasoning clear can share a batch with the final content. Only
    # new reasoning supersedes the finishing smile or preceding tool reaction.
    if ephemeral_data.get('set') or ephemeral_data.get('append'):
        clear_activity(scene)


def reset_for_state(scene, state: str) -> None:
    """New work/questions/connectivity clear hints; IDLE can finish a smile."""
    if state == 'IDLE' and getattr(scene, 'mixie_chat_cat_activity', '') == 'RESPONDING':
        try:
            remaining = float(scene.mixie_chat_cat_activity_until) - time.time()
        except (TypeError, ValueError):
            remaining = 0.0
        if math.isfinite(remaining) and 0.0 < remaining <= CAT_ACTIVITY_HOLD_SECONDS + 0.01:
            return
    clear_activity(scene)
