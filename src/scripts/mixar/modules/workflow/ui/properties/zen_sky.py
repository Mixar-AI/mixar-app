# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Persistent world and per-viewport snapshots for the reversible sky toggle."""

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty, StringProperty

from ...core.zen_sky_viewports import sync_sky_viewports


class MixarZenSkyViewportSnapshot(bpy.types.PropertyGroup):
    use_scene_world: BoolProperty()
    use_scene_world_render: BoolProperty()


class MixarZenSkyViewportState(bpy.types.PropertyGroup):
    key: StringProperty()
    applied: BoolProperty()
    previous_preview: BoolProperty()
    previous_render: BoolProperty()


class MixarZenSkyViewportOwner(bpy.types.PropertyGroup):
    scene: PointerProperty(type=bpy.types.Scene)


class MixarZenSkySettings(bpy.types.PropertyGroup):
    previous_world: PointerProperty(type=bpy.types.World)
    sky_world: PointerProperty(type=bpy.types.World)
    viewports: CollectionProperty(type=MixarZenSkyViewportSnapshot)


classes = (MixarZenSkyViewportSnapshot, MixarZenSkyViewportState,
           MixarZenSkyViewportOwner, MixarZenSkySettings)


def _handler_lists():
    return (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post, bpy.app.handlers.load_post)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mixar_zen_sky = PointerProperty(type=MixarZenSkySettings)
    bpy.types.Screen.mixar_zen_sky_owners = CollectionProperty(type=MixarZenSkyViewportOwner)
    bpy.types.View3DShading.mixar_zen_sky = PointerProperty(type=MixarZenSkyViewportState)
    for handlers in _handler_lists():
        if sync_sky_viewports not in handlers:
            handlers.append(sync_sky_viewports)


def unregister():
    for handlers in _handler_lists():
        if sync_sky_viewports in handlers:
            handlers.remove(sync_sky_viewports)
    del bpy.types.View3DShading.mixar_zen_sky
    del bpy.types.Screen.mixar_zen_sky_owners
    del bpy.types.Scene.mixar_zen_sky
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
