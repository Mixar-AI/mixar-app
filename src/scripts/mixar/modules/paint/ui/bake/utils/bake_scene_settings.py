# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene and compositor settings utilities for baking operations"""

import bpy

from ....core.io.input_outputs.outputs import new_tree_output
from ....utils.blender_commons import is_bl_newer_than


def get_compositor_node_tree(scene):
    """Get compositor node tree for the scene based on Blender version.

    Args:
        scene: Blender scene object.

    Returns:
        NodeTree: Compositor node tree for the scene.
    """
    if not is_bl_newer_than(5):
        return scene.node_tree

    return scene.compositing_node_group


def get_compositor_output_node(tree):
    """Get or create compositor output node for the given tree.

    Args:
        tree: Compositor node tree.

    Returns:
        Node: Compositor output node or None if tree is None.
    """
    # Safety check: return None if tree is None
    if not tree:
        return None

    node_type = "GROUP_OUTPUT" if is_bl_newer_than(5) else "COMPOSITE"
    for n in tree.nodes:
        if n.type == node_type:
            return n

    # Create new compositor output if there's none
    if is_bl_newer_than(5):
        n = tree.nodes.new("NodeGroupOutput")
        if "Image" not in n.inputs:
            new_tree_output(tree, "Image", "NodeSocketColor")
    else:
        n = tree.nodes.new("CompositorNodeComposite")

    return n


def get_scene_bake_multires(scene):
    """Get multires bake setting from scene based on Blender version.

    Args:
        scene: Blender scene object.

    Returns:
        bool: Multires bake setting value.
    """
    if is_bl_newer_than(4, 1):
        return scene.render.bake.use_multires
    return scene.render.use_bake_multires


def get_scene_bake_clear(scene):
    """Get bake clear setting from scene based on Blender version.

    Args:
        scene: Blender scene object.

    Returns:
        bool: Bake clear setting value.
    """
    if is_bl_newer_than(4, 1):
        return scene.render.bake.use_clear
    return scene.render.bake.use_clear


def get_scene_render_bake_type(scene):
    """Get render bake type from scene.

    Args:
        scene: Blender scene object.

    Returns:
        str: Bake type value.
    """
    return scene.render.bake.type


def get_scene_bake_margin(scene):
    """Get bake margin from scene.

    Args:
        scene: Blender scene object.

    Returns:
        int: Bake margin value in pixels.
    """
    return scene.render.bake.margin


def set_scene_bake_multires(scene, value):
    """Set multires bake setting on scene based on Blender version.

    Args:
        scene: Blender scene object.
        value: Boolean value to set.
    """
    if is_bl_newer_than(4, 1):
        scene.render.bake.use_multires = value
    else:
        scene.render.use_bake_multires = value


def set_scene_bake_clear(scene, value):
    """Set bake clear setting on scene based on Blender version.

    Args:
        scene: Blender scene object.
        value: Boolean value to set.
    """
    if is_bl_newer_than(4, 1):
        scene.render.bake.use_clear = value
    else:
        scene.render.bake.use_clear = value


def set_scene_render_bake_type(scene, value):
    """Set render bake type on scene.

    Args:
        scene: Blender scene object.
        value: Bake type string value.
    """
    scene.render.bake.type = value


def set_scene_bake_margin(scene, value):
    """Set bake margin on scene.

    Args:
        scene: Blender scene object.
        value: Margin value in pixels.
    """
    scene.render.bake.margin = value
