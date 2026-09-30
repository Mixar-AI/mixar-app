# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""First-time Quick Setup: one language choice for UI and tour.

The language property is registered with this menu, synchronously, so the
first draw has the same rows as every later draw. Continue saves Blender
preferences; the selection also persists through Mixar's per-user config.
"""

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.types import Menu

from mixar.modules.onboarding.core.tour.config import WM_PROP_TOUR_LANGUAGE


class WM_MT_splash_quick_setup(Menu):
    bl_label = "Quick Setup"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        layout.operator_context = 'EXEC_DEFAULT'

        copy_prev = getattr(bpy.types, "PREFERENCES_OT_copy_prev", None)
        old_version = copy_prev.previous_version() if copy_prev else None
        can_import = bool(copy_prev and copy_prev.poll(context) and old_version)

        if can_import:
            layout.label(text="Import Preferences From Previous Version")
            split = layout.split(factor=0.20)  # Left margin.
            split.label()
            split = split.split(factor=0.73)  # Content width.
            col = split.column()
            col.operator(
                "preferences.copy_prev",
                text=iface_("Import Blender {:d}.{:d} Preferences", "Operator").format(*old_version),
                icon='NONE',
                translate=False,
            )
            layout.separator()
            layout.separator(type='LINE')

        layout.label(text="Create New Preferences" if can_import else "Quick Setup")

        split = layout.split(factor=0.20)  # Left margin.
        split.label()
        split = split.split(factor=0.73)  # Content width.
        col = split.column()
        col.use_property_split = True
        col.use_property_decorate = False

        col.prop(wm, WM_PROP_TOUR_LANGUAGE, text="Language")

        # Theme.
        sub = col.column(heading="Theme")
        label = bpy.types.USERPREF_MT_interface_theme_presets.bl_label
        if label == "Presets":
            label = "Blender Dark"
        sub.menu("USERPREF_MT_interface_theme_presets", text=label)

        col.separator()

        # Shortcuts.
        kc = wm.keyconfigs.active
        kc_prefs = kc.preferences

        sub = col.column(heading="Keymap")
        text = bpy.path.display_name(kc.name)
        if not text:
            text = "Blender"
        sub.menu("USERPREF_MT_keyconfigs", text=text)

        if hasattr(kc_prefs, "select_mouse"):
            col.row().prop(kc_prefs, "select_mouse", text="Mouse Select", expand=True)

        if hasattr(kc_prefs, "spacebar_action"):
            col.row().prop(kc_prefs, "spacebar_action", text="Spacebar Action")

        # Save Preferences.
        sub = col.column()
        sub.separator(factor=2)

        if can_import:
            sub.operator("wm.save_userpref", text="Save New Preferences", icon='NONE')
        else:
            sub.operator("wm.save_userpref", text="Continue")

        layout.separator(factor=2.0)


def register():
    """Replace native WM_MT_splash_quick_setup with Mixar's."""
    from mixar.modules.onboarding.ui.properties import language_props
    from mixar.modules.onboarding.core.tour.language_preferences import restore_unsaved_choice
    language_props.register()
    restore_unsaved_choice()
    bpy.utils.register_class(WM_MT_splash_quick_setup)


def unregister():
    bpy.utils.unregister_class(WM_MT_splash_quick_setup)
    from mixar.modules.onboarding.ui.properties import language_props
    language_props.unregister()
