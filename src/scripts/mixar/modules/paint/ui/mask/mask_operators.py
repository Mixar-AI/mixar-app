# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import random
import re
import time

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy_extras.io_utils import ImportHelper

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.element.check_elements import (
    check_colorid_vcol,
    is_colorid_already_being_used,
    is_colorid_vcol_still_being_used,
)
from ...core.element.create_vcol import new_vertex_color
from ...core.element.get_elements import (
    get_default_uv_name,
    get_vcol_data_type_and_domain_by_name,
    get_vertex_color_names,
)
from ...core.element.update_fcurves import swap_mask_fcurves
from ...core.element.update_vcol import set_active_vertex_color
from ...core.io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.get_entities import get_all_baked_channel_images
from ...core.layer.layer_utils import get_active_layer, get_height_channel
from ...core.layer.mappings import is_mapping_possible
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.modifier.mask_modifier import mask_modifier_type_items
from ...core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_mask_mix_nodes,
    check_mp_linear_nodes,
)
from ...core.node.get_nodes import get_layer_source, get_mask_source
from ...core.node.node_utils import get_active_mpaint_node, get_vertex_colors
from ...core.subtree.check_subtree import check_mask_source_tree
from ...core.subtree.get_subtree import get_tree
from ...utils.blender_commons import (
    get_active_object,
    get_noncolor_name,
    get_operator_description,
    get_scene_objects,
    get_user_preferences,
    is_image_available_to_open,
)
from ...utils.common import is_object_work_with_uv, split_layout
from ...utils.constants import (
    COLORID_TOLERANCE,
    COLOR_ID_VCOL_NAME,
    TEMP_UV,
    hemi_space_items,
    image_resolution_items,
    interpolation_type_items,
    mask_texcoord_type_items,
    mask_type_items,
    vcol_data_type_items,
    vcol_domain_items,
)
from ...utils.statics import mask_blend_type_items
from ..image_atlas.image_atlas_utils import (
    check_need_of_erasing_segments,
    clear_unused_segments,
    get_set_image_atlas_segment,
)
from ..mask.mask_operators_helper import (
    add_new_mask,
    get_new_mask_name,
    remove_mask,
    replace_mask_type,
    update_new_mask_uv_map,
)
from ..other.base_operator import OpenImage
from ..udim.udim_operators_helper import fill_tile
from ..udim.udim_utils import (
    get_set_udim_atlas_segment,
    get_tile_numbers,
    initial_pack_udim,
)

# Import extracted operator classes
from .mask_operators_new import MNewLayerMask
from .mask_operators_open import MOpenImageAsMask, MOpenAvailableDataAsMask




class MMoveLayerMask(bpy.types.Operator):
    bl_idname = "wm.m_move_layer_mask"
    bl_label = "Move Layer Mask"
    bl_description = "Move layer mask"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    @classmethod
    def poll(cls, context):
        return hasattr(context, "mask") and hasattr(context, "layer")

    def execute(self, context):
        mpui = context.window_manager.mpui
        mask = context.mask
        layer = context.layer

        num_masks = len(layer.masks)
        if num_masks < 2:
            return {"CANCELLED"}

        m = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", mask.path_from_id())
        index = int(m.group(2))

        # Get new index
        if self.direction == "UP" and index > 0:
            new_index = index - 1
        elif self.direction == "DOWN" and index < num_masks - 1:
            new_index = index + 1
        else:
            return {"CANCELLED"}

        # Remove input props first
        check_layer_tree_ios(layer, remove_props=True)

        # Swap masks
        layer.masks.move(index, new_index)
        swap_mask_fcurves(layer, index, new_index)

        # Dealing with transition bump
        tree = get_tree(layer)
        check_mask_mix_nodes(layer, tree)
        check_mask_source_tree(layer)  # , bump_ch)
        # check_mask_image_linear_node(mask)

        # Create input props again
        check_layer_tree_ios(layer)

        # Swap UI expand content
        props = ["expand_content", "expand_channels", "expand_source", "expand_vector"]

        for p in props:
            neighbor_prop = getattr(mpui.layer_ui.masks[new_index], p)
            prop = getattr(mpui.layer_ui.masks[index], p)
            setattr(mpui.layer_ui.masks[new_index], p, prop)
            setattr(mpui.layer_ui.masks[index], p, neighbor_prop)

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        return {"FINISHED"}


