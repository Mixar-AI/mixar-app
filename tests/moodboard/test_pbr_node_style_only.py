# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas PBR node parity with the sidebar, and Model Gen modes from the catalog.

The PBR card carries the sidebar's "Use Image Style Only" toggle as a
client-side parameter: on, with a prompt, the single connected reference is
sent as style guidance; it never reaches the backend as a model parameter.
The Generate to 3D card's runnable mode set is defined once.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.core import node_schema
from mixar.modules.moodboard.core.node_client_params import (
    PBR_STYLE_ONLY_PARAM,
    injected_parameters,
)

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "src/scripts/mixar/modules/moodboard/core"


class _Collection(list):
    def __init__(self, factory):
        super().__init__()
        self._factory = factory

    def add(self):
        item = self._factory()
        self.append(item)
        return item

    def clear(self):
        del self[:]


def _parameter():
    return NS(name="", label="", description="", parameter_type='STRING', widget="text",
              group="", choices_json="[]", visible_if_json="{}", visible=True, required=False,
              order=0, minimum=-1.0e18, maximum=1.0e18, value_string="", value_integer=0,
              value_float=0.0, value_boolean=False, value_enum="", value_label="")


def _socket():
    return NS(socket_id="", label="", accepted_types="", required=False, group_id="",
              repeatable=False, visible=True)


def _node(action_type, **kwargs):
    values = dict(
        node_id="n", action_type=action_type, label="", show_prompt=True, show_mode=True,
        schema_json="{}", width=700.0, height=560.0, preview_image=None, preview_object=None,
        state='DRAFT', params_json="{}", result_names="", prompt="", service_key="",
        model="", service_key_slug="", model_slug="",
        input_sockets=_Collection(_socket), parameters=_Collection(_parameter),
    )
    values.update(kwargs)
    return NS(**values)


def _catalog(monkeypatch, parameters):
    """Stand in for the catalog cache: one PBR service with one model."""
    model = {"slug": "tex", "parameters": parameters}
    fake = NS(
        get_model=lambda service, slug: model,
        get_service=lambda service: {"key": "tripo_texture", "input_spec": {"inputs": []}},
        get_services=lambda capability, surface=None: [{"key": "tripo_texture"}],
    )
    monkeypatch.setitem(sys.modules, "mixar.bootstrap.generation_catalog_cache", fake)
    monkeypatch.setattr(node_schema, "node_service_key", lambda node: "tripo_texture")
    monkeypatch.setattr(node_schema, "node_model_slug", lambda node: "tex")


# --------------------------------------------------------------------------- #
# Schema: the toggle is minted beside the catalog parameters
# --------------------------------------------------------------------------- #

def test_pbr_node_gets_the_sidebar_toggle_first_and_off(monkeypatch):
    _catalog(monkeypatch, {"resolution": {"type": "string", "default": "2k", "order": 1}})
    node = _node('PBR_GEN')
    node_schema.sync_node_schema(None, node)

    rows = {parameter.name: parameter for parameter in node.parameters}
    toggle = rows[PBR_STYLE_ONLY_PARAM]
    assert toggle.parameter_type == 'BOOLEAN' and toggle.value_boolean is False
    assert toggle.label == "Use Image Style Only"  # the sidebar's, one translation
    assert toggle.description.startswith("When enabled, only the image's artistic style")
    assert [parameter.name for parameter in node.parameters] == [PBR_STYLE_ONLY_PARAM, "resolution"]
    assert json.loads(node.schema_json)["parameters"][PBR_STYLE_ONLY_PARAM]["type"] == "boolean"


@pytest.mark.parametrize("action_type", ['RETOPOLOGY', 'AUTO_RIG', 'MESH_SEGMENT', 'IMAGE_GEN'])
def test_only_the_pbr_node_carries_it(monkeypatch, action_type):
    assert injected_parameters(action_type) == {}
    _catalog(monkeypatch, {"resolution": {"type": "string", "default": "2k"}})
    node = _node(action_type)
    node_schema.sync_node_schema(None, node)
    assert PBR_STYLE_ONLY_PARAM not in {parameter.name for parameter in node.parameters}


def test_a_catalog_parameter_of_the_same_name_wins(monkeypatch):
    _catalog(monkeypatch, {PBR_STYLE_ONLY_PARAM: {"type": "boolean", "default": True,
                                                  "label": "Server label"}})
    node = _node('PBR_GEN')
    node_schema.sync_node_schema(None, node)
    toggle = next(p for p in node.parameters if p.name == PBR_STYLE_ONLY_PARAM)
    assert toggle.value_boolean is True and toggle.label == "Server label"


def test_reset_puts_the_toggle_back_off(monkeypatch):
    _catalog(monkeypatch, {})
    node = _node('PBR_GEN')
    node_schema.sync_node_schema(None, node)
    toggle = node.parameters[0]
    toggle.value_boolean = True
    node_schema.reset_node_parameters(node)
    assert toggle.value_boolean is False


# --------------------------------------------------------------------------- #
# Run: the toggle picks the payload key and never ships as a param
# --------------------------------------------------------------------------- #

class _Obj:
    def __init__(self, name):
        self.name, self.type, self._selected = name, 'MESH', False

    def select_get(self):
        return self._selected

    def select_set(self, state):
        self._selected = bool(state)


class _Objects(list):
    active = None

    def __contains__(self, name):
        return any(obj.name == name for obj in self)


