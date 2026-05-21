# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Subdivision and displacement setup for baking operations"""

from mixar.config.logging_config import get_logger

import math

import bpy

logger = get_logger(__name__)

from ....core.element.get_elements import get_multires_modifier, get_subsurf_modifier
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_channels import check_all_channel_ios, check_displacement_node
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.get_nodes import get_material_output
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_user_preferences,
    set_active_object,
)
from ....utils.common import is_mesh_flat_shaded


def check_subdiv_setup(height_ch):
    """Configure subdivision and displacement settings for height channel.

    Parameters:
        height_ch: Height channel with subdivision properties

    Returns:
        None
    """
    tree = height_ch.id_data
    mp = tree.mp
    mpup = get_user_preferences()

    if not height_ch:
        return
    mat = get_active_material()
    scene = bpy.context.scene
    objs = get_all_objects_with_same_materials(mat, True)

    mtree = mat.node_tree

    # Get active output material
    output_mat = get_material_output(mat)
    if not output_mat:
        return

    # Get active mpaint node
    node = get_active_mpaint_node()
    norm_outp = node.outputs[height_ch.name]

    # Scene and material displacement settings
    if height_ch.enable_subdiv_setup:

        # Displacement only works with experimental feature set in Blender 2.79
        if height_ch.subdiv_adaptive:
            scene.cycles.feature_set = "EXPERIMENTAL"

        if height_ch.subdiv_adaptive:
            scene.cycles.dicing_rate = height_ch.subdiv_global_dicing
            scene.cycles.preview_dicing_rate = height_ch.subdiv_global_dicing

        # Set displacement mode
        if hasattr(mat, "displacement_method"):
            mat.displacement_method = "BOTH"

        # Set cycles displacement mode
        if hasattr(mat.cycles, "displacement_method"):
            mat.cycles.displacement_method = "BOTH"

        if not mp.use_baked or not mp.enable_baked_outside:
            check_displacement_node(mat, node, set_one=True)

    # Remember active object
    ori_active_obj = get_active_object()

    # Iterate all objects with same materials
    proportions = get_objs_size_proportions(objs)
    for obj in objs:

        # Set active object to modify modifier order
        set_active_object(obj)

        # Subsurf / Multires Modifier
        subsurf = get_subsurf_modifier(obj)
        multires = get_multires_modifier(obj, include_hidden=True)

        if multires:
            if height_ch.enable_subdiv_setup and (
                height_ch.subdiv_subsurf_only or height_ch.subdiv_adaptive
            ):
                multires.show_render = False
                multires.show_viewport = False
            else:
                if subsurf:
                    obj.modifiers.remove(subsurf)
                multires.show_render = True
                multires.show_viewport = True
                subsurf = multires

        if height_ch.enable_subdiv_setup:
            if not subsurf:
                subsurf = obj.modifiers.new("Subsurf", "SUBSURF")
                if obj.type == "MESH" and is_mesh_flat_shaded(obj.data):
                    subsurf.subdivision_type = "SIMPLE"

            setup_subdiv_to_max_polys(
                obj,
                height_ch.subdiv_on_max_polys * 1000 * proportions[obj.name],
                subsurf,
            )

        # Set subsurf to visible
        if subsurf:
            subsurf.show_render = True
            subsurf.show_viewport = True

        # Adaptive subdiv - only available in certain Blender versions
        # In Blender 2.80-2.93 it was removed, reintroduced in 4.5+
        # Handle gracefully if not available
        try:
            if height_ch.enable_subdiv_setup and height_ch.subdiv_adaptive:
                obj.cycles.use_adaptive_subdivision = True
            else:
                obj.cycles.use_adaptive_subdivision = False
        except AttributeError:
            # Adaptive subdivision not available in this Blender version
            # This is expected in some versions and can be safely ignored
            pass

    set_active_object(ori_active_obj)


def remember_subsurf_levels():
    """Store original subdivision levels for all objects using active material.

    Parameters:
        None

    Returns:
        None
    """
    # print('Remembering')
    mat = get_active_material()
    objs = get_all_objects_with_same_materials(mat, True)

    for obj in objs:
        subsurf = get_subsurf_modifier(obj)
        if subsurf:
            obj.mp.ori_subsurf_render_levels = subsurf.render_levels
            obj.mp.ori_subsurf_levels = subsurf.levels

        multires = get_multires_modifier(obj)
        if multires:
            obj.mp.ori_multires_render_levels = multires.render_levels
            obj.mp.ori_multires_levels = multires.levels


