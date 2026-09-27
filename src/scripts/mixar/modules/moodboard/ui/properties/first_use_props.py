# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read-only native mirror of the board's saved first-use history."""

import bpy
from ...core import first_use


def register():
    bpy.types.Scene.mixie_moodboard_started = bpy.props.BoolProperty(
        name="Moodboard Started", get=first_use.started, options={'HIDDEN'},
    )
    first_use.register()


def unregister():
    first_use.unregister()
    if hasattr(bpy.types.Scene, "mixie_moodboard_started"):
        del bpy.types.Scene.mixie_moodboard_started
