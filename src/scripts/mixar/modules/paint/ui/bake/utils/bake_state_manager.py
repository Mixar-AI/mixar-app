# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake state management - saving and restoring state before/after baking"""

import bpy

from ....core.layer.get_layers import get_all_layer_collections
from ....core.layer.layer_utils import get_root_parallax_channel, get_uv_layers
from ....utils.blender_commons import (
    get_active_object,
    get_scene_objects,
)
from .bake_scene_settings import (
    get_scene_bake_clear,
    get_scene_bake_margin,
    get_scene_bake_multires,
    get_scene_render_bake_type,
    set_scene_bake_clear,
    set_scene_bake_margin,
    set_scene_bake_multires,
    set_scene_render_bake_type,
)
from ..operators.bake_uv_ops import ACTIVE_UV_NODE

# Constants
EMPTY_IMG_NODE = "___EMPTY_IMAGE__"


def remember_before_bake(mp=None, mat=None):
    """Remember current state before baking for later restoration.

    Args:
        mp: MPaint node tree property group, defaults to None.
        mat: Blender material object, defaults to None.

    Returns:
        dict: Dictionary containing all saved state information.
    """
    book = {}
    book["scene"] = scene = bpy.context.scene
    book["obj"] = obj = get_active_object()
    book["mode"] = obj.mode
    uv_layers = get_uv_layers(obj)
    mpui = bpy.context.window_manager.mpui

    # Remember render settings
    book["ori_engine"] = scene.render.engine
    book["ori_bake_type"] = scene.cycles.bake_type
    book["ori_samples"] = scene.cycles.samples
    book["ori_use_osl"] = scene.cycles.shading_system
    book["ori_threads_mode"] = scene.render.threads_mode
    book["ori_margin"] = scene.render.bake.margin
    book["ori_use_clear"] = scene.render.bake.use_clear
    book["ori_normal_space"] = scene.render.bake.normal_space
    book["ori_simplify"] = scene.render.use_simplify
    book["ori_device"] = scene.cycles.device
    if hasattr(scene.render.bake, "use_pass_direct"):
        book["ori_use_pass_direct"] = scene.render.bake.use_pass_direct
    if hasattr(scene.render.bake, "use_pass_indirect"):
        book["ori_use_pass_indirect"] = scene.render.bake.use_pass_indirect
    if hasattr(scene.render.bake, "use_pass_diffuse"):
        book["ori_use_pass_diffuse"] = scene.render.bake.use_pass_diffuse
    if hasattr(scene.render.bake, "use_pass_emit"):
        book["ori_use_pass_emit"] = scene.render.bake.use_pass_emit
    if hasattr(scene.render.bake, "use_pass_ambient_occlusion"):
        book["ori_use_pass_ambient_occlusion"] = (
            scene.render.bake.use_pass_ambient_occlusion
        )

    if hasattr(scene.render, "tile_x"):
        book["ori_tile_x"] = scene.render.tile_x
        book["ori_tile_y"] = scene.render.tile_y
    book["ori_use_selected_to_active"] = scene.render.bake.use_selected_to_active
    if hasattr(scene.render.bake, "max_ray_distance"):
        book["ori_max_ray_distance"] = scene.render.bake.max_ray_distance
    book["ori_cage_extrusion"] = scene.render.bake.cage_extrusion
    book["ori_use_cage"] = scene.render.bake.use_cage
    book["ori_cage_object_name"] = (
        scene.render.bake.cage_object.name if scene.render.bake.cage_object else ""
    )

    if hasattr(scene.render.bake, "margin_type"):
        book["ori_margin_type"] = scene.render.bake.margin_type

    if hasattr(scene.cycles, "use_denoising"):
        book["ori_use_denoising"] = scene.cycles.use_denoising

    if hasattr(scene.cycles, "use_fast_gi"):
        book["ori_use_fast_gi"] = scene.cycles.use_fast_gi

    if hasattr(scene.render.bake, "target"):
        book["ori_bake_target"] = scene.render.bake.target

    book["ori_material_override"] = bpy.context.view_layer.material_override

    # Multires related
    book["ori_use_bake_multires"] = get_scene_bake_multires(scene)
    book["ori_use_bake_clear"] = get_scene_bake_clear(scene)
    book["ori_render_bake_type"] = get_scene_render_bake_type(scene)
    book["ori_bake_margin"] = get_scene_bake_margin(scene)

    # Remember uv
    book["ori_active_uv"] = uv_layers.active.name
    active_render_uvs = [u for u in uv_layers if u.active_render]
    if active_render_uvs:
        book["ori_active_render_uv"] = active_render_uvs[0].name

    # Remember scene objects
    book["ori_hide_selects"] = [
        o for o in bpy.context.view_layer.objects if o.hide_select
    ]
    book["ori_active_selected_objs"] = [
        o for o in bpy.context.view_layer.objects if o.select_get()
    ]
    book["ori_hide_renders"] = [
        o for o in bpy.context.view_layer.objects if o.hide_render
    ]
    book["ori_hide_viewports"] = [
        o for o in bpy.context.view_layer.objects if o.hide_viewport
    ]
    book["ori_hide_objs"] = [o for o in bpy.context.view_layer.objects if o.hide_get()]

    layer_cols = get_all_layer_collections([], bpy.context.view_layer.layer_collection)

    book["ori_layer_col_hide_viewport"] = [lc for lc in layer_cols if lc.hide_viewport]
    book["ori_layer_col_exclude"] = [lc for lc in layer_cols if lc.exclude]
    book["ori_col_hide_viewport"] = [c for c in bpy.data.collections if c.hide_viewport]
    book["ori_col_hide_render"] = [c for c in bpy.data.collections if c.hide_render]

    # Remember image editor images
    book["editor_images"] = [
        a.spaces[0].image for a in bpy.context.screen.areas if a.type == "IMAGE_EDITOR"
    ]
    book["editor_pins"] = [
        a.spaces[0].use_image_pin
        for a in bpy.context.screen.areas
        if a.type == "IMAGE_EDITOR"
    ]

    # Remember world settings
    if scene.world:
        book["ori_distance"] = scene.world.light_settings.distance

    # Remember mpui
    # book['ori_disable_temp_uv'] = mpui.disable_auto_temp_uv_update

    # Remember mp
    if mp:
        book["parallax_ch"] = get_root_parallax_channel(mp)
    else:
        book["parallax_ch"] = None

    # Remember material props
    if mat:
        book["ori_bsdf"] = mat.mp.ori_bsdf

    return book


