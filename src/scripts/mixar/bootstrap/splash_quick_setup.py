# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
First-time splash (Quick Setup) replacement.

Blender draws ``WM_MT_splash_quick_setup`` instead of the normal splash
while no preferences file exists yet (``wm_splash_screen.cc``), so it is
the very first screen a new install shows. Registering a Menu with the
same ``bl_idname`` replaces upstream's, the way ``splash_menu.py`` replaces
``WM_MT_splash``.

Mixar's version keeps upstream's rows (import previous preferences, theme,
keymap, mouse select, spacebar action, save) and:

* puts the **tour language** dropdown at the top
  (``WindowManager.mixar_tour_language`` — ``onboarding/core/tour/language``
  owns the list, the persisted choice and the change notification that
  starts the language pack download);
* drops Blender's own ``view.language`` row. Two language fields on one
  screen would confuse, and Mixar's interface strings are not translated
  yet, so that row would switch only half the UI.

The drawn value is the persisted choice, so a reinstall that kept the user
config shows the language the user picked before. The tour's language is
deliberately not saved into ``userpref.blend``: it lives with the other
Mixar config keys in the per-user ``mixar.json`` overlay.
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

        # Tour language: the first choice on the first screen. English is the
        # default; any other pick starts that language's download at once.
        if hasattr(wm, WM_PROP_TOUR_LANGUAGE):
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
    bpy.utils.register_class(WM_MT_splash_quick_setup)


def unregister():
    bpy.utils.unregister_class(WM_MT_splash_quick_setup)
