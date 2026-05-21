# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import re

from ...utils.blender_commons import (
    get_bpy_data,
    get_bpy_utils,
    get_current_filepath,
    get_user_preferences,
    remove_datablock,
)
from ..layer.layer_utils import get_root_height_channel
from .lib import (
    NEIGHBOR_UV_CAMERA,
    NEIGHBOR_UV_OBJECT,
    NEIGHBOR_UV_OTHER_UV,
    NEIGHBOR_UV_TANGENT,
)

def load_from_lib_blend(tree_name, filename):
    """Load a node group from a Blender library file.

    Loads a specific node group from a .blend library file into the current
    Blender session. Node groups are searched by name and appended if found.

    Parameters:
        tree_name (str): The name of the node group to load from the library.
        filename (str): The filename of the .blend library file (relative to
                       current filepath).

    Returns:
        bool: True if the node group was found and loaded successfully,
              False otherwise.
    """
    # Node groups necessary are in lib.blend
    # Use __file__ to get the directory of this file (lib_operations.py)
    # which is the same directory where lib.blend is located
    filepath = os.path.dirname(os.path.abspath(__file__)) + os.sep + filename

    # Load node groups
    lib_found = False
    with get_bpy_data().libraries.load(filepath) as (data_from, data_to):
        from_ngs = data_from.node_groups
        to_ngs = data_to.node_groups
        for ng in from_ngs:
            if ng == tree_name:
                to_ngs.append(ng)
                lib_found = True
                break

    return lib_found

def check_if_node_is_duplicated_from_lib(node, lib_name):
    """Check if a node is a duplicated copy from a library.

    Determines whether a given node is a duplicated copy of a library node
    by checking if its name matches the pattern '{lib_name}_Copy' optionally
    followed by a period and up to 3 digits.

    Parameters:
        node: The Blender node to check. Can be None.
        lib_name (str): The base name of the library node to match against.

    Returns:
        bool: True if the node is a GROUP type and its name matches the
              duplicated library pattern, False otherwise.
    """
    if not node or node.type != 'GROUP': return False
    m = re.match(r'^' + lib_name + '_Copy\.*\d{0,3}$', node.node_tree.name)
    if m: return True
    return False

def duplicate_lib_node_tree(node): #, duplicate_group_inside=False):
    """Duplicate a library node tree for independent editing.

    Creates a copy of a node's node tree by appending '_Copy' to its name.
    If the node tree has multiple users, creates an actual copy to ensure
    modifications don't affect other users.

    Parameters:
        node: The Blender node whose node tree should be duplicated.

    Returns:
        None
    """
    node.node_tree.name += '_Copy'
    if node.node_tree.users > 1:
        node.node_tree = node.node_tree.copy()

def check_uv_difference_to_main_uv(entity):
    """Check if an entity uses a different UV map than the main UV.

    Compares the entity's UV map name with the main UV map defined in the
    root height channel. Used to determine if special UV handling is needed.

    Parameters:
        entity: The entity object to check. Must have an id_data attribute
               with a mp property, and optionally a uv_name attribute.

    Returns:
        bool: True if the entity has a UV name that differs from the main UV
              and the height channel exists with a non-empty main UV,
              False otherwise.
    """
    mp = entity.id_data.mp
    height_ch = get_root_height_channel(mp)
    if height_ch:
        # Check if entity uv is different to main uv
        if height_ch.main_uv != '' and hasattr(entity, 'uv_name') and entity.uv_name != height_ch.main_uv:
            return True

    return False