def recover_bake_settings(book, mp=None, recover_active_uv=False, mat=None):
    """Recover/restore scene and object settings after baking operation.

    Args:
        book (dict): Dictionary containing saved state information.
        mp: MPaint node tree property group, defaults to None.
        recover_active_uv (bool, optional): Recover active UV layer. Defaults to False.
        mat: Blender material object, defaults to None.
    """
    scene = book["scene"]
    obj = book["obj"]
    uv_layers = get_uv_layers(obj)
    mpui = bpy.context.window_manager.mpui
    wmyp = bpy.context.window_manager.mpprops

    scene.render.engine = book["ori_engine"]
    scene.cycles.samples = book["ori_samples"]
    scene.cycles.shading_system = book["ori_use_osl"]
    scene.cycles.bake_type = book["ori_bake_type"]
    scene.render.threads_mode = book["ori_threads_mode"]
    scene.render.bake.margin = book["ori_margin"]
    scene.render.bake.use_clear = book["ori_use_clear"]
    scene.render.bake.normal_space = book["ori_normal_space"]
    scene.render.use_simplify = book["ori_simplify"]
    scene.cycles.device = book["ori_device"]
    if hasattr(scene.render.bake, "use_pass_direct"):
        scene.render.bake.use_pass_direct = book["ori_use_pass_direct"]
    if hasattr(scene.render.bake, "use_pass_indirect"):
        scene.render.bake.use_pass_indirect = book["ori_use_pass_indirect"]
    if hasattr(scene.render.bake, "use_pass_emit"):
        scene.render.bake.use_pass_emit = book["ori_use_pass_emit"]
    if hasattr(scene.render.bake, "use_pass_diffuse"):
        scene.render.bake.use_pass_diffuse = book["ori_use_pass_diffuse"]
    if hasattr(scene.render.bake, "use_pass_ambient_occlusion"):
        scene.render.bake.use_pass_ambient_occlusion = book[
            "ori_use_pass_ambient_occlusion"
        ]
    if hasattr(scene.render, "tile_x"):
        scene.render.tile_x = book["ori_tile_x"]
        scene.render.tile_y = book["ori_tile_y"]
    if hasattr(scene.cycles, "use_denoising"):
        scene.cycles.use_denoising = book["ori_use_denoising"]
    if hasattr(scene.cycles, "use_fast_gi"):
        scene.cycles.use_fast_gi = book["ori_use_fast_gi"]
    if hasattr(scene.render.bake, "target"):
        scene.render.bake.target = book["ori_bake_target"]
    if hasattr(scene.render.bake, "margin_type"):
        scene.render.bake.margin_type = book["ori_margin_type"]
    scene.render.bake.use_selected_to_active = book["ori_use_selected_to_active"]
    if hasattr(scene.render.bake, "max_ray_distance"):
        scene.render.bake.max_ray_distance = book["ori_max_ray_distance"]
    scene.render.bake.cage_extrusion = book["ori_cage_extrusion"]
    scene.render.bake.use_cage = book["ori_use_cage"]
    if book["ori_cage_object_name"] != "":
        cage_object = bpy.data.objects.get(book["ori_cage_object_name"])
        if cage_object:
            scene.render.bake.cage_object = cage_object

    bpy.context.view_layer.material_override = book["ori_material_override"]

    # Multires related
    set_scene_bake_multires(scene, book["ori_use_bake_multires"])
    set_scene_bake_clear(scene, book["ori_use_bake_clear"])
    set_scene_render_bake_type(scene, book["ori_render_bake_type"])
    set_scene_bake_margin(scene, book["ori_bake_margin"])

    if "compute_device_type" in book:
        bpy.context.preferences.addons["cycles"].preferences["compute_device_type"] = (
            book["compute_device_type"]
        )

    if "material_override" in book:
        bpy.context.view_layer.material_override = book["material_override"]

    # Recover world settings
    if scene.world:
        scene.world.light_settings.distance = book["ori_distance"]

    # Recover uv
    if recover_active_uv:
        uvl = uv_layers.get(book["ori_active_uv"])
        if uvl:
            uv_layers.active = uvl

    if "ori_active_render_uv" in book:
        uvl = uv_layers.get(book["ori_active_render_uv"])
        if uvl:
            uvl.active_render = True

    # Recover active object and mode
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode=book["mode"])

    # Recover collections
    _recover_collections(book)

    # Recover objects
    _recover_objects(book)

    # Recover image editors
    _recover_image_editors(book)

    # Recover parallax
    if book["parallax_ch"]:
        book["parallax_ch"].enable_parallax = True

    # Recover modifiers
    _recover_modifiers(book)

    if mat:
        # Recover stored material original bsdf for preview
        if "ori_bsdf" in book:
            mat.mp.ori_bsdf = book["ori_bsdf"]

    # Recover other material active nodes
    _recover_material_active_nodes(book)

    # Bring back the hack functions
    wmyp.halt_hacks = False


