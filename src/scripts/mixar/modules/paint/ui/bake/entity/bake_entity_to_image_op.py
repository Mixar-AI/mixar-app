# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake entity to image operator - extracted from bake_to_layer_operators.py."""

import time

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from ....core.element.update_image import update_image_editor_image
from ....core.element.update_uv import refresh_temp_uv, set_uv_neighbor_resolution
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.layer_utils import (
    get_layer_index,
    get_root_height_channel,
    get_uv_layers,
)
from ....core.node.check_nodes import check_mask_mix_nodes
from ....core.node.get_nodes import get_layer_source, get_mask_source
from ....core.node.node_utils import get_active_mpaint_node, remove_node
from ....core.subtree.check_subtree import check_mask_source_tree
from ....core.subtree.get_subtree import get_mask_tree, get_source_tree, get_tree
from ...mask.mask_creation import add_new_mask
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_object_parent_layer_collections,
    get_operator_description,
    get_scene_objects,
    get_unique_name,
    get_user_preferences,
    get_viewport_context,
    set_active_object,
    set_object_hide,
    set_object_select,
)
from ....utils.common import get_addon_title, get_channel_index, split_layout
from ....utils.constants import (
    TEMP_UV,
    bake_type_items,
    bake_type_labels,
    bake_type_suffixes,
    interpolation_type_items,
    layer_type_labels,
    mask_type_labels,
    normal_blend_items,
)
from ....utils.statics import blend_type_items
from ..utils.bake_operators_helper import bake_to_entity, rebake_baked_images
from ..layer.bake_to_layer_operators_helper import (
    get_bake_properties_from_self,
    update_bake_to_layer_uv_map,
)
from ...image_atlas.image_atlas_utils import set_segment_mapping
from ...udim.udim_operators_helper import remove_udim_atlas_segment_by_name
from ...udim.udim_utils import get_udim_segment_tilenums
from ..utils.bake_common import BaseBakeOperator, bake_entity_as_image

# Import helper modules
from .bake_entity_to_image_invoke import invoke_bake_entity_to_image
from .bake_entity_to_image_ui import draw_bake_entity_to_image_ui