class MRemoveLayerMask(bpy.types.Operator):
    bl_idname = "wm.m_remove_layer_mask"
    bl_label = "Remove Layer Mask"
    bl_description = "Remove Layer Mask"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node()

    def invoke(self, context, event):
        layer = self.layer = context.layer
        mask = self.mask = context.mask

        # Check for any dirty images
        self.any_dirty_images = False
        source = get_mask_source(mask)
        image = source.image if mask.type == "IMAGE" else None
        baked_source = get_mask_source(mask, get_baked=True)

        if (image and image.is_dirty) or (
            baked_source and baked_source.image and baked_source.image.is_dirty
        ):
            self.any_dirty_images = True

        if self.any_dirty_images:
            return context.window_manager.invoke_props_dialog(self, width=300)

        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # Warning message
        warning_row1 = main_col.row(align=True)
        warning_row1.scale_y = 1.2
        warning_row1.label(
            text="Unsaved data will be LOST if you UNDO this operation.",
            icon="ERROR",
        )

        main_col.separator(factor=0.4)

        # Confirmation question
        question_row = main_col.row(align=True)
        question_row.scale_y = 1.2
        question_row.label(text="Are you sure you want to continue?", icon="QUESTION")

        main_col.separator(factor=0.4)

    def execute(self, context):
        mask = self.mask
        layer = self.layer
        tree = get_tree(layer)
        obj = get_active_object()
        mat = obj.active_material
        mp = layer.id_data.mp

        mask_type = mask.type

        # Remove input props first
        check_layer_tree_ios(layer, remove_props=True)

        remove_mask(layer, mask, obj)

        # Create input props again
        check_all_layer_channel_io_and_nodes(layer, tree)

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        reconnect_mp_nodes(layer.id_data)
        rearrange_mp_nodes(layer.id_data)

        # Seach for active edit mask
        found_active_edit = False
        for m in layer.masks:
            if m.active_edit:
                found_active_edit = True
                break

        # Use layer image as active image if active edit mask not found
        if not found_active_edit:
            # if layer.type == 'IMAGE':
            #    source = get_layer_source(layer, tree)
            #    update_image_editor_image(context, source.image)
            # else:
            #    update_image_editor_image(context, None)
            mp.active_layer_index = mp.active_layer_index

        if mask_type == "COLOR_ID":

            # Check if color id vcol need to be removed or not
            objs = get_all_objects_with_same_materials(mat)
            if not is_colorid_vcol_still_being_used(objs):
                for o in objs:
                    ovcols = get_vertex_colors(o)
                    vcol = ovcols.get(COLOR_ID_VCOL_NAME)
                    if vcol:
                        ovcols.remove(vcol)

        # Refresh viewport and image editor
        for area in bpy.context.screen.areas:
            if area.type in ["VIEW_3D", "IMAGE_EDITOR", "NODE_EDITOR"]:
                area.tag_redraw()

        return {"FINISHED"}


