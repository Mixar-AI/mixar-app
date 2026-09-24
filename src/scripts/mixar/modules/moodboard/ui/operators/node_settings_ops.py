# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared model and parameter editor for every inference card."""

import math

import bpy
from bpy.types import Operator

from mixar.modules.common.generation_params.core.bounds import integer_window
from mixar.modules.moodboard.core.parameter_help import parameter_help, parameter_specs

from mixar.modules.moodboard.constants import GRAPH_NODE_ID_MAXLEN
from mixar.modules.moodboard.core.canvas_context import (
    is_moodboard_context,
    redraw_moodboard_canvases,
)
from mixar.modules.moodboard.ui.sidebar_ui_helpers import (
    draw_dropdown,
    draw_input,
    draw_section_box,
    draw_toggle,
)


def _popup_node(context, node_id):
    """Never substitute the active selection for the popup's owning card."""
    from mixar.modules.moodboard.core.node_graph import action_node_by_id

    scene = getattr(context, "scene", None)
    return action_node_by_id(scene, node_id) if scene and node_id else None


def _clamp_numeric_settings(node):
    """Native number fields share RNA; the catalog owns each field's range.

    Popup ``check`` runs after a property edit, outside drawing. As with the
    canvas's manual numeric buttons, typed values settle inside the catalog
    bounds. Do not use a slider backed by the shared unbounded RNA range.
    """
    if node.state in {'QUEUED', 'RUNNING'}:
        return
    for parameter in node.parameters:
        kind = parameter.parameter_type
        if not parameter.visible or kind not in {'INTEGER', 'FLOAT'}:
            continue
        low, high = parameter.minimum, parameter.maximum
        if kind == 'INTEGER':
            # Same ceiling as the canvas. minimum/maximum are C floats, so
            # ceil() of a rounded bound can sit outside the int setter's range.
            window = integer_window(low, high)
            if window is None:
                continue
            low, high = window
            value = parameter.value_integer
            bounded = max(low, min(high, value))
            if bounded != value:
                parameter.value_integer = bounded
        else:
            if not math.isfinite(low) or not math.isfinite(high) or low > high:
                continue
            value = parameter.value_float
            bounded = max(low, min(high, value))
            if bounded != value:
                parameter.value_float = bounded


def _draw_parameter(layout, parameter, spec=None):
    label = parameter.label or parameter.name.replace('_', ' ').title()
    kind = parameter.parameter_type
    field = layout.column(align=True)
    caption = field.row(align=True)
    if kind == 'BOOLEAN':
        draw_toggle(caption, parameter, 'value_boolean', text=label)
    else:
        caption.label(text=label)
    info = caption.operator('mixie.moodboard_parameter_info', text='', icon='INFO', emboss=False)
    info.details = parameter_help(parameter, spec)
    if kind == 'BOOLEAN':
        return
    elif kind == 'ENUM':
        draw_dropdown(field, parameter, 'value_enum', text="")
    elif kind in {'INTEGER', 'FLOAT'}:
        field.prop(parameter, 'value_integer' if kind == 'INTEGER' else 'value_float', text="")
        if hasattr(field, 'mixar_style'):
            field.mixar_style(component='NUMBER')
    else:
        draw_input(field, parameter, 'value_string', text="")


def _draw_settings(layout, node, scene=None):
    if hasattr(layout, 'mixar_surface'):
        layout = layout.mixar_surface(theme='ZEN')
    layout.use_property_split = False
    layout.use_property_decorate = False
    layout.label(text="Node Settings", icon='PREFERENCES')
    running = node.state in {'QUEUED', 'RUNNING'}
    if running:
        layout.label(text="Settings are locked while generating", icon='LOCKED')
    # Assemble has no catalog model: its settings are per-part attachment rows.
    if scene is not None and node.action_type == 'ASSEMBLE':
        from ..assemble_node_drawer import draw_assemble_node

        draw_assemble_node(layout, scene, node)
        return

    settings = draw_section_box(layout)
    settings.enabled = not running
    if node.show_mode:
        settings.label(text="Mode")
        draw_dropdown(settings, node, 'service_key', text="")
    settings.label(text="Model")
    draw_dropdown(settings, node, 'model', text="")
    specs = parameter_specs(node)
    for parameter in node.parameters:
        if parameter.visible:
            _draw_parameter(settings, parameter, specs.get(parameter.name))

    if scene is not None and node.action_type == 'CHARACTER_PARTS':
        from ..character_parts_node_drawer import draw_character_parts_node

        components = layout.column()
        components.enabled = not running
        draw_character_parts_node(components, scene, node)

    actions = layout.column(align=True)
    actions.enabled = not running
    if (node.preview_image or node.preview_object) and node.state in {
        'SUCCESS', 'FAILED', 'CANCELLED'
    }:
        edit = actions.row()
        op = edit.operator('mixie.moodboard_run_action_node', text="Edit & Run Again")
        op.node_id = node.node_id
        op.edit_before_run = True
        if hasattr(edit, 'mixar_style'):
            edit.mixar_style(component='ACTION', variant='SECONDARY')
    reset = actions.row()
    op = reset.operator('mixie.moodboard_reset_node_params', text="Reset Settings")
    op.node_id = node.node_id
    if hasattr(reset, 'mixar_style'):
        reset.mixar_style(component='ACTION', variant='GHOST')


class MIXIE_OT_moodboard_node_settings(Operator):
    bl_idname = "mixie.moodboard_node_settings"
    bl_label = "Node Settings"
    bl_description = "Edit this node's model and generation settings"

    node_id: bpy.props.StringProperty(
        default="", maxlen=GRAPH_NODE_ID_MAXLEN, options={'SKIP_SAVE'}
    )

    @classmethod
    def poll(cls, context):
        return is_moodboard_context(context)

    def invoke(self, context, event):
        if _popup_node(context, self.node_id) is None:
            self.report({'WARNING'}, "This inference node is no longer available")
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=340)

    def draw(self, context):
        node = _popup_node(context, self.node_id)
        if node is None:
            self.layout.label(text="This inference node is no longer available", icon='INFO')
            return
        _draw_settings(self.layout, node, context.scene)

    def check(self, context):
        node = _popup_node(context, self.node_id)
        if node is not None:
            _clamp_numeric_settings(node)
        redraw_moodboard_canvases()
        return True

    def execute(self, context):
        # Edits bind to the card's RNA immediately. Enter only dismisses this
        # settings popup; it cannot submit a generation or change selection.
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_node_settings,)