def _recover_collections(book):
    """Recover collection visibility settings.

    Args:
        book (dict): Dictionary containing saved state information.
    """
    layer_cols = get_all_layer_collections([], bpy.context.view_layer.layer_collection)
    for lc in layer_cols:
        if lc in book["ori_layer_col_hide_viewport"]:
            lc.hide_viewport = True
        else:
            lc.hide_viewport = False

        if lc in book["ori_layer_col_exclude"]:
            lc.exclude = True
        else:
            lc.exclude = False

    for c in bpy.data.collections:
        if c in book["ori_col_hide_viewport"]:
            c.hide_viewport = True
        else:
            c.hide_viewport = False

        if c in book["ori_col_hide_render"]:
            c.hide_render = True
        else:
            c.hide_render = False


def _recover_objects(book):
    """Recover object visibility and selection settings.

    Args:
        book (dict): Dictionary containing saved state information.
    """
    objs = [o for o in bpy.context.view_layer.objects]
    for o in objs:
        if o in book["ori_active_selected_objs"]:
            o.select_set(True)
        else:
            o.select_set(False)
        if o in book["ori_hide_renders"]:
            o.hide_render = True
        else:
            o.hide_render = False
        if o in book["ori_hide_viewports"]:
            o.hide_viewport = True
        else:
            o.hide_viewport = False
        if o in book["ori_hide_objs"]:
            o.hide_set(True)
        else:
            o.hide_set(False)
        if o in book["ori_hide_selects"]:
            o.hide_select = True
        else:
            o.hide_select = False


def _recover_image_editors(book):
    """Recover image editor settings.

    Args:
        book (dict): Dictionary containing saved state information.
    """
    for i, area in enumerate(
        [a for a in bpy.context.screen.areas if a.type == "IMAGE_EDITOR"]
    ):
        # Some image can be deleted after baking process so use try except
        try:
            area.spaces[0].image = book["editor_images"][i]
        except:
            area.spaces[0].image = None

        area.spaces[0].use_image_pin = book["editor_pins"][i]


def _recover_modifiers(book):
    """Recover modifier visibility settings.

    Args:
        book (dict): Dictionary containing saved state information.
    """
    for obj_name, lib in book["obj_mods_lib"].items():
        o = get_scene_objects().get(obj_name)
        if o:
            for mod_name in lib["disabled_mods"]:
                mod = o.modifiers.get(mod_name)
                if mod:
                    mod.show_render = True

            for mod_name in lib["disabled_viewport_mods"]:
                mod = o.modifiers.get(mod_name)
                if mod:
                    mod.show_viewport = True


def _recover_material_active_nodes(book):
    """Recover material active nodes and remove temporary nodes.

    Args:
        book (dict): Dictionary containing saved state information.
    """
    if "ori_mat_objs" in book:
        for i, o_name in enumerate(book["ori_mat_objs"]):
            o = bpy.data.objects.get(o_name)
            if not o:
                continue
            for j, m in enumerate(o.data.materials):
                if not m or not m.use_nodes:
                    continue
                active_node = m.node_tree.nodes.get(
                    book["ori_mat_objs_active_nodes"][i][j]
                )
                m.node_tree.nodes.active = active_node

                # Remove temporary nodes
                temp = m.node_tree.nodes.get(EMPTY_IMG_NODE)
                if temp:
                    m.node_tree.nodes.remove(temp)
                # act_uv = m.node_tree.nodes.get(ACTIVE_UV_NODE)
                # if act_uv: m.node_tree.nodes.remove(act_uv)
