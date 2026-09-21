# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise the narrow-canvas settings popup without Blender's mocked base."""

import ast
import math
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.common.generation_params.constants import (
    UNBOUNDED_INT_MAX,
    UNBOUNDED_INT_MIN,
)
from mixar.modules.common.generation_params.core.bounds import integer_window
from mixar.modules.moodboard.core.parameter_help import parameter_help, parameter_specs


PATH = (Path(__file__).resolve().parents[2] / 'src/scripts/mixar/modules/moodboard'
        / 'ui/operators/node_settings_ops.py')


@pytest.fixture
def popup():
    tree = ast.parse(PATH.read_text())
    body = []
    for item in tree.body:
        if isinstance(item, ast.FunctionDef):
            body.append(item)
        elif isinstance(item, ast.ClassDef):
            item.bases = [ast.Name(id='object', ctx=ast.Load())]
            item.body = [child for child in item.body if not isinstance(child, ast.AnnAssign)]
            body.append(item)
    namespace = {
        'math': math,
        'integer_window': integer_window,
        'parameter_help': parameter_help,
        'parameter_specs': parameter_specs,
        'draw_dropdown': lambda layout, data, prop, **kw: layout.prop(data, prop, **kw),
        'draw_input': lambda layout, data, prop, **kw: layout.prop(data, prop, **kw),
        'draw_toggle': lambda layout, data, prop, **kw: layout.prop(data, prop, **kw),
        'draw_section_box': lambda layout: layout.column(),
        'redraw_moodboard_canvases': Mock(),
        'is_moodboard_context': Mock(return_value=True),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
                 str(PATH), 'exec'), namespace)
    return namespace


class Layout:
    def __init__(self, parent=None):
        self.parent = parent
        self.enabled = True
        self.events = parent.events if parent else []

    def active(self):
        return self.enabled and (self.parent is None or self.parent.active())

    def column(self, **kwargs):
        return Layout(self)

    row = column
    mixar_surface = column

    def label(self, **kwargs):
        self.events.append(('label', kwargs['text'], self.active()))

    def prop(self, data, name, **kwargs):
        self.events.append(('prop', (data, name, kwargs), self.active()))

    def operator(self, name, **kwargs):
        result = SimpleNamespace()
        self.events.append(('op', (name, result), self.active()))
        return result

    def mixar_style(self, **kwargs):
        pass


def parameter(kind, **kwargs):
    values = dict(parameter_type=kind, visible=True, name='quality', label='Quality',
                  minimum=1.0, maximum=4.0, value_integer=1, value_float=1.0)
    values.update(kwargs)
    return SimpleNamespace(**values)


def node(**kwargs):
    values = dict(node_id='owner', state='DRAFT', show_mode=True, parameters=[],
                  preview_image=None, preview_object=None)
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_explicit_owner_survives_selection_changes_and_deletion(popup):
    owner, other = node(), node(node_id='other')
    context = SimpleNamespace(scene=SimpleNamespace(
        mixie_moodboard_action_nodes=[owner, other],
        mixie_moodboard_active_node_id='other'))
    resolve = popup['_popup_node']
    assert resolve(context, 'owner') is owner
    assert resolve(context, '') is None
    context.scene.mixie_moodboard_action_nodes.remove(owner)
    assert resolve(context, 'owner') is None


def test_popup_has_no_submit_or_confirmation_side_effect(popup):
    cls = popup['MIXIE_OT_moodboard_node_settings']
    op = cls()
    op.node_id, op.report = 'owner', Mock()
    context = SimpleNamespace(scene=SimpleNamespace(mixie_moodboard_action_nodes=[node()]),
                              window_manager=SimpleNamespace(invoke_popup=Mock(
                                  return_value={'RUNNING_MODAL'})))
    assert op.invoke(context, None) == {'RUNNING_MODAL'}
    context.window_manager.invoke_popup.assert_called_once_with(op, width=340)
    assert op.execute(context) == {'FINISHED'}
    assert context.scene.mixie_moodboard_action_nodes[0].state == 'DRAFT'
    context.scene.mixie_moodboard_action_nodes.clear()
    assert op.invoke(context, None) == {'CANCELLED'}
    source = PATH.read_text()
    assert "options={'SKIP_SAVE'}" in source
    assert 'invoke_props_dialog' not in source


