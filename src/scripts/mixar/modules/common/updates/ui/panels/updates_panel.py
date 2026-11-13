# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Updates section in Edit > Preferences > System.

Registered from Python into the native Preferences editor, next to Privacy
and Notifications, which keeps the upstream merge surface untouched.
"""

from bpy.types import Panel


class MIXAR_PT_updates_preferences(Panel):
    """How Mixar installs the updates it downloads"""

    bl_label = "Updates"
    bl_idname = "MIXAR_PT_updates_preferences"
    bl_space_type = 'PREFERENCES'
    bl_region_type = 'WINDOW'
    bl_context = "system"

    @classmethod
    def poll(cls, context):
        # The property only exists in interactive, non-headless sessions.
        return hasattr(context.window_manager, "mixar_install_updates_on_quit")

    def draw(self, context):
        # Not property-split, like Privacy: the checkbox stays next to its
        # explanation.
        col = self.layout.column()
        col.prop(context.window_manager, "mixar_install_updates_on_quit")
        sub = col.column()
        sub.active = False
        sub.label(text="Downloaded updates install as Mixar closes, without asking.")
        sub.label(text="Turn this off to update only with Restart to Update.")


classes = (
    MIXAR_PT_updates_preferences,
)
