# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for managing bake settings in vector displacement operations.

This module contains utility functions for storing, preparing, and recovering
bake settings during VDM baking operations.
"""

import bpy

from ...utils.blender_commons import get_object_parent_layer_collections
from ..bake.utils.bake_scene_settings import (
    get_scene_bake_clear,
    get_scene_bake_margin,
    get_scene_bake_multires,
    get_scene_render_bake_type,
    set_scene_bake_clear,
    set_scene_bake_margin,
    set_scene_bake_multires,
    set_scene_render_bake_type,
)


def remember_before_bake(obj):
    """Store current scene and object settings before baking.

    Args:
        obj (bpy.types.Object): The object being prepared for baking.

    Returns:
        dict: Dictionary containing all saved settings.
    """
    book = {}
    book["scene"] = scene = bpy.context.scene
    book["obj"] = obj
    book["mode"] = obj.mode
    uv_layers = obj.data.uv_layers
    mpui = bpy.context.window_manager.mpui

    # Remember render settings
    book["ori_engine"] = scene.render.engine
    book["ori_bake_type"] = scene.cycles.bake_type
    book["ori_samples"] = scene.cycles.samples
    book["ori_threads_mode"] = scene.render.threads_mode
    book["ori_margin"] = scene.render.bake.margin
    book["ori_margin_type"] = scene.render.bake.margin_type
    book["ori_use_clear"] = scene.render.bake.use_clear
    book["ori_normal_space"] = scene.render.bake.normal_space
    book["ori_simplify"] = scene.render.use_simplify
    book["ori_device"] = scene.cycles.device
    book["ori_use_selected_to_active"] = scene.render.bake.use_selected_to_active
    book["ori_max_ray_distance"] = scene.render.bake.max_ray_distance
    book["ori_cage_extrusion"] = scene.render.bake.cage_extrusion
    book["ori_use_cage"] = scene.render.bake.use_cage
    book["ori_use_denoising"] = scene.cycles.use_denoising
    book["ori_bake_target"] = scene.render.bake.target
    book["ori_material_override"] = bpy.context.view_layer.material_override

    # Multires related
    book["ori_use_bake_multires"] = get_scene_bake_multires(scene)
    book["ori_use_bake_clear"] = get_scene_bake_clear(scene)
    book["ori_render_bake_type"] = get_scene_render_bake_type(scene)
    book["ori_bake_margin"] = get_scene_bake_margin(scene)
    book["ori_view_transform"] = scene.view_settings.view_transform

    # Remember world settings
    if scene.world:
        book["ori_distance"] = scene.world.light_settings.distance

    # Remember image editor images
    book["editor_images"] = [
        a.spaces[0].image for a in bpy.context.screen.areas if a.type == "IMAGE_EDITOR"
    ]
    book["editor_pins"] = [
        a.spaces[0].use_image_pin
        for a in bpy.context.screen.areas
        if a.type == "IMAGE_EDITOR"
    ]

    # Remember uv
    book["ori_active_uv"] = uv_layers.active.name
    active_render_uvs = [u for u in uv_layers if u.active_render]
    if active_render_uvs:
        book["ori_active_render_uv"] = active_render_uvs[0].name

    return book


def prepare_bake_settings(
    book, obj, uv_map="", samples=1, margin=15, bake_device="CPU"
):
    """Prepare scene and object settings for baking operation.

    Args:
        book (dict): Dictionary to store original settings (passed from remember_before_bake).
        obj (bpy.types.Object): The object to prepare for baking.
        uv_map (str, optional): Name of the UV map to use. Defaults to "".
        samples (int, optional): Number of render samples. Defaults to 1.
        margin (int, optional): Bake margin in pixels. Defaults to 15.
        bake_device (str, optional): Device to use for baking ("CPU" or "GPU"). Defaults to "CPU".
    """
    scene = bpy.context.scene
    mpui = bpy.context.window_manager.mpui
    wmyp = bpy.context.window_manager.mpprops

    # Hack function on depsgraph update can cause crash, so halt it before baking
    wmyp.halt_hacks = True

    scene.render.engine = "CYCLES"
    scene.render.threads_mode = "AUTO"
    scene.render.bake.margin = margin
    scene.render.bake.margin_type = "EXTEND"
    scene.render.bake.use_clear = False
    scene.render.bake.use_selected_to_active = False
    scene.render.bake.max_ray_distance = 0.0
    scene.render.bake.cage_extrusion = 0.0
    scene.render.bake.use_cage = False
    scene.render.use_simplify = False
    scene.render.bake.target = "IMAGE_TEXTURES"
    set_scene_bake_multires(scene, False)
    set_scene_bake_margin(scene, margin)
    set_scene_bake_clear(scene, False)
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.bake_type = "EMIT"
    scene.cycles.device = bake_device
    scene.view_settings.view_transform = "Standard"
    bpy.context.view_layer.material_override = None

    # Show viewport and render of object layer collection
    obj.hide_select = False
    obj.hide_viewport = False
    obj.hide_render = False
    obj.hide_set(False)
    layer_cols = get_object_parent_layer_collections(
        [], bpy.context.view_layer.layer_collection, obj
    )
    for lc in layer_cols:
        lc.hide_viewport = False
        lc.collection.hide_viewport = False
        lc.collection.hide_render = False

    # Set object to active
    bpy.context.view_layer.objects.active = obj
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)

    # Set active uv layers
    if uv_map != "":
        uv_layers = obj.data.uv_layers
        uv = uv_layers.get(uv_map)
        if uv:
            uv_layers.active = uv
            uv.active_render = True


def recover_bake_settings(book, recover_active_uv=False):
    """Restore scene and object settings after baking operation.

    Args:
        book (dict): Dictionary containing saved settings from remember_before_bake.
        recover_active_uv (bool, optional): Whether to restore active UV settings. Defaults to False.
    """
    scene = book["scene"]
    obj = book["obj"]
    uv_layers = obj.data.uv_layers
    mpui = bpy.context.window_manager.mpui
    wmyp = bpy.context.window_manager.mpprops

    scene.render.engine = book["ori_engine"]
    scene.cycles.samples = book["ori_samples"]
    scene.cycles.bake_type = book["ori_bake_type"]
    scene.render.threads_mode = book["ori_threads_mode"]
    scene.render.bake.margin = book["ori_margin"]
    scene.render.bake.margin_type = book["ori_margin_type"]
    scene.render.bake.use_clear = book["ori_use_clear"]
    scene.render.use_simplify = book["ori_simplify"]
    scene.cycles.device = book["ori_device"]
    scene.cycles.use_denoising = book["ori_use_denoising"]
    scene.render.bake.target = book["ori_bake_target"]
    scene.render.bake.use_selected_to_active = book["ori_use_selected_to_active"]
    scene.render.bake.max_ray_distance = book["ori_max_ray_distance"]
    scene.render.bake.cage_extrusion = book["ori_cage_extrusion"]
    scene.render.bake.use_cage = book["ori_use_cage"]
    scene.view_settings.view_transform = book["ori_view_transform"]
    bpy.context.view_layer.material_override = book["ori_material_override"]

    # Multires related
    set_scene_bake_multires(scene, book["ori_use_bake_multires"])
    set_scene_bake_clear(scene, book["ori_use_bake_clear"])
    set_scene_render_bake_type(scene, book["ori_render_bake_type"])
    set_scene_bake_margin(scene, book["ori_bake_margin"])

    # Recover world settings
    if scene.world:
        scene.world.light_settings.distance = book["ori_distance"]

    # Recover image editors
    for i, area in enumerate(
        [a for a in bpy.context.screen.areas if a.type == "IMAGE_EDITOR"]
    ):
        # Some image can be deleted after baking process so use try except
        try:
            area.spaces[0].image = book["editor_images"][i]
        except:
            area.spaces[0].image = None

        area.spaces[0].use_image_pin = book["editor_pins"][i]

    # Recover uv
    if recover_active_uv:
        uvl = uv_layers.get(book["ori_active_uv"])
        if uvl:
            uv_layers.active = uvl
        if "ori_active_render_uv" in book:
            uvl = uv_layers.get(book["ori_active_render_uv"])
            if uvl:
                uvl.active_render = True

    # Bring back the hack functions
    wmyp.halt_hacks = False
