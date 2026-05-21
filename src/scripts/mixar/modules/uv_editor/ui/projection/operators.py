# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Projection Operators

Operators for UV projection in the Mixar UV Editor.
"""

import bpy
import bmesh
import mathutils
from bpy.types import Operator
from bpy.props import EnumProperty, FloatProperty, BoolProperty

from mixar.modules.uv_editor.common.uv_utils import (
    get_mixar_uv_image_editor,
    poll_mixar_uv_edit_mode,
    with_uv_context,
    get_operator_properties,
)


# =============================================================================
# Blender Built-in Projection Wrappers
# =============================================================================

class MIXAR_OT_cube_project(Operator):
    """Project UVs using cube projection"""
    bl_idname = "mixar.cube_project"
    bl_label = "Cube Projection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.cube_project")
        with context.temp_override(area=area):
            bpy.ops.uv.cube_project(
                cube_size=op_props.cube_size,
                correct_aspect=op_props.correct_aspect,
                clip_to_bounds=op_props.clip_to_bounds,
                scale_to_bounds=op_props.scale_to_bounds
            )
        return {'FINISHED'}


class MIXAR_OT_cylinder_project(Operator):
    """Project UVs using cylinder projection"""
    bl_idname = "mixar.cylinder_project"
    bl_label = "Cylinder Projection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.cylinder_project")
        with context.temp_override(area=area):
            bpy.ops.uv.cylinder_project(
                direction=op_props.direction,
                align=op_props.align,
                pole=op_props.pole,
                seam=op_props.seam,
                radius=op_props.radius,
                correct_aspect=op_props.correct_aspect,
                clip_to_bounds=op_props.clip_to_bounds,
                scale_to_bounds=op_props.scale_to_bounds
            )
        return {'FINISHED'}


class MIXAR_OT_sphere_project(Operator):
    """Project UVs using sphere projection"""
    bl_idname = "mixar.sphere_project"
    bl_label = "Sphere Projection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.sphere_project")
        with context.temp_override(area=area):
            bpy.ops.uv.sphere_project(
                direction=op_props.direction,
                align=op_props.align,
                pole=op_props.pole,
                seam=op_props.seam,
                correct_aspect=op_props.correct_aspect,
                clip_to_bounds=op_props.clip_to_bounds,
                scale_to_bounds=op_props.scale_to_bounds
            )
        return {'FINISHED'}


class MIXAR_OT_reset_uvs(Operator):
    """Reset UVs to default 0-1 space"""
    bl_idname = "mixar.reset_uvs"
    bl_label = "Reset UVs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.reset()
        return {'FINISHED'}


# =============================================================================
# Custom Projection Operators (Maya-style)
# =============================================================================

class MIXAR_OT_camera_project(Operator):
    """Project UVs from the current camera view (similar to Maya Camera Based projection)"""
    bl_idname = "mixar.camera_project"
    bl_label = "Camera Based Projection"
    bl_options = {'REGISTER', 'UNDO'}

    scale: FloatProperty(
        name="Scale",
        description="Scale factor for UV projection",
        default=1.0,
        min=0.001,
        max=100.0
    )

    correct_aspect: BoolProperty(
        name="Correct Aspect",
        description="Map UVs taking image aspect ratio into account",
        default=True
    )

    @classmethod
    def poll(cls, context):
        if not poll_mixar_uv_edit_mode(context):
            return False
        # Need a 3D view with a camera or perspective view
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                return True
        return False

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}

        # Find the 3D view to get the view matrix
        view_3d = None
        region_3d = None
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                view_3d = area
                for region in area.regions:
                    if region.type == 'WINDOW':
                        region_3d = area.spaces.active.region_3d
                        break
                break

        if not region_3d:
            self.report({'ERROR'}, "No 3D view found")
            return {'CANCELLED'}

        # Get view and projection matrices
        view_matrix = region_3d.view_matrix
        obj_matrix = obj.matrix_world

        # Get bmesh for editing
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # Calculate the view projection for each selected face
        for face in bm.faces:
            if not face.select:
                continue

            for loop in face.loops:
                # Transform vertex to view space
                world_co = obj_matrix @ loop.vert.co
                view_co = view_matrix @ world_co

                # Project to 2D (orthographic-like projection from view)
                # Using X and Y from view space
                u = view_co.x * self.scale
                v = view_co.y * self.scale

                # Apply aspect correction if needed
                if self.correct_aspect:
                    # Get image aspect ratio if available
                    area = get_mixar_uv_image_editor(context)
                    if area:
                        sima = area.spaces.active
                        if sima.image:
                            width, height = sima.image.size
                            if width > 0 and height > 0:
                                aspect = width / height
                                v *= aspect

                # Center the UVs
                loop[uv_layer].uv = (u + 0.5, v + 0.5)

        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class MIXAR_OT_normal_project(Operator):
    """Project UVs based on face normals (similar to Maya Automatic Mapping)"""
    bl_idname = "mixar.normal_project"
    bl_label = "Normal Projection"
    bl_options = {'REGISTER', 'UNDO'}

    scale: FloatProperty(
        name="Scale",
        description="Scale factor for UV projection",
        default=1.0,
        min=0.001,
        max=100.0
    )

    correct_aspect: BoolProperty(
        name="Correct Aspect",
        description="Map UVs taking image aspect ratio into account",
        default=True
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}

        obj_matrix = obj.matrix_world
        obj_matrix_normal = obj_matrix.to_3x3().inverted().transposed()

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        for face in bm.faces:
            if not face.select:
                continue

            # Get face normal in world space
            world_normal = (obj_matrix_normal @ face.normal).normalized()

            # Determine the best projection axis based on normal
            abs_normal = (abs(world_normal.x), abs(world_normal.y), abs(world_normal.z))

            # Create projection matrix based on dominant axis
            if abs_normal[2] >= abs_normal[0] and abs_normal[2] >= abs_normal[1]:
                # Z-dominant: project onto XY plane
                proj_u = mathutils.Vector((1, 0, 0))
                proj_v = mathutils.Vector((0, 1, 0))
                if world_normal.z < 0:
                    proj_u = mathutils.Vector((-1, 0, 0))
            elif abs_normal[1] >= abs_normal[0]:
                # Y-dominant: project onto XZ plane
                proj_u = mathutils.Vector((1, 0, 0))
                proj_v = mathutils.Vector((0, 0, 1))
                if world_normal.y < 0:
                    proj_u = mathutils.Vector((-1, 0, 0))
            else:
                # X-dominant: project onto YZ plane
                proj_u = mathutils.Vector((0, 1, 0))
                proj_v = mathutils.Vector((0, 0, 1))
                if world_normal.x < 0:
                    proj_u = mathutils.Vector((0, -1, 0))

            # Calculate UV bounds for the face
            uvs = []
            for loop in face.loops:
                world_co = obj_matrix @ loop.vert.co
                u = world_co.dot(proj_u) * self.scale
                v = world_co.dot(proj_v) * self.scale
                uvs.append((u, v))

            # Apply UVs
            for i, loop in enumerate(face.loops):
                loop[uv_layer].uv = uvs[i]

        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class MIXAR_OT_planar_project(Operator):
    """Project UVs from a planar projection (similar to Maya Planar Mapping)"""
    bl_idname = "mixar.planar_project"
    bl_label = "Planar Projection"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(
        name="Axis",
        description="Projection axis",
        items=[
            ('X', "X", "Project along X axis (YZ plane)"),
            ('Y', "Y", "Project along Y axis (XZ plane)"),
            ('Z', "Z", "Project along Z axis (XY plane)"),
            ('BEST', "Best Planar", "Automatically choose best axis based on selection"),
        ],
        default='BEST'
    )

    scale: FloatProperty(
        name="Scale",
        description="Scale factor for UV projection",
        default=1.0,
        min=0.001,
        max=100.0
    )

    correct_aspect: BoolProperty(
        name="Correct Aspect",
        description="Map UVs taking image aspect ratio into account",
        default=True
    )

    center_uvs: BoolProperty(
        name="Center UVs",
        description="Center the projected UVs in UV space",
        default=True
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}

        obj_matrix = obj.matrix_world

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()

        # Collect all selected faces
        selected_faces = [f for f in bm.faces if f.select]
        if not selected_faces:
            self.report({'WARNING'}, "No faces selected")
            return {'CANCELLED'}

        # Determine projection axis
        axis = self.axis
        if axis == 'BEST':
            # Calculate average normal of selected faces
            avg_normal = mathutils.Vector((0, 0, 0))
            for face in selected_faces:
                world_normal = (obj_matrix.to_3x3() @ face.normal).normalized()
                avg_normal += world_normal
            avg_normal.normalize()

            # Choose axis based on dominant component
            abs_normal = (abs(avg_normal.x), abs(avg_normal.y), abs(avg_normal.z))
            if abs_normal[2] >= abs_normal[0] and abs_normal[2] >= abs_normal[1]:
                axis = 'Z'
            elif abs_normal[1] >= abs_normal[0]:
                axis = 'Y'
            else:
                axis = 'X'

        # Set projection vectors based on axis
        if axis == 'X':
            proj_u = mathutils.Vector((0, 1, 0))
            proj_v = mathutils.Vector((0, 0, 1))
        elif axis == 'Y':
            proj_u = mathutils.Vector((1, 0, 0))
            proj_v = mathutils.Vector((0, 0, 1))
        else:  # Z
            proj_u = mathutils.Vector((1, 0, 0))
            proj_v = mathutils.Vector((0, 1, 0))

        # Collect all UVs first for centering
        all_uvs = []
        uv_data = []

        for face in selected_faces:
            for loop in face.loops:
                world_co = obj_matrix @ loop.vert.co
                u = world_co.dot(proj_u) * self.scale
                v = world_co.dot(proj_v) * self.scale
                all_uvs.append((u, v))
                uv_data.append((loop, u, v))

        # Calculate offset for centering
        offset_u, offset_v = 0.0, 0.0
        if self.center_uvs and all_uvs:
            min_u = min(uv[0] for uv in all_uvs)
            max_u = max(uv[0] for uv in all_uvs)
            min_v = min(uv[1] for uv in all_uvs)
            max_v = max(uv[1] for uv in all_uvs)
            center_u = (min_u + max_u) / 2
            center_v = (min_v + max_v) / 2
            offset_u = 0.5 - center_u
            offset_v = 0.5 - center_v

        # Apply UVs
        for loop, u, v in uv_data:
            loop[uv_layer].uv = (u + offset_u, v + offset_v)

        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


# =============================================================================
# Unified Project dispatcher
# =============================================================================

_PROJECTION_OPERATOR = {
    'CUBE': "mixar.cube_project",
    'CYLINDER': "mixar.cylinder_project",
    'SPHERE': "mixar.sphere_project",
    'CAMERA': "mixar.camera_project",
    'NORMAL': "mixar.normal_project",
    'PLANAR': "mixar.planar_project",
}


class MIXAR_OT_project(Operator):
    """Project UVs using the type and properties shown in the Projection panel"""
    bl_idname = "mixar.project"
    bl_label = "Project"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    def execute(self, context):
        wm = context.window_manager
        ui = getattr(wm, 'mixar_uv_ui', None)
        if ui is None:
            self.report({'ERROR'}, "Mixar UV UI state not initialized")
            return {'CANCELLED'}

        op_idname = _PROJECTION_OPERATOR.get(ui.projection_type)
        if op_idname is None:
            self.report({'ERROR'}, f"Unknown projection type: {ui.projection_type}")
            return {'CANCELLED'}

        # Resolve "module.op_name" -> bpy.ops.module.op_name and invoke with
        # 'EXEC_DEFAULT' so the per-type operator reads its last-used props.
        module_name, op_name = op_idname.split('.', 1)
        op = getattr(getattr(bpy.ops, module_name), op_name)
        return op('EXEC_DEFAULT')


classes = (
    MIXAR_OT_cube_project,
    MIXAR_OT_cylinder_project,
    MIXAR_OT_sphere_project,
    MIXAR_OT_reset_uvs,
    MIXAR_OT_camera_project,
    MIXAR_OT_normal_project,
    MIXAR_OT_planar_project,
    MIXAR_OT_project,
)
