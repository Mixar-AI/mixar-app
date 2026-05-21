# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender image utility functions."""

import os
import pathlib
import re

import bpy
import bpy_extras.image_utils

from ....config.logging_config import get_logger

logger = get_logger(__name__)

# Import needed functions from main module
from .blender_commons import (
    get_active_material,
    get_active_object,
    get_scene_objects,
    get_unique_name,
    is_bl_newer_than,
    remove_datablock,
    remove_mesh_obj,
)

def get_active_paint_slot_image():
    """Get the currently active paint slot image.

    Returns:
        bpy.types.Image: The active paint slot image, or None if no image is active.
    """
    scene = bpy.context.scene
    image = None
    if scene.tool_settings.image_paint.mode == "IMAGE":
        image = scene.tool_settings.image_paint.canvas
    else:
        mat = get_active_material()
        if len(mat.texture_paint_images):
            image = mat.texture_paint_images[mat.paint_active_slot]

    return image


def get_editor_images_dict(return_pins=False):
    """Get a dictionary of all images displayed in image editors across all windows.

    Args:
        return_pins (bool, optional): If True, also returns pin state for each editor. Defaults to False.

    Returns:
        dict or tuple: Dictionary mapping window/area indices to image names.
            If return_pins is True, returns tuple of (editor_images, editor_pins).
    """
    editor_images = {}
    editor_pins = {}

    for i, window in enumerate(bpy.context.window_manager.windows):
        screen_dict = {}
        screen_pin_dict = {}
        for j, area in enumerate(window.screen.areas):
            if area.type == "IMAGE_EDITOR":
                space = area.spaces[0]
                img = space.image
                if img:
                    screen_dict[j] = img.name
                else:
                    screen_dict[j] = ""
                screen_pin_dict[j] = space.use_image_pin
        editor_images[i] = screen_dict
        editor_pins[i] = screen_pin_dict

    if return_pins:
        return editor_images, editor_pins

    return editor_images


def set_editor_images(editor_images=None, editor_pins=None):
    """Set images in image editors across all windows.

    Args:
        editor_images (dict, optional): Dictionary mapping window/area indices to image names. Defaults to None.
        editor_pins (dict, optional): Dictionary mapping window/area indices to pin states. Defaults to None.
    """
    if editor_images is None:
        editor_images = {}
    if editor_pins is None:
        editor_pins = {}
    for i, window in enumerate(bpy.context.window_manager.windows):
        if i in editor_images:
            screen_dict = editor_images[i]
            screen_pin_dict = editor_pins[i] if len(editor_pins) > 0 else None
            for j, area in enumerate(window.screen.areas):
                if area.type == "IMAGE_EDITOR":
                    if j in screen_dict:
                        space = area.spaces[0]
                        img = bpy.data.images.get(screen_dict[j])
                        if space.image != img:
                            space.image = img

                        if screen_pin_dict is not None and j in screen_pin_dict:
                            space.use_image_pin = screen_pin_dict[j]


def safely_set_image_paint_canvas(image, scene=None):
    """Set the image paint canvas while preserving image editor states.

    Temporarily stores and restores all image editor images and pin states
    to prevent them from being changed when setting the canvas.

    Args:
        image (bpy.types.Image): The image to set as the paint canvas.
        scene (bpy.types.Scene, optional): The scene to modify. If None, uses current scene. Defaults to None.
    """
    if not scene:
        scene = bpy.context.scene

    # HACK: Remember all original images in all image editors since setting canvas/paint slot will replace all of them
    ori_editor_imgs, ori_editor_pins = get_editor_images_dict(return_pins=True)

    try:
        scene.tool_settings.image_paint.canvas = image
        success = True
    except Exception as e:
        logger.error("Exception: %s", e)

    # HACK: Revert back to original editor images
    if success:
        set_editor_images(ori_editor_imgs, ori_editor_pins)


def set_image_paint_canvas(image):
    """Set the image paint canvas to IMAGE mode with the specified image.

    Args:
        image (bpy.types.Image): The image to set as the paint canvas.
    """
    scene = bpy.context.scene
    try:
        scene.tool_settings.image_paint.mode = "IMAGE"
        safely_set_image_paint_canvas(image, scene)
    except Exception as e:
        logger.error("Exception: %s", e)


