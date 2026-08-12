# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Privacy section in Edit > Preferences > System.

Registered from Python into the native Preferences editor — no bl_ui overlay
needed, which keeps the upstream merge surface untouched.
"""

from bpy.types import Panel


class MIXAR_PT_privacy_preferences(Panel):
    """Telemetry consent, placed where users conventionally look to opt out."""

    bl_label = "Privacy"
    bl_idname = "MIXAR_PT_privacy_preferences"
    bl_space_type = 'PREFERENCES'
    bl_region_type = 'WINDOW'
    bl_context = "system"

    @classmethod
    def poll(cls, context):
        # The property only exists in interactive, non-headless sessions.
        return hasattr(context.window_manager, "mixar_share_usage_data")

    def draw(self, context):
        # Deliberately not property-split: the split pushes the checkbox to
        # the value column while labels stay at the panel edge, visually
        # divorcing the toggle from its explanation.
        layout = self.layout
        col = layout.column()
        col.prop(context.window_manager, "mixar_share_usage_data")
        sub = col.column()
        sub.active = False
        sub.label(text="Shares which Mixar features you use, to help improve the product.")
        sub.label(text="Your prompts, files, and scene content are never included.")

        col.separator()
        col.operator(
            "wm.url_open", text="Privacy Policy", icon='URL',
        ).url = "https://www.mixar.app/legal/privacy-policy"


classes = (
    MIXAR_PT_privacy_preferences,
)
