# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decal constraint update handler for Mixar paint system.

This module provides a depsgraph handler that applies shrinkwrap constraint
after transform operations on decal empty objects.
"""

import bpy
from bpy.app.handlers import persistent

from .....config.logging_config import get_logger

logger = get_logger(__name__)


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


@persistent
def mpaint_decal_constraint_update(scene):
    """Apply shrinkwrap constraint after transform operations.

    This handler runs after depsgraph updates and checks if a transform
    operation was performed on a decal empty with shrinkwrap enabled.
    It "bakes" the snapped position so the empty stays on the surface.

    Args:
        scene: The current scene.
    """
    try:
        wm = getattr(bpy.context, 'window_manager', None)
        if not wm or len(wm.operators) == 0:
            return
        op = wm.operators[-1]
        if not op.bl_idname.startswith('TRANSFORM_OT_'):
            return

        for obj in getattr(bpy.context, 'selected_objects', []):
            # Check if object has decal properties
            if not hasattr(obj, 'mp_decal') or not obj.mp_decal.enable_shrinkwrap:
                continue

            # Get shrinkwrap constraint
            c = get_decal_shrinkwrap_constraint(obj)
            if not c or c.mute:
                continue

            # Check if this is a new operator (avoid re-processing)
            op_id = op.bl_idname
            op_ptr = str(op.as_pointer())

            if (obj.mp_decal.last_operator != op_id or
                    obj.mp_decal.last_operator_pointer != op_ptr):
                obj.mp_decal.last_operator = op_id
                obj.mp_decal.last_operator_pointer = op_ptr

                # Bake the snapped position
                mat = obj.matrix_world.copy()
                try:
                    c.mute = True
                    obj.matrix_world = mat
                    c.mute = False
                except Exception as e:
                    logger.warning(f"Failed to bake decal position: {e}")

    except Exception as e:
        # Silently ignore errors in handler to avoid spamming console
        pass


def register_decal_handlers():
    """Register decal-related handlers."""
    if mpaint_decal_constraint_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(mpaint_decal_constraint_update)


def unregister_decal_handlers():
    """Unregister decal-related handlers."""
    if mpaint_decal_constraint_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(mpaint_decal_constraint_update)
