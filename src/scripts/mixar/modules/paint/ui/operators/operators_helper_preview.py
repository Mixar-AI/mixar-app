# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview mode helper functions.

Functions for managing preview/emission viewer mode in materials.
"""

import bpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.layer.check_channels import check_all_channel_ios
from ...core.layer.layer_utils import update_preview_mix
from ...core.lib.lib import (
    ADVANCED_EMISSION_VIEWER,
    ADVANCED_NORMAL_EMISSION_VIEWER,
    NORMAL_EMISSION_VIEWER,
)
from ...core.lib.lib_operations import duplicate_lib_node_tree
from ...core.material.check_materials import is_mp_on_material
from ...core.material.get_materials import get_materials_using_mp
from ...core.node.get_nodes import (
    get_active_mat_output_node,
    get_nodes_using_mp,
)
from ...core.node.node_utils import get_active_mpaint_node
from ...core.node.update_nodes import simple_replace_new_node
from ...utils.blender_commons import (
    get_active_material,
    get_user_preferences,
    is_bl_newer_than,
    simple_remove_node,
)
from ...utils.constants import (
    EMISSION_VIEWER,
    LAYER_ALPHA_VIEWER,
    LAYER_VIEWER,
)

def get_preview(mat, output=None, advanced=False, normal_viewer=False):
    """Get or create emission viewer node for preview mode.

    Args:
        mat: Material to get preview node from.
        output (optional): Material output node. Defaults to None.
        advanced (bool, optional): Use advanced emission viewer. Defaults to False.
        normal_viewer (bool, optional): Use normal-specific viewer. Defaults to False.

    Returns:
        Node: Emission viewer node, or None if output not found.
    """
    tree = mat.node_tree
    # nodes = tree.nodes

    # Search for output
    if not output:
        output = get_active_mat_output_node(tree)

    if not output:
        return None

    if advanced:
        if normal_viewer:
            preview, dirty = simple_replace_new_node(
                tree,
                EMISSION_VIEWER,
                "ShaderNodeGroup",
                "Emission Viewer",
                ADVANCED_NORMAL_EMISSION_VIEWER,
                return_status=True,
                hard_replace=True,
            )
        else:
            preview, dirty = simple_replace_new_node(
                tree,
                EMISSION_VIEWER,
                "ShaderNodeGroup",
                "Emission Viewer",
                ADVANCED_EMISSION_VIEWER,
                return_status=True,
                hard_replace=True,
            )
        if dirty:
            duplicate_lib_node_tree(preview)
            # preview.node_tree = preview.node_tree.copy()
            # Set blend method to alpha
            # if is_bl_newer_than(2, 80):
            #    blend_method = mat.blend_method
            #    mat.blend_method = 'HASHED'
            # else:
            #    blend_method = mat.game_settings.alpha_blend
            #    mat.game_settings.alpha_blend = 'ALPHA'
            # mat.mp.ori_blend_method = blend_method
    else:
        if normal_viewer:
            preview, dirty = simple_replace_new_node(
                tree,
                EMISSION_VIEWER,
                "ShaderNodeGroup",
                "Emission Viewer",
                NORMAL_EMISSION_VIEWER,
                return_status=True,
                hard_replace=True,
            )
        else:
            preview, dirty = simple_replace_new_node(
                tree,
                EMISSION_VIEWER,
                "ShaderNodeEmission",
                "Emission Viewer",
                return_status=True,
            )

    if dirty:
        preview.hide = True
        preview.location = (output.location.x, output.location.y + 30.0)

    if output.inputs[0].links:

        # Remember output and original bsdf
        ori_bsdf = output.inputs[0].links[0].from_node
        ori_socket = output.inputs[0].links[0].from_socket
        ori_bsdf_output_index = 0
        for i, outp in enumerate(ori_bsdf.outputs):
            if outp == ori_socket:
                ori_bsdf_output_index = i

        # Only remember original BSDF if its not the preview node itself
        if ori_bsdf != preview:
            mat.mp.ori_bsdf = ori_bsdf.name
            mat.mp.ori_bsdf_output_index = ori_bsdf_output_index

    return preview


def set_srgb_view_transform():
    """Set view transform to sRGB for accurate preview mode.

    Saves original view settings and switches to Standard/sRGB view transform
    for accurate color preview.
    """
    scene = bpy.context.scene

    mpup = get_user_preferences()

    # Set view transform to srgb
    if scene.mp.ori_view_transform == "" and mpup.make_preview_mode_srgb:

        scene.mp.ori_look = scene.view_settings.look
        scene.view_settings.look = "None"

        if is_bl_newer_than(5):
            if scene.compositing_node_group:
                scene.mp.ori_compositing_node_name = scene.compositing_node_group.name
                scene.compositing_node_group = None
        else:
            scene.mp.ori_use_compositing = scene.use_nodes
            scene.use_nodes = False

        scene.mp.ori_view_transform = scene.view_settings.view_transform
        if is_bl_newer_than(2, 80):
            try:
                scene.view_settings.view_transform = "Standard"
            except Exception as e:
                logger.error(e)
        else:
            try:
                scene.view_settings.view_transform = "Default"
            except Exception as e:
                logger.error(e)

        scene.mp.ori_display_device = scene.display_settings.display_device
        try:
            scene.display_settings.display_device = "sRGB"
        except Exception as e:
            logger.error(e)

        scene.mp.ori_exposure = scene.view_settings.exposure
        scene.view_settings.exposure = 0.0

        scene.mp.ori_gamma = scene.view_settings.gamma
        scene.view_settings.gamma = 1.0

        scene.mp.ori_use_curve_mapping = scene.view_settings.use_curve_mapping
        scene.view_settings.use_curve_mapping = False


def remove_preview(mat, advanced=False):
    """Remove emission viewer preview node and restore original connections.

    Args:
        mat: Material to remove preview from.
        advanced (bool, optional): Whether preview was advanced type. Defaults to False.
    """
    nodes = mat.node_tree.nodes
    preview = nodes.get(EMISSION_VIEWER)
    scene = bpy.context.scene

    if preview:
        simple_remove_node(mat.node_tree, preview)
        bsdf = nodes.get(mat.mp.ori_bsdf)
        output = get_active_mat_output_node(mat.node_tree)
        mat.mp.ori_bsdf = ""

        if bsdf and output:
            mat.node_tree.links.new(
                bsdf.outputs[mat.mp.ori_bsdf_output_index], output.inputs[0]
            )

        # Recover view transform
        if scene.mp.ori_view_transform != "":
            scene.view_settings.view_transform = scene.mp.ori_view_transform
            scene.mp.ori_view_transform = ""

            scene.display_settings.display_device = scene.mp.ori_display_device
            scene.view_settings.look = scene.mp.ori_look
            scene.view_settings.exposure = scene.mp.ori_exposure
            scene.view_settings.gamma = scene.mp.ori_gamma
            scene.view_settings.use_curve_mapping = scene.mp.ori_use_curve_mapping
            if is_bl_newer_than(5):
                if scene.mp.ori_compositing_node_name != "":
                    cng = bpy.data.node_groups.get(scene.mp.ori_compositing_node_name)
                    if cng:
                        scene.compositing_node_group = cng
                    scene.mp.ori_compositing_node_name = ""
            else:
                scene.use_nodes = scene.mp.ori_use_compositing


def update_preview_mode(self, context):
    """Toggle channel preview mode on/off.

    Sets up or removes emission viewer for previewing individual channel outputs.

    Args:
        self: MPaint property group.
        context: Blender context.
    """
    mp = self
    mat = get_active_material()

    if is_mp_on_material(mp, mat):
        group_node = get_active_mpaint_node()
    else:
        mats = get_materials_using_mp(mp)
        if not mats:
            return
        mat = mats[0]
        group_nodes = get_nodes_using_mp(mat, mp)
        if not group_nodes:
            return
        group_node = group_nodes[0]

    tree = mat.node_tree
    index = mp.active_channel_index
    channel = mp.channels[index]

    if mp.layer_preview_mode and mp.preview_mode:
        mp.layer_preview_mode = False

    if self.preview_mode:
        # Set view transform to srgb so color picker won't pick wrong color
        set_srgb_view_transform()

        output = get_active_mat_output_node(mat.node_tree)

        # Get preview node by name first
        preview = mat.node_tree.nodes.get(EMISSION_VIEWER)

        # Try to get socket that connected to preview first input
        if preview:
            from_socket = [link.from_socket for link in preview.inputs[0].links]
            if from_socket:
                from_socket = from_socket[0]
        else:
            from_socket = None

        # Check if there's any valid socket connected to first input of preview node
        is_from_socket_missing = not from_socket or (
            from_socket and not from_socket.name.startswith(channel.name)
        )

        # Get all outputs from current channel
        outs = [o for o in group_node.outputs if o.name.startswith(channel.name)]

        # Use special preview for normal
        if channel.type == "NORMAL" and (
            is_from_socket_missing or (from_socket and from_socket == outs[-1])
        ):
            preview = get_preview(mat, output, False, True)
        else:
            preview = get_preview(mat, output, False)

        # Preview should exists by now
        if not preview:
            return

        if is_from_socket_missing:
            # Connect first output
            tree.links.new(group_node.outputs[channel.name], preview.inputs[0])
        else:
            # Cycle outputs
            for i, o in enumerate(outs):
                if o == from_socket:
                    if i != len(outs) - 1:
                        tree.links.new(outs[i + 1], preview.inputs[0])
                    else:
                        tree.links.new(outs[0], preview.inputs[0])

        tree.links.new(preview.outputs[0], output.inputs[0])
    else:
        remove_preview(mat)


def update_layer_preview_mode(self, context):
    """Toggle layer preview mode on/off.

    Sets up or removes advanced emission viewer for previewing individual layer output.

    Args:
        self: MPaint property group.
        context: Blender context.
    """
    mp = self
    mat = get_active_material()

    if is_mp_on_material(mp, mat):
        group_node = get_active_mpaint_node()
    else:
        mats = get_materials_using_mp(mp)
        if not mats:
            return
        mat = mats[0]
        group_nodes = get_nodes_using_mp(mat, mp)
        if not group_nodes:
            return
        group_node = group_nodes[0]

    tree = mat.node_tree
    index = mp.active_channel_index
    channel = mp.channels[index]
    layer = mp.layers[mp.active_layer_index]

    if mp.preview_mode and mp.layer_preview_mode:
        mp.preview_mode = False

    # Get preview node
    if mp.layer_preview_mode:

        check_all_channel_ios(mp, specific_layer=layer)

        # Set view transform to srgb so color picker won't pick wrong color
        set_srgb_view_transform()

        output = get_active_mat_output_node(mat.node_tree)
        if mp.layer_preview_mode_type in {"ALPHA", "SPECIFIC_MASK"}:
            preview = get_preview(mat, output, False)
            if not preview:
                return

            tree.links.new(group_node.outputs[LAYER_ALPHA_VIEWER], preview.inputs[0])
            tree.links.new(preview.outputs[0], output.inputs[0])

        else:
            ch = layer.channels[mp.active_channel_index]

            if (
                channel.type == "NORMAL"
                and ch.normal_map_type != "VECTOR_DISPLACEMENT_MAP"
            ):
                preview = get_preview(mat, output, True, True)
            else:
                preview = get_preview(mat, output, True)
            if not preview:
                return

            tree.links.new(group_node.outputs[LAYER_VIEWER], preview.inputs[0])
            tree.links.new(group_node.outputs[LAYER_ALPHA_VIEWER], preview.inputs[1])
            tree.links.new(preview.outputs[0], output.inputs[0])

            # Set gamma
            if "Gamma" in preview.inputs:
                if channel.colorspace != "LINEAR" and not mp.use_linear_blending:
                    if preview.inputs["Gamma"].default_value != 2.2:
                        preview.inputs["Gamma"].default_value = 2.2
                else:
                    if preview.inputs["Gamma"].default_value != 1.0:
                        preview.inputs["Gamma"].default_value = 1.0

            # Set channel layer blending
            # mix = preview.node_tree.nodes.get('Mix')
            # mix.blend_type = ch.blend_type
            update_preview_mix(ch, preview)

            # Use different grid if channel is not enabled
            preview.inputs["Missing Data"].default_value = (
                1.0 if (not ch.enable or not layer.enable) else 0.0
            )

    else:
        check_all_channel_ios(mp)
        remove_preview(mat)