def test_visible_fields_keep_names_and_bind_to_node_values(popup):
    params = [parameter(kind, label=f'{kind} label')
              for kind in ('ENUM', 'INTEGER', 'FLOAT', 'BOOLEAN', 'STRING')]
    hidden = parameter('INTEGER', visible=False, label='Hidden label')
    layout = Layout()
    popup['_draw_settings'](layout, node(parameters=params + [hidden]))
    labels = [value for kind, value, _ in layout.events if kind == 'label']
    assert {'Mode', 'Model', 'ENUM label', 'INTEGER label', 'FLOAT label',
            'STRING label'} <= set(labels)
    fields = [value for kind, value, _ in layout.events if kind == 'prop']
    assert not any(data is hidden for data, _, _ in fields)
    assert {name for _, name, _ in fields} == {
        'service_key', 'model', 'value_enum', 'value_integer', 'value_float',
        'value_boolean', 'value_string'}
    assert next(kw['text'] for _, name, kw in fields if name == 'value_boolean') == 'BOOLEAN label'
    assert not any(kw.get('slider') for _, _, kw in fields)


@pytest.mark.parametrize('state', ['QUEUED', 'RUNNING'])
def test_running_settings_and_reset_are_disabled(popup, state):
    layout = Layout()
    popup['_draw_settings'](layout, node(state=state, parameters=[parameter('INTEGER')]))
    controls = [(kind, value, enabled) for kind, value, enabled in layout.events
                if kind in {'prop', 'op'}]
    assert controls and not any(enabled for _, _, enabled in controls)
    assert [value[0] for kind, value, _ in controls if kind == 'op'] == [
        'mixie.moodboard_parameter_info', 'mixie.moodboard_reset_node_params']


@pytest.mark.parametrize('state', ['SUCCESS', 'FAILED', 'CANCELLED'])
def test_terminal_result_offers_edit_without_submitting(popup, state):
    layout = Layout()
    popup['_draw_settings'](layout, node(state=state, preview_image=object()))
    ops = [value for kind, value, _ in layout.events if kind == 'op']
    assert ops[0][0] == 'mixie.moodboard_run_action_node'
    assert ops[0][1].node_id == 'owner'
    assert ops[0][1].edit_before_run is True
    assert ops[1][1].node_id == 'owner'


def test_numeric_edits_settle_inside_each_catalog_range(popup):
    small = parameter('INTEGER', value_integer=-200, minimum=1.1, maximum=5.9)
    large = parameter('FLOAT', value_float=200.0, minimum=0.2, maximum=0.8)
    hidden = parameter('INTEGER', visible=False, value_integer=900)
    owner = node(parameters=[small, large, hidden])
    popup['_clamp_numeric_settings'](owner)
    assert small.value_integer == 2
    assert large.value_float == 0.8
    assert hidden.value_integer == 900
    owner.state = 'RUNNING'
    small.value_integer = -200
    popup['_clamp_numeric_settings'](owner)
    assert small.value_integer == -200


def _c_float(value):
    """Round the way an RNA FloatProperty (a C float) stores a bound."""
    return struct.unpack('f', struct.pack('f', float(value)))[0]


class _RnaIntField:
    """value_integer rejects anything outside the C int range, as bpy does."""

    def __init__(self, minimum, maximum, value):
        self.parameter_type = 'INTEGER'
        self.visible = True
        self.minimum = _c_float(minimum)
        self.maximum = _c_float(maximum)
        self._value = value

    @property
    def value_integer(self):
        return self._value

    @value_integer.setter
    def value_integer(self, value):
        if not UNBOUNDED_INT_MIN <= int(value) <= UNBOUNDED_INT_MAX:
            raise ValueError("value not in 'int' range")
        self._value = int(value)


def test_integer_popup_clamp_survives_float32_catalog_bounds(popup):
    # 2147483647 is a legal RNA int, but a C float stores it as 2147483648.
    field = _RnaIntField(2147483647, 4294967295, 0)
    popup['_clamp_numeric_settings'](node(parameters=[field]))
    assert field.value_integer == UNBOUNDED_INT_MAX

    field = _RnaIntField(4294967295, 4294967295, 0)
    popup['_clamp_numeric_settings'](node(parameters=[field]))
    assert field.value_integer == UNBOUNDED_INT_MAX


def test_info_uses_owning_nodes_default_and_keeps_current_value(popup):
    field = parameter('INTEGER', value_integer=3)
    layout = Layout()
    popup['_draw_settings'](layout, node(parameters=[field],
                                        schema_json='{"parameters":{"quality":{"default":1}}}'))
    info = next(value[1] for kind, value, _ in layout.events
                if kind == 'op' and value[0] == 'mixie.moodboard_parameter_info')
    assert 'Default: 1' in info.details
    assert 'Range: 1 to 4' in info.details
    assert field.value_integer == 3
