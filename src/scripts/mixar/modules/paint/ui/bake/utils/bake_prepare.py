# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake preparation - setting up scene and objects for baking operations"""

import bpy

from mixar.config.logging_config import get_logger

from ....core.element.get_elements import get_multires_modifier
from ....core.layer.layer_utils import get_uv_layers
from ....utils.blender_commons import (
    get_active_object,
    get_object_parent_layer_collections,
)
from .bake_scene_settings import (
    set_scene_bake_clear,
    set_scene_bake_margin,
    set_scene_bake_multires,
    set_scene_render_bake_type,
)
from ..operators.bake_uv_ops import add_active_render_uv_node
from .bake_validation import get_problematic_modifiers

logger = get_logger(__name__)

# Constants
EMPTY_IMG_NODE = "___EMPTY_IMAGE__"


def prepare_bake_settings(
    book,
    objs,
    mp=None,
    samples=1,
    margin=5,
    uv_map="",
    bake_type="EMIT",
    disable_problematic_modifiers=False,
    hide_other_objs=True,
    bake_from_multires=False,
    tile_x=64,
    tile_y=64,
    use_selected_to_active=False,
    max_ray_distance=0.0,
    cage_extrusion=0.0,
    bake_target="IMAGE_TEXTURES",
    source_objs=[],
    bake_device="CPU",
    use_denoising=False,
    margin_type="ADJACENT_FACES",
    use_cage=False,
    cage_object_name="",
    normal_space="TANGENT",
    use_osl=False,
):
    """Prepare scene and object settings for baking operation.

    Args:
        book (dict): Dictionary to store original settings.
        objs (list): List of objects to bake.
        mp: MPaint node tree property group, defaults to None.
        samples (int, optional): Number of samples for baking. Defaults to 1.
        margin (int, optional): Bake margin in pixels. Defaults to 5.
        uv_map (str, optional): UV map name to use. Defaults to "".
        bake_type (str, optional): Type of bake operation. Defaults to "EMIT".
        disable_problematic_modifiers (bool, optional): Disable problematic modifiers.
            Defaults to False.
        hide_other_objs (bool, optional): Hide other objects during bake.
            Defaults to True.
        bake_from_multires (bool, optional): Bake from multires modifier.
            Defaults to False.
        tile_x (int, optional): Render tile size X. Defaults to 64.
        tile_y (int, optional): Render tile size Y. Defaults to 64.
        use_selected_to_active (bool, optional): Use selected to active baking.
            Defaults to False.
        max_ray_distance (float, optional): Maximum ray distance. Defaults to 0.0.
        cage_extrusion (float, optional): Cage extrusion distance. Defaults to 0.0.
        bake_target (str, optional): Bake target type. Defaults to "IMAGE_TEXTURES".
        source_objs (list, optional): Source objects for baking. Defaults to [].
        bake_device (str, optional): Device to use for baking. Defaults to "CPU".
        use_denoising (bool, optional): Use denoising. Defaults to False.
        margin_type (str, optional): Type of margin. Defaults to "ADJACENT_FACES".
        use_cage (bool, optional): Use cage object. Defaults to False.
        cage_object_name (str, optional): Name of cage object. Defaults to "".
        normal_space (str, optional): Normal space for normal baking.
            Defaults to "TANGENT".
        use_osl (bool, optional): Use OSL shading. Defaults to False.
    """

    scene = bpy.context.scene
    mpui = bpy.context.window_manager.mpui
    wmyp = bpy.context.window_manager.mpprops

    # Hack function on depsgraph update can cause crash, so halt it before baking
    wmyp.halt_hacks = True

    # Configure render settings
    _configure_render_settings(
        scene,
        samples,
        margin,
        use_osl,
        use_selected_to_active,
        max_ray_distance,
        cage_extrusion,
        cage_object_name,
        use_cage,
        tile_x,
        tile_y,
        use_denoising,
        bake_target,
        margin_type,
    )

    # Configure bake type settings
    _configure_bake_type(scene, bake_type, bake_from_multires, margin, normal_space)

    # A GPU bake needs a Cycles compute backend enabled in preferences —
    # otherwise device='GPU' silently renders on CPU. ensure_gpu_compute()
    # enables one on factory prefs and respects an explicit user choice;
    # when no GPU is usable, fall back loudly instead of pretending.
    if bake_device == "GPU":
        from mixar.modules.common.utils.cycles_device_utils import ensure_gpu_compute

        if ensure_gpu_compute() is None:
            logger.warning(
                "GPU bake requested but no Cycles GPU backend is available; "
                "baking on CPU"
            )
            bake_device = "CPU"
    scene.cycles.device = bake_device

    # Configure object visibility and selection
    _configure_object_visibility(
        book, objs, source_objs, hide_other_objs, bake_from_multires
    )

    # Disable problematic modifiers if requested
    _handle_problematic_modifiers(book, objs, disable_problematic_modifiers)

    # Set to object mode
    if get_active_object() and get_active_object().mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except:
            pass

    # Disable parallax channel
    if book["parallax_ch"]:
        book["parallax_ch"].enable_parallax = False

    # Handle material settings for baking
    _prepare_materials_for_bake(book, objs, uv_map)