def is_image_single_user(image):
    """Check if an image has only one user (accounting for paint canvas).

    Args:
        image (bpy.types.Image): The image to check.

    Returns:
        bool: True if the image has only one actual user, False otherwise.
    """
    scene = bpy.context.scene

    return (
        (scene.tool_settings.image_paint.canvas == image and image.users == 2)
        or (scene.tool_settings.image_paint.canvas != image and image.users == 1)
        or image.users == 0
    )


def get_all_image_users(image):
    """Get all nodes and textures that use a specific image.

    Searches through materials, node groups, and textures to find all users of an image.

    Args:
        image (bpy.types.Image): The image to find users for.

    Returns:
        list: List of nodes and textures that reference the image.
    """
    users = []

    # Materials
    for mat in bpy.data.materials:
        if mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image == image:
                    users.append(node)

    # Node groups
    for ng in bpy.data.node_groups:
        for node in ng.nodes:
            if node.type == "TEX_IMAGE" and node.image == image:
                users.append(node)

    # Textures
    for tex in bpy.data.textures:
        if tex.type == "IMAGE" and tex.image == image:
            users.append(tex)

    return users


def safe_remove_image(image, remove_on_disk=False, user=None, user_prop=""):
    """Safely remove an image if it has only one user, optionally deleting the file.

    Args:
        image (bpy.types.Image): The image to remove.
        remove_on_disk (bool, optional): If True, also delete the image file from disk. Defaults to False.
        user (optional): The user object. Defaults to None.
        user_prop (str, optional): The property name on the user object. Defaults to "".
    """

    scene = bpy.context.scene

    if is_image_single_user(image):

        # Remove image from canvas
        if scene.tool_settings.image_paint.canvas == image:
            safely_set_image_paint_canvas(None, scene)

        if remove_on_disk and not image.packed_file and image.filepath != "":
            if image.source == "TILED":
                for tile in image.tiles:
                    filepath = image.filepath.replace("<UDIM>", str(tile.number))
                    try:
                        os.remove(os.path.abspath(bpy.path.abspath(filepath)))
                    except Exception as e:
                        logger.error("Exception: %s", e)
            else:
                try:
                    os.remove(os.path.abspath(bpy.path.abspath(image.filepath)))
                except Exception as e:
                    logger.error("Exception: %s", e)

        remove_datablock(bpy.data.images, image, user=user, user_prop=user_prop)


def simple_remove_node(
    tree, node, remove_data=True, passthrough_links=False, remove_on_disk=False
):
    """Remove a shader node and optionally its associated data.

    Args:
        tree (bpy.types.NodeTree): The node tree containing the node.
        node (bpy.types.Node): The node to remove.
        remove_data (bool, optional): If True, remove associated images/node groups. Defaults to True.
        passthrough_links (bool, optional): If True, reconnect matching input/output sockets. Defaults to False.
        remove_on_disk (bool, optional): If True, delete image files from disk. Defaults to False.
    """
    # if not node: return
    scene = bpy.context.scene

    # Reconneect links if input and output has same name
    if passthrough_links:
        for inp in node.inputs:
            if len(inp.links) == 0:
                continue
            outp = node.outputs.get(inp.name)
            if not outp:
                continue
            for link in outp.links:
                tree.links.new(inp.links[0].from_socket, link.to_socket)

    if remove_data:
        if node.bl_idname == "ShaderNodeTexImage":
            image = node.image
            if image:
                safe_remove_image(image, remove_on_disk, user=node, user_prop="image")

        elif node.bl_idname == "ShaderNodeGroup":
            if node.node_tree and node.node_tree.users == 1:

                # Recursive remove
                for n in node.node_tree.nodes:
                    if n.bl_idname in {"ShaderNodeTexImage", "ShaderNodeGroup"}:
                        simple_remove_node(node.node_tree, n, remove_data)

                remove_datablock(
                    bpy.data.node_groups,
                    node.node_tree,
                    user=node,
                    user_prop="node_tree",
                )

            # remove_tree_data_recursive(node)

    tree.nodes.remove(node)


