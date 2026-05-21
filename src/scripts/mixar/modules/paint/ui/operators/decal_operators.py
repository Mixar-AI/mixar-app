# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decal object operators for Mixar layers system.

Implements operators for decal object selection and positioning:
- MSelectDecalObject: Select and activate the decal empty object
- MSetDecalObjectPositionToCursor: Move decal object to 3D cursor
"""

import re
import bpy
from bpy.types import Operator

from .....config.logging_config import get_logger
from ...core.node.get_nodes import get_tree
from ...core.subtree.get_subtree import get_mask_tree
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    set_active_object,
    set_object_select,
    get_scene_objects,
    link_object,
)

logger = get_logger(__name__)


def get_decal_object(entity):
    """Get the decal empty object for a layer or mask entity.

    Args:
        entity: Layer or mask property group with texcoord property.

    Returns:
        bpy.types.Object: The decal empty object, or None if not found.
    """
    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    if m1:
        tree = get_tree(entity)
    elif m2:
        tree = get_mask_tree(entity)
    else:
        return None

    if not tree:
        return None

    decal_obj = None
    texcoord = tree.nodes.get(entity.texcoord) if hasattr(entity, 'texcoord') else None
    if texcoord and hasattr(texcoord, 'object'):
        decal_obj = texcoord.object

    return decal_obj


def get_decal_shrinkwrap_constraint(decal_obj):
    """Get the shrinkwrap constraint on a decal object.

    Args:
        decal_obj: The decal empty object.

    Returns:
        bpy.types.Constraint: The shrinkwrap constraint, or None if not found.
    """
    if not decal_obj or not hasattr(decal_obj, 'constraints'):
        return None
    cs = [c for c in decal_obj.constraints if c.type == 'SHRINKWRAP']
    if len(cs) > 0:
        return cs[0]
    return None


class M_OT_SelectDecalObject(Operator):
    """Select the decal empty object for the current layer/mask"""

    bl_idname = "wm.m_select_decal_object"
    bl_label = "Select Decal Object"
    bl_description = "Select and activate the decal empty object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Check if operator can run."""
        group_node = get_active_mpaint_node()
        return group_node and hasattr(context, 'entity')

    def execute(self, context):
        """Execute the operator to select the decal object.

        Args:
            context: Blender context with 'entity' attribute.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        scene = context.scene

        decal_obj = get_decal_object(context.entity)
        if not decal_obj:
            self.report({'WARNING'}, "No decal object found")
            return {'CANCELLED'}

        # Switch to object mode
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

        # Deselect all objects
        bpy.ops.object.select_all(action='DESELECT')

        # Link decal object to scene if not already linked
        if decal_obj.name not in get_scene_objects():
            parent = decal_obj.parent
            custom_collection = (
                parent.users_collection[0]
                if parent and len(parent.users_collection) > 0
                else None
            )
            link_object(scene, decal_obj, custom_collection)

        # Select and set as active
        set_active_object(decal_obj)
        set_object_select(decal_obj, True)

        return {'FINISHED'}


class M_OT_SetDecalObjectPositionToCursor(Operator):
    """Set decal object position to the 3D cursor"""

    bl_idname = "wm.m_set_decal_object_position_to_cursor"
    bl_label = "Set Decal Position to Cursor"
    bl_description = "Move the decal object to the 3D cursor location"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Check if operator can run."""
        group_node = get_active_mpaint_node()
        return group_node and hasattr(context, 'entity')

    def execute(self, context):
        """Execute the operator to move decal to cursor.

        Args:
            context: Blender context with 'entity' attribute.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        scene = context.scene
        entity = context.entity

        m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
        m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

        if m1:
            tree = get_tree(entity)
        elif m2:
            tree = get_mask_tree(entity)
        else:
            self.report({'WARNING'}, "Invalid entity type")
            return {'CANCELLED'}

        if not tree:
            self.report({'WARNING'}, "Could not find node tree")
            return {'CANCELLED'}

        texcoord = tree.nodes.get(entity.texcoord) if hasattr(entity, 'texcoord') else None

        if texcoord and hasattr(texcoord, 'object') and texcoord.object:
            # Move decal object to 3D cursor
            texcoord.object.location = scene.cursor.location.copy()
            texcoord.object.rotation_euler = scene.cursor.rotation_euler.copy()
        else:
            self.report({'WARNING'}, "No decal object found")
            return {'CANCELLED'}

        return {'FINISHED'}


# Classes for registration
classes = (
    M_OT_SelectDecalObject,
    M_OT_SetDecalObjectPositionToCursor,
)
