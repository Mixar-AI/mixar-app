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
    draw_tooltip,
)


# Space between stacked fields so captions read as belonging to their control.
FIELD_GAP = 0.6


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


MODE_HELP = "The kind of generation this node runs."
MODEL_HELP = "The AI model this node generates with."


def _draw_parameter(layout, parameter, spec=None):
    """Caption over the control for every kind; hover either for help."""
    label = parameter.label or parameter.name.replace('_', ' ').title()
    kind = parameter.parameter_type
    field = layout.column(align=True)
    field.label(text=label)
    if kind == 'BOOLEAN':
        draw_toggle(field, parameter, 'value_boolean',
                    text="On" if parameter.value_boolean else "Off")
    elif kind == 'ENUM':
        draw_dropdown(field, parameter, 'value_enum', text="")
    elif kind in {'INTEGER', 'FLOAT'}:
        field.prop(parameter, 'value_integer' if kind == 'INTEGER' else 'value_float', text="")
        if hasattr(field, 'mixar_style'):
            field.mixar_style(component='NUMBER')
    else:
        draw_input(field, parameter, 'value_string', text="")
    # After the control exists, so the caption and the value share it.
    draw_tooltip(field, parameter_help(parameter, spec))


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
        mode = settings.column(align=True)
        mode.label(text="Mode")
        draw_dropdown(mode, node, 'service_key', text="")
        draw_tooltip(mode, MODE_HELP)
        settings.separator(factor=FIELD_GAP)
    model = settings.column(align=True)
    model.label(text="Model")
    draw_dropdown(model, node, 'model', text="")
    draw_tooltip(model, MODEL_HELP)
    specs = parameter_specs(node)
    for parameter in node.parameters:
        if parameter.visible:
            settings.separator(factor=FIELD_GAP)
            _draw_parameter(settings, parameter, specs.get(parameter.name))

    if scene is not None and node.action_type == 'CHARACTER_PARTS':
        from ..character_parts_node_drawer import draw_character_parts_node

        components = layout.column()
        components.enabled = not running
        draw_character_parts_node(components, scene, node)

    layout.separator(factor=FIELD_GAP)
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

    overlay_offset: bpy.props.IntVectorProperty(
        size=2, default=(0, 0), options={'HIDDEN', 'SKIP_SAVE'}
    )
    anchored_overlay: bpy.props.BoolProperty(
        default=False, options={'HIDDEN', 'SKIP_SAVE'}
    )

    def invoke(self, context, event):
        node = _popup_node(context, self.node_id)
        if node is None:
            self.report({'WARNING'}, "This inference node is no longer available")
            return {'CANCELLED'}
        # Pin the native overlay below this card's model row, over the prompt.
        # No cursor warp, saved UI state or changes to the draft are needed.
        region = context.region
        width = 340
        self.anchored_overlay = region.type in {'WINDOW', 'TOOL_PROPS'}
        if self.anchored_overlay:
            scale = context.preferences.system.ui_scale
            left, top = region.view2d.view_to_region(
                node.position_x, node.position_y + node.height, clip=False)
            right, _ = region.view2d.view_to_region(
                node.position_x + node.width, node.position_y, clip=False)
            width = max(240, min(480, int((right - left) / scale) - 24))
            self.overlay_offset = (
                int(region.x + left + 12 * scale - event.mouse_x),
                int(region.y + top - 52 * scale - event.mouse_y),
            )
        return context.window_manager.invoke_popup(self, width=width)

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
