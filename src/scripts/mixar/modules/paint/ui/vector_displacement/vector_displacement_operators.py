# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import time

import bpy
from mathutils import Vector

from ...core.element.get_elements import (
    get_armature_modifier,
    get_multires_modifier,
    get_subsurf_modifier,
)
from ...core.layer.get_channels import get_height_channel
from ...core.layer.layer_utils import get_root_height_channel, get_uv_layers
from ...core.layer.mappings import get_layer_mapping
from ...core.layer.transformations import is_transformed
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.get_nodes import get_layer_source
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    link_object,
    remove_mesh_obj,
    set_active_object,
    set_object_select,
)
from ...utils.common import is_mesh_flat_shaded
from ..vector_displacement.vector_displacement_lib import get_vdm_loader_geotree
from ..vector_displacement.vector_displacement_operators_helper import (
    bake_multires_image,
    get_vdm_intensity,
    is_multi_disp_used,
)
from .vector_displacement_utils import (
    TEMP_MULTIRES_NAME,
    get_combined_vdm_image,
    get_tangent_bitangent_images,
)


class MSculptImage(bpy.types.Operator):
    bl_idname = "sculpt.y_sculpt_image"
    bl_label = "Sculpt Vector Displacement Image"
    bl_description = "Sculpt vector displacement image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            bool: True if there is an active mpaint node, active mesh object, and context image.
        """
        return (
            get_active_mpaint_node()
            and get_active_object()
            and get_active_object().type == "MESH"
            and hasattr(context, "image")
            and context.image
        )

    def execute(self, context):
        """Execute the sculpt image operation.

        Sets up a multires modifier and geometry nodes to enable sculpting of vector displacement images.
        Creates temporary objects, bakes tangent/bitangent data, and prepares the mesh for sculpt mode.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            set: {"FINISHED"} if successful, {"CANCELLED"} if operation failed.
        """
        T = time.time()

        mat = get_active_material()
        obj = get_active_object()
        scene = context.scene
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer = mp.layers[mp.active_layer_index]

        if layer.type != "IMAGE":
            self.report({"ERROR"}, "This is not an image layer!")
            return {"CANCELLED"}

        source = get_layer_source(layer)
        image = source.image

        if not image:
            self.report({"ERROR"}, "This layer image is missing!")
            return {"CANCELLED"}

        uv_name = layer.uv_name
        mapping = get_layer_mapping(layer)

        height_root_ch = get_root_height_channel(mp)
        if not height_root_ch:
            self.report({"ERROR"}, "Need normal channel!")
            return {"CANCELLED"}

        height_ch = get_height_channel(layer)
        intensity = get_vdm_intensity(layer, height_ch) if height_ch else 1.0

        if mapping and is_transformed(mapping, layer):
            self.report({"ERROR"}, "Cannot sculpt VDM with transformed mapping!")
            return {"CANCELLED"}

        # Get combined VDM image
        combined_vdm_image = None
        if is_multi_disp_used(mp):
            combined_vdm_image = get_combined_vdm_image(
                obj, uv_name, width=image.size[0], height=image.size[1]
            )

        # Enable sculpt mode to disable all vector displacement layers
        mp.sculpt_mode = True

        # Get related modifiers
        subsurf = get_subsurf_modifier(obj)
        multires = get_multires_modifier(obj)

        if multires:
            multires.levels = multires.total_levels
            subsurf = multires
        elif not subsurf:
            # Create new subsurf modifier if there's none
            bpy.ops.object.modifier_add(type="SUBSURF")
            subsurf = [m for m in obj.modifiers if m.type == "SUBSURF"][0]
            # NOTE: This just random default subdivision levels
            subsurf.levels = 3
            subsurf.render_levels = 3
            if is_mesh_flat_shaded(obj.data):
                subsurf.subdivision_type = "SIMPLE"

        # Disable other modifiers
        ori_show_viewports = {}
        ori_show_renders = {}
        for m in obj.modifiers:
            if m != subsurf:
                ori_show_viewports[m.name] = m.show_viewport
                ori_show_renders[m.name] = m.show_render
                m.show_viewport = False
                m.show_render = False
            else:
                m.show_viewport = True
                m.show_render = True

        # Bake tangent and bitangent first
        tanimage, bitimage = get_tangent_bitangent_images(obj, uv_name)

        # Create a temporary object
        temp = obj.copy()
        link_object(scene, temp)
        temp.data = temp.data.copy()
        context.view_layer.objects.active = temp
        temp.location += Vector(((obj.dimensions[0] + 0.1) * 1, 0.0, 0.0))

        # Select temp object
        set_active_object(temp)
        set_object_select(temp, True)

        # Create geometry nodes to load vdm
        sculpt_image = image
        if combined_vdm_image:
            sculpt_image = combined_vdm_image
            intensity = 1.0

        vdm_loader = get_vdm_loader_geotree(
            uv_name, sculpt_image, tanimage, bitimage, intensity
        )
        bpy.ops.object.modifier_add(type="NODES")
        geomod = temp.modifiers[-1]
        geomod.node_group = vdm_loader
        temp.modifiers.active = geomod

        # Select back active object
        set_active_object(obj)
        set_object_select(obj, True)

        # Add multires modifier
        multires = get_multires_modifier(obj)  # , TEMP_MULTIRES_NAME)
        if not multires:
            bpy.ops.object.modifier_add(type="MULTIRES")
            multires = [m for m in obj.modifiers if m.type == "MULTIRES"][0]
            multires.name = TEMP_MULTIRES_NAME

        # Disable subsurf
        subsurf = get_subsurf_modifier(obj)
        if subsurf:
            subsurf.show_viewport = False
            subsurf.show_render = False
            levels = subsurf.levels
            subdiv_type = subsurf.subdivision_type
        else:
            levels = multires.total_levels
            subdiv_type = "SIMPLE" if is_mesh_flat_shaded(obj.data) else "CATMULL_CLARK"

        # Set to max levels
        for i in range(levels - multires.total_levels):
            bpy.ops.object.multires_subdivide(modifier=multires.name, mode=subdiv_type)
        multires.levels = multires.total_levels
        multires.sculpt_levels = multires.total_levels
        multires.render_levels = multires.total_levels

        # Disable use simplify before reshape
        ori_use_simplify = scene.render.use_simplify
        scene.render.use_simplify = False

        # Reshape multires
        bpy.ops.object.multires_reshape(modifier=multires.name)

        # Recover use simplify
        if ori_use_simplify:
            scene.render.use_simplify = True

        # Remove temp data
        remove_mesh_obj(temp)
        # bpy.data.images.remove(tanimage)
        # bpy.data.images.remove(bitimage)
        bpy.data.node_groups.remove(vdm_loader)
        if combined_vdm_image:
            bpy.data.images.remove(combined_vdm_image)

        # Enable some modifiers again
        for mod_name, ori_show_viewport in ori_show_viewports.items():
            m = obj.modifiers.get(mod_name)
            if m:
                m.show_viewport = ori_show_viewport
        for mod_name, ori_show_render in ori_show_renders.items():
            m = obj.modifiers.get(mod_name)
            if m:
                m.show_render = ori_show_render

        # Set armature to the top
        arm = get_armature_modifier(obj)
        if arm:
            bpy.ops.object.modifier_move_to_index(modifier=arm.name, index=0)

        bpy.ops.object.mode_set(mode="SCULPT")

        self.report(
            {"INFO"},
            "Sculpt mode is entered in "
            + "{:0.2f}".format(time.time() - T)
            + " seconds!",
        )

        return {"FINISHED"}


class MApplySculptToImage(bpy.types.Operator):
    bl_idname = "sculpt.y_apply_sculpt_to_image"
    bl_label = "Apply Sculpt to Image"
    bl_description = "Apply sculpt to image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            bool: True if there is an active mpaint node.
        """
        return get_active_mpaint_node()

    def execute(self, context):
        """Execute the apply sculpt to image operation.

        Bakes the multires sculpt data back to the vector displacement image, removes the multires
        modifier, and exits sculpt mode.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            set: {"FINISHED"} when operation completes successfully.
        """
        T = time.time()

        obj = get_active_object()
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp
        layer = mp.layers[mp.active_layer_index]
        height_ch = get_height_channel(layer)

        if height_ch:

            source = get_layer_source(layer)
            image = source.image
            uv_name = layer.uv_name

            intensity = get_vdm_intensity(layer, height_ch)

            # Bake multires image
            bake_multires_image(obj, image, uv_name, intensity)

        # Remove multires
        multires = get_multires_modifier(obj)
        levels = -1
        if multires:
            levels = multires.total_levels
            bpy.ops.object.modifier_remove(modifier=multires.name)

        # Enable subsurf back
        subsurf = get_subsurf_modifier(obj)
        if subsurf:
            subsurf.show_viewport = True
            subsurf.show_render = True
        else:
            bpy.ops.object.modifier_add(type="SUBSURF")
            subsurf = [m for m in obj.modifiers if m.type == "SUBSURF"][0]
            if levels != -1:
                subsurf.levels = levels
                subsurf.render_levels = levels

        # Disable sculpt mode to bring back all vector displacement layers
        mp.sculpt_mode = False
        bpy.ops.object.mode_set(mode="OBJECT")

        # Go back to material view
        space = bpy.context.space_data
        if space.type == "VIEW_3D" and space.shading.type not in {
            "MATERIAL",
            "RENDERED",
        }:
            space.shading.type = "MATERIAL"

        self.report(
            {"INFO"},
            "Applying sculpt to VDM is done in "
            + "{:0.2f}".format(time.time() - T)
            + " seconds!",
        )

        return {"FINISHED"}


