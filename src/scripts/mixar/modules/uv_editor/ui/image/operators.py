# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Image Operators

Operators for image operations in the Mixar UV Editor.
"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, EnumProperty, IntVectorProperty

from mixar.modules.uv_editor.common.uv_utils import (
    get_mixar_uv_image_editor,
    poll_mixar_uv_edit_mode,
    poll_mixar_uv_with_image,
    poll_mixar_uv_with_packed_image,
    poll_mixar_uv_with_unpacked_image,
    with_uv_context,
)


# ============================================================
# Image Operation Wrappers
# ============================================================

class MIXAR_OT_image_save(Operator):
    """Save the current image"""
    bl_idname = "mixar.image_save"
    bl_label = "Save Image"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.save()
        return {'FINISHED'}


class MIXAR_OT_image_save_as(Operator):
    """Save the image with a new name"""
    bl_idname = "mixar.image_save_as"
    bl_label = "Save Image As"
    bl_options = {'REGISTER'}

    copy: BoolProperty(
        name="Save Copy",
        description="Save a copy of the image",
        default=False
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.save_as('INVOKE_DEFAULT', copy=self.copy)
        return {'FINISHED'}


class MIXAR_OT_image_reload(Operator):
    """Reload the image from disk"""
    bl_idname = "mixar.image_reload"
    bl_label = "Reload Image"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.reload()
        return {'FINISHED'}


class MIXAR_OT_image_replace(Operator):
    """Replace the current image"""
    bl_idname = "mixar.image_replace"
    bl_label = "Replace Image"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.replace('INVOKE_DEFAULT')
        return {'FINISHED'}


class MIXAR_OT_image_external_edit(Operator):
    """Edit the image in an external application"""
    bl_idname = "mixar.image_external_edit"
    bl_label = "Edit Externally"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.external_edit()
        return {'FINISHED'}


class MIXAR_OT_image_flip(Operator):
    """Flip the image"""
    bl_idname = "mixar.image_flip"
    bl_label = "Flip Image"
    bl_options = {'REGISTER', 'UNDO'}

    use_flip_x: BoolProperty(name="Flip X", default=False)
    use_flip_y: BoolProperty(name="Flip Y", default=False)

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.flip(use_flip_x=self.use_flip_x, use_flip_y=self.use_flip_y)
        return {'FINISHED'}


class MIXAR_OT_image_rotate_orthogonal(Operator):
    """Rotate the image 90 degrees"""
    bl_idname = "mixar.image_rotate_orthogonal"
    bl_label = "Rotate Image"
    bl_options = {'REGISTER', 'UNDO'}

    degrees: EnumProperty(
        name="Degrees",
        items=[
            ('90', "90", ""),
            ('180', "180", ""),
            ('270', "270", ""),
        ],
        default='90'
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.rotate_orthogonal(degrees=self.degrees)
        return {'FINISHED'}


class MIXAR_OT_image_resize(Operator):
    """Resize the image to the size shown in the Resize section"""
    bl_idname = "mixar.image_resize"
    bl_label = "Resize Image"
    bl_options = {'REGISTER'}

    size: IntVectorProperty(
        name="Size",
        description="New image size in pixels",
        size=2,
        default=(1024, 1024),
        min=1,
        soft_max=16384,
    )
    all_udims: BoolProperty(
        name="All UDIM Tiles",
        description="Scale all the image's UDIM tiles",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.resize(
                'EXEC_DEFAULT',
                size=tuple(self.size),
                all_udims=self.all_udims,
            )
        return {'FINISHED'}


class MIXAR_OT_image_invert(Operator):
    """Invert image channels"""
    bl_idname = "mixar.image_invert"
    bl_label = "Invert Image"
    bl_options = {'REGISTER', 'UNDO'}

    invert_r: BoolProperty(name="Red", default=False)
    invert_g: BoolProperty(name="Green", default=False)
    invert_b: BoolProperty(name="Blue", default=False)
    invert_a: BoolProperty(name="Alpha", default=False)

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.invert(
                invert_r=self.invert_r,
                invert_g=self.invert_g,
                invert_b=self.invert_b,
                invert_a=self.invert_a
            )
        return {'FINISHED'}


class MIXAR_OT_image_pack(Operator):
    """Pack the image into the blend file"""
    bl_idname = "mixar.image_pack"
    bl_label = "Pack Image"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_unpacked_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.pack()
        return {'FINISHED'}


class MIXAR_OT_image_unpack(Operator):
    """Unpack the image to disk"""
    bl_idname = "mixar.image_unpack"
    bl_label = "Unpack Image"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_packed_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.image.unpack('INVOKE_DEFAULT')
        return {'FINISHED'}


class MIXAR_OT_palette_extract(Operator):
    """Extract palette from image"""
    bl_idname = "mixar.palette_extract"
    bl_label = "Extract Palette"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_with_image(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.palette.extract_from_image()
        return {'FINISHED'}


class MIXAR_OT_visualize(Operator):
    """Create and apply material with the current UV editor image"""
    bl_idname = "mixar.visualize"
    bl_label = "Visualize"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Must be in edit mode with mesh selected
        if not poll_mixar_uv_edit_mode(context):
            return False

        # Must have an image in the UV editor
        area = get_mixar_uv_image_editor(context)
        if area:
            sima = area.spaces.active
            return sima and sima.image is not None
        return False

    def execute(self, context):
        # Get the active object
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No mesh object selected")
            return {'CANCELLED'}

        # Get the image from UV editor
        area = get_mixar_uv_image_editor(context)
        if not area:
            self.report({'ERROR'}, "Could not find UV editor")
            return {'CANCELLED'}

        sima = area.spaces.active
        image = sima.image
        if not image:
            self.report({'ERROR'}, "No image in UV editor")
            return {'CANCELLED'}

        # Create new material
        mat_name = f"{image.name}_Material"
        mat = bpy.data.materials.get(mat_name)

        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)

        # Enable nodes
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Clear existing nodes
        nodes.clear()

        # Create shader nodes
        output_node = nodes.new(type='ShaderNodeOutputMaterial')
        output_node.location = (300, 0)

        bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
        bsdf_node.location = (0, 0)

        tex_node = nodes.new(type='ShaderNodeTexImage')
        tex_node.location = (-300, 0)
        tex_node.image = image

        # Link nodes
        links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
        links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])

        # Apply material to object
        if len(obj.data.materials) == 0:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[0] = mat

        # Switch 3D viewport to Material Preview mode if open
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'MATERIAL'
                        break
                break

        self.report({'INFO'}, f"Material '{mat_name}' created and applied")
        return {'FINISHED'}


classes = (
    MIXAR_OT_image_save,
    MIXAR_OT_image_save_as,
    MIXAR_OT_image_reload,
    MIXAR_OT_image_replace,
    MIXAR_OT_image_external_edit,
    MIXAR_OT_image_flip,
    MIXAR_OT_image_rotate_orthogonal,
    MIXAR_OT_image_resize,
    MIXAR_OT_image_invert,
    MIXAR_OT_image_pack,
    MIXAR_OT_image_unpack,
    MIXAR_OT_palette_extract,
    MIXAR_OT_visualize,
)
