# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake to layer operator - main operator class."""

import bpy

from ....core.element.update_image import update_image_editor_image
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_active_object, get_operator_description, get_user_preferences
from ....utils.constants import bake_type_labels
from ..utils.bake_common import BaseBakeOperator
from ..utils.bake_operators_helper import bake_to_entity
from .bake_to_layer_invoke import invoke_bake_to_layer
from .bake_to_layer_operators_helper import get_bake_properties_from_self
from .bake_to_layer_properties import BakeToLayerProperties
from .bake_to_layer_ui import draw_bake_to_layer_ui


class MBakeToLayer(bpy.types.Operator, BaseBakeOperator, BakeToLayerProperties):
    """Operator to bake various maps as layer or mask."""

    bl_idname = "wm.m_bake_to_layer"
    bl_label = "Bake To Layer"
    bl_description = "Bake something as layer/mask"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    @classmethod
    def description(cls, context, properties):
        return get_operator_description(cls)

    def invoke(self, context, event):
        return invoke_bake_to_layer(self, context, event)

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
        draw_bake_to_layer_ui(self, context)

    def execute(self, context):
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        # Disable any active preview mode before starting a new bake
        # This prevents conflicts when baking a new map while another map's preview is active
        if mp.layer_preview_mode:
            # Find and disable the layer that's currently being previewed
            if mp.active_layer_index >= 0 and mp.active_layer_index < len(mp.layers):
                layer = mp.layers[mp.active_layer_index]
                layer.enable = False  # Disable the layer so it doesn't affect final material
            mp.layer_preview_mode = False

        if (
            self.overwrite_choice or self.overwrite_current
        ) and self.overwrite_name == "":
            self.report({"ERROR"}, "Overwrite layer/mask cannot be empty!")
            return {"CANCELLED"}

        # Get overwrite image
        overwrite_img = None
        segment = None
        if (
            self.overwrite_choice or self.overwrite_current
        ) and self.overwrite_image_name != "":
            overwrite_img = bpy.data.images.get(self.overwrite_image_name)

            if overwrite_img.yia.is_image_atlas:
                segment = overwrite_img.yia.segments.get(self.overwrite_segment_name)
            elif overwrite_img.yua.is_udim_atlas:
                segment = overwrite_img.yua.segments.get(self.overwrite_segment_name)

        # Get bake properties
        bprops = get_bake_properties_from_self(self)

        rdict = bake_to_entity(bprops, overwrite_img, segment)

        if rdict["message"] != "":
            self.report({"ERROR"}, rdict["message"])
            return {"CANCELLED"}

        active_id = rdict["active_id"]
        image = rdict["image"]

        # Refresh active index (only when not overwriting current entity)
        if active_id is not None and not self.overwrite_current:
            mp.active_layer_index = active_id
        elif image:
            update_image_editor_image(context, image)

        # Expand image source to show rebake button
        mpui = context.window_manager.mpui
        if hasattr(mpui, 'layer_ui'):
            if self.target_type == "MASK":
                mpui.layer_ui.expand_masks = True
            else:
                mpui.layer_ui.expand_content = True
                mpui.layer_ui.expand_source = True
        mpui.need_update = True

        if image:
            self.report(
                {"INFO"},
                "Baking "
                + bake_type_labels[self.type]
                + " is done in "
                + "{:0.2f}".format(rdict["time_elapsed"])
                + " seconds!",
            )

        return {"FINISHED"}


classes = (MBakeToLayer,)
