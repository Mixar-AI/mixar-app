# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main channel baking operations"""

from mixar.config.logging_config import get_logger

import json
import time

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from ....core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_mp_nodes
from ....core.layer.check_channels import check_start_end_root_ch_nodes
from ....core.layer.check_layers import is_any_layer_using_channel
from ....core.layer.layer_utils import get_root_height_channel, get_uv_layers
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.check_nodes import check_uv_nodes
from ....core.node.node_utils import get_active_mpaint_node, get_vertex_colors, remove_node
from ...udim.udim_utils import get_tile_numbers
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_operator_description,
    get_scene_objects,
    get_user_preferences,
    remove_mesh_obj,
)
from ....utils.constants import TEMP_UV, interpolation_type_items
from ..utils.bake_common import BaseBakeOperator, prepare_bake_settings, recover_bake_settings, remember_before_bake
from ..utils.bake_operators_helper import (
    bake_channel,
    bake_vcol_channel_items,
    check_subdiv_setup,
    merge_channel_items,
    udim_tilenum_items,
    update_bake_channel_uv_map,
)
from ..utils.bake_utils import update_enable_baked_outside
from .bake_channel_operators_helpers import (
    bake_vcol_for_channels,
    get_bake_objects,
    post_bake_operations,
    prepare_objects_for_bake,
    process_baked_images,
    process_custom_bake_targets,
    recover_multi_material,
    set_bake_info_to_images,
    setup_multi_material,
)
from .bake_channel_operators_ui import draw_bake_channels_ui

logger = get_logger(__name__)


class MDeleteBakedChannelImages(bpy.types.Operator):
    bl_idname = "wm.m_delete_baked_channel_images"
    bl_label = "Delete All Baked Channel Images"
    bl_description = "Delete all baked channel images"
    bl_options = {"UNDO"}

    also_del_vcol: BoolProperty(name="Also delete the vertex color", default=False)

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    @classmethod
    def description(self, context, properties):
        return get_operator_description(self)

    def invoke(self, context, event):
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp

        self.any_channel_use_baked_vcol = False

        if not get_user_preferences().skip_property_popups or event.shift:
            for ch in mp.channels:
                baked_vcol_node = tree.nodes.get(ch.baked_vcol)
                self.baked_vcol_name = (
                    baked_vcol_node.attribute_name if baked_vcol_node else ""
                )
                if self.baked_vcol_name != "":
                    self.any_channel_use_baked_vcol = True
                    return context.window_manager.invoke_props_dialog(self, width=320)

        self.also_del_vcol = False
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        if self.any_channel_use_baked_vcol:
            col = layout.column(align=True)
            row = col.row(align=True)
            row.scale_y = 1.2
            row.prop(self, "also_del_vcol", text="Also remove baked vertex colors")

    def execute(self, context):
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp
        mat = get_active_material()

        # Set bake to false first
        if mp.use_baked:
            mp.use_baked = False

        # Remove baked nodes
        for root_ch in mp.channels:

            # Delete baked vertex color
            if self.also_del_vcol:
                for ob in get_all_objects_with_same_materials(mat):
                    vcols = get_vertex_colors(ob)
                    if len(vcols) == 0:
                        continue
                    baked_vcol_node = tree.nodes.get(root_ch.baked_vcol)
                    if baked_vcol_node:
                        vcol = vcols.get(baked_vcol_node.attribute_name)
                        if vcol:
                            vcols.remove(vcol)

            remove_node(tree, root_ch, "baked")
            remove_node(tree, root_ch, "baked_vcol")

            if root_ch.type == "NORMAL":
                remove_node(tree, root_ch, "baked_disp")
                remove_node(tree, root_ch, "baked_vdisp")
                remove_node(tree, root_ch, "baked_normal_overlay")
                remove_node(tree, root_ch, "baked_normal_prep")
                remove_node(tree, root_ch, "baked_normal")
                remove_node(tree, root_ch, "end_max_height")

        # Reconnect
        reconnect_mp_nodes(tree)
        rearrange_mp_nodes(tree)

        return {"FINISHED"}


