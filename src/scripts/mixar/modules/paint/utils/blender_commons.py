# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import pathlib
import re

import bpy
import bpy_extras.image_utils
from mathutils import Color

from ....config.logging_config import get_logger

logger = get_logger(__name__)

# Import extracted color functions for re-export
from .blender_commons_color import (
    get_srgb_name,
    get_noncolor_name,
    get_linear_color_name,
    srgb_to_linear_per_element,
    linear_to_srgb_per_element,
    srgb_to_linear,
    linear_to_srgb,
    remove_datablock,
)

# Import extracted context and version functions for re-export
from .blender_commons_context import (
    get_window_context,
    get_viewport_context,
    get_bpy_data,
    get_bpy_utils,
    get_current_filepath,
    get_current_blender_version_str,
    is_online,
    is_bl_newer_than,
    is_bl_equal,
    is_created_before,
    get_bpytypes,
)

# Import extracted image functions for re-export (after this module is fully loaded)
# Note: Actual import happens at end of file to avoid circular imports


def get_active_object():
    """Get the active object from the current Blender context.

    Returns:
        bpy.types.Object: The currently active object, or None if no object is active.
    """
    return bpy.context.active_object


def get_bpy_context():
    """Get the current Blender context.

    Returns:
        bpy.types.Context: The current Blender context object.
    """
    return bpy.context




# def get_active_object():
#     return bpy.context.view_layer.objects.active


def set_active_object(obj):
    """Set the active object in the current view layer.

    Args:
        obj (bpy.types.Object): The object to set as active.
    """
    try:
        bpy.context.view_layer.objects.active = obj
    except (RuntimeError, AttributeError, ReferenceError) as e:
        logger.error("Exception: Cannot set active object! %s", e)


def link_object(scene, obj, custom_collection=None):
    """Link an object to a scene's collection or a custom collection.

    Args:
        scene (bpy.types.Scene): The scene to link the object to.
        obj (bpy.types.Object): The object to link.
        custom_collection (bpy.types.Collection, optional): Custom collection to link to.
            If None, links to the scene's main collection. Defaults to None.
    """
    if custom_collection:
        custom_collection.objects.link(obj)
    else:
        scene.collection.objects.link(obj)


def get_object_select(obj):
    """Get the selection state of an object.

    Args:
        obj (bpy.types.Object): The object to check.

    Returns:
        bool: True if the object is selected, False otherwise or if selection state cannot be retrieved.
    """
    try:
        return obj.select_get()
    except (RuntimeError, AttributeError, ReferenceError):
        return False


def set_object_select(obj, val):
    """Set the selection state of an object.

    Args:
        obj (bpy.types.Object): The object to modify.
        val (bool): True to select the object, False to deselect.
    """
    obj.select_set(val)


def set_object_hide(obj, val):
    """Set the visibility state of an object.

    Args:
        obj (bpy.types.Object): The object to modify.
        val (bool): True to hide the object, False to show.
    """
    obj.hide_set(val)


def get_scene_objects():
    """Get all objects in the current view layer.

    Returns:
        bpy.types.LayerObjects: Collection of objects in the current view layer.
    """
    return bpy.context.view_layer.objects


def remove_mesh_obj(obj):
    """Remove a mesh object and its associated mesh data from Blender.

    Args:
        obj (bpy.types.Object): The mesh object to remove.
    """
    data = obj.data
    remove_datablock(bpy.data.objects, obj)
    remove_datablock(bpy.data.meshes, data)


def get_viewport_shade():
    """Get the current viewport shading type.

    Returns:
        str: The shading type (e.g., 'SOLID', 'MATERIAL', 'RENDERED', 'WIREFRAME').
    """
    return bpy.context.area.spaces[0].shading.type


def get_user_preferences():
    """Get the Mixar paint preferences from the current scene.

    Returns:
        bpy.types.PropertyGroup: The mixar_paint_preferences property group containing user preferences.
    """
    # Preferences are now stored in the scene instead of addon preferences
    return bpy.context.scene.mixar_paint_preferences


