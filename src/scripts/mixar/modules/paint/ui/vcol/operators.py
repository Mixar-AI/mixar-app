# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vertex color editor operators.

This module contains all operators for vertex color editing including
setting active vertex colors, selecting faces by color, and filling
with colors.
"""

import bpy
import bmesh
import numpy
import time
from mathutils import Color
from bpy.props import StringProperty, FloatVectorProperty, EnumProperty

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.get_elements import get_active_vertex_color
from ...core.element.update_vcol import set_active_vertex_color
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.node_utils import get_vertex_colors
from ...utils.blender_commons import set_object_select
from ...utils.common import set_entity_prop_value


class MSetActiveVcol(bpy.types.Operator):
    """Operator to set the active vertex color."""

    bl_idname = "mesh.y_set_active_vcol"
    bl_label = "Set Active Vertex Color"
    bl_description = "Set active vertex color"
    bl_options = {'REGISTER', 'UNDO'}

    vcol_name: StringProperty(default='')

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        vcols = get_vertex_colors(obj)
        vcol = vcols.get(self.vcol_name)

        if vcol:
            set_active_vertex_color(obj, vcol)
            return {'FINISHED'}

        self.report({'ERROR'}, "There's no vertex color named " + self.vcol_name + '!')
        return {'CANCELLED'}


class MSelectFacesByVcol(bpy.types.Operator):
    """Operator to select faces based on vertex color."""

    bl_idname = "mesh.y_select_faces_by_vcol"
    bl_label = "Select Faces based on Vertex Color"
    bl_description = "Select faces based on vertex color"
    bl_options = {'REGISTER', 'UNDO'}

    color: FloatVectorProperty(
        name='Color',
        size=4,
        subtype='COLOR',
        default=(1.0, 0.0, 1.0, 1.0),
        min=0.0, max=1.0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'MESH' or not any(get_vertex_colors(obj)):
            return False

        vcol = obj.data.color_attributes.active_color
        if not vcol or vcol.domain != 'CORNER':
            return False

        return obj.mode == 'EDIT'

    def execute(self, context):

        threshold = .004
        mat = context.object.active_material
        vcol_name = get_active_vertex_color(context.object).name
        target = Color((self.color[0], self.color[1], self.color[2]))

        if mat.users > 1:
            objs = get_all_objects_with_same_materials(mat, mesh_only=True)
        else:
            objs = [context.object]

        # Select object first
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objs:
            set_object_select(obj, True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action='DESELECT')

        bpy.ops.object.mode_set(mode="OBJECT")

        for obj in objs:

            # Select vcol
            vcols = get_vertex_colors(obj)
            vcol = vcols.get(vcol_name)
            if not vcol:
                continue
            set_active_vertex_color(obj, vcol)

            # Select polygons
            for p in obj.data.polygons:
                r = g = b = 0
                for i in p.loop_indices:
                    c = vcol.data[i].color
                    r += c[0]
                    g += c[1]
                    b += c[2]
                r /= p.loop_total
                g /= p.loop_total
                b /= p.loop_total
                source = Color((r, g, b))

                if (abs(source.r - target.r) < threshold and
                    abs(source.g - target.g) < threshold and
                    abs(source.b - target.b) < threshold):

                    p.select = True

        bpy.ops.object.mode_set(mode="EDIT")

        return {'FINISHED'}


class MVcolFillFaceCustom(bpy.types.Operator):
    """Operator to fill selected faces with a custom vertex color."""

    bl_idname = "mesh.y_vcol_fill_face_custom"
    bl_label = "Vertex Color Fill Face with Custom Color"
    bl_description = "Fill selected polygon with vertex color with custom color"
    bl_options = {'REGISTER', 'UNDO'}

    color: FloatVectorProperty(
        name='Color ID',
        size=4,
        subtype='COLOR',
        default=(1.0, 0.0, 1.0, 1.0),
        min=0.0, max=1.0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'MESH' or not any(get_vertex_colors(obj)):
            return False

        vcol = obj.data.color_attributes.active_color
        if not vcol or vcol.domain != 'CORNER':
            return False

        return obj.mode == 'EDIT'

    def execute(self, context):
        T = time.time()

        # Experiment with numpy
        use_numpy = True

        objs = context.objects_in_mode

        # Set the same vertex color for all objects first
        vcol = get_active_vertex_color(context.object)
        for obj in objs:
            vcols = get_vertex_colors(obj)
            vc = vcols.get(vcol.name)
            set_active_vertex_color(obj, vc)

        for obj in objs:

            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)

            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            loop_indices = []
            for face in bm.faces:
                if face.select:
                    for loop in face.loops:
                        loop_indices.append(loop.index)

            bpy.ops.object.mode_set(mode='OBJECT')
            vcol = get_active_vertex_color(obj)

            if not vcol:
                bpy.ops.object.mode_set(mode='EDIT')
                continue

            color = Color((self.color[0], self.color[1], self.color[2]))
            color = (color[0], color[1], color[2], self.color[3])

            # HACK: Sometimes color assigned are different so read the assigned color and write it back to mask color id
            if len(loop_indices) > 0:
                vcol.data[loop_indices[0]].color = color
                if any([color[i] for i in range(3) if color[i] != vcol.data[loop_indices[0]].color[i]]) and hasattr(context, 'mask'):
                    written_col = vcol.data[loop_indices[0]].color
                    color = (written_col[0], written_col[1], written_col[2])

                    set_entity_prop_value(context.mask, 'color_id', Color(color))
                    color = (written_col[0], written_col[1], written_col[2], written_col[3])

                # Blender 2.80+ has alpha channel on vertex color
                dimension = 4

                if use_numpy:
                    nvcol = numpy.zeros(len(vcol.data) * dimension, dtype=numpy.float32)
                    vcol.data.foreach_get('color', nvcol)
                    nvcol2D = nvcol.reshape(-1, dimension)
                    nvcol2D[loop_indices] = color
                    vcol.data.foreach_set('color', nvcol)
                else:
                    for i, loop_index in enumerate(loop_indices):
                        vcol.data[loop_index].color = color

            bpy.ops.object.mode_set(mode='EDIT')

        logger.info("VCOL: Fill Color ID is done in %0.2f seconds!", time.time() - T)

        return {'FINISHED'}


class MVcolFill(bpy.types.Operator):
    """Operator to fill selected geometry with vertex color."""

    bl_idname = "mesh.y_vcol_fill"
    bl_label = "Vertex Color Fill"
    bl_description = "Fill selected polygon with vertex color"
    bl_options = {'REGISTER', 'UNDO'}

    color_option: EnumProperty(
        name='Color Option',
        description='Color Option',
        items=(
            ('WHITE', 'White', ''),
            ('BLACK', 'Black', ''),
            ('CUSTOM', 'Custom', ''),
        ),
        default='WHITE'
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'MESH' or not any(get_vertex_colors(obj)):
            return False

        vcol = obj.data.color_attributes.active_color
        if not vcol or vcol.domain not in {'CORNER', 'POINT'}:
            return False

        return obj.mode == 'EDIT'

    def execute(self, context):
        T = time.time()

        # Experiment with numpy
        use_numpy = True

        objs = context.objects_in_mode

        if context.tool_settings.mesh_select_mode[0] or context.tool_settings.mesh_select_mode[1]:
            fill_mode = 'VERTEX'
        else:
            fill_mode = 'FACE'

        for obj in objs:

            mesh = obj.data
            ve = context.scene.ve_edit
            bm = bmesh.from_edit_mesh(mesh)

            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            loop_indices = []
            for face in bm.faces:
                if face.select:
                    for loop in face.loops:
                        loop_indices.append(loop.index)

            vert_indices = []
            for vert in bm.verts:
                if vert.select:
                    vert_indices.append(vert.index)

            bpy.ops.object.mode_set(mode='OBJECT')
            vcol = get_active_vertex_color(obj)

            if not vcol:
                bpy.ops.object.mode_set(mode='EDIT')
                continue

            color = Color((ve.color[0], ve.color[1], ve.color[2]))
            alpha = context.scene.ve_edit.color[3]

            if self.color_option == 'WHITE':
                color = (1, 1, 1)
                alpha = 1.0
            elif self.color_option == 'BLACK':
                color = (0, 0, 0)
                alpha = 1.0

            # Blender 2.80+ has alpha channel on vertex color
            dimension = 4
            color = (color[0], color[1], color[2], alpha)

            if vcol.domain == 'POINT':
                if use_numpy:
                    nvcol = numpy.zeros(len(vcol.data) * dimension, dtype=numpy.float32)
                    vcol.data.foreach_get('color', nvcol)
                    nvcol2D = nvcol.reshape(-1, dimension)
                    nvcol2D[vert_indices] = color
                    vcol.data.foreach_set('color', nvcol)
                else:
                    for vert_index in vert_indices:
                        vcol.data[vert_index].color = color
            else:
                if fill_mode == 'FACE':
                    if use_numpy:
                        nvcol = numpy.zeros(len(vcol.data) * dimension, dtype=numpy.float32)
                        vcol.data.foreach_get('color', nvcol)
                        nvcol2D = nvcol.reshape(-1, dimension)
                        nvcol2D[loop_indices] = color
                        vcol.data.foreach_set('color', nvcol)
                    else:
                        for loop_index in loop_indices:
                            vcol.data[loop_index].color = color
                else:
                    if use_numpy:
                        loop_to_vert = numpy.zeros(len(mesh.loops), dtype=numpy.uint32)
                        mesh.loops.foreach_get('vertex_index', loop_to_vert)
                        loop_indices = (numpy.in1d(loop_to_vert, vert_indices)).nonzero()[0]
                        nvcol = numpy.zeros(len(vcol.data) * dimension, dtype=numpy.float32)
                        vcol.data.foreach_get('color', nvcol)
                        nvcol2D = nvcol.reshape(-1, dimension)
                        nvcol2D[loop_indices] = color
                        vcol.data.foreach_set('color', nvcol)
                    else:
                        for poly in mesh.polygons:
                            for loop_index in poly.loop_indices:
                                loop_vert_index = mesh.loops[loop_index].vertex_index
                                if loop_vert_index in vert_indices:
                                    vcol.data[loop_index].color = color

            bpy.ops.object.mode_set(mode='EDIT')

        logger.info("VCOL: Fill vertex color is done in %0.2f seconds!", time.time() - T)

        return {'FINISHED'}
