# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)

from ...core import animation_browser as browser, animation_preview as preview


class MixarAnimationClip(bpy.types.PropertyGroup):
    action_name: StringProperty()
    slot_handle: IntProperty()
    slot_name: StringProperty()
    start: FloatProperty()
    end: FloatProperty()
    used: BoolProperty()
    reason: StringProperty()


class MixarAnimationBrowser(bpy.types.PropertyGroup):
    clips: CollectionProperty(type=MixarAnimationClip, options={'SKIP_SAVE'})
    active_index: IntProperty(options={'SKIP_SAVE'})
    target_name: StringProperty(options={'SKIP_SAVE'})
    search: StringProperty(name="Search animations", options={'SKIP_SAVE'},
                           update=browser.invalidate)
    scope: EnumProperty(name="Animations", items=(
        ('SELECTED', 'Selected object', 'Animations assigned to this object or its rig'),
        ('ALL', 'All in file', 'Browse every animation; only matching slots can be previewed'),
    ), options={'SKIP_SAVE'}, update=browser.invalidate)
    loading: BoolProperty(options={'SKIP_SAVE'})
    error: BoolProperty(options={'SKIP_SAVE'})
    preview_name: StringProperty(options={'SKIP_SAVE'})
    preparing: BoolProperty(options={'SKIP_SAVE'})
    playing: BoolProperty(options={'SKIP_SAVE'})
    loop: BoolProperty(name="Loop", default=True, options={'SKIP_SAVE'})
    hide_rig: BoolProperty(name="Hide Rig", default=False,
                           description="Hide the preview rig while the character keeps animating",
                           options={'SKIP_SAVE'}, update=preview.update_rig_visibility)
    position: FloatProperty(name="Position", min=0, max=1, subtype='FACTOR',
                            get=lambda self: preview.position(),
                            set=lambda self, value: preview.seek(value),
                            options={'SKIP_SAVE'})


classes = (MixarAnimationClip, MixarAnimationBrowser)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.mixar_animations = PointerProperty(
        type=MixarAnimationBrowser, options={'SKIP_SAVE'})
    browser.register()


def unregister():
    browser.unregister()
    del bpy.types.WindowManager.mixar_animations
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
