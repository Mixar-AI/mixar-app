# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Core logic for reverting from a baked export material to the original.

Restores the original Mixar material, removes baked images created by the
export material, and deletes the export material datablock.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_MIXAR_ORIGINAL_MAT_KEY = "_mixar_original_material"


def revert_to_original_material(obj):
    """Revert the object from a baked export material to its original.

    1. Reads the stored original material name from the baked material.
    2. Reassigns the original material to the active slot.
    3. Collects and removes images created for the export material.
    4. Removes the export material datablock.

    Args:
        obj: The Blender object to revert.

    Returns:
        True on success, False on failure.
    """
    baked_mat = obj.active_material
    if not baked_mat:
        logger.error("No active material on object")
        return False

    original_name = baked_mat.get(_MIXAR_ORIGINAL_MAT_KEY, "")
    if not original_name:
        logger.error("Active material has no stored original material reference")
        return False

    original_mat = bpy.data.materials.get(original_name)
    if not original_mat:
        logger.error(f"Original material '{original_name}' not found")
        return False

    # Collect images used by the baked export material before removing it
    images_to_remove = _collect_export_images(baked_mat)

    # Reassign original material
    slot_idx = obj.active_material_index
    obj.data.materials[slot_idx] = original_mat

    # Remove the export material if it has no remaining users
    if baked_mat.users == 0:
        bpy.data.materials.remove(baked_mat)

    # Remove baked images that have no other users
    for img in images_to_remove:
        if img.users == 0:
            bpy.data.images.remove(img)

    logger.info(
        f"Reverted '{obj.name}' to original material '{original_name}'"
    )
    return True


def _collect_export_images(mat):
    """Collect all images used by texture nodes in a material.

    Only collects images that are referenced by ShaderNodeTexImage nodes
    in the material's node tree.

    Args:
        mat: The Blender material to scan.

    Returns:
        List of bpy.types.Image objects.
    """
    images = []
    if not mat or not mat.node_tree:
        return images

    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            images.append(node.image)

    return images