class MOpenImageToReplaceMask(bpy.types.Operator, ImportHelper, OpenImage):
    """Open Image to Replace Mask"""

    bl_idname = "wm.m_open_image_to_replace_mask"
    bl_label = "Open Image to Replace Mask"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        group_node = get_active_mpaint_node()
        return get_active_object() and group_node and len(group_node.node_tree.mp.layers) > 0

    def invoke(self, context, event):
        self.mask = context.mask
        return self.running_fileselect_modal(context, event)

    def execute(self, context):

        T = time.time()

        wm = context.window_manager
        mask = self.mask
        mp = mask.id_data.mp

        loaded_images = self.get_loaded_images()

        if len(loaded_images) == 0 or loaded_images[0] is None:
            self.report({"ERROR"}, "No image is selected!")
            return {"CANCELLED"}

        image = loaded_images[0]

        replace_mask_type(mask, "IMAGE", image.name)

        logger.info(
            "Layer %s is updated in %s ms!",
            mask.name, "{:0.2f}".format((time.time() - T) * 1000)
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


class MReplaceMaskType(bpy.types.Operator):
    bl_idname = "wm.m_replace_mask_type"
    bl_label = "Replace Mask Type"
    bl_description = "Replace Mask Type"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(name="Layer Type", items=mask_type_items, default="IMAGE")

    modifier_type: EnumProperty(
        name="Mask Modifier Type", items=mask_modifier_type_items, default="INVERT"
    )

    item_name: StringProperty(name="Item")
    item_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    load_item: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        group_node = get_active_mpaint_node()
        return get_active_object() and group_node and len(group_node.node_tree.mp.layers) > 0

    def invoke(self, context, event):
        obj = get_active_object()
        self.mask = context.mask
        if self.load_item and self.type in {"IMAGE", "VCOL"}:

            self.item_coll.clear()
            self.item_name = ""

            # Update image names
            if self.type == "IMAGE":
                baked_channel_images = get_all_baked_channel_images(self.mask.id_data)
                for img in bpy.data.images:
                    if (
                        not img.yia.is_image_atlas
                        and not img.yua.is_udim_atlas
                        and img not in baked_channel_images
                    ):
                        self.item_coll.add().name = img.name
            else:
                for vcol_name in get_vertex_color_names(obj):
                    if vcol_name not in {COLOR_ID_VCOL_NAME}:
                        self.item_coll.add().name = vcol_name

            return context.window_manager.invoke_props_dialog(self)  # , width=400)

        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== SELECTION SECTION ==========
        select_box = main_col.box()
        select_col = select_box.column(align=False)

        # Header
        header_row = select_col.row(align=True)
        header_row.scale_y = 1.4
        if self.type == "IMAGE":
            header_row.label(text="Select Image", icon="IMAGE_DATA")
        else:
            header_row.label(text="Select Vertex Color", icon="GROUP_VCOL")

        select_col.separator(factor=1.2)

        # Selection
        select_row = select_col.row(align=True)
        select_row.scale_y = 1.4
        select_split = select_row.split(factor=0.25, align=True)
        label_col = select_split.column(align=True)
        label_col.alignment = "RIGHT"
        if self.type == "IMAGE":
            label_col.label(text="Image:")
            select_split.prop_search(
                self, "item_name", self, "item_coll", text="", icon="IMAGE_DATA"
            )
        else:
            label_col.label(text="Vertex Color:")
            select_split.prop_search(
                self, "item_name", self, "item_coll", text="", icon="GROUP_VCOL"
            )

        select_col.separator(factor=0.4)

        select_col.separator(factor=0.8)

    def execute(self, context):

        T = time.time()

        wm = context.window_manager
        mask = self.mask
        mp = mask.id_data.mp

        if mask.use_temp_bake:
            self.report({"ERROR"}, "Cannot replace temporarily baked mask!")
            return {"CANCELLED"}

        if self.type == mask.type and self.type not in {"IMAGE", "VCOL", "MODIFIER"}:
            return {"CANCELLED"}

        if self.load_item and self.type in {"VCOL", "IMAGE"} and self.item_name == "":
            self.report({"ERROR"}, "Form is cannot be empty!")
            return {"CANCELLED"}

        replace_mask_type(
            self.mask, self.type, self.item_name, modifier_type=self.modifier_type
        )

        logger.info(
            "Mask %s is updated in %s ms!",
            mask.name, "{:0.2f}".format((time.time() - T) * 1000)
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


class MFixEdgeDetectAO(bpy.types.Operator):
    """Eevee Ambient Occlusion must be enabled to make edge detect mask to work"""

    bl_idname = "wm.m_fix_edge_detect_ao"
    bl_label = "Fix Edge Detect Mask AO"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return hasattr(context, "layer")

    def execute(self, context):
        bpy.context.scene.eevee.use_gtao = True
        return {"FINISHED"}


# Mask Source Menu (for changing mask type/source)
class MASKS_MT_MaskSourceMenu(bpy.types.Menu):
    """Menu for changing mask source type"""

    bl_idname = "MASKS_MT_mask_source_menu"
    bl_label = "Mask Source"

    def draw(self, context):
        """Draw the mask source menu with all type options."""
        mask = context.mask
        layer = context.layer
        tree = get_tree(layer) if layer else None

        col = self.layout.column()
        col.label(text='Mask Source')
        col.separator()

        folder_emoji = '> '

        # ===== IMAGE SECTION =====
        cache_image = tree.nodes.get(mask.cache_image) if tree else None
        if mask.type != 'IMAGE' and cache_image and cache_image.image:
            op = col.operator('wm.m_replace_mask_type', text='Image: ' + cache_image.image.name, icon='RADIOBUT_OFF')
            op.type = 'IMAGE'
            op.load_item = False
            op.item_name = ''
        else:
            source = get_mask_source(mask)
            suffix = ''
            if mask.type == 'IMAGE' and source and source.image:
                suffix += ': ' + source.image.name
            icon = 'RADIOBUT_ON' if mask.type == 'IMAGE' else 'RADIOBUT_OFF'
            col.label(text='Image' + suffix, icon=icon)

        label = 'Open Image' if mask.type != 'IMAGE' else 'Replace Image'
        col.operator('wm.m_open_image_to_replace_mask', text=folder_emoji + label)

        label = 'Open Available Image' if mask.type != 'IMAGE' else 'Replace with Available Image'
        op = col.operator('wm.m_replace_mask_type', text=folder_emoji + label)
        op.type = 'IMAGE'
        op.load_item = True

        col.separator()

        # ===== VERTEX COLOR SECTION =====
        cache_vcol = tree.nodes.get(mask.cache_vcol) if tree else None
        if mask.type != 'VCOL' and cache_vcol and cache_vcol.attribute_name != '':
            op = col.operator('wm.m_replace_mask_type', text='Vertex Color: ' + cache_vcol.attribute_name, icon='RADIOBUT_OFF')
            op.type = 'VCOL'
            op.load_item = False
            op.item_name = ''
        else:
            source = get_mask_source(mask)
            suffix = ''
            if mask.type == 'VCOL' and source and hasattr(source, 'attribute_name') and source.attribute_name != '':
                suffix += ': ' + source.attribute_name
            icon = 'RADIOBUT_ON' if mask.type == 'VCOL' else 'RADIOBUT_OFF'
            col.label(text='Vertex Color' + suffix, icon=icon)

        label = 'Open Available Vertex Color' if mask.type != 'VCOL' else 'Replace Vertex Color'
        op = col.operator('wm.m_replace_mask_type', text=folder_emoji + label)
        op.type = 'VCOL'
        op.load_item = True

        col.separator()

        # ===== PROCEDURAL TEXTURES SECTION =====
        icon = 'RADIOBUT_ON' if mask.type == 'BRICK' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Brick', icon=icon).type = 'BRICK'

        icon = 'RADIOBUT_ON' if mask.type == 'CHECKER' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Checker', icon=icon).type = 'CHECKER'

        icon = 'RADIOBUT_ON' if mask.type == 'GRADIENT' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Gradient', icon=icon).type = 'GRADIENT'

        icon = 'RADIOBUT_ON' if mask.type == 'MAGIC' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Magic', icon=icon).type = 'MAGIC'

        icon = 'RADIOBUT_ON' if mask.type == 'NOISE' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Noise', icon=icon).type = 'NOISE'

        icon = 'RADIOBUT_ON' if mask.type == 'GABOR' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Gabor', icon=icon).type = 'GABOR'

        icon = 'RADIOBUT_ON' if mask.type == 'VORONOI' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Voronoi', icon=icon).type = 'VORONOI'

        icon = 'RADIOBUT_ON' if mask.type == 'WAVE' else 'RADIOBUT_OFF'
        col.operator('wm.m_replace_mask_type', text='Wave', icon=icon).type = 'WAVE'

        col.separator()

        # ===== GEOMETRY-BASED SECTION =====
        icon = 'RADIOBUT_ON' if mask.type == 'HEMI' else 'RADIOBUT_OFF'
        col.operator("wm.m_replace_mask_type", icon=icon, text='Fake Lighting').type = 'HEMI'

        col.separator()

        icon = 'RADIOBUT_ON' if mask.type == 'COLOR_ID' else 'RADIOBUT_OFF'
        col.operator("wm.m_replace_mask_type", icon=icon, text='Color ID').type = 'COLOR_ID'

        icon = 'RADIOBUT_ON' if mask.type == 'OBJECT_INDEX' else 'RADIOBUT_OFF'
        col.operator("wm.m_replace_mask_type", icon=icon, text='Object Index').type = 'OBJECT_INDEX'

        icon = 'RADIOBUT_ON' if mask.type == 'BACKFACE' else 'RADIOBUT_OFF'
        col.operator("wm.m_replace_mask_type", icon=icon, text='Backface').type = 'BACKFACE'

        icon = 'RADIOBUT_ON' if mask.type == 'AO' else 'RADIOBUT_OFF'
        col.operator("wm.m_replace_mask_type", icon=icon, text='Ambient Occlusion').type = 'AO'

        icon = 'RADIOBUT_ON' if mask.type == 'EDGE_DETECT' else 'RADIOBUT_OFF'
        col.operator("wm.m_replace_mask_type", icon=icon, text='Edge Detect').type = 'EDGE_DETECT'

        col.separator()

        # ===== MODIFIER MASKS SECTION =====
        icon = 'RADIOBUT_ON' if mask.type == 'MODIFIER' and mask.modifier_type == 'INVERT' else 'RADIOBUT_OFF'
        op = col.operator("wm.m_replace_mask_type", icon=icon, text='Invert Modifier')
        op.type = 'MODIFIER'
        op.modifier_type = 'INVERT'

        icon = 'RADIOBUT_ON' if mask.type == 'MODIFIER' and mask.modifier_type == 'RAMP' else 'RADIOBUT_OFF'
        op = col.operator("wm.m_replace_mask_type", icon=icon, text='Ramp Modifier')
        op.type = 'MODIFIER'
        op.modifier_type = 'RAMP'

        icon = 'RADIOBUT_ON' if mask.type == 'MODIFIER' and mask.modifier_type == 'CURVE' else 'RADIOBUT_OFF'
        op = col.operator("wm.m_replace_mask_type", icon=icon, text='Curve Modifier')
        op.type = 'MODIFIER'
        op.modifier_type = 'CURVE'


# Only register classes defined in this file
# Imported classes are registered by their source modules to avoid double registration
# (mask_operators_new.py, mask_operators_open.py)
classes = (
    MMoveLayerMask,
    MRemoveLayerMask,
    MOpenImageToReplaceMask,
    MReplaceMaskType,
    MFixEdgeDetectAO,
    MASKS_MT_MaskSourceMenu,
)