# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.blender_commons import get_bpy_data, remove_datablock


def remove_decal_object(tree, entity):
    """Remove a decal object from the shader node tree if it meets specific criteria.

    This function checks for a texture coordinate node associated with the entity
    and removes its linked decal object if the object is an EMPTY type with 2 or
    fewer users. This helps clean up unused decal objects from the scene.

    Parameters
    ----------
    tree : bpy.types.ShaderNodeTree or None
        The shader node tree containing the texture coordinate node.
        If None, the function returns immediately without performing any operations.
    entity : object
        An entity object that contains a texcoord attribute referencing
        the name of a texture coordinate node in the shader tree.

    Returns
    -------
    None
        This function does not return any value. It performs cleanup operations
        on the scene data by removing the decal object if conditions are met.
    """
    if not tree: return

    texcoord = tree.nodes.get(entity.texcoord)
    if texcoord and hasattr(texcoord, 'object') and texcoord.object:
        decal_obj = texcoord.object
        if decal_obj.type == 'EMPTY' and decal_obj.users <= 2:
            texcoord.object = None
            remove_datablock(get_bpy_data().objects, decal_obj)
