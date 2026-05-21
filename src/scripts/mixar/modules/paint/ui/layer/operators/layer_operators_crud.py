# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer CRUD operators for creating and managing paint layers"""

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

from ....core.element.get_elements import get_default_uv_name
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import (
    get_active_object,
    get_operator_description,
    get_user_preferences,
)
from ....utils.common import get_layer_type_items_callback
from ....utils.constants import (
    hemi_space_items,
    image_resolution_items,
    interpolation_type_items,
    normal_blend_items,
    texcoord_type_items,
    vcol_data_type_items,
    vcol_domain_items,
)
from ....utils.statics import blend_type_items
from mixar.config.logging_config import get_logger

from ...image_atlas.image_atlas_utils import check_need_of_erasing_segments

logger = get_logger(__name__)


# -------------------------------------------------------------------------
# Wrapper functions with delayed imports to avoid circular imports
# -------------------------------------------------------------------------
def channel_items(self, context):
    """Wrapper for channel_items with delayed import."""
    from ..helpers.layer_ui_helpers import channel_items as _impl
    return _impl(self, context)


def get_normal_map_type_items(self, context):
    """Wrapper for get_normal_map_type_items with delayed import."""
    from ..helpers.layer_ui_helpers import get_normal_map_type_items as _impl
    return _impl(self, context)


def update_channel_idx_new_layer(self, context):
    """Wrapper for update_channel_idx_new_layer with delayed import."""
    from ..helpers.layer_ui_helpers import update_channel_idx_new_layer as _impl
    return _impl(self, context)


def update_new_layer_mask_uv_map(self, context):
    """Wrapper for update_new_layer_mask_uv_map with delayed import."""
    from ..helpers.layer_ui_helpers import update_new_layer_mask_uv_map as _impl
    return _impl(self, context)


def update_new_layer_uv_map(self, context):
    """Wrapper for update_new_layer_uv_map with delayed import."""
    from ..helpers.layer_ui_helpers import update_new_layer_uv_map as _impl
    return _impl(self, context)