class MCancelSculptToImage(bpy.types.Operator):
    bl_idname = "sculpt.y_cancel_sculpt_to_image"
    bl_label = "Cancel Sculpt to Image"
    bl_description = "Cancel sculpt to image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            bool: True if there is an active mpaint node.
        """
        return get_active_mpaint_node()

    def execute(self, context):
        """Execute the cancel sculpt to image operation.

        Removes the temporary multires modifier without saving changes, restores the subsurf modifier,
        and exits sculpt mode.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            set: {"FINISHED"} when operation completes successfully.
        """
        obj = get_active_object()
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp
        layer = mp.layers[mp.active_layer_index]
        height_ch = get_height_channel(layer)

        # Remove multires
        multires = get_multires_modifier(obj, TEMP_MULTIRES_NAME)
        if multires:
            bpy.ops.object.modifier_remove(modifier=multires.name)

        # Enable subsurf back
        subsurf = get_subsurf_modifier(obj)
        if not subsurf:
            subsurf = get_multires_modifier(obj)
        if subsurf:
            subsurf.show_viewport = True
            subsurf.show_render = True

        # Disable sculpt mode to bring back all vector displacement layers
        mp.sculpt_mode = False
        bpy.ops.object.mode_set(mode="OBJECT")

        # Go back to material view
        space = bpy.context.space_data
        if space.type == "VIEW_3D" and space.shading.type not in {
            "MATERIAL",
            "RENDERED",
        }:
            space.shading.type = "MATERIAL"

        return {"FINISHED"}


class MFixVDMMismatchUV(bpy.types.Operator):
    bl_idname = "object.y_fix_vdm_missmatch_uv"
    bl_label = "Fix Missmatch VDM UV"
    bl_description = "Active VDM layer has different UV than the active render UV, use this operator to fix it"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            bool: True if there is an active mpaint node.
        """
        return get_active_mpaint_node()

    def execute(self, context):
        """Execute the fix VDM mismatch UV operation.

        Sets the VDM layer's UV map as the active render UV for all objects with the same material.

        Args:
            context: Blender context containing scene and object data.

        Returns:
            set: {"FINISHED"} when operation completes successfully.
        """
        obj = get_active_object()
        mat = get_active_material(obj)
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer = mp.layers[mp.active_layer_index]

        # Set uv map active render
        objs = get_all_objects_with_same_materials(mat)
        for obj in objs:
            uv_layers = get_uv_layers(obj)
            uv = uv_layers.get(layer.uv_name)
            if uv and not uv.active_render:
                uv.active_render = True

        return {"FINISHED"}