def _configure_render_settings(
    scene,
    samples,
    margin,
    use_osl,
    use_selected_to_active,
    max_ray_distance,
    cage_extrusion,
    cage_object_name,
    use_cage,
    tile_x,
    tile_y,
    use_denoising,
    bake_target,
    margin_type,
):
    """Configure render settings for baking.

    Args:
        scene: Blender scene object.
        samples (int): Number of samples.
        margin (int): Bake margin in pixels.
        use_osl (bool): Use OSL shading.
        use_selected_to_active (bool): Use selected to active baking.
        max_ray_distance (float): Maximum ray distance.
        cage_extrusion (float): Cage extrusion distance.
        cage_object_name (str): Name of cage object.
        use_cage (bool): Use cage object.
        tile_x (int): Render tile size X.
        tile_y (int): Render tile size Y.
        use_denoising (bool): Use denoising.
        bake_target (str): Bake target type.
        margin_type (str): Type of margin.
    """
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.shading_system = use_osl
    scene.render.threads_mode = "AUTO"
    scene.render.bake.margin = margin
    scene.render.bake.use_clear = False
    scene.render.bake.use_selected_to_active = use_selected_to_active

    if hasattr(scene.render.bake, "max_ray_distance"):
        scene.render.bake.max_ray_distance = max_ray_distance

    scene.render.bake.cage_extrusion = cage_extrusion
    cage_object = (
        bpy.data.objects.get(cage_object_name) if cage_object_name != "" else None
    )
    scene.render.bake.use_cage = use_cage
    if cage_object:
        scene.render.bake.cage_object = cage_object
    scene.render.use_simplify = False

    if hasattr(scene.render.bake, "use_pass_direct"):
        scene.render.bake.use_pass_direct = True
    if hasattr(scene.render.bake, "use_pass_indirect"):
        scene.render.bake.use_pass_indirect = True
    if hasattr(scene.render.bake, "use_pass_diffuse"):
        scene.render.bake.use_pass_diffuse = True
    if hasattr(scene.render.bake, "use_pass_emit"):
        scene.render.bake.use_pass_emit = True
    if hasattr(scene.render.bake, "use_pass_ambient_occlusion"):
        scene.render.bake.use_pass_ambient_occlusion = True

    if hasattr(scene.render, "tile_x"):
        scene.render.tile_x = tile_x
        scene.render.tile_y = tile_y

    if hasattr(scene.cycles, "use_denoising"):
        scene.cycles.use_denoising = use_denoising

    if hasattr(scene.render.bake, "target"):
        scene.render.bake.target = bake_target

    if hasattr(scene.render.bake, "margin_type"):
        scene.render.bake.margin_type = margin_type

    bpy.context.view_layer.material_override = None


def _configure_bake_type(scene, bake_type, bake_from_multires, margin, normal_space):
    """Configure bake type settings.

    Args:
        scene: Blender scene object.
        bake_type (str): Type of bake operation.
        bake_from_multires (bool): Bake from multires modifier.
        margin (int): Bake margin in pixels.
        normal_space (str): Normal space for normal baking.
    """
    if bake_from_multires:
        set_scene_bake_multires(scene, True)
        set_scene_render_bake_type(scene, bake_type)
        set_scene_bake_margin(scene, margin)
        set_scene_bake_clear(scene, False)
    else:
        set_scene_bake_multires(scene, False)
        scene.cycles.bake_type = bake_type

    if bake_type == "NORMAL":
        scene.render.bake.normal_space = normal_space


