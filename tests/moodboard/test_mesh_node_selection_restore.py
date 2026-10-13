# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A mesh node run hands the user's viewport selection back.

Exporting the source mesh needs it selected and active; the user's own
selection and active object must be restored afterwards, on success and on a
failed export alike.
"""

from types import SimpleNamespace as NS

import pytest


class Obj:
    def __init__(self, name, type='MESH', selected=False):
        self.name = name
        self.type = type
        self._selected = selected

    def select_get(self):
        return self._selected

    def select_set(self, state):
        self._selected = bool(state)


class Objects(list):
    active = None

    def __contains__(self, name):
        return any(obj.name == name for obj in self)


def _setup(monkeypatch, export):
    from mixar.modules.common import generation_params
    from mixar.modules.common.job_queue.core import model_io
    from mixar.modules.moodboard.core import node_mesh_execution as nme

    source = Obj('Source')
    chosen = Obj('Chosen', selected=True)
    other = Obj('Other', type='LIGHT', selected=True)
    objects = Objects([source, chosen, other])
    objects.active = chosen
    context = NS(scene=NS(name='Scene'), view_layer=NS(objects=objects))
    node = NS(node_id='n', action_type='RETOPOLOGY', prompt='')

    monkeypatch.setattr(nme, 'mesh_input_objects', lambda *_: [source])
    monkeypatch.setattr(generation_params, 'resolve_service_key', lambda *_: 'svc')
    monkeypatch.setattr(generation_params, 'resolve_model_slug', lambda *_: 'model')
    monkeypatch.setattr(generation_params, 'assemble_payload', lambda s, p, payload, m: payload)
    monkeypatch.setattr(nme, 'collect_node_params', lambda *_: {})
    monkeypatch.setattr(nme, 'ensure_graph_listener', lambda *_: None)
    monkeypatch.setattr(nme, 'enqueue_generation', lambda **_: NS(id='job'))
    monkeypatch.setattr(model_io, 'export_selected_mesh', export)
    return nme, context, node, objects, source, chosen, other


def test_selection_and_active_object_are_restored_after_export(monkeypatch):
    seen = {}

    def export(context, fmt):
        objects = context.view_layer.objects
        seen['selected'] = [obj.name for obj in objects if obj.select_get()]
        seen['active'] = objects.active.name
        return b'glb', 'Source.glb'

    nme, context, node, objects, source, chosen, other = _setup(monkeypatch, export)
    nme._run_mesh_feature(context, node, None)

    assert seen == {'selected': ['Source'], 'active': 'Source'}
    assert [obj.name for obj in objects if obj.select_get()] == ['Chosen', 'Other']
    assert objects.active is chosen


def test_selection_is_restored_when_the_export_fails(monkeypatch):
    def export(context, fmt):
        raise RuntimeError('exporter failed')

    nme, context, node, objects, source, chosen, other = _setup(monkeypatch, export)
    with pytest.raises(RuntimeError, match='exporter failed'):
        nme._run_mesh_feature(context, node, None)

    assert [obj.name for obj in objects if obj.select_get()] == ['Chosen', 'Other']
    assert objects.active is chosen