def _run_pbr(monkeypatch, *, images, params, prompt):
    from mixar.modules.common import generation_params
    from mixar.modules.common.job_queue.core import model_io
    from mixar.modules.common.utils import image_utils
    from mixar.modules.moodboard.core import node_mesh_execution as nme

    source = _Obj('Source')
    objects = _Objects([source])
    context = NS(scene=NS(name='Scene'), view_layer=NS(objects=objects))
    node = _node('PBR_GEN', prompt=prompt)
    seen = {}

    def assemble(service, merged, payload, model):
        seen['params'] = dict(merged)
        return payload

    monkeypatch.setattr(nme, 'mesh_input_objects', lambda *_: [source])
    monkeypatch.setattr(nme, 'input_media_items', lambda *_: [NS(image=NS(name=n)) for n in images])
    monkeypatch.setattr(nme, 'is_still_item', lambda item: True)
    monkeypatch.setattr(nme, 'collect_node_params', lambda *_: dict(params))
    monkeypatch.setattr(nme, 'ensure_graph_listener', lambda *_: None)
    monkeypatch.setattr(nme, 'enqueue_generation', lambda **kw: seen.setdefault('job', kw) and NS(id='job'))
    monkeypatch.setattr(generation_params, 'resolve_service_key', lambda *_: 'tripo_texture')
    monkeypatch.setattr(generation_params, 'resolve_model_slug', lambda *_: 'tex')
    monkeypatch.setattr(generation_params, 'assemble_payload', assemble)
    monkeypatch.setattr(model_io, 'export_selected_mesh', lambda *_: (b'glb', 'Source.glb'))
    monkeypatch.setattr(image_utils, 'compress_image_for_upload', lambda image: image.name.encode())
    nme._run_mesh_feature(context, node, None)
    return seen['job']['payload'], seen['params']


def test_style_only_with_a_prompt_sends_the_reference_as_style_guidance(monkeypatch):
    payload, params = _run_pbr(monkeypatch, images=['ref'], prompt='rusty metal',
                               params={PBR_STYLE_ONLY_PARAM: True, 'resolution': '2k'})
    assert 'style_ref_image_bytes_b64' in payload
    assert 'reference_image_bytes_b64' not in payload
    assert params == {'resolution': '2k', 'prompt': 'rusty metal'}


@pytest.mark.parametrize("style_only, prompt", [(True, ''), (False, 'rusty metal'), (False, '')])
def test_otherwise_the_reference_drives_the_texture_directly(monkeypatch, style_only, prompt):
    payload, params = _run_pbr(monkeypatch, images=['ref'], prompt=prompt,
                               params={PBR_STYLE_ONLY_PARAM: style_only})
    assert 'reference_image_bytes_b64' in payload
    assert 'style_ref_image_bytes_b64' not in payload
    assert PBR_STYLE_ONLY_PARAM not in params


def test_four_views_stay_turnaround_views_whatever_the_toggle(monkeypatch):
    payload, _ = _run_pbr(monkeypatch, images=['f', 'l', 'b', 'r'], prompt='p',
                          params={PBR_STYLE_ONLY_PARAM: True})
    assert len(payload['reference_images_b64']) == 4
    assert 'style_ref_image_bytes_b64' not in payload


def test_a_node_without_the_toggle_runs_as_before(monkeypatch):
    payload, params = _run_pbr(monkeypatch, images=['ref'], prompt='p', params={})
    assert 'reference_image_bytes_b64' in payload and params == {'prompt': 'p'}


# --------------------------------------------------------------------------- #
# Generate to 3D: the runnable mode set has one definition
# --------------------------------------------------------------------------- #

def test_model_gen_modes_are_defined_once_and_shared_by_schema_and_run():
    """The template gate and the run-time refusal must never drift apart."""
    from mixar.modules.moodboard.core import node_execution

    execution = (CORE / "node_execution.py").read_text(encoding="utf-8")
    assert node_execution.MODEL_3D_SERVICE_KEYS is node_schema.MODEL_3D_SERVICE_KEYS
    assert "service_key not in MODEL_3D_SERVICE_KEYS" in execution
    assert "service_key not in {" not in execution
    services = [{"key": "model_3d"}, {"key": "text_to_3d"}]
    assert node_schema.services_for_action('MODEL_3D', services) == [{"key": "model_3d"}]


def test_the_run_leaves_undo_to_the_queue_and_the_toggle_to_its_button():
    """Per-tab undo: a node run pushes no step of its own. The job's Import
    step is filed by ``queue_download`` under the tab the queue stamped at
    submit (``resolve_job_scene``), so a result landing while the window shows
    another tab still joins the node's tab; an UNDO flag on the run operator
    would file a step under the window's tab instead. The toggle itself is
    scene-owned RNA edited through a native button, which pushes its own step."""
    OPS = REPO / "src/scripts/mixar/modules/moodboard/ui/operators"
    for name in ("node_mesh_execution.py", "node_client_params.py", "node_schema.py"):
        assert "undo_push" not in (CORE / name).read_text(encoding="utf-8")
    ops = (OPS / "node_graph_ops.py").read_text(encoding="utf-8")
    run = ops[ops.index("class MIXIE_OT_moodboard_run_action_node"):ops.index("class MIXIE_OT_moodboard_toggle_node_edit")]
    assert "'UNDO'" not in run[run.index("bl_options"):].splitlines()[0]
    settings = (OPS / "node_settings_ops.py").read_text(encoding="utf-8")
    assert "undo_push" not in settings


def test_reset_and_delete_are_semantic_node_actions():
    from mixar.modules.common.analytics.journey_events import ACTIONS

    assert ACTIONS['mixie.moodboard_reset_node_params'] == ('moodboard', 'reset_node')
    assert ACTIONS['mixie.moodboard_delete_action_node'] == ('moodboard', 'delete_node')
