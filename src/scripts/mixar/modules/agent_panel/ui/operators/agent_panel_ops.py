# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators the C++ Parallel Agents panel invokes.

The panel is drawn natively but ``core/cards.py`` owns the mirror, so every
mutation of it lands here and the C++ side only calls in — the same split the
Director surface uses ("reads RNA and invokes Python operators", so behaviour
has exactly one owner).
"""

from __future__ import annotations

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core.cards import begin_dismiss, clear_cards

logger = get_logger(__name__)


class MIXAR_OT_agent_panel_dismiss_card(Operator):
    """Remove one agent's card from the panel"""

    bl_idname = "mixar.agent_panel_dismiss_card"
    bl_label = "Dismiss Agent Card"
    bl_options = {'INTERNAL'}

    task_id: StringProperty(
        name="Task ID",
        description="Card to remove; empty dismisses the whole panel",
        default="",
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        if not self.task_id:
            clear_cards()
            return {'FINISHED'}
        if not begin_dismiss(self.task_id):
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (MIXAR_OT_agent_panel_dismiss_card,)
