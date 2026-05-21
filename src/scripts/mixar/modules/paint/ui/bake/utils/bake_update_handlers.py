# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update handler functions for bake operations."""

from ....core.element.get_elements import get_multires_modifier, get_subsurf_modifier
from ....core.element.update_image import update_image_editor_image
from ....core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_mp_nodes
from ....core.layer.check_channels import check_start_end_root_ch_nodes
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.check_nodes import check_uv_nodes
from ....utils.blender_commons import get_active_material, get_user_preferences
from .bake_operators_helper import get_objs_size_proportions, setup_subdiv_to_max_polys


def update_subdiv_max_polys(self, context):
    """Update subdivision max polygons settings for objects.

    Args:
        self: Height channel property group.
        context: Blender context.
    """
    mat = get_active_material()
    tree = self.id_data
    mp = tree.mp
    height_ch = self
    objs = get_all_objects_with_same_materials(mat, True)

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


def update_subdiv_global_dicing(self, context):
    """Update global dicing rate for subdivision in Cycles.

    Args:
        self: Height channel property group.
        context: Blender context.
    """
    scene = context.scene
    height_ch = self

    scene.cycles.dicing_rate = height_ch.subdiv_global_dicing
    scene.cycles.preview_dicing_rate = height_ch.subdiv_global_dicing


def update_active_bake_target_index(self, context):
    """Update active bake target and display its image in editor.

    Args:
        self: MPaint property group.
        context: Blender context.
    """
    mp = self
    tree = self.id_data
    try:
        bt = mp.bake_targets[mp.active_bake_target_index]
    except:
        return

    bt_node = tree.nodes.get(bt.image_node)
    if bt_node and bt_node.image:
        update_image_editor_image(context, bt_node.image)
    else:
        update_image_editor_image(context, None)


def update_use_baked(self, context):
    """Update baked texture usage and reconnect nodes accordingly.

    Args:
        self: Channel or entity property group.
        context: Blender context.
    """
    # Import here to avoid circular imports
    from ..channel.bake_outside_nodes import update_enable_baked_outside
    from ...operators.operators_helper_preview import remove_preview

    tree = self.id_data
    mp = tree.mp

    if mp.halt_update:
        return

    # When disabling use_baked, clean up preview state
    if not mp.use_baked:
        if mp.preview_mode:
            # This triggers update_preview_mode which calls remove_preview
            mp.preview_mode = False
        else:
            # Clean up any lingering emission viewer even if preview_mode wasn't on
            mat = get_active_material()
            if mat:
                remove_preview(mat)

    # Check uv nodes
    check_uv_nodes(mp)

    # Check start and end nodes
    check_start_end_root_ch_nodes(tree)

    # Reconnect nodes
    reconnect_mp_nodes(tree)
    rearrange_mp_nodes(tree)

    # Trigger active image update
    if mp.use_baked:
        mp.active_channel_index = mp.active_channel_index
    else:
        mp.active_layer_index = mp.active_layer_index

    # Update baked outside
    update_enable_baked_outside(self, context)


def update_enable_bake_to_vcol(self, context):
    """Update bake to vertex color settings.

    Args:
        self: Channel or entity property group.
        context: Blender context.
    """
    tree = self.id_data
    mp = tree.mp

    if mp.halt_update:
        return
    if mp.enable_baked_outside:
        # Reset the node location
        mp.enable_baked_outside = False
        mp["enable_baked_outside"] = True
    update_use_baked(self, context)
