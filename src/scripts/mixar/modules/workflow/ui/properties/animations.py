# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)

from ...core import animation_browser as browser


class MixarAnimationClip(bpy.types.PropertyGroup):
    action_name: StringProperty()
    slot_handle: IntProperty()
    slot_name: StringProperty()
    start: FloatProperty()
    end: FloatProperty()
    used: BoolProperty()
    reason: StringProperty()
    kind: EnumProperty(items=(('ACTION', 'Active action', ''), ('STRIP', 'Strip', ''),
                              ('FILE', 'In file', '')))
    track_name: StringProperty()
    strip_name: StringProperty()
    nested: BoolProperty()


class MixarAnimationBrowser(bpy.types.PropertyGroup):
    clips: CollectionProperty(type=MixarAnimationClip, options={'SKIP_SAVE'})
    active_index: IntProperty(options={'SKIP_SAVE'})
    target_name: StringProperty(options={'SKIP_SAVE'})
    search: StringProperty(name="Search animations", options={'SKIP_SAVE'},
                           update=browser.invalidate)
    scope: EnumProperty(name="Animations", items=(
        ('SELECTED', 'Selected object', 'The active action and NLA strips of this object or its rig'),
        ('ALL', 'All in file', 'Browse every animation; only matching slots can be played'),
    ), options={'SKIP_SAVE'}, update=browser.invalidate)
    loading: BoolProperty(options={'SKIP_SAVE'})
    # The preview range a browser Play replaced; Stop puts it back.
    play_target: StringProperty(options={'SKIP_SAVE'})
    range_saved: BoolProperty(options={'SKIP_SAVE'})
    range_scene: IntProperty(options={'SKIP_SAVE'})
    range_use: BoolProperty(options={'SKIP_SAVE'})
    range_start: IntProperty(options={'SKIP_SAVE'})
    range_end: IntProperty(options={'SKIP_SAVE'})


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