def get_operator_description(operator):
    """Get the description text for a Blender operator.

    Retrieves the operator's description or label, and appends a hint about
    holding Shift for options if property popups are skipped in preferences.

    Args:
        operator: The Blender operator class.

    Returns:
        str: The operator description, optionally with usage hint, or empty string if no description.
    """
    if hasattr(operator, "bl_description"):
        description = operator.bl_description
    elif hasattr(operator, "bl_label"):
        description = operator.bl_label
    else:
        return ""
    return (
        description + ". Hold Shift for options"
        if get_user_preferences().skip_property_popups
        else ""
    )


def get_active_material(obj=None):
    """Get the active material of an object.

    Args:
        obj (bpy.types.Object, optional): The object to get the material from.
            If None, uses the active object. Defaults to None.

    Returns:
        bpy.types.Material: The active material, or None if no object/material or using legacy render engine.
    """
    scene = bpy.context.scene
    engine = scene.render.engine

    if not obj:
        obj = get_active_object()

    if not obj:
        return None

    mat = obj.active_material

    if engine in {"BLENDER_RENDER", "BLENDER_GAME"}:
        return None

    return mat


def in_active_279_layer(obj):
    """Check if an object is in an active layer (Blender 2.79 compatibility).

    Args:
        obj (bpy.types.Object): The object to check.

    Returns:
        bool: True if the object is in an active layer, False otherwise.
    """
    scene = bpy.context.scene
    space = bpy.context.space_data
    if space.type == "VIEW_3D" and space.local_view:
        return any([layer for layer in obj.layers_local_view if layer])
    else:
        return any(
            [layer for i, layer in enumerate(obj.layers) if layer and scene.layers[i]]
        )


def get_unique_name(name, items, surname=""):
    """Generate a unique name by adding a numeric suffix if necessary.

    Checks if a name exists in the items collection and adds a numeric suffix
    to make it unique. Optionally appends a surname.

    Args:
        name (str): The base name to make unique.
        items (list): List of items (objects with .name attribute) or list of strings.
        surname (str, optional): Additional suffix to append. Defaults to "".

    Returns:
        str: A unique name not present in the items collection.
    """

    # Check if items is list of strings
    if len(items) > 0 and type(items[0]) == str:
        item_names = items
    else:
        item_names = [item.name for item in items]

    if surname != "":
        unique_name = name + " " + surname
    else:
        unique_name = name

    name_found = [item for item in item_names if item == unique_name]
    if name_found:

        m = re.match(r"^(.+)\s(\d*)$", name)
        if m:
            name = m.group(1)
            i = int(m.group(2))
        else:
            i = 1

        while True:

            if surname != "":
                new_name = name + " " + str(i) + " " + surname
            else:
                new_name = name + " " + str(i)

            name_found = [item for item in item_names if item == new_name]
            if not name_found:
                unique_name = new_name
                break
            i += 1

    return unique_name


def get_object_parent_layer_collections(arr, col, obj):
    """Recursively get all parent layer collections containing an object.

    Args:
        arr (list): List to store the parent layer collections (modified in place).
        col (bpy.types.LayerCollection): The layer collection to search.
        obj (bpy.types.Object): The object to find.

    Returns:
        list: List of parent layer collections containing the object.
    """
    for o in col.collection.objects:
        if o == obj:
            if col not in arr:
                arr.append(col)

    if not arr:
        for c in col.children:
            get_object_parent_layer_collections(arr, c, obj)
            if arr:
                break

    if arr:
        if col not in arr:
            arr.append(col)

    return arr


def in_renderable_layer_collection(obj):
    """Check if an object is in a renderable layer collection.

    Args:
        obj (bpy.types.Object): The object to check.

    Returns:
        bool: True if the object is in a renderable layer collection, False otherwise.
    """
    layer_cols = get_object_parent_layer_collections(
        [], bpy.context.view_layer.layer_collection, obj
    )
    if any([lc for lc in layer_cols if lc.collection.hide_render]):
        return False
    return True


