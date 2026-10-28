# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate Mask with AI: queue a generated grayscale mask for the active layer."""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from mixar.modules.common.i18n import rpt_
from ...core.element.get_elements import get_default_uv_name
from ...core.layer.ai_layer_mask import LOCATION_ITEMS, default_model, enqueue_layer_mask
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import get_active_object
from ...utils.common import is_object_work_with_uv
from ..ui_state import NO_BRUSH_MODEL, _get_brush_model_items


def _agent_target(object_name, layer_index):
    """(object, layer) the agent named: its paint stack's layer at ``layer_index``
    (-1 = the active layer), resolved the way the agent's layer tools resolve it."""
    from ...core.agent_tools.layer_params import _find_mpaint_node, _resolve_single_paint_object

    obj = _resolve_single_paint_object(object_name)
    node = _find_mpaint_node(obj)
    if node is None:
        raise ValueError(f"'{obj.name}' has no Mixar Paint material")
    mp = node.node_tree.mp
    index = layer_index if layer_index >= 0 else mp.active_layer_index
    if not 0 <= index < len(mp.layers):
        raise ValueError(f"Layer index {index} out of range")
    return obj, mp.layers[index]


def _active_layer(context):
    layer = getattr(context, "layer", None)
    if layer is not None:
        return layer
    node = get_active_mpaint_node()
    mp = node.node_tree.mp if node else None
    if mp is None or not (0 <= mp.active_layer_index < len(mp.layers)):
        return None
    return mp.layers[mp.active_layer_index]


class MGenerateLayerMask(Operator):
    """Generate a mask for the active layer from a description using AI"""
    bl_idname = "wm.m_generate_layer_mask"
    bl_label = "Generate Mask with AI"
    bl_description = "Describe where the layer should show; AI generates a grayscale mask for it"
    bl_options = {'REGISTER'}

    prompt: StringProperty(
        name="Describe",
        description="What the mask shows, e.g. rust streaks, moss patches, chipped paint",
        default="",
    )
    location: EnumProperty(name="Placement", items=LOCATION_ITEMS, default='ANY')
    model: EnumProperty(name="Model", items=_get_brush_model_items)
    # Agent targeting (hidden from the dialog): the object's paint stack and
    # layer index as get_paint_layer_stack reports them.
    object_name: StringProperty(name="Object", default="", options={'HIDDEN', 'SKIP_SAVE'})
    layer_index: IntProperty(name="Layer Index", default=-1, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        # The agent passes its own target; only the menu needs an active layer.
        return True

    def invoke(self, context, event):
        obj = get_active_object()
        if obj is None or obj.type != 'MESH' or _active_layer(context) is None:
            self.report({'WARNING'}, "Select a mesh with a paint layer first")
            return {'CANCELLED'}
        # A dynamic enum opens on item 0 (catalog sort order), or on the last
        # run's remembered pick (a list position, so stale once the catalog
        # changes); open on the catalog's default model instead, unless the
        # caller passed one. The default ghost=True keeps the remembered value
        # from counting as passed.
        if not self.properties.is_property_set("model"):
            model = default_model(item[0] for item in _get_brush_model_items(self, context))
            if model:
                self.model = model
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "prompt")
        col.prop(self, "location")
        col.prop(self, "model")

    def execute(self, context):
        from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

        prompt = self.prompt.strip()
        if not prompt:
            set_agent_gen_reason(context, "No description provided for the mask")
            self.report({'WARNING'}, "Describe the mask first")
            return {'CANCELLED'}

        if self.model == NO_BRUSH_MODEL:
            set_agent_gen_reason(context, "No mask generation model is available")
            self.report({'ERROR'}, "No mask generation model is available")
            return {'CANCELLED'}

        if self.object_name or self.layer_index >= 0:
            try:
                obj, layer = _agent_target(self.object_name, self.layer_index)
            except ValueError as exc:
                set_agent_gen_reason(context, str(exc))
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
        else:
            layer = _active_layer(context)
            obj = get_active_object()
        if layer is None or obj is None:
            set_agent_gen_reason(context, "No active paint layer")
            self.report({'ERROR'}, "Select a paint layer first")
            return {'CANCELLED'}
        if not is_object_work_with_uv(obj):
            set_agent_gen_reason(context, "The active object has no UV map")
            self.report({'ERROR'}, "The object needs a UV map for an image mask")
            return {'CANCELLED'}

        job = enqueue_layer_mask(
            layer=layer,
            uv_name=get_default_uv_name(obj, layer.id_data.mp),
            prompt=prompt,
            location=self.location,
            model=self.model,
        )
        if not job:
            set_agent_gen_reason(context, "This mask is already being generated")
            self.report({'WARNING'}, "This mask is already being generated")
            return {'CANCELLED'}

        self.report({'INFO'}, rpt_("Generating a mask for '{layer}'...").format(layer=layer.name))
        return {'FINISHED'}


classes = (MGenerateLayerMask,)
