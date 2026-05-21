# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Displacement and parallax helper functions.

Functions for managing parallax, displacement, and subdivision settings.
"""

import math

import bpy

from ...core.element.get_elements import get_multires_modifier, get_subsurf_modifier
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.subtree.get_subtree import get_displacement_max_height
from ...utils.blender_commons import (
    get_active_material,
    get_user_preferences,
    set_active_object,
)
from ...utils.common import is_mesh_flat_shaded
from ..bake.utils.bake_subdivision import get_objs_size_proportions


def update_parallax_rim_hack(self, context):
    """Update parallax rim hack settings for all UVs.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    group_tree = self.id_data
    mp = group_tree.mp

    # parallax = group_tree.nodes.get(BAKED_PARALLAX)
    # if parallax:
    #    try:
    #        parallax.inputs['Rim Hack'].default_value = 1.0 if self.parallax_rim_hack else 0.0
    #        parallax.inputs['Rim Hack Hardness'].default_value = self.parallax_rim_hack_hardness
    #    except: pass

    for uv in mp.uvs:
        parallax_prep = group_tree.nodes.get(uv.parallax_prep)
        if parallax_prep:
            parallax_prep.inputs["Rim Hack"].default_value = (
                1.0 if self.parallax_rim_hack else 0.0
            )
            parallax_prep.inputs["Rim Hack Hardness"].default_value = (
                self.parallax_rim_hack_hardness
            )


def update_parallax_height_tweak(self, context):
    """Update parallax height tweak value for all UVs.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    group_tree = self.id_data
    mp = group_tree.mp

    for uv in mp.uvs:
        parallax_prep = group_tree.nodes.get(uv.parallax_prep)
        if parallax_prep:
            parallax_prep.inputs["depth_scale"].default_value = (
                get_displacement_max_height(self) * self.parallax_height_tweak
            )


def update_displacement_ref_plane(self, context):
    """Update displacement reference plane for all UVs.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    group_tree = self.id_data
    mp = group_tree.mp

    for uv in mp.uvs:
        parallax_prep = group_tree.nodes.get(uv.parallax_prep)
        if parallax_prep:
            parallax_prep.inputs["ref_plane"].default_value = self.parallax_ref_plane


def setup_subdiv_to_max_polys(obj, max_polys, subsurf=None):
    """Setup subdivision modifier to reach maximum polygon count.

    Calculates and sets subdivision levels to reach the target polygon count.

    Args:
        obj: Object to setup subdivision on.
        max_polys (int): Maximum number of polygons target.
        subsurf (optional): Subdivision modifier to use. Defaults to None.
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


def update_subdiv_max_polys(self, context):
    """Update subdivision max polygons for all objects with material.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    mat = get_active_material()
    tree = self.id_data
    mp = tree.mp
    mpup = get_user_preferences()
    height_ch = self
    objs = get_all_objects_with_same_materials(mat, True)

    # if not mpup.eevee_next_displacement and (not mp.use_baked or not height_ch.enable_subdiv_setup or self.subdiv_adaptive): return
    if not height_ch.enable_subdiv_setup:
        return

    proportions = get_objs_size_proportions(objs)

    for obj in objs:

        subsurf = get_subsurf_modifier(obj)
        multires = get_multires_modifier(obj)

        if multires and not height_ch.subdiv_subsurf_only:
            subsurf = multires

        if not subsurf:
            continue

        setup_subdiv_to_max_polys(
            obj, height_ch.subdiv_on_max_polys * 1000 * proportions[obj.name], subsurf
        )