def is_layer_collection_hidden(obj):
    """Check if an object's layer collection is hidden in the viewport.

    Args:
        obj (bpy.types.Object): The object to check.

    Returns:
        bool: True if any parent layer collection is hidden in viewport, False otherwise.
    """
    layer_cols = get_object_parent_layer_collections(
        [], bpy.context.view_layer.layer_collection, obj
    )
    if any([lc for lc in layer_cols if lc.collection.hide_viewport]):
        return True
    if any([lc for lc in layer_cols if lc.hide_viewport]):
        return True
    return False


def load_image(path, directory, check_existing=True):
    """Load an image from a file path.

    Args:
        path (str): The image filename or path.
        directory (str): The directory containing the image.
        check_existing (bool, optional): If True, returns existing image if already loaded. Defaults to True.

    Returns:
        bpy.types.Image: The loaded image.
    """
    return bpy_extras.image_utils.load_image(
        path, directory, check_existing=check_existing
    )


def get_brush_image_tool(brush):
    """Get the image paint tool type for a brush.

    Args:
        brush (bpy.types.Brush): The brush to query.

    Returns:
        str: The image brush type (e.g., 'DRAW', 'SOFTEN', 'SMEAR', etc.).
    """
    return brush.image_brush_type


def get_brush_sculpt_tool(brush):
    """Get the sculpt tool type for a brush.

    Args:
        brush (bpy.types.Brush): The brush to query.

    Returns:
        str: The sculpt brush type (e.g., 'DRAW', 'CLAY', 'SMOOTH', etc.).
    """
    return brush.sculpt_brush_type


def get_active_tool_idname():
    """Get the identifier name of the active tool in the 3D viewport.

    Returns:
        str: The idname of the active tool for the current mode.
    """
    tools = bpy.context.workspace.tools
    return tools.from_space_view3d_mode(bpy.context.mode).idname


def enable_eevee_ao():
    """Enable Eevee ambient occlusion (GTAO) if not already enabled.

    Only applies to Blender versions 2.80 to 4.1. Required for edge detect entity to work.
    """
    # Enable Eevee AO to make edge detect entity works
    scene = bpy.context.scene
    if (
        is_bl_newer_than(2, 80)
        and not is_bl_newer_than(4, 2)
        and not scene.eevee.use_gtao
    ):
        scene.eevee.use_gtao = True


def is_image_available_to_open(image):
    """Check if an image can be opened in the editor.

    Args:
        image (bpy.types.Image): The image to check.

    Returns:
        bool: True if the image can be opened, False if it's an atlas or special image.
    """
    return (
        not image.yia.is_image_atlas
        and not image.yua.is_udim_atlas
        and image.name not in {"Render Result", "Viewer Node"}
    )


def mute_node(tree, entity, prop):
    """Mute a node referenced by a property on an entity.

    Args:
        tree (bpy.types.NodeTree): The node tree containing the node.
        entity: The entity object containing the property.
        prop (str): The property name that holds the node name.
    """
    if not hasattr(entity, prop):
        return
    node = tree.nodes.get(getattr(entity, prop))
    if node:
        node.mute = True


def unmute_node(tree, entity, prop):
    """Unmute a node referenced by a property on an entity.

    Args:
        tree (bpy.types.NodeTree): The node tree containing the node.
        entity: The entity object containing the property.
        prop (str): The property name that holds the node name.
    """
    if not hasattr(entity, prop):
        return
    node = tree.nodes.get(getattr(entity, prop))
    if node:
        node.mute = False


# Re-export image functions from extracted module
from .blender_commons_image import (
    get_active_paint_slot_image,
    get_editor_images_dict,
    set_editor_images,
    safely_set_image_paint_canvas,
    set_image_paint_canvas,
    is_image_single_user,
    get_all_image_users,
    safe_remove_image,
    simple_remove_node,
    update_viewport_for_objects,
    set_active_mode,
    get_geometry_operators,
    get_mesh_operators,
    is_image_filepath_unique,
    duplicate_image,
)