def update_viewport_for_objects(objs):
    """Update viewport display for a list of objects by toggling their mode.

    Args:
        objs (list): List of objects (bpy.types.Object) to update.
    """
    for o in objs:
        set_active_object(o)
        if o.mode == "OBJECT":
            bpy.ops.object.mode_set(mode="SCULPT")
            bpy.ops.object.mode_set(mode="OBJECT")
        else:
            ori_mode = o.mode
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode=ori_mode)


def set_active_mode(mode_to_set):
    """Set the active object mode.

    Args:
        mode_to_set (str): The mode to set (e.g., 'OBJECT', 'EDIT', 'SCULPT', 'TEXTURE_PAINT').
    """
    bpy.ops.object.mode_set(mode=mode_to_set)


def get_geometry_operators():
    """Get the geometry operators module.

    Returns:
        bpy.ops.geometry: The geometry operators module.
    """
    return bpy.ops.geometry


def get_mesh_operators():
    """Get the mesh operators module.

    Returns:
        bpy.ops.mesh: The mesh operators module.
    """
    return bpy.ops.mesh


def is_image_filepath_unique(filepath, check_disk=True):
    """Check if an image filepath is unique (not used by any loaded image).

    Args:
        filepath (str): The filepath to check.
        check_disk (bool, optional): If True, also checks if the file exists on disk. Defaults to True.

    Returns:
        bool: True if the filepath is unique, False if already in use or file exists.
    """
    abspath = bpy.path.abspath(filepath)
    for img in bpy.data.images:
        # NOTE: 'Check disk' will also check the actual image existing in disk
        if bpy.path.abspath(img.filepath) == abspath or (
            check_disk and pathlib.Path(abspath).is_file()
        ):
            return False
    return True


def duplicate_image(image, ondisk_duplicate=True):
    """Create a duplicate of an image, optionally creating a new file on disk.

    Args:
        image (bpy.types.Image): The image to duplicate.
        ondisk_duplicate (bool, optional): If True, creates a new file on disk with unique name. Defaults to True.

    Returns:
        bpy.types.Image: The duplicated image.
    """
    # Make sure UDIM image is updated
    if image.source == "TILED" and image.is_dirty:
        if image.packed_file:
            image.pack()
        else:
            image.save()

    # Copy image
    new_image = image.copy()

    if ondisk_duplicate and (
        image.source == "TILED" or (not image.packed_file and image.filepath != "")
    ):

        directory = os.path.dirname(bpy.path.abspath(image.filepath))
        filename = bpy.path.basename(new_image.filepath)

        # Get base name
        if image.source == "TILED":
            splits = filename.split(".<UDIM>.")
            infix = ".<UDIM>."
        else:
            splits = os.path.splitext(filename)
            infix = ""

        basename = splits[0]
        extension = splits[1]

        # Try to get the counter
        m = re.match(r"^(.+)\s(\d*)$", basename)
        if m:
            basename = m.group(1)
            counter = int(m.group(2))
        else:
            counter = 1

        # Try to get unique image filepath with added counter
        while True:
            new_name = basename + " " + str(counter)
            new_path = os.path.join(directory, new_name + infix + extension)
            if is_image_filepath_unique(new_path):
                break
            counter += 1

        # Save the image to disk if image is not packed
        if not image.packed_file:
            override = bpy.context.copy()
            override["edit_image"] = new_image
            if is_bl_newer_than(4):
                with bpy.context.temp_override(**override):
                    bpy.ops.image.save_as(filepath=new_path, relative_path=True)
            else:
                bpy.ops.image.save_as(override, filepath=new_path, relative_path=True)
        else:
            new_image.filepath = new_path

            # Trying to set the filepath to relative
            try:
                new_image.filepath = bpy.path.relpath(new_image.filepath)
            except:
                pass

        # Set image name based on new filepath
        if not image.name.endswith(extension):
            filename = bpy.path.basename(os.path.splitext(new_path)[0])
        else:
            filename = bpy.path.basename(new_path)
        filename = filename.replace(".<UDIM>", "")
        new_image.name = filename
    else:

        # Set new name
        new_image.name = get_unique_name(image.name, bpy.data.images)

    # Copied image is not updated by default if it's dirty,
    # So copy the pixels
    if image.is_dirty and new_image.source != "TILED":
        new_image.pixels = list(image.pixels)

    return new_image