def recover_subsurf_levels():
    """Restore subdivision levels from stored values for all objects using active material.

    Parameters:
        None

    Returns:
        None
    """
    # print('Recovering')
    mat = get_active_material()
    objs = get_all_objects_with_same_materials(mat, True)

    for obj in objs:
        subsurf = get_subsurf_modifier(obj)
        if subsurf:
            if subsurf.render_levels != obj.mp.ori_subsurf_render_levels:
                subsurf.render_levels = obj.mp.ori_subsurf_render_levels
            if subsurf.levels != obj.mp.ori_subsurf_levels:
                subsurf.levels = obj.mp.ori_subsurf_levels

        multires = get_multires_modifier(obj)
        if multires:
            render_levels = (
                obj.mp.ori_multires_render_levels
                if obj.mp.ori_multires_render_levels <= multires.total_levels
                else multires.total_levels
            )
            if multires.render_levels != render_levels:
                multires.render_levels = render_levels

            levels = (
                obj.mp.ori_multires_levels
                if obj.mp.ori_multires_levels <= multires.total_levels
                else multires.total_levels
            )
            if multires.levels != levels:
                multires.levels = levels


def setup_subdiv_to_max_polys(obj, max_polys, subsurf=None):
    """Configure subdivision modifier to achieve target polygon count.

    Parameters:
        obj: Blender object to modify
        max_polys (float): Target maximum polygon count
        subsurf (Modifier, optional): Subsurf/multires modifier. Default None

    Returns:
        None
    """
    if obj.type != "MESH":
        return
    if not subsurf:
        subsurf = get_subsurf_modifier(obj)
    if not subsurf:
        return

    # Check object polygons
    num_poly = len(obj.data.polygons)

    # Get levels
    level = int(math.log(max_polys / num_poly, 4))

    if subsurf.type == "MULTIRES":
        if level > subsurf.total_levels:
            set_active_object(obj)
            for i in range(level - subsurf.total_levels):
                if is_mesh_flat_shaded(obj.data):
                    bpy.ops.object.multires_subdivide(
                        modifier=subsurf.name, mode="SIMPLE"
                    )
                else:
                    bpy.ops.object.multires_subdivide(
                        modifier=subsurf.name, mode="CATMULL_CLARK"
                    )
            level = subsurf.total_levels
    else:
        # Maximum subdivision is 10
        if level > 10:
            level = 10

    subsurf.render_levels = level
    subsurf.levels = level


def get_objs_size_proportions(objs):
    """Calculate size proportion of each object relative to total size.

    Parameters:
        objs (list): List of Blender objects

    Returns:
        dict: Dictionary mapping object names to size proportions (0.0-1.0)
    """
    sizes = []

    for obj in objs:
        sorted_dim = sorted(obj.dimensions, reverse=True)
        # Object size is only measured on its largest 2 dimensions because this should work on a plane too
        size = sorted_dim[0] * sorted_dim[1]
        sizes.append(size)

    total_size = sum(sizes)

    # Measure object size compared to total size
    proportions = {}
    for i, size in enumerate(sizes):
        proportions[objs[i].name] = size / total_size

    return proportions


def update_enable_subdiv_setup(self, context):
    """Update when subdivision setup is enabled or disabled.

    Parameters:
        self: Height channel property
        context: Blender context

    Returns:
        None
    """
    tree = self.id_data
    mp = tree.mp
    height_ch = self

    if height_ch.enable_subdiv_setup:
        remember_subsurf_levels()

    update_subdiv_setup(self, context)

    if not height_ch.enable_subdiv_setup:
        recover_subsurf_levels()


def update_subdiv_setup(self, context):
    """Update subdivision setup and reconnect nodes.

    Parameters:
        self: Height channel property
        context: Blender context

    Returns:
        None
    """
    tree = self.id_data
    mp = tree.mp

    # Unset displacement node setup
    if not self.enable_subdiv_setup:
        mat = get_active_material()
        node = get_active_mpaint_node()
        check_displacement_node(mat, node, unset_one=True)

    # Check input and outputs
    check_all_channel_ios(mp, reconnect=False)

    # Check subdiv setup
    check_subdiv_setup(self)

    # Reconnect layers
    for layer in mp.layers:
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

    # Reconnect nodes
    reconnect_mp_nodes(tree)
    rearrange_mp_nodes(tree)
