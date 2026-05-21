# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image save and pack helper functions.

This module provides functions for saving and packing images,
cleaning object references, and handling temporary scene operations.
"""

import os
import time

import bpy

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.layer.get_entities import get_mp_images
from ...core.node.get_nodes import get_layer_source
from ...utils.blender_commons import (
    get_active_object,
    get_noncolor_name,
    get_srgb_name,
    remove_datablock,
)
from ..udim.udim_utils import get_temp_udim_dir, is_using_temp_dir, remove_empty_tiles, remove_udim_files_from_disk
from .image_ops_utils import pack_image
from .float_image_helpers import save_float_image


def clean_object_references(image):
    """Remove invalid object references from image bake information.

    Checks if objects referenced in the image's bake info are still accessible in any
    scene view layer. Removes references to objects that no longer exist.

    Args:
        image: The Blender image object containing bake information.

    Returns:
        None
    """
    removed_references = []
    if image.yia.is_image_atlas:
        for segment in image.yia.segments:
            if segment.bake_info.is_baked:

                # Check if selected objects data are still accessible on any view layers
                indices = []
                for i, o in enumerate(segment.bake_info.selected_objects):
                    if o.object:
                        if not any(
                            [
                                s
                                for s in bpy.data.scenes
                                if o.object.name in s.collection.all_objects
                            ]
                        ):
                            removed_references.append(o.object.name)
                            indices.append(i)

                for i in reversed(indices):
                    segment.bake_info.selected_objects.remove(i)

                # Check if other object's data is still accessible on any view layers
                indices = []
                for i, o in enumerate(segment.bake_info.other_objects):
                    if o.object:
                        if not any(
                            [
                                s
                                for s in bpy.data.scenes
                                if o.object.name in s.collection.all_objects
                            ]
                        ):
                            removed_references.append(o.object.name)
                            indices.append(i)

                for i in reversed(indices):
                    segment.bake_info.other_objects.remove(i)

    elif image.m_bake_info.is_baked:

        if image.m_bake_info.is_baked:

            # Check if selected objects data are still accessible on any view layers
            indices = []
            for i, o in enumerate(image.m_bake_info.selected_objects):
                if o.object:
                    if not any(
                        [
                            s
                            for s in bpy.data.scenes
                            if o.object.name in s.collection.all_objects
                        ]
                    ):
                        removed_references.append(o.object.name)
                        indices.append(i)
            for i in reversed(indices):
                image.m_bake_info.selected_objects.remove(i)

            # Check if other object's data is still accessible on any view layers
            indices = []
            for i, o in enumerate(image.m_bake_info.other_objects):
                if o.object:
                    if not any(
                        [
                            s
                            for s in bpy.data.scenes
                            if o.object.name in s.collection.all_objects
                        ]
                    ):
                        removed_references.append(o.object.name)
                        indices.append(i)
            for i in reversed(indices):
                image.m_bake_info.other_objects.remove(i)

    for r in removed_references:
        logger.warning("Reference for %s is removed because it's no longer found!", r)


def create_temp_scene():
    """Create a temporary scene configured for image saving operations.

    Creates a new Blender scene with standard view transform and PNG file format
    settings for use in image save operations.

    Args:
        None

    Returns:
        The newly created temporary scene object.
    """
    logger.info("Creating temporary scene for saving some images...")
    tmpscene = bpy.data.scenes.new("Temp Save Scene")

    try:
        tmpscene.view_settings.view_transform = "Standard"
    except:
        logger.error("Cannot set view transform on temporary save scene!")
    try:
        tmpscene.render.image_settings.file_format = "PNG"
    except:
        logger.error("Cannot set file format on temporary save scene!")

    return tmpscene


def unpack_image(image, filepath):
    """Unpack a packed image to disk with temporary file handling.

    Unpacks the image to Blender's default textures directory, handling existing files
    by temporarily renaming them to avoid conflicts.

    Args:
        image: The Blender packed image to unpack.
        filepath (str): The target filepath for the unpacked image.

    Returns:
        Tuple containing (default_dir, default_dir_found, default_filepath, temp_path, unpacked_path).
    """

    # Get blender default unpack directory
    default_dir = os.path.join(os.path.abspath(bpy.path.abspath("//")), "textures")

    # Check if default directory is available or not, delete later if not found now
    default_dir_found = os.path.isdir(default_dir)

    # Blender always unpack at \\textures\file.ext
    if image.filepath == "":
        default_filepath = os.path.join(default_dir, image.name)
    else:
        default_filepath = os.path.join(default_dir, bpy.path.basename(image.filepath))

    # Check if file with default path is already available
    temp_path = ""
    if os.path.isfile(default_filepath) and default_filepath != filepath:
        temp_path = os.path.join(default_dir, "__TEMP__")
        os.rename(default_filepath, temp_path)

    # Unpack the file
    image.unpack()
    unpacked_path = bpy.path.abspath(image.filepath)

    # HACK: Unpacked path sometimes has inconsistent backslash
    folder, file = os.path.split(unpacked_path)
    unpacked_path = os.path.join(folder, file)

    return default_dir, default_dir_found, default_filepath, temp_path, unpacked_path


def remove_unpacked_image_path(
    image,
    filepath,
    default_dir,
    default_dir_found,
    default_filepath,
    temp_path,
    unpacked_path,
):
    """Clean up temporary files created during image unpacking.

    Removes the unpacked image file if it differs from the target filepath, restores
    any temporarily renamed files, and removes the default directory if it was created.

    Args:
        image: The Blender image object.
        filepath (str): The target filepath where the image should be saved.
        default_dir (str): The default Blender unpack directory path.
        default_dir_found (bool): Whether the default directory existed before unpacking.
        default_filepath (str): The default filepath Blender uses for unpacking.
        temp_path (str): Path to temporarily renamed file, if any.
        unpacked_path (str): The actual path where Blender unpacked the image.

    Returns:
        None
    """

    # Remove unpacked file
    if filepath != unpacked_path:
        if image.source == "TILED":
            for tile in image.tiles:
                upath = unpacked_path.replace("<UDIM>", str(tile.number))
                try:
                    os.remove(upath)
                except Exception as e:
                    logger.error(e)
        else:
            try:
                os.remove(unpacked_path)
            except Exception as e:
                logger.error(e)

    # Rename back temporary file
    if temp_path != "":
        if temp_path != filepath:
            os.rename(temp_path, default_filepath)
        else:
            os.remove(temp_path)

    # Delete default directory if not found before
    if not default_dir_found:
        os.rmdir(default_dir)


def save_pack_all(mp):
    """Save or pack all dirty images in the MPaint node tree.

    Iterates through all images used in the MPaint layers, saving unpacked images to
    disk or packing them into the blend file. Handles special cases for float images,
    UDIM tiles, and temporary directories.

    Args:
        mp: The MPaint node tree property group containing layers and images.

    Returns:
        None
    """

    images = get_mp_images(mp, get_baked_channels=True)  # , check_overlay_normal=True)
    packed_float_images = []

    # Temporary scene for some saving hack
    tmpscene = None
    temp_udim_dir = get_temp_udim_dir()

    # Save/pack images
    for image in images:
        if not image:
            continue

        # There's a need to check if there's empty tile to make sure the image will be packed correctly
        # NOTE: There's actually no need to do this for Blender 4.1 onward,
        # but empty tile will still be removed just in case it will cause unexpected problem
        force_pack = False
        if (
            image.source == "TILED"
            and remove_empty_tiles(image)
            and is_using_temp_dir(image)
        ):
            force_pack = True

        if not image.is_dirty and not force_pack:
            continue
        T = time.time()

        if image.packed_file or image.filepath == "" or force_pack:

            temp_saved = False
            pack_image(image, reload_float=True)

            if temp_saved:
                # Remove file if they are using temporary directory
                if is_using_temp_dir(image):
                    remove_udim_files_from_disk(image, temp_udim_dir, True)

            logger.info(
                "%s image is packed in %s ms!",
                image.name, "{:0.2f}".format((time.time() - T) * 1000)
            )
        else:
            if image.is_float:
                save_float_image(image)
            else:
                # BLENDER BUG: Blender 3.3 has wrong srgb if not packed first
                if image.colorspace_settings.name in {
                    "Linear",
                    get_noncolor_name(),
                }:

                    # Create temporary scene
                    if not tmpscene:
                        tmpscene = create_temp_scene()

                    # Get image path
                    path = bpy.path.abspath(image.filepath)

                    # Pack image first
                    image.pack()
                    image.colorspace_settings.name = get_srgb_name()

                    # Remove old files to avoid caching (?)
                    try:
                        os.remove(path)
                    except Exception as e:
                        logger.error(e)

                    # Then unpack
                    (
                        default_dir,
                        default_dir_found,
                        default_filepath,
                        temp_path,
                        unpacked_path,
                    ) = unpack_image(image, path)

                    # Save image
                    image.save_render(path, scene=tmpscene)

                    # Set the filepath to the image
                    image.filepath = path
                    if bpy.data.filepath != "":
                        try:
                            image.filepath = bpy.path.relpath(path)
                        except:
                            pass

                    # Bring back linear
                    image.colorspace_settings.name = get_noncolor_name()

                    # Remove unpacked images in Blender 3.3
                    remove_unpacked_image_path(
                        image,
                        path,
                        default_dir,
                        default_dir_found,
                        default_filepath,
                        temp_path,
                        unpacked_path,
                    )

                    logger.info(
                        "%s image is saved in %s ms!",
                        image.name, "{:0.2f}".format((time.time() - T) * 1000)
                    )

                else:
                    try:
                        ori_colorspace = image.colorspace_settings.name
                        image.save()
                        image.colorspace_settings.name = ori_colorspace

                        logger.info(
                            "%s image is saved in %s ms!",
                            image.name, "{:0.2f}".format((time.time() - T) * 1000)
                        )
                    except Exception as e:
                        logger.error(e)

    # Delete temporary scene
    if tmpscene:
        logger.info("Deleting temporary scene used for saving some images...")
        remove_datablock(bpy.data.scenes, tmpscene)

    # HACK: For some reason active float image will glitch after auto save
    # This is only happen if active object is in texture paint mode
    obj = get_active_object()
    if len(mp.layers) > 0 and obj and obj.mode == "TEXTURE_PAINT":
        layer = mp.layers[mp.active_layer_index]
        if layer.type == "IMAGE":
            source = get_layer_source(layer)
            image = source.image
            if image in packed_float_images:
                mpui = bpy.context.window_manager.mpui
                mpui.refresh_image_hack = True

    # Clean object reference on images
    for image in images:
        clean_object_references(image)