class MBakeChannels(bpy.types.Operator, BaseBakeOperator):
    """Bake Channels to Image(s)"""

    bl_idname = "wm.m_bake_channels"
    bl_label = "Bake channels to Image"
    bl_options = {"REGISTER", "UNDO"}

    uv_map: StringProperty(default="", update=update_bake_channel_uv_map)
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    interpolation: EnumProperty(
        name="Image Interpolation Type",
        description="Image interpolation type",
        items=interpolation_type_items,
        default="Linear",
    )

    only_active_channel: BoolProperty(
        name="Only Bake Active Channel", description="Only bake active channel", default=False,
    )

    fxaa: BoolProperty(
        name="Use FXAA",
        description="Use FXAA to baked images (doesn't work with float/non clamped images)",
        default=True,
    )

    aa_level: IntProperty(
        name="Anti Aliasing Level", description="Super Sample Anti Aliasing Level (1=off)",
        default=1, min=1, max=2,
    )

    denoise: BoolProperty(name="Use Denoise", description="Use Denoise on baked images", default=False)

    force_bake_all_polygons: BoolProperty(
        name="Force Bake all Polygons",
        description="Force bake all polygons, useful if material is not using direct polygon",
        default=False,
    )

    enable_bake_as_vcol: BoolProperty(
        name="Enable Bake As VCol", description="Has any channel enabled Bake As Vertex Color", default=False,
    )

    vcol_force_first_ch_idx: EnumProperty(
        name="Force First Vertex Color Channel",
        description="Force the first channel after baking the Vertex Color",
        items=bake_vcol_channel_items,
    )

    vcol_force_first_ch_idx_bool: BoolProperty(
        name="Force First Vertex Color Channel",
        description="Force the first channel after baking the Vertex Color",
        default=False,
    )

    use_udim: BoolProperty(name="Use UDIM Tiles", description="Use UDIM Tiles", default=False)

    use_float_for_normal: BoolProperty(
        name="Use Float for Normal", description="Use float image for baked normal", default=False,
    )

    use_float_for_displacement: BoolProperty(
        name="Use Float for Displacement", description="Use float image for baked displacement", default=False,
    )

    use_osl: BoolProperty(
        name="Use OSL",
        description="Use Open Shading Language (slower but can handle more complex layer setup)",
        default=False,
    )

    use_dithering: BoolProperty(name="Use Dithering", description="Use dithering for less banding color", default=False)

    dither_intensity: FloatProperty(
        name="Dither Intensity",
        description="Amount of dithering noise added to the rendered image to break up banding",
        default=1.0, min=0.0, max=2.0, subtype="FACTOR",
    )

    bake_disabled_layers: BoolProperty(
        name="Bake Disabled Layers", description="Take disabled layers into account when baking", default=False,
    )

    export_target_names: StringProperty(
        default="", options={'HIDDEN', 'SKIP_SAVE'},
        description="JSON mesh-name allowlist used by deterministic export baking",
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    def invoke(self, context, event):
        self._initialize_for_execution(context)
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        if (get_user_preferences().skip_property_popups and not event.shift) or len(self.channels) == 0 or self.no_layer_using:
            return self.execute(context)

        return context.window_manager.invoke_props_dialog(self, width=320)

    def _initialize_for_execution(self, context):
        """Initialize defaults for both INVOKE_DEFAULT and EXEC_DEFAULT."""
        self.invoke_operator(context)
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        obj = self.obj = get_active_object()
        mpup = get_user_preferences()

        self._setup_uv_map(obj, mp)
        self._setup_channels(mp, node, mpup)

        if self.vcol_force_first_ch_idx == "":
            self.vcol_force_first_ch_idx = "Do Nothing"
        self._mixar_initialized = True

    def _setup_uv_map(self, obj, mp):
        """Setup UV map collection."""
        uv_layers = get_uv_layers(obj)
        if obj.type == "MESH" and len(uv_layers) > 0:
            if uv_layers.get(mp.baked_uv_name):
                self.uv_map = mp.baked_uv_name
            else:
                active_name = uv_layers.active.name
                self.uv_map = mp.layers[mp.active_layer_index].uv_name if active_name == TEMP_UV else active_name

            self.uv_map_coll.clear()
            for uv in uv_layers:
                if not uv.name.startswith(TEMP_UV):
                    self.uv_map_coll.add().name = uv.name

    def _setup_channels(self, mp, node, mpup):
        """Setup channels for baking."""
        self.channels = []
        if self.only_active_channel:
            if mp.active_channel_index < len(mp.channels):
                self.channels = [mp.channels[mp.active_channel_index]]
        else:
            self.channels = mp.channels

        self.no_layer_using = False
        self.enable_bake_as_vcol = False
        if len(self.channels) > 0:
            self._init_channels_from_bake_info(node, mpup)

    def _init_channels_from_bake_info(self, node, mpup):
        """Initialize channel settings from existing bake info."""
        layer_found = any(is_any_layer_using_channel(ch, node) for ch in self.channels)
        if not layer_found:
            self.no_layer_using = True

        bi = None
        for ch in self.channels:
            baked = node.node_tree.nodes.get(ch.baked)
            if baked and baked.image:
                if baked.image.m_bake_info.is_baked:
                    bi = baked.image.m_bake_info
                self.width = baked.image.size[0] if baked.image.size[0] != 0 else mpup.default_new_image_size
                self.height = baked.image.size[1] if baked.image.size[1] != 0 else mpup.default_new_image_size
                break

        self.enable_bake_as_vcol = any(ch.enable_bake_to_vcol for ch in self.channels)

        if bi:
            for attr in dir(bi):
                if attr in {"other_objects", "selected_objects"} or attr.startswith(("__", "bl_")) or attr == "rna_type":
                    continue
                try:
                    setattr(self, attr, getattr(bi, attr))
                except Exception:
                    pass

    def check(self, context):
        self.check_operator(context)
        return True

    def draw(self, context):
        draw_bake_channels_ui(self, context, self.layout)

    def execute(self, context):
        if not getattr(self, "_mixar_initialized", False):
            self._initialize_for_execution(context)
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        T = time.time()
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp
        obj = get_active_object()
        mat = obj.active_material

        error = self._validate_bake_inputs(obj)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        ori_edit_mode = len(obj.data.materials) > 1 and obj.mode == "EDIT"
        if ori_edit_mode:
            bpy.ops.object.mode_set(mode="OBJECT")

        book = remember_before_bake(mp)
        height_ch = get_root_height_channel(mp)

        if mp.use_baked:
            mp.use_baked = False

        objs, _ = get_bake_objects(obj, mat, get_scene_objects, get_uv_layers)
        if self.export_target_names:
            try:
                allowed = set(json.loads(self.export_target_names))
                objs = [candidate for candidate in objs if candidate.name in allowed]
            except (TypeError, ValueError):
                self.report({"ERROR"}, "Invalid export bake target restriction")
                return {"CANCELLED"}
        if not objs:
            self.report({"ERROR"}, "No valid objects to bake!")
            return {"CANCELLED"}

        ori_mat_ids, ori_loop_locs = setup_multi_material(objs, mat, self.uv_map, self.force_bake_all_polygons, get_uv_layers)
        temp_objs, ori_objs = prepare_objects_for_bake(context.scene, objs, mp, mat)
        if temp_objs:
            objs = temp_objs

        margin = self.margin * self.aa_level
        width = self.width * self.aa_level
        height = self.height * self.aa_level

        # From here on the scene's render engine, sample count and modifier
        # visibility are mutated (prepare_bake_settings) and temp meshes exist.
        # Any failure in the bake body MUST still restore them — otherwise the
        # artist is silently left on the wrong render engine/samples with
        # orphan *_temp meshes and only a console traceback.
        disabled_layers = []
        try:
            prepare_bake_settings(
                book, objs, mp, self.samples, margin, self.uv_map,
                disable_problematic_modifiers=True, bake_device=self.bake_device,
                margin_type=self.margin_type, use_osl=self.use_osl,
            )

            tilenums = get_tile_numbers(objs, self.uv_map) if self.use_udim else [1001]
            disabled_layers = self._enable_disabled_layers(mp)
            baked_exists = self._bake_all_channels(node, mat, width, height, tilenums)

            baked_images = process_baked_images(
                self, self.channels, tree, baked_exists,
                self.use_dithering, self.dither_intensity, self.denoise,
                self.aa_level, self.width, self.height, self.fxaa, self.bake_device,
            )
            set_bake_info_to_images(baked_images, self)

            if not self.only_active_channel:
                process_custom_bake_targets(mp, tree, self.channels, tilenums, self.width, self.height, self.use_udim)

            mp.baked_uv_name = self.uv_map
            recover_bake_settings(book, mp)
            self._recover_disabled_layers(disabled_layers)
            disabled_layers = []

            if ori_objs:
                objs = ori_objs

            recover_multi_material(objs, ori_mat_ids, ori_loop_locs, self.uv_map, get_uv_layers)

            prepare_bake_settings(book, objs, mp, disable_problematic_modifiers=True, bake_device=self.bake_device, bake_target="VERTEX_COLORS")
            bake_vcol_for_channels(
                self.channels, mp, mat, node, tree, objs, ori_mat_ids,
                self.only_active_channel, self.vcol_force_first_ch_idx_bool, self.vcol_force_first_ch_idx,
            )
            recover_bake_settings(book, mp)

            mp.halt_update = True
            mp.use_baked = True
            mp.halt_update = False

            post_bake_operations(
                context, tree, mp, height_ch, ori_edit_mode, temp_objs,
                check_subdiv_setup, check_uv_nodes, check_start_end_root_ch_nodes,
                reconnect_mp_nodes, rearrange_mp_nodes, update_enable_baked_outside, remove_mesh_obj,
            )

            self._report_bake_result(T, mp, tree)
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Channel bake failed, restoring scene state: %s", exc, exc_info=True)
            self._recover_after_bake_failure(
                context, book, mp, ori_objs if ori_objs else objs,
                ori_mat_ids, ori_loop_locs, disabled_layers, temp_objs,
                ori_edit_mode,
            )
            self.report({"ERROR"}, f"Bake failed: {exc}")
            return {"CANCELLED"}

    def _recover_after_bake_failure(
        self, context, book, mp, recover_objs, ori_mat_ids, ori_loop_locs,
        disabled_layers, temp_objs, ori_edit_mode,
    ):
        """Best-effort restoration after a mid-bake exception.

        Each step is independently guarded so one failure never blocks the
        rest — the priority is leaving render settings, materials and temp
        meshes as they were, not perfect ordering.
        """
        try:
            recover_bake_settings(book, mp)
        except Exception as e:
            logger.error("Failed to restore bake settings after failure: %s", e)
        try:
            self._recover_disabled_layers(disabled_layers)
        except Exception as e:
            logger.error("Failed to restore disabled layers after failure: %s", e)
        try:
            recover_multi_material(recover_objs, ori_mat_ids, ori_loop_locs, self.uv_map, get_uv_layers)
        except Exception as e:
            logger.error("Failed to restore multi-material after failure: %s", e)
        for temp in (temp_objs or []):
            try:
                remove_mesh_obj(temp)
            except Exception as e:
                logger.error("Failed to remove temp bake object after failure: %s", e)
        if ori_edit_mode:
            try:
                bpy.ops.object.mode_set(mode="EDIT")
            except Exception as e:
                logger.error("Failed to restore edit mode after failure: %s", e)

    def _validate_bake_inputs(self, obj):
        """Validate bake inputs and return error message if invalid."""
        if len(self.channels) == 0:
            return "This node has no channel!"
        if self.only_active_channel and self.no_layer_using:
            return "No layer is using '" + self.channels[0].name + "' channel!"
        if self.no_layer_using:
            return "No layer is using any channel!"
        if obj.hide_viewport or obj.hide_render:
            return "Please unhide render and viewport of the active object!"
        return None

    def _enable_disabled_layers(self, mp):
        """Enable disabled layers if bake_disabled_layers is set."""
        disabled_layers = []
        if self.bake_disabled_layers:
            disabled_layers = [layer for layer in mp.layers if not layer.enable]
            for layer in disabled_layers:
                layer.enable = True
        return disabled_layers

    def _bake_all_channels(self, node, mat, width, height, tilenums):
        """Bake all channels and return list of whether baked existed."""
        tree = node.node_tree
        baked_exists = []
        for ch in self.channels:
            baked = tree.nodes.get(ch.baked)
            baked_exists.append(bool(baked))

            ch.no_layer_using = not is_any_layer_using_channel(ch, node)
            if not ch.no_layer_using:
                use_hdr = not ch.use_clamp or (self.use_dithering and ch.type == "RGB" and ch.colorspace == "SRGB")
                bake_channel(
                    self.uv_map, mat, node, ch, width, height, use_hdr=use_hdr,
                    force_use_udim=self.use_udim, tilenums=tilenums, interpolation=self.interpolation,
                    use_float_for_displacement=self.use_float_for_displacement, use_float_for_normal=self.use_float_for_normal,
                )
        return baked_exists

    def _recover_disabled_layers(self, disabled_layers):
        """Recover disabled layers."""
        if self.bake_disabled_layers:
            for layer in disabled_layers:
                layer.enable = False

    def _report_bake_result(self, start_time, mp, tree):
        """Report bake result."""
        elapsed = "{:0.2f}".format(time.time() - start_time)
        if self.only_active_channel:
            self.report({"INFO"}, mp.channels[mp.active_channel_index].name + " channel is baked in " + elapsed + " seconds!")
        else:
            self.report({"INFO"}, tree.name + " channels are baked in " + elapsed + " seconds!")


classes = (
    MDeleteBakedChannelImages,
    MBakeChannels,
)
