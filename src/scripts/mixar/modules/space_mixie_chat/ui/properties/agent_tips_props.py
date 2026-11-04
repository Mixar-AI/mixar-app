# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The island composer's busy placeholder (core/agent_tips.py writes it,
the C++ island reads and translates it)."""
import bpy
from bpy.props import StringProperty


def register():
    bpy.types.WindowManager.mixie_chat_busy_hint = StringProperty(
        name="Busy Hint",
        description="Composer placeholder shown while the agent works (English template)",
        default="", maxlen=128, options={'SKIP_SAVE'})


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixie_chat_busy_hint'):
        del bpy.types.WindowManager.mixie_chat_busy_hint
