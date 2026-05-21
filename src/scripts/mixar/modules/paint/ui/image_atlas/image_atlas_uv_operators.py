# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for UV manipulation in image atlas context."""

import bpy

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.element.get_elements import get_relevant_uv
from ...core.element.update_image import get_active_image_and_stuffs, update_image_editor_image
from ...core.element.update_uv import refresh_temp_uv
from ...core.layer.layer_utils import get_uv_layers
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...utils.blender_commons import get_active_material, get_active_object
from ...utils.constants import TEMP_UV


class MRefreshTransformedLayerUV(bpy.types.Operator):
    """Operator to refresh layer UV with custom transformation."""

    bl_idname = "wm.m_refresh_transformed_uv"
    bl_label = "Refresh Layer UV with Custom Transformation"
    bl_description = "Refresh layer UV with custom transformation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return hasattr(context, "layer")

    def execute(self, context):

        obj = get_active_object()
        layer = context.layer
        mp = layer.id_data.mp
        mpui = context.window_manager.mpui

        uv_layers = get_uv_layers(obj)

        image, uv_name, src_of_img, entity, mapping, vcol = get_active_image_and_stuffs(
            obj, mp
        )
        if image:
            refresh_temp_uv(obj, src_of_img)
            update_image_editor_image(context, image)
            context.scene.tool_settings.image_paint.canvas = image
        else:
            uv_name = get_relevant_uv(obj, mp)
            if uv_name != "":
                uv = uv_layers.get(uv_name)
                if uv:
                    uv_layers.active = uv

        mp.need_temp_uv_refresh = False

        return {"FINISHED"}


class MBackToOriginalUV(bpy.types.Operator):
    """Operator to return to original UV when transformed UV is detected."""

    bl_idname = "wm.m_back_to_original_uv"
    bl_label = "Back to Original UV"
    bl_description = "Transformed UV detected, your changes will be lost if you edit on this UV.\nClick this button to go back to original UV"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return hasattr(context, "layer")

    def execute(self, context):

        obj = get_active_object()
        mat = get_active_material()
        objs = get_all_objects_with_same_materials(mat, selected_only=True)
        layer = context.layer
        mp = layer.id_data.mp
        mpui = context.window_manager.mpui

        # Get active image
        image, uv_name, src_of_img, entity, mapping, vcol = get_active_image_and_stuffs(
            obj, mp
        )

        if not src_of_img:
            try:
                src_of_img = mp.layers[mp.active_layer_index]
            except Exception as e:
                logger.error(e)
                return {"CANCELLED"}

        for ob in objs:
            uv_layers = get_uv_layers(ob)

            for uv in uv_layers:
                if uv.name == uv_name:

                    if uv_layers.active != uv_layers.get(uv_name):
                        uv_layers.active = uv_layers.get(uv_name)

                if uv.name == TEMP_UV:
                    uv_layers.remove(uv)
        # Hide active image
        if image:
            update_image_editor_image(context, None)
            context.scene.tool_settings.image_paint.canvas = None

        # mp.need_temp_uv_refresh = True

        return {"FINISHED"}


# Classes to be registered
classes = (
    MRefreshTransformedLayerUV,
    MBackToOriginalUV,
)
