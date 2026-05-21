# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""New Layer Mask operator.

This module contains the MNewLayerMask operator which handles creating
new masks for layers with various types including image, vertex color,
color ID, and procedural masks.
"""

import random

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

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.check_elements import is_colorid_already_being_used
from ...core.element.get_elements import get_default_uv_name
from ...core.layer.layer_utils import get_active_layer, get_height_channel
from ...core.layer.mappings import is_mapping_possible
from ...core.modifier.mask_modifier import mask_modifier_type_items
from ...core.node.get_nodes import get_layer_source
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_object,
    get_operator_description,
    get_user_preferences,
)
from ...utils.common import is_object_work_with_uv
from ...utils.constants import (
    COLORID_TOLERANCE,
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
from ..mask.mask_operators_helper import get_new_mask_name, update_new_mask_uv_map

# Import draw helpers
from .mask_operators_new_draw import (
    draw_image_atlas_warning,
    draw_mask_properties_section,
    draw_mask_setup_section,
)

# Import execute helpers
from .mask_operators_new_execute import (
    add_new_mask,
    check_duplicate_name,
    clear_unused_segments,
    create_mask_image,
    finalize_mask_creation,
    get_to_be_cleared_image_atlas,
    remove_mask,
    setup_color_id_mask,
    setup_vertex_color_mask,
)


class MNewLayerMask(bpy.types.Operator):
    bl_idname = "wm.m_new_layer_mask"
    bl_label = "New Layer Mask"
    bl_description = "New Layer Mask"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(default="")

    type: EnumProperty(name="Mask Type", items=mask_type_items, default="IMAGE")

    modifier_type: EnumProperty(
        name="Mask Modifier Type", items=mask_modifier_type_items, default="INVERT"
    )

    width: IntProperty(name="Width", default=1024, min=1, max=16384)
    height: IntProperty(name="Height", default=1024, min=1, max=16384)

    interpolation: EnumProperty(
        name="Image Interpolation Type",
        description="image interpolation type",
        items=interpolation_type_items,
        default="Linear",
    )

    blend_type: EnumProperty(
        name="Blend", description="Blend type", items=mask_blend_type_items, default=3
    )

    color_option: EnumProperty(
        name="Color Option",
        description="Color Option",
        items=(
            ("WHITE", "White (Full Opacity)", ""),
            ("BLACK", "Black (Full Transparency)", ""),
        ),
        default="WHITE",
    )

    color_id: FloatVectorProperty(
        name="Color ID",
        size=3,
        subtype="COLOR",
        default=(1.0, 0.0, 1.0),
        min=0.0,
        max=1.0,
    )

    vcol_fill: BoolProperty(
        name="Fill Selected Geometry with Vertex Color / Color ID",
        description="Fill selected geometry with vertex color / color ID",
        default=True,
    )

    hdr: BoolProperty(name="32 bit Float", default=False)

    texcoord_type: EnumProperty(
        name="Mask Coordinate Type",
        description="Mask Coordinate Type",
        items=mask_texcoord_type_items,
        default="UV",
    )

    uv_name: StringProperty(default="", update=update_new_mask_uv_map)
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    use_udim: BoolProperty(
        name="Use UDIM Tiles", description="Use UDIM Tiles", default=False
    )

    use_image_atlas: BoolProperty(
        name="Use Image Atlas", description="Use Image Atlas", default=False
    )

    # For fake lighting
    hemi_space: EnumProperty(
        name="Fake Lighting Space",
        description="Fake lighting space",
        items=hemi_space_items,
        default="WORLD",
    )

    hemi_use_prev_normal: BoolProperty(
        name="Use previous Normal",
        description="Take previous Normal into the account",
        default=True,
    )

    # For object index
    object_index: IntProperty(
        name="Object Index", description="Object Pass Index", default=0, min=0
    )

    edge_detect_radius: FloatProperty(
        name="Detect Mask Radius",
        description="Edge detect radius",
        default=0.05,
        min=0.0,
        max=10.0,
    )

    ao_distance: FloatProperty(
        name="Ambient Occlusion Distance",
        description="Ambient occlusion distance",
        default=1.0,
        min=0.0,
        max=10.0,
    )

    vcol_data_type: EnumProperty(
        name="Vertex Color Data Type",
        description="Vertex color data type",
        items=vcol_data_type_items,
        default="BYTE_COLOR",
    )

    vcol_domain: EnumProperty(
        name="Vertex Color Domain",
        description="Vertex color domain",
        items=vcol_domain_items,
        default="CORNER",
    )

    image_resolution: EnumProperty(
        name="Image Resolution", items=image_resolution_items, default="1024"
    )

    use_custom_resolution: BoolProperty(
        name="Custom Resolution",
        default=False,
        description="Use custom Resolution to adjust the width and height individually",
    )

    @classmethod
    def poll(cls, context):
        return True

    @classmethod
    def description(self, context, properties):
        return get_operator_description(self)

    def _get_to_be_cleared_image_atlas(self, context, mp):
        """Check if an image atlas needs to be cleared for reuse."""
        return get_to_be_cleared_image_atlas(
            self.type, self.use_image_atlas, mp,
            self.color_option, self.width, self.height, self.hdr
        )

    def invoke(self, context, event):
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        obj = get_active_object()
        layer = get_active_layer(mp)

        self.auto_cancel = False
        if not layer:
            self.auto_cancel = True
            return self.execute(context)

        mp = layer.id_data.mp
        mpup = get_user_preferences()

        self.name = get_new_mask_name(obj, layer, self.type, self.modifier_type)

        # Use user preference default image size
        if mpup.default_image_resolution == "CUSTOM":
            self.use_custom_resolution = True
            self.width = self.height = mpup.default_new_image_size
        elif mpup.default_image_resolution != "DEFAULT":
            self.image_resolution = mpup.default_image_resolution

        if self.type == "COLOR_ID":
            # Check if color id already being used
            while True:
                # Use color id tolerance value as lowest value to avoid pure black color
                self.color_id = (
                    random.uniform(COLORID_TOLERANCE, 1.0),
                    random.uniform(COLORID_TOLERANCE, 1.0),
                    random.uniform(COLORID_TOLERANCE, 1.0),
                )
                if not is_colorid_already_being_used(mp, self.color_id):
                    break

        # Disable use previous normal for edge detect since it has very little effect
        if self.type == "EDGE_DETECT":
            self.hemi_use_prev_normal = False

        # Make sure decal is off when adding non mappable mask
        if not is_mapping_possible(self.type) and self.texcoord_type == "Decal":
            self.texcoord_type = "UV"

        if not is_object_work_with_uv(obj):
            self.texcoord_type = "Generated"

        if obj.type == "MESH" and len(obj.data.uv_layers) > 0:
            self.uv_name = get_default_uv_name(obj, mp)

            # UV Map collections update
            self.uv_map_coll.clear()
            for uv in obj.data.uv_layers:
                if not uv.name.startswith(TEMP_UV):
                    self.uv_map_coll.add().name = uv.name

        # The default blend type for mask is multiply
        if self.type in {"MODIFIER"}:
            self.blend_type = "MIX"
        else:
            self.blend_type = "MULTIPLY"

        # Check if there's height channel and use cubic interpolation if there is one
        height_ch = get_height_channel(layer)
        if height_ch and height_ch.enable and self.type == "IMAGE":
            self.interpolation = "Cubic"
        elif layer.type == "IMAGE":
            source = get_layer_source(layer)
            if source and source.image:
                self.interpolation = source.interpolation

        # Always show dialog for mask creation to let user choose mask type
        # (skip_property_popups preference should not apply here as mask type
        # selection is critical and using cached values causes confusion)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        mpup = get_user_preferences()

        if not self.use_custom_resolution:
            self.height = self.width = int(self.image_resolution)

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
        obj = get_active_object()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # Draw mask setup section
        draw_mask_setup_section(main_col, self)

        main_col.separator(factor=0.8)

        # Draw mask properties section
        draw_mask_properties_section(main_col, self, obj)

        # Draw image atlas warning if needed
        draw_image_atlas_warning(
            main_col,
            self._get_to_be_cleared_image_atlas(context, mp)
        )

    def execute(self, context):
        if hasattr(self, "auto_cancel") and self.auto_cancel:
            return {"CANCELLED"}

        # Save all modified images before creating new mask
        if any(img.is_dirty for img in bpy.data.images):
            try:
                bpy.ops.image.save_all_modified()
            except RuntimeError as e:
                self.report({"WARNING"}, f"Could not save modified images before creating mask: {e}")

        obj = get_active_object()
        mat = obj.active_material
        mpui = context.window_manager.mpui
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer = get_active_layer(mp)

        # Check if object is not a mesh
        if self.type == "VCOL" and obj.type != "MESH":
            self.report({"ERROR"}, "Vertex color mask only works with mesh object!")
            return {"CANCELLED"}

        # Clearing unused image atlas segments
        img_atlas = self._get_to_be_cleared_image_atlas(context, mp)
        if img_atlas:
            clear_unused_segments(img_atlas.yia)

        # Check for duplicate names
        has_duplicate, duplicate_type = check_duplicate_name(
            self.type, self.name, layer, obj
        )
        if has_duplicate:
            if duplicate_type == "IMAGE":
                self.report(
                    {"ERROR"}, "Image named '" + self.name + "' is already available!"
                )
                return {"CANCELLED"}
            elif duplicate_type == "VCOL":
                self.report(
                    {"ERROR"},
                    "Vertex Color named '" + self.name + "' is already available!",
                )
                return {"CANCELLED"}
            elif self.options.is_repeat:
                # Get the mask with same name and remove it before re-adding
                same_name_mask = [m for m in layer.masks if m.name == self.name][0]
                remove_mask(layer, same_name_mask, obj)
            else:
                self.report(
                    {"ERROR"}, "Mask named '" + self.name + "' is already available!"
                )
                return {"CANCELLED"}

        img = None
        vcol_name = ""
        segment = None

        # New image
        if self.type == "IMAGE":
            img, segment = create_mask_image(
                self.name, self.width, self.height, self.color_option,
                self.hdr, self.use_udim, self.use_image_atlas,
                mat, self.uv_name, mp
            )

        # New vertex color
        elif self.type == "VCOL":
            vcol_name = setup_vertex_color_mask(
                self.name, self.color_option, self.vcol_data_type, self.vcol_domain,
                self.vcol_fill, obj, mat
            )

        # Color ID
        elif self.type == "COLOR_ID":
            setup_color_id_mask(self.color_id, self.vcol_fill, obj, mat)

        # Voronoi and noise mask will use grayscale value by default
        source_input = "RGB" if self.type not in {"VORONOI", "NOISE"} else "ALPHA"

        # Add new mask
        mask = add_new_mask(
            layer,
            self.name,
            self.type,
            self.texcoord_type,
            self.uv_name,
            img,
            vcol_name,
            segment,
            self.object_index,
            self.blend_type,
            self.hemi_space,
            self.hemi_use_prev_normal,
            self.color_id,
            source_input=source_input,
            edge_detect_radius=self.edge_detect_radius,
            modifier_type=self.modifier_type,
            interpolation=self.interpolation,
            ao_distance=self.ao_distance,
        )

        # Finalize mask creation
        finalize_mask_creation(mask, self.type, layer, mpui)

        return {"FINISHED"}


# Classes for auto-registration by bootstrap
classes = (MNewLayerMask,)