def _configure_object_visibility(
    book, objs, source_objs, hide_other_objs, bake_from_multires
):
    """Configure object visibility and selection for baking.

    Args:
        book (dict): Dictionary to store original settings.
        objs (list): List of objects to bake.
        source_objs (list): Source objects for baking.
        hide_other_objs (bool): Hide other objects during bake.
        bake_from_multires (bool): Bake from multires modifier.
    """
    # Disable exclude only works on source objects
    for o in source_objs:
        layer_cols = get_object_parent_layer_collections(
            [], bpy.context.view_layer.layer_collection, o
        )
        for lc in layer_cols:
            lc.exclude = False

    # Show viewport and render of object layer collection
    for o in objs:
        o.hide_select = False
        o.hide_viewport = False
        o.hide_render = False
        layer_cols = get_object_parent_layer_collections(
            [], bpy.context.view_layer.layer_collection, o
        )
        for lc in layer_cols:
            lc.hide_viewport = False
            lc.collection.hide_viewport = False
            lc.collection.hide_render = False

    if hide_other_objs:
        for o in bpy.context.view_layer.objects:
            if o not in objs:
                o.hide_render = True

    for o in bpy.context.view_layer.objects:
        o.select_set(False)

    for obj in objs:
        obj.hide_set(False)

        if bake_from_multires:
            # Do not select object without multires modifier
            mod = get_multires_modifier(obj)
            if not mod:
                obj.select_set(False)
            else:
                obj.select_set(True)
        else:
            obj.select_set(True)


def _handle_problematic_modifiers(book, objs, disable_problematic_modifiers):
    """Handle problematic modifiers by disabling them if requested.

    Args:
        book (dict): Dictionary to store original settings.
        objs (list): List of objects to bake.
        disable_problematic_modifiers (bool): Disable problematic modifiers.
    """
    # Disable material override
    book["material_override"] = bpy.context.view_layer.material_override
    bpy.context.view_layer.material_override = None
    book["obj_mods_lib"] = {}

    if disable_problematic_modifiers:
        for obj in objs:
            book["obj_mods_lib"][obj.name] = {}
            book["obj_mods_lib"][obj.name]["disabled_mods"] = []
            book["obj_mods_lib"][obj.name]["disabled_viewport_mods"] = []

            for mod in get_problematic_modifiers(obj):

                if mod.show_render:
                    mod.show_render = False
                    book["obj_mods_lib"][obj.name]["disabled_mods"].append(mod.name)

                if mod.show_viewport:
                    mod.show_viewport = False
                    book["obj_mods_lib"][obj.name]["disabled_viewport_mods"].append(
                        mod.name
                    )


def _prepare_materials_for_bake(book, objs, uv_map):
    """Prepare materials for baking operation.

    Args:
        book (dict): Dictionary to store original settings.
        objs (list): List of objects to bake.
        uv_map (str): UV map name to use.
    """
    # Remember object materials related to baking
    book["ori_mat_objs"] = []
    book["ori_mat_objs_active_nodes"] = []

    for o in objs:
        mat = o.active_material
        if not mat:
            continue

        # Remember other material active nodes
        active_node_names = []
        for m in o.data.materials:
            if m and m.use_nodes and m.node_tree.nodes.active:
                active_node_names.append(m.node_tree.nodes.active.name)
                continue
            active_node_names.append("")

        book["ori_mat_objs"].append(o.name)
        book["ori_mat_objs_active_nodes"].append(active_node_names)

        # Add extra uv nodes for non connected texture nodes outside mp node
        if uv_map != "":

            uv_layers = get_uv_layers(o)
            active_render_uvs = [u for u in uv_layers if u.active_render]

            if active_render_uvs:
                active_render_uv = active_render_uvs[0]

                # Only add new uv node if target uv map is different than active render uv
                if active_render_uv.name != uv_map:
                    add_active_render_uv_node(mat.node_tree, active_render_uv.name)

        for m in o.data.materials:
            if not m or not m.use_nodes:
                continue

            # Create temporary image texture node to make sure
            # other materials inside single object did not bake to their active image
            if m != mat:
                temp = m.node_tree.nodes.get(EMPTY_IMG_NODE)
                if not temp:
                    temp = m.node_tree.nodes.new("ShaderNodeTexImage")
                    temp.name = EMPTY_IMG_NODE
                m.node_tree.nodes.active = temp

    # Set active uv layers
    if uv_map != "":
        for obj in objs:
            if obj.type != "MESH":
                continue
            uv_layers = get_uv_layers(obj)
            uv = uv_layers.get(uv_map)
            if uv:
                uv_layers.active = uv
