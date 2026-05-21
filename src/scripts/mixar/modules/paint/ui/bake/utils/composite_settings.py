# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Composite settings management for post-processing operations"""

import bpy

from ....utils.blender_commons import (
    get_active_object,
    get_window_context,
    is_bl_newer_than,
    link_object,
    remove_datablock,
    set_active_object,
)
from .bake_scene_settings import get_compositor_node_tree


def prepare_composite_settings(res_x=1024, res_y=1024, use_hdr=False):
    """Prepare compositor settings for post-processing operations.

    Args:
        res_x (int, optional): Resolution width in pixels. Defaults to 1024.
        res_y (int, optional): Resolution height in pixels. Defaults to 1024.
        use_hdr (bool, optional): Use HDR/float image format. Defaults to False.

    Returns:
        dict: Dictionary containing saved state information and scene reference.
    """

    book = {}

    # Remember original scene
    book["ori_scene_name"] = bpy.context.scene.name

    # Get a valid window context (important for Properties panel context)
    window_ctx = get_window_context()

    # Remember active object and view layer
    if window_ctx:
        book["ori_viewlayer"] = (
            window_ctx['window'].view_layer.name
            if window_ctx['window'].view_layer
            else ""
        )
    else:
        book["ori_viewlayer"] = ""
    book["ori_object"] = get_active_object().name if get_active_object() else ""

    # Check if original viewport is using camera view
    view3d_area = _find_view3d_area(window_ctx)

    book["ori_camera_view"] = (
        view3d_area is not None
        and view3d_area.spaces[0].region_3d.view_perspective == "CAMERA"
    )

    # Create new temporary scene
    scene = bpy.data.scenes.new(name="TEMP_COMPOSITE_SCENE")

    # Set the scene using context override if window is available
    if window_ctx:
        with bpy.context.temp_override(**window_ctx):
            bpy.context.window.scene = scene

    # Store window context for later use
    book["window_ctx"] = window_ctx

    # Set up render settings
    _configure_composite_render_settings(scene, res_x, res_y, use_hdr)

    # Remember temp scene name
    book["temp_scene_name"] = scene.name

    # Create temporary camera
    if not scene.camera:
        cam_data = bpy.data.cameras.new("TEMP_CAM")
        cam_obj = bpy.data.objects.new("TEMP_CAM", cam_data)
        link_object(scene, cam_obj)
        scene.camera = cam_obj
        book["temp_camera_name"] = cam_obj.name

    return book


def recover_composite_settings(book):
    """Recover/restore compositor settings and clean up temporary resources.

    Args:
        book (dict): Dictionary containing saved state information.
    """
    scene = bpy.data.scenes.get(book["temp_scene_name"])

    # Remove temporary objects
    if "temp_camera_name" in book:
        cam_obj = bpy.data.objects.get(book["temp_camera_name"])
        if cam_obj:
            cam = cam_obj.data
            remove_datablock(bpy.data.objects, cam_obj)
            remove_datablock(bpy.data.cameras, cam)

    # Remove compositor node tree
    if is_bl_newer_than(5):
        comp_tree = get_compositor_node_tree(scene)
        remove_datablock(bpy.data.node_groups, comp_tree)

    # Remove temp scene
    remove_datablock(bpy.data.scenes, scene)

    # Go back to original scene using stored window context
    scene = bpy.data.scenes.get(book["ori_scene_name"])
    window_ctx = book.get("window_ctx")
    if window_ctx:
        with bpy.context.temp_override(**window_ctx):
            bpy.context.window.scene = scene

    # Recover camera view
    if book["ori_camera_view"]:
        view3d_area = _find_view3d_area_from_context()
        if view3d_area:
            view3d_area.spaces[0].region_3d.view_perspective = "CAMERA"

    # Recover view layer
    ori_viewlayer = bpy.context.scene.view_layers.get(book["ori_viewlayer"])
    if ori_viewlayer and bpy.context.window.view_layer != ori_viewlayer:
        bpy.context.window.view_layer = ori_viewlayer

    # Recover active object
    ori_object = bpy.data.objects.get(book["ori_object"])
    if ori_object and get_active_object() != ori_object:
        set_active_object(ori_object)


def _find_view3d_area(window_ctx):
    """Find VIEW_3D area from window context.

    Args:
        window_ctx: Window context dictionary or None.

    Returns:
        Area object or None if not found.
    """
    if window_ctx:
        for area in window_ctx['window'].screen.areas:
            if area.type == 'VIEW_3D':
                return area
    return None


def _find_view3d_area_from_context():
    """Find VIEW_3D area from current context window.

    Returns:
        Area object or None if not found.
    """
    if bpy.context.window:
        for area in bpy.context.window.screen.areas:
            if area.type == 'VIEW_3D':
                return area
    return None


def _configure_composite_render_settings(scene, res_x, res_y, use_hdr):
    """Configure render settings for compositing.

    Args:
        scene: Blender scene object.
        res_x (int): Resolution width in pixels.
        res_y (int): Resolution height in pixels.
        use_hdr (bool): Use HDR/float image format.
    """
    scene.cycles.samples = 1
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 1
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0

    if is_bl_newer_than(5):
        comp_tree = bpy.data.node_groups.new(
            "TEMP_COMPOSITOR_TREE__", "CompositorNodeTree"
        )
        scene.compositing_node_group = comp_tree
    else:
        scene.use_nodes = True

    scene.view_settings.view_transform = "Standard"
    scene.render.dither_intensity = 0.0

    # Float/HDR image related
    scene.render.image_settings.file_format = "OPEN_EXR" if use_hdr else "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "32" if use_hdr else "8"
