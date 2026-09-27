# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scene cards use the existing image-node geometry, selection and IMAGE socket."""
import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ...core import scene_nodes
from ...core.node_graph import media_item_by_id


class MIXIE_OT_moodboard_add_scene(Operator):
    bl_idname = 'mixie.moodboard_add_scene'
    bl_label = 'Add Scene Node'
    bl_description = 'Add a scene preview you can open locally or share as an image reference'
    bl_options = {'UNDO'}
    scene_name: StringProperty(name='Scene')

    def invoke(self, context, event):
        self.scene_name = context.scene.name
        return context.window_manager.invoke_props_dialog(self, width=400, confirm_text='Add Scene')

    def draw(self, context):
        layout = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        layout.prop_search(self, 'scene_name', bpy.data, 'scenes', text='Scene')
        layout.label(text='Right-click the node to open its scene.', icon='INFO')
        layout.label(text='Its preview can connect to image inputs.')

    def execute(self, context):
        try:
            scene_nodes.add_scene_node(context.scene, bpy.data.scenes.get(self.scene_name))
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXIE_OT_moodboard_open_scene(Operator):
    bl_idname = 'mixie.moodboard_open_scene'
    bl_label = 'Open Scene'
    bl_description = 'Switch to the scene referenced by this node'
    node_id: StringProperty()

    def execute(self, context):
        item = media_item_by_id(context.scene, self.node_id)
        if item is None or not item.scene_node:
            return {'CANCELLED'}
        try:
            scene_nodes.open_scene(item)
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXIE_OT_moodboard_refresh_scene(Operator):
    bl_idname = 'mixie.moodboard_refresh_scene'
    bl_label = 'Refresh Scene Preview'
    bl_description = 'Use the last visible viewport snapshot for this scene'
    bl_options = {'UNDO'}
    node_id: StringProperty()

    def execute(self, context):
        item = media_item_by_id(context.scene, self.node_id)
        if item is None or not item.scene_node:
            return {'CANCELLED'}
        try:
            scene_nodes.refresh(item)
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_add_scene, MIXIE_OT_moodboard_open_scene, MIXIE_OT_moodboard_refresh_scene)
