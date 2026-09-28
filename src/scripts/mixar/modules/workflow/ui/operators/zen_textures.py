# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Undoable texture actions with file-browser target revalidation."""
import bpy
from bpy.props import EnumProperty, StringProperty
from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ...constants import ZEN_TEXTURE_CHANNELS
from ...core.zen_object_controls import editable_mesh
from ...core.zen_textures import load_texture, remove_texture, editable_channel


def _target(operator, context):
    obj = editable_mesh(context, operator.object_name)
    material = obj.active_material if obj else None
    if material is None or material.name != operator.material_name:
        raise ValueError('The selected object or material changed; reopen Textures')
    return obj, material


def _refresh(context):
    if context.region_popup and context.region_popup.type == 'TEMPORARY':
        context.region_popup.tag_refresh_ui()
    if context.area:
        context.area.tag_redraw()


class MIXAR_OT_zen_load_texture(bpy.types.Operator):
    bl_idname = 'mixar.zen_load_texture'
    bl_label = 'Load Texture'
    bl_description = 'Load an image into this material channel; data maps use Non-Color'
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    material_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    channel: EnumProperty(items=ZEN_TEXTURE_CHANNELS, options={'HIDDEN'})
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(
        default='*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.exr;*.hdr;*.tga;*.bmp;*.webp',
        options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        return f'Load {properties.channel} texture from an image file'

    def invoke(self, context, event):
        try:
            obj, material = _target(self, context)
            editable_channel(obj, material, context.scene.render.engine, self.channel)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not file_select_guard(self, context):
            return {'CANCELLED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            obj, material = _target(self, context)
            load_texture(obj, material, context.scene.render.engine, self.channel, self.filepath)
        except (RuntimeError, ValueError, OSError) as exc:
            self.report({'ERROR'}, f'Could not load texture: {exc}')
            return {'CANCELLED'}
        mark_file_select_executed(self)
        if context.area and context.area.type == 'VIEW_3D':
            if context.space_data.shading.type in {'SOLID', 'WIREFRAME'}:
                context.space_data.shading.type = 'MATERIAL'
        _refresh(context)
        return {'FINISHED'}


class MIXAR_OT_zen_remove_texture(bpy.types.Operator):
    bl_idname = 'mixar.zen_remove_texture'
    bl_label = 'Remove Texture'
    bl_description = 'Disconnect this texture and restore the channel value; keep other uses'
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    material_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    channel: EnumProperty(items=ZEN_TEXTURE_CHANNELS, options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        return f'Remove {properties.channel} texture and restore the channel value'

    def execute(self, context):
        try:
            obj, material = _target(self, context)
            remove_texture(obj, material, context.scene.render.engine, self.channel)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        _refresh(context)
        return {'FINISHED'}


class MIXAR_OT_zen_copy_material(bpy.types.Operator):
    bl_idname = 'mixar.zen_copy_material'
    bl_label = 'Make Unique'
    bl_description = 'Copy this material for the active slot so other objects keep their look'
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    material_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        try:
            obj, material = _target(self, context)
            if not obj.data.is_editable or obj.data.users > 1:
                raise ValueError('Make the mesh data single-user in Engine Mode first')
            obj.active_material = material.copy()
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        _refresh(context)
        return {'FINISHED'}


classes = (MIXAR_OT_zen_load_texture, MIXAR_OT_zen_remove_texture, MIXAR_OT_zen_copy_material)
