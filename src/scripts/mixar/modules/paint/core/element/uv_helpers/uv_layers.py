# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UV layer manipulation functions.
"""

from ......config.logging_config import get_logger
from ....utils.blender_commons import (
    get_mesh_operators,
    set_active_object,
)
from ...layer.layer_utils import get_uv_layers

logger = get_logger(__name__)


def move_uv_to_bottom(obj, index):
    """
    Move a UV layer at the specified index to the bottom of the UV layers list.

    This function moves a UV layer from a given index to the last position in the
    UV layers collection by duplicating it, removing the original, and renaming
    the duplicate to preserve the original name.

    Parameters
    ----------
    obj : bpy.types.Object
        The Blender object containing the UV layer to be moved.
    index : int
        The index of the UV layer to move to the bottom.

    Returns
    -------
    None
    """
    set_active_object(obj)
    uv_layers = get_uv_layers(obj)

    # Get original uv name
    uv_layers.active_index = index
    ori_name = uv_layers.active.name

    # Duplicate uv
    get_mesh_operators().uv_texture_add()

    # Delete old uv
    uv_layers.active_index = index
    get_mesh_operators().uv_texture_remove()

    # Set original name to newly created uv
    uv_layers[-1].name = ori_name


def move_uv(obj, from_index, to_index):
    """
    Move a UV layer from one index to another in the UV layers collection.

    This function reorders UV layers by moving a layer from a source index to a
    target index. It handles both upward and downward moves by using repeated
    calls to move_uv_to_bottom(). The function validates indices before performing
    the move operation.

    Parameters
    ----------
    obj : bpy.types.Object
        The Blender object containing the UV layers to be reordered.
    from_index : int
        The current index of the UV layer to move.
    to_index : int
        The target index where the UV layer should be moved.

    Returns
    -------
    None
        The function returns early without action if indices are invalid
        (equal, negative, or out of bounds).
    """
    uv_layers = get_uv_layers(obj)

    if (from_index == to_index or from_index < 0 or from_index >= len(uv_layers)
            or to_index < 0 or to_index >= len(uv_layers)):
        logger.error("Invalid indices: %s, %s", from_index, to_index)
        return

    # Move the UV map down to the target index
    if from_index < to_index:
        move_uv_to_bottom(obj, from_index)
        for i in range(len(uv_layers) - 1 - to_index):
            move_uv_to_bottom(obj, to_index)

    # Move the UV map up to the target index
    elif from_index > to_index:
        for i in range(from_index - to_index):
            move_uv_to_bottom(obj, to_index)
        for i in range(len(uv_layers) - 1 - from_index):
            move_uv_to_bottom(obj, to_index + 1)

    uv_layers.active_index = to_index


def set_active_uv_layer(obj, uv_name):
    """
    Set the active UV layer on an object by its name.

    This function searches through all UV layers on the object and sets the
    active UV layer to the one matching the provided name. If the layer is
    already active, no change is made.

    Parameters
    ----------
    obj : bpy.types.Object
        The Blender object whose active UV layer should be set.
    uv_name : str
        The name of the UV layer to set as active.

    Returns
    -------
    None
    """
    uv_layers = get_uv_layers(obj)

    for i, uv in enumerate(uv_layers):
        if uv.name == uv_name:
            if uv_layers.active_index != i:
                uv_layers.active_index = i