class MBakeEntityToImage(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_bake_entity_to_image"
    bl_label = "Bake Layer/Mask To Image"
    bl_description = "Bake Layer/Mask to an image"
    bl_options = {"UNDO"}

    name: StringProperty(default="")

    uv_map: StringProperty(default="", update=update_bake_to_layer_uv_map)
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    hdr: BoolProperty(name="32 bit Float", default=False)

    fxaa: BoolProperty(
        name="Use FXAA",
        description="Use FXAA to baked image (doesn't work with float images)",
        default=True,
    )

    denoise: BoolProperty(
        name="Use Denoise", description="Use Denoise on baked images", default=False
    )

    use_image_atlas: BoolProperty(
        name="Use Image Atlas", description="Use Image Atlas", default=False
    )

    blur_type: EnumProperty(
        name="Blur Type",
        description="Blur type for the baked image",
        items=(
            (
                "NOISE",
                "Noise",
                "Noisy and need more samples but has matching value to the blur vector option",
            ),
            ("FLAT", "Flat", "Flat blur"),
            ("TENT", "Tent", "Tent blur"),
            ("QUAD", "Quadratic", "Quadratic blur"),
            ("CUBIC", "Cubic", "Cubic blur"),
            ("GAUSS", "Gaussian", "Gausssian blur"),
            ("FAST_GAUSS", "Fast Gaussian", "Fast gausssian blur"),
            ("CATROM", "Catrom", "Catrom blur"),
            ("MITCH", "Mitch", "Mitch blur"),
        ),
        default="GAUSS",
    )

    blur: BoolProperty(
        name="Use Blur", description="Use blur to the baked image", default=False
    )

    blur_factor: FloatProperty(
        name="Blur Factor",
        description="Blur factor to the baked image",
        default=1.0,
        min=0.0,
        max=100.0,
    )

    blur_size: FloatProperty(
        name="Blur Size",
        description="Blur size (in pixels) to the baked image",
        default=10.0,
        min=0.0,
    )

    duplicate_entity: BoolProperty(
        name="Duplicate Entity", description="Duplicate entity", default=False
    )

    disable_current: BoolProperty(
        name="Disable current layer/mask",
        description="Disable current layer/mask",
        default=True,
    )

    use_udim: BoolProperty(
        name="Use UDIM Tiles", description="Use UDIM Tiles", default=False
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    @classmethod
    def description(self, context, properties):
        return get_operator_description(self)

    def invoke(self, context, event):
        return invoke_bake_entity_to_image(self, context, event)

    def check(self, context):
        self.check_operator(context)
        mpup = get_user_preferences()

        # New image cannot use more pixels than the image atlas
        if self.use_image_atlas:
            if self.hdr:
                max_size = mpup.hdr_image_atlas_size
            else:
                max_size = mpup.image_atlas_size
            if self.width > max_size:
                self.width = max_size
            if self.height > max_size:
                self.height = max_size

        return True

    def draw(self, context):
        draw_bake_entity_to_image_ui(self, context)

    def execute(self, context):
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        if not self.layer:
            self.report({"ERROR"}, "Invalid context!")
            return {"CANCELLED"}

        if self.uv_map == "":
            self.report({"ERROR"}, "UV Map cannot be empty!")
            return {"CANCELLED"}

        T = time.time()
        node = get_active_mpaint_node()
        self.mp = mp = node.node_tree.mp
        tree = node.node_tree
        layer_tree = get_tree(self.layer)

        # Entity checking
        entity = self.mask if self.mask else self.layer
        entity_label = (
            mask_type_labels[entity.type]
            if self.mask
            else layer_type_labels[entity.type]
        )

        # Get bake properties
        bprops = get_bake_properties_from_self(self)

        # Bake entity to image
        rdict = bake_entity_as_image(
            entity, bprops, set_image_to_entity=not self.duplicate_entity
        )

        if rdict["message"] != "":
            self.report({"ERROR"}, rdict["message"])
            return {"CANCELLED"}

        image = rdict["image"]
        segment = rdict["segment"]

        # Duplicate entity
        if self.duplicate_entity:
            self._handle_duplicate_entity(image, segment, layer_tree)

        # Make current entity active to update image
        if self.mask:
            self.mask.active_edit = True
        elif get_layer_index(self.layer) == mp.active_layer_index:
            mp.active_layer_index = mp.active_layer_index

        reconnect_layer_nodes(self.layer)
        rearrange_layer_nodes(self.layer)

        reconnect_mp_nodes(node.node_tree)
        rearrange_mp_nodes(node.node_tree)

        # Expand entity source to show rebake button
        mpui = context.window_manager.mpui
        if self.mask and not self.duplicate_entity:
            self.mask.expand_content = True
            self.mask.expand_source = True
        mpui.need_update = True

        # Update texture slot to the newly baked image if mask is active
        if self.mask and self.mask.active_edit and image:
            from ....utils.blender_commons import set_image_paint_canvas
            set_image_paint_canvas(image)

        if image:
            self.report(
                {"INFO"},
                "Baking "
                + entity_label
                + " is done in "
                + "{:0.2f}".format(time.time() - T)
                + " seconds!",
            )

        return {"FINISHED"}

    def _handle_duplicate_entity(self, image, segment, layer_tree):
        """Handle duplicating the entity after baking.

        Args:
            image: The baked image
            segment: Image segment or None
            layer_tree: Layer node tree
        """
        if self.mask:
            # Disable source mask
            if self.mask and self.disable_current:
                self.mask.enable = False

            # New entity name
            new_entity_name = (
                get_unique_name(self.name, self.entities)
                if self.use_image_atlas
                else image.name
            )

            # Create new mask
            mask = add_new_mask(
                self.layer,
                new_entity_name,
                "IMAGE",
                "UV",
                self.uv_map,
                image,
                "",
                segment,
            )

            # Set mask properties
            mask.intensity_value = self.mask.intensity_value
            mask.blend_type = self.mask.blend_type
            for i, c in enumerate(self.mask.channels):
                mask.channels[i].enable = c.enable

            # Reorder index
            target_index = min(self.index + 1, len(self.layer.masks) - 1)
            self.layer.masks.move(len(self.layer.masks) - 1, target_index)
            check_mask_mix_nodes(self.layer, layer_tree)
            check_mask_source_tree(self.layer)
            mask = self.layer.masks[target_index]

            if segment:
                set_segment_mapping(mask, segment, image)
                mask.segment_name = segment.name

            # Refresh uv
            refresh_temp_uv(get_active_object(), mask)

            # Refresh Neighbor UV resolution
            set_uv_neighbor_resolution(mask)

            # Make new mask active
            self.mask = mask
        else:
            # TODO: Duplicate layer as image(s)
            pass


# =============================================================================
# Re-exports for backward compatibility
# =============================================================================

# Re-export UI drawing functions
from .bake_entity_to_image_ui import (
    draw_bake_entity_to_image_ui,
)

# Re-export invoke functions
from .bake_entity_to_image_invoke import (
    invoke_bake_entity_to_image,
)


classes = (MBakeEntityToImage,)
