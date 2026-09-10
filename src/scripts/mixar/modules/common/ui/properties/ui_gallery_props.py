# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from mixar.modules.common.constants import UI_GALLERY_ENUM_ITEMS, UI_GALLERY_UNICODE


class MIXAR_PG_ui_gallery(bpy.types.PropertyGroup):
    text: StringProperty(name="Text", default=UI_GALLERY_UNICODE, options={"SKIP_SAVE"})
    prompt: StringProperty(name="Multiline", default="First line\nSecond line", options={"SKIP_SAVE"})
    empty: StringProperty(name="Empty", options={"SKIP_SAVE"})
    enabled: BoolProperty(name="Enabled", default=True, options={"SKIP_SAVE"})
    choice: EnumProperty(name="Choice", items=UI_GALLERY_ENUM_ITEMS, default="MEDIUM", options={"SKIP_SAVE"})
    count: IntProperty(name="Integer", default=11, min=3, max=27, options={"SKIP_SAVE"})
    factor: FloatProperty(name="Factor", default=0.25, min=-1, max=2, options={"SKIP_SAVE"})
    clicks: IntProperty(name="Local clicks", options={"SKIP_SAVE"})
    theme: EnumProperty(name="Profile", items=(
        ("ZEN", "Zen", "Shared Zen components"),
        ("NATIVE", "Native", "Blender theme"),
        ("LEGACY_MIXAR", "Legacy Mixar", "Compatibility profile"),
    ), options={"SKIP_SAVE"})


classes = (MIXAR_PG_ui_gallery,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.mixar_ui_gallery = PointerProperty(type=MIXAR_PG_ui_gallery, options={"SKIP_SAVE"})


def unregister():
    del bpy.types.WindowManager.mixar_ui_gallery
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
