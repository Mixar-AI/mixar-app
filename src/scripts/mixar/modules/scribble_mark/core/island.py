# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep the sketch unobstructed, then reveal its completed preview."""
import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def minimize():
    from mixar.modules.space_mixie_chat.core import scribble

    scribble.release_composer()
    try:
        bpy.ops.mixar.bubble_minimise()
    except RuntimeError:
        logger.debug('Sketch: could not minimize the Agent', exc_info=True)


def reveal_draft(context):
    from . import marks

    if not context.scene.mixie_chat_input and not marks.count(context.scene, drafts_only=True):
        return
    try:
        bpy.ops.mixar.bubble_restore()
    except RuntimeError:
        logger.debug('Sketch: could not reveal the draft', exc_info=True)