class MNewLayer(bpy.types.Operator):
    bl_idname = "wm.m_new_layer"
    bl_label = "New Layer"
    bl_description = "New Layer"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(default="")

    type: EnumProperty(name="Layer Type", items=get_layer_type_items_callback)

    # For image layer
    width: IntProperty(name="Width", default=1024, min=1, max=16384)
    height: IntProperty(name="Height", default=1024, min=1, max=16384)
    hdr: BoolProperty(name="32 bit Float", default=False)

    interpolation: EnumProperty(
        name="Image Interpolation Type",
        description="Image interpolation type",
        items=interpolation_type_items,
        default="Linear",
    )

    texcoord_type: EnumProperty(
        name="Layer Coordinate Type",
        description="Layer Coordinate Type",
        items=texcoord_type_items,
        default="UV",
    )

    channel_idx: EnumProperty(
        name="Channel",
        description="Channel of new layer, can be changed later",
        items=channel_items,
        update=update_channel_idx_new_layer,
    )

    blend_type: EnumProperty(
        name="Blend",
        description="Blend type",
        items=blend_type_items,
    )

    normal_blend_type: EnumProperty(
        name="Normal Blend Type", items=normal_blend_items, default="MIX"
    )

    solid_color: FloatVectorProperty(
        name="Fill Color",
        size=3,
        subtype="COLOR",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )

    add_mask: BoolProperty(
        name="Add Mask", description="Add mask to new layer", default=False
    )

    mask_type: EnumProperty(
        name="Mask Type",
        description="Mask type",
        items=(
            ("IMAGE", "Image", "", "IMAGE_DATA", 0),
            ("VCOL", "Vertex Color", "", "GROUP_VCOL", 1),
            ("COLOR_ID", "Color ID", "", "COLOR", 2),
            ("EDGE_DETECT", "Edge Detect", "", "MESH_CUBE", 3),
        ),
        default="IMAGE",
    )

    mask_color: EnumProperty(
        name="Mask Color",
        description="Mask Color",
        items=(
            ("WHITE", "White (Full Opacity)", ""),
            ("BLACK", "Black (Full Transparency)", ""),
        ),
        default="BLACK",
    )

    mask_width: IntProperty(name="Mask Width", default=1024, min=1, max=4096)
    mask_height: IntProperty(name="Mask Height", default=1024, min=1, max=4096)

    mask_image_resolution: EnumProperty(
        name="Image Resolution", items=image_resolution_items, default="1024"
    )

    mask_use_custom_resolution: BoolProperty(
        name="Custom Resolution",
        description="Use custom Resolution to adjust the width and height individually",
        default=False,
    )

    mask_interpolation: EnumProperty(
        name="Mask Image Interpolation Type",
        description="Mask image interpolation type",
        items=interpolation_type_items,
        default="Linear",
    )

    mask_texcoord_type: EnumProperty(
        name="Mask Coordinate Type",
        description="Mask Coordinate Type",
        items=texcoord_type_items,
        default="UV",
    )

    mask_uv_name: StringProperty(default="", update=update_new_layer_mask_uv_map)
    mask_use_hdr: BoolProperty(name="32 bit Float", default=False)

    mask_color_id: FloatVectorProperty(
        name="Color ID",
        size=3,
        subtype="COLOR",
        default=(1.0, 0.0, 1.0),
        min=0.0,
        max=1.0,
    )

    mask_vcol_fill: BoolProperty(
        name="Fill Selected Geometry with Vertex Color / Color ID Mask",
        description="Fill selected geometry with vertex color or color ID mask",
        default=True,
    )

    mask_image_filepath: StringProperty(
        name="Mask Image Path",
        description="Path to mask image",
        default="",
        subtype="FILE_PATH",
        options={"SKIP_SAVE"},
    )

    mask_relative: BoolProperty(
        name="Relative Mask Path", default=True, description="Apply relative paths"
    )

    uv_map: StringProperty(default="", update=update_new_layer_uv_map)

    normal_map_type: EnumProperty(
        name="Normal Map Type",
        description="Normal map type of this layer",
        items=get_normal_map_type_items,
    )

    use_udim: BoolProperty(
        name="Use UDIM Tiles", description="Use UDIM Tiles", default=False
    )

    use_udim_for_mask: BoolProperty(
        name="Use UDIM Tiles for Mask",
        description="Use UDIM Tiles for Mask",
        default=False,
    )

    use_image_atlas: BoolProperty(
        name="Use Image Atlas", description="Use Image Atlas", default=False
    )

    use_image_atlas_for_mask: BoolProperty(
        name="Use Image Atlas for Mask",
        description="Use Image Atlas for Mask",
        default=False,
    )

    hemi_space: EnumProperty(
        name="Fake Lighting Space",
        description="Fake lighting space",
        items=hemi_space_items,
        default="WORLD",
    )

    hemi_use_prev_normal: BoolProperty(
        name="Use previous Normal",
        description="Take account previous Normal",
        default=True,
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

    mask_vcol_data_type: EnumProperty(
        name="Mask Vertex Color Data Type",
        description="Mask Vertex color data type",
        items=vcol_data_type_items,
        default="BYTE_COLOR",
    )

    mask_vcol_domain: EnumProperty(
        name="Mask Vertex Color Domain",
        description="Mask Vertex color domain",
        items=vcol_domain_items,
        default="CORNER",
    )

    use_divider_alpha: BoolProperty(
        name="Divide RGB by Alpha",
        description="Divide RGB by its alpha value (very recommended for vertex color layer)",
        default=False,
    )

    # For edge detection
    edge_detect_radius: FloatProperty(
        name="Detect Mask Radius",
        description="Edge detect radius",
        default=0.05,
        min=0.0,
        max=10.0,
    )

    mask_edge_detect_radius: FloatProperty(
        name="Edge Detect Mask Radius",
        description="Edge detect mask radius",
        default=0.05,
        min=0.0,
        max=10.0,
    )

    mask_use_prev_normal: BoolProperty(
        name="Use previous Normal for Mask",
        description="Take account previous Normal for mask",
        default=True,
    )

    # For procedural materials
    procedural_material_id: StringProperty(
        name="Procedural Material ID",
        description="ID of the procedural material to use",
        default="",
    )

    ao_distance: FloatProperty(
        name="Ambient Occlusion Distance",
        description="Ambient occlusion distance",
        default=1.0,
        min=0.0,
        max=10.0,
    )

    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    image_resolution: EnumProperty(
        name="Image Resolution", items=image_resolution_items, default="1024"
    )

    use_custom_resolution: BoolProperty(
        name="Custom Resolution",
        description="Use custom Resolution to adjust the width and height individually",
        default=False,
    )

    default_layer: BoolProperty(
        name="Default Layer",
        description="Create a default layer",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node()

    @classmethod
    def description(cls, context, properties):
        return get_operator_description(cls)

    def invoke(self, context, event):
        from .layer_operators_crud_helpers import invoke_new_layer
        return invoke_new_layer(self, context, event)

    def check(self, context):
        mpup = get_user_preferences()

        if not self.use_custom_resolution:
            self.width = int(self.image_resolution)
            self.height = int(self.image_resolution)

        if not self.mask_use_custom_resolution:
            self.mask_width = int(self.mask_image_resolution)
            self.mask_height = int(self.mask_image_resolution)

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

        if self.use_image_atlas_for_mask:
            if self.mask_use_hdr:
                mask_max_size = mpup.hdr_image_atlas_size
            else:
                mask_max_size = mpup.image_atlas_size
            if self.mask_width > mask_max_size:
                self.mask_width = mask_max_size
            if self.mask_height > mask_max_size:
                self.mask_height = mask_max_size

        # Init mask uv name
        if self.add_mask and self.mask_uv_name == "":
            obj = get_active_object()
            uv_name = get_default_uv_name(obj, self.mp)
            self.mask_uv_name = uv_name

        return True

    def get_to_be_cleared_image_atlas(self, context, mp):
        """Get image atlas segments that need to be cleared for this operation."""
        if self.type == "IMAGE" and not self.add_mask and self.use_image_atlas:
            return check_need_of_erasing_segments(
                mp, "TRANSPARENT", self.width, self.height, self.hdr
            )
        if (
            self.add_mask
            and self.mask_type == "IMAGE"
            and self.use_image_atlas_for_mask
        ):
            return check_need_of_erasing_segments(
                mp, self.mask_color, self.mask_width, self.mask_height, self.hdr
            )
        return None

    def draw(self, context):
        from .layer_operators_crud_ui import draw_new_layer_ui
        draw_new_layer_ui(self, context)

    def execute(self, context):
        # Save all modified images before creating new layer
        if any(img.is_dirty for img in bpy.data.images):
            try:
                bpy.ops.image.save_all_modified()
            except RuntimeError as e:
                self.report({"WARNING"}, f"Could not save modified images before creating layer: {e}")

        from .layer_operators_crud_helpers import execute_new_layer
        return execute_new_layer(self, context)


class MNewFillLayer(bpy.types.Operator):
    """Add a new Fill Layer with uniform color fill"""
    bl_idname = "wm.m_new_fill_layer"
    bl_label = "Add Fill Layer"
    bl_description = "Add a new Fill Layer with uniform color that affects all channels"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return bpy.ops.wm.m_new_layer('INVOKE_DEFAULT', type='COLOR', add_mask=False)


class MNewPaintLayer(bpy.types.Operator):
    """Add a new Paint Layer for image-based painting"""
    bl_idname = "wm.m_new_paint_layer"
    bl_label = "Add Paint Layer"
    bl_description = "Add a new Paint Layer for texture painting with brushes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return bpy.ops.wm.m_new_layer('INVOKE_DEFAULT', type='IMAGE', add_mask=False)


# Classes for registration
classes = (
    MNewLayer,
    MNewFillLayer,
    MNewPaintLayer,
)