def get_neighbor_uv_tree_name(texcoord_type, entity):
    """Get the appropriate neighbor UV node tree name based on texture coordinate type.

    Determines which neighbor UV node tree should be used based on the texture
    coordinate type and entity UV settings. Different coordinate types require
    different neighbor UV calculation methods.

    Parameters:
        texcoord_type (str): The type of texture coordinate. Valid values include:
                           'UV', 'Generated', 'Normal', 'Object', 'Decal',
                           'Camera', 'Window', 'Reflection'.
        entity: The entity object to check for UV differences.

    Returns:
        str or None: The name of the appropriate neighbor UV node tree constant:
                    - NEIGHBOR_UV_OTHER_UV if UV type with different UV map
                    - NEIGHBOR_UV_TANGENT if UV type with same UV map
                    - NEIGHBOR_UV_OBJECT for Generated/Normal/Object/Decal types
                    - NEIGHBOR_UV_CAMERA for Camera/Window/Reflection types
                    - None if texcoord_type doesn't match any category
    """
    if texcoord_type == 'UV':
        different_uv = check_uv_difference_to_main_uv(entity)
        if different_uv: return NEIGHBOR_UV_OTHER_UV
        return NEIGHBOR_UV_TANGENT
    if texcoord_type in {'Generated', 'Normal', 'Object', 'Decal'}:
        return NEIGHBOR_UV_OBJECT
    if texcoord_type in {'Camera', 'Window', 'Reflection'}:
        return NEIGHBOR_UV_CAMERA

def clean_unused_libraries():
    """Remove unused library node groups from the Blender file.

    Iterates through all node groups and removes those that start with the
    '~yPL ' prefix (library node groups) and have no users. This helps keep
    the Blender file clean and reduces file size.

    Parameters:
        None

    Returns:
        None
    """
    for ng in get_bpy_data().node_groups:
        if ng.name.startswith('~yPL ') and ng.users == 0:
            remove_datablock(get_bpy_data().node_groups, ng)

def get_icon_folder():
    """Get the path to the appropriate icon folder based on theme and preferences.

    Determines which icon set to use (light, dark, or legacy) based on user
    preferences and the current Blender theme. For DEFAULT preference, detects
    whether a dark theme is active and selects appropriate icons.

    Parameters:
        None

    Returns:
        str: The absolute path to the icon folder, ending with a path separator.
             Format: '{current_filepath}icons/{icon_set}/'
             where icon_set is 'light', 'dark', or 'legacy'.
    """
    icons = get_user_preferences().icons

    if icons == 'DEFAULT':
        bg_color = bpy.context.preferences.themes[0].preferences.space.back
        is_dark_theme = bg_color[0] + bg_color[1] + bg_color[2] < 1.5
        icon_set = 'light' if is_dark_theme else 'dark'
    else:
        icon_set = 'legacy'

    return get_current_filepath() + 'icons' + os.sep + icon_set.lower() + os.sep


def load_custom_icons():
    """Load custom icons from the icon folder into Blender's preview system.

    Creates a new preview collection and loads all icon images from the
    appropriate icon folder. Icons are expected to be PNG files with names
    ending in '_icon.png'. The '_icon.png' suffix is removed to create the
    icon identifier.

    Parameters:
        None

    Returns:
        None

    Note:
        Sets the global 'custom_icons' variable. Returns early if the Blender
        utils module doesn't have a 'previews' attribute.
    """
    # Custom Icon
    if not hasattr(get_bpy_utils(), 'previews'): return
    global custom_icons
    custom_icons = get_bpy_utils().previews.new()

    folder = get_icon_folder()

    for f in os.listdir(folder):
        icon_name = f.replace('_icon.png', '')
        custom_icons.load(icon_name, folder + f, 'IMAGE')

def unload_custom_icons():
    """Unload and remove custom icons from Blender's preview system.

    Removes the custom icon preview collection and cleans up the global
    custom_icons variable. This should be called when the addon is disabled
    or unloaded to prevent memory leaks.

    Parameters:
        None

    Returns:
        None

    Note:
        Sets the global 'custom_icons' variable to None after removal.
    """
    global custom_icons
    if hasattr(get_bpy_utils(), 'previews'):
        get_bpy_utils().previews.remove(custom_icons)
        custom_icons = None

def get_icon(custom_icon_name):
    """Get the icon ID for a custom icon by name.

    Retrieves the icon ID from the custom icons collection. Currently returns
    None as the functionality is commented out.

    Parameters:
        custom_icon_name (str): The name of the custom icon to retrieve.

    Returns:
        None: Always returns None in current implementation.

    Note:
        The actual icon retrieval (custom_icons[custom_icon_name].icon_id)
        is commented out.
    """
    return None
    # return custom_icons[custom_icon_name].icon_id