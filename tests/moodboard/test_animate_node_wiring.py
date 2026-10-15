# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Animate card: identity, schema, rig sourcing, presets and the run.

Appended as action index 12 with a MESH output (its result IS the rigged
character, now animated). It takes one rigged-character input, no export,
a multi-select of catalog presets narrowed to the rig's skeleton, and
submits ``rig_job_id`` + params through the shared retarget enqueue.
"""

import ast
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"

if "keyring" not in sys.modules:  # the enqueue helper reaches the API client
    sys.modules["keyring"] = ModuleType("keyring")

from mixar.modules.common.generation_params.core.multi_select import selected_values
from mixar.modules.hunyuan.constants import (
    ANIMATE_IN_PLACE_PARAM,
    ANIMATE_PRESETS_PARAM,
    ANIMATE_RIG_JOB_PROP,
    ANIMATE_RIG_SKELETON_PROP,
)
from mixar.modules.moodboard.core import animate_node, node_graph, node_schema
from mixar.modules.moodboard.core.node_action_types import ACTION_TYPES


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


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

    def remove(self, index):
        del self[index]


def _choice():
    return NS(value="", label="", group="", selected=False)


def _parameter():
    return NS(name="", label="", description="", parameter_type='STRING', widget="text",
              group="", choices_json="[]", visible_if_json="{}", visible=True, required=False,
              order=0, minimum=-1.0e18, maximum=1.0e18, value_string="", value_integer=0,
              value_float=0.0, value_boolean=False, value_enum="", value_label="",
              choices=_Collection(_choice), active_choice=0, choice_filter="")


def _socket():
    return NS(socket_id="", label="", accepted_types="", required=False, group_id="",
              repeatable=False, visible=True)


def _node(action_type='ANIMATE', node_id="anim", **kwargs):
    values = dict(
        node_id=node_id, action_type=action_type, label="", show_prompt=True, show_mode=True,
        schema_json="{}", width=700.0, height=560.0, preview_image=None, preview_object=None,
        state='DRAFT', params_json="{}", result_names="", prompt="", job_id="",
        input_sockets=_Collection(_socket), parameters=_Collection(_parameter),
    )
    values.update(kwargs)
    return NS(**values)


class _Object:
    def __init__(self, name, type='MESH', parent=None, **stamps):
        self.name, self.type, self.parent = name, type, parent
        self.modifiers, self.children_recursive = [], []
        self._props = dict(stamps)
        if parent is not None:
            parent.children_recursive.append(self)

    def get(self, key, default=None):
        return self._props.get(key, default)

    def find_armature(self):
        return self.parent if self.parent is not None and self.parent.type == 'ARMATURE' else None


def _link(from_id, to_id, socket="rig"):
    return NS(from_node_id=from_id, to_node_id=to_id, to_socket=socket, input_order=0)


def _scene(nodes=(), links=(), assets=(), objects=()):
    return NS(name="Scene", mixie_moodboard_action_nodes=list(nodes),
              mixie_moodboard_asset_nodes=list(assets), mixie_moodboard_images=[],
              mixie_moodboard_links=_Collection(dict) + list(links)
              if False else _links(links),
              objects=_Objects((obj.name, obj) for obj in objects))


class _Objects(dict):
    """``scene.objects``: looked up by name, iterated as objects."""

    def __iter__(self):
        return iter(list(self.values()))


def _links(links):
    collection = _Collection(dict)
    collection.extend(links)
    return collection


PRESETS = [
    {"value": "preset:biped:walk", "label": "Walk"},
    {"value": "preset:biped:idle", "label": "Idle"},
    {"value": "preset:quadruped:walk", "label": "Quadruped Walk"},
]
MODEL = {
    "slug": "tripo_retarget_v2_5",
    "parameters": {
        ANIMATE_PRESETS_PARAM: {
            "type": "array", "label": "Animations", "required": True, "order": 0,
            "items": {"type": "string", "enum": [c["value"] for c in PRESETS]},
            "choices": PRESETS,
        },
        ANIMATE_IN_PLACE_PARAM: {"type": "boolean", "label": "In Place", "default": False,
                                 "order": 1},
    },
}


@pytest.fixture
def catalog(monkeypatch):
    fake = NS(
        get_model=lambda service, slug: MODEL,
        get_service=lambda service: {"key": "tripo_retarget", "input_spec": {"inputs": []}},
        get_services=lambda capability, surface=None: [{"key": "tripo_retarget"}],
        get_default_model_slug=lambda service: MODEL["slug"],
    )
    monkeypatch.setitem(sys.modules, "mixar.bootstrap.generation_catalog_cache", fake)
    monkeypatch.setattr(node_schema, "node_service_key", lambda node: "tripo_retarget")
    monkeypatch.setattr(node_schema, "node_model_slug", lambda node: MODEL["slug"])
    monkeypatch.setattr(node_schema, "reconcile_node_links", lambda scene, node: None,
                        raising=False)
    return fake


# --------------------------------------------------------------------------- #
# Identity and the maps
# --------------------------------------------------------------------------- #


def test_animate_is_appended_as_index_twelve_with_a_mesh_output():
    assert ACTION_TYPES[12][0] == 'ANIMATE'
    assert node_schema._OUTPUT_TYPES['ANIMATE'] == 'MESH'
    assert node_schema.output_type_for_action('ANIMATE') == 'MESH'
    assert 'ANIMATE' in node_schema._PROMPTLESS_ACTION_TYPES
    assert node_schema._capability_for_action('ANIMATE') == "animation"
    from mixar.modules.moodboard.ui.moodboard_graph_properties import (
        MESH_FEATURE_ACTIONS, capability_for_action,
    )
    assert capability_for_action('ANIMATE') == "animation"
    assert 'ANIMATE' in MESH_FEATURE_ACTIONS
    assert 'ANIMATE' in node_graph.MESH_FEATURE_ACTIONS
    assert node_graph._ACCEPTED_SOURCE_TYPES['ANIMATE'] == {'MESH'}


def test_animate_is_not_an_exporting_mesh_feature():
    from mixar.modules.moodboard.core.node_mesh_execution import _MESH_FEATURE_ROUTING

    assert 'ANIMATE' not in _MESH_FEATURE_ROUTING
    source = (MOODBOARD / "core/node_execution.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "run_action_node")
    body = ast.unparse(fn)
    branch = body.split("node.action_type == 'ANIMATE'")[1]
    assert "from .animate_node import run_animate_node" in branch
    assert body.index("'ANIMATE'") < body.index("_MESH_FEATURE_ROUTING")


def test_animate_is_a_template_gated_on_the_animation_capability():
    from mixar.modules.moodboard.constants import NODE_TEMPLATES

    entry = next(item for item in NODE_TEMPLATES if item[0] == 'ANIMATE')
    assert entry[3] == "animation"
    # Right after Auto Rig in the strip order.
    ids = [item[0] for item in NODE_TEMPLATES]
    assert ids.index('ANIMATE') == ids.index('AUTO_RIG') + 1


# --------------------------------------------------------------------------- #
# Schema: one rig socket, a multi-select of presets, the in-place toggle
# --------------------------------------------------------------------------- #


def test_sync_mints_the_rig_socket_and_the_preset_rows(catalog):
    node = _node()
    node_schema.sync_node_schema(None, node)
    assert node.show_prompt is False
    assert [(s.socket_id, s.label, s.accepted_types, s.required) for s in node.input_sockets] == [
        ("rig", "Rigged Character", "MESH", True)]
    assert json.loads(node.schema_json)["inputs"]["limits"] == {"MESH": 1}
    presets, in_place = node.parameters
    assert presets.name == ANIMATE_PRESETS_PARAM and presets.parameter_type == 'ARRAY'
    assert [(r.value, r.label, r.selected) for r in presets.choices] == [
        (c["value"], c["label"], False) for c in PRESETS]
    assert in_place.parameter_type == 'BOOLEAN' and in_place.value_boolean is False
    assert node_schema.collect_node_params(node) == {
        ANIMATE_PRESETS_PARAM: [], ANIMATE_IN_PLACE_PARAM: False}


def test_ticks_collect_in_catalog_order_and_survive_a_same_model_resync(catalog):
    node = _node()
    node_schema.sync_node_schema(None, node)
    presets = node.parameters[0]
    presets.choices[2].selected = True
    presets.choices[0].selected = True
    assert node_schema.collect_node_params(node)[ANIMATE_PRESETS_PARAM] == [
        "preset:biped:walk", "preset:quadruped:walk"]
    node.input_sockets.clear()  # force the same-model rebuild path
    node_schema.sync_node_schema(None, node)
    assert selected_values(node.parameters[0].choices) == [
        "preset:biped:walk", "preset:quadruped:walk"]
    node_schema.reset_node_parameters(node)
    assert selected_values(node.parameters[0].choices) == []


def test_duplicate_carries_the_ticks_and_rebuilds_the_rows(catalog):
    from mixar.modules.moodboard.core import node_duplicate

    node = _node()
    node_schema.sync_node_schema(None, node)
    node.parameters[0].choices[1].selected = True
    data = node_duplicate._serialize_parameter(node.parameters[0])
    assert data["values"] == ["preset:biped:idle"]
    copy = _parameter()
    node_duplicate._apply_parameter(copy, data)
    assert copy.parameter_type == 'ARRAY'
    assert [(r.value, r.selected) for r in copy.choices] == [
        ("preset:biped:walk", False), ("preset:biped:idle", True),
        ("preset:quadruped:walk", False)]


# --------------------------------------------------------------------------- #
# Where the rig comes from
# --------------------------------------------------------------------------- #


def _rig_stamps(skeleton="biped"):
    stamps = {ANIMATE_RIG_JOB_PROP: "job-1"}
    if skeleton:
        stamps[ANIMATE_RIG_SKELETON_PROP] = skeleton
    return stamps


def test_only_rig_cards_and_stamped_assets_feed_animate():
    armature = _Object("Rig", 'ARMATURE', **_rig_stamps())
    body = _Object("Body", parent=armature)
    plain = _Object("Plain")
    scene = _scene(
        nodes=[_node('AUTO_RIG', "rig"), _node('ANIMATE', "anim"), _node('PBR_GEN', "pbr")],
        assets=[NS(node_id="stamped", preview_object=body, object_names=""),
                NS(node_id="plain", preview_object=plain, object_names=""),
                NS(node_id="legacy", preview_object=None, object_names="Rig")],
        objects=[armature, body, plain],
    )
    # A rig card that has not produced its character yet: the run checks it.
    assert animate_node.source_carries_rig(scene, "rig")
    assert animate_node.source_carries_rig(scene, "anim")
    assert not animate_node.source_carries_rig(scene, "pbr")
    assert animate_node.source_carries_rig(scene, "stamped")
    assert not animate_node.source_carries_rig(scene, "plain")
    assert animate_node.source_carries_rig(scene, "legacy")
    assert not animate_node.source_carries_rig(scene, "missing")
    with pytest.raises(ValueError, match="rigged character"):
        animate_node.require_rig_source(scene, "plain")
    animate_node.require_rig_source(scene, "rig")


def test_a_rig_without_its_skeleton_stamp_is_refused_everywhere():
    # A Meshy rig (or a rig from before Animate) carries the job id alone.
    armature = _Object("Rig", 'ARMATURE', **_rig_stamps(skeleton=""))
    body = _Object("Body", parent=armature)
    scene = _scene(
        nodes=[_node('AUTO_RIG', "rig", result_names="Rig, Body")],
        assets=[NS(node_id="meshy", preview_object=body, object_names="")],
        objects=[armature, body],
    )
    for node_id in ("rig", "meshy"):
        assert not animate_node.source_carries_rig(scene, node_id)
        with pytest.raises(ValueError, match="can't take preset animations"):
            animate_node.require_rig_source(scene, node_id)


def test_the_continuation_menu_offers_animate_only_for_a_skeleton_stamped_rig(monkeypatch):
    from mixar.modules.moodboard.ui import moodboard_menu_actions as actions

    monkeypatch.setattr(actions, "capability_available", lambda capability: True)
    monkeypatch.setattr(actions, "template_available", lambda template: True)
    armature = _Object("Rig", 'ARMATURE', **_rig_stamps())
    body = _Object("Body", parent=armature)
    scene = _scene(nodes=[_node('AUTO_RIG', "rig", result_names="Rig, Body")],
                   objects=[armature, body])
    assert 'ANIMATE' in [entry[0] for entry in actions.mesh_continuations_for(scene, "rig")]
    del armature._props[ANIMATE_RIG_SKELETON_PROP]
    assert 'ANIMATE' not in [entry[0] for entry in actions.mesh_continuations_for(scene, "rig")]


def test_connect_nodes_refuses_an_unrigged_mesh_on_animate(monkeypatch):
    monkeypatch.setattr(node_graph, "ensure_media_node_ids", lambda scene: None)
    monkeypatch.setattr(node_graph, "node_output_type", lambda scene, node_id: 'MESH')
    target = _node('ANIMATE', "anim")
    target.input_sockets.add().socket_id = "rig"
    target.input_sockets[0].accepted_types = "MESH"
    scene = _scene(nodes=[_node('MODEL_3D', "m3d"), target])
    with pytest.raises(ValueError, match="Auto Rig result"):
        node_graph.connect_nodes(scene, "m3d", "anim", "rig")
    assert list(scene.mixie_moodboard_links) == []


def test_the_rig_comes_from_the_stamps_on_the_connected_character():
    armature = _Object("Rig", 'ARMATURE', **_rig_stamps())
    body = _Object("Body", parent=armature)
    rig_card = _node('AUTO_RIG', "rig", result_names="Rig, Body", job_id="backend-9")
    anim = _node('ANIMATE', "anim")
    scene = _scene(nodes=[rig_card, anim], links=[_link("rig", "anim")],
                   objects=[armature, body])
    assert animate_node.rig_source(scene, anim) == ("job-1", "biped", ["Rig", "Body"], armature)
    # Unstamped: the card's own job id is never a substitute (no skeleton).
    armature._props.clear()
    assert animate_node.rig_source(scene, anim) == ("", "", ["Rig", "Body"], None)


def test_the_preset_filter_groups_rows_by_skeleton_and_narrows_to_the_rigs(catalog):
    armature = _Object("Rig", 'ARMATURE', **{ANIMATE_RIG_JOB_PROP: "job-1",
                                             ANIMATE_RIG_SKELETON_PROP: "quadruped"})
    rig_card = _node('AUTO_RIG', "rig", result_names="Rig")
    anim = _node('ANIMATE', "anim")
    node_schema.sync_node_schema(None, anim)
    scene = _scene(nodes=[rig_card, anim], links=[_link("rig", "anim")], objects=[armature])
    assert animate_node.refresh_preset_filter(scene, anim) == "quadruped"
    presets = anim.parameters[0]
    assert [r.group for r in presets.choices] == ["biped", "biped", "quadruped"]
    assert presets.choice_filter == "quadruped"
    armature._props[ANIMATE_RIG_SKELETON_PROP] = ""
    assert animate_node.refresh_preset_filter(scene, anim) == ""
    assert presets.choice_filter == ""


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


@pytest.fixture
def run_seams(monkeypatch, catalog):
    from mixar.modules.common import generation_params

    calls = {}
    monkeypatch.setattr(generation_params, "resolve_service_key",
                        lambda capability, selected: "tripo_retarget")
    monkeypatch.setattr(generation_params, "resolve_model_slug",
                        lambda service, selected: MODEL["slug"])
    monkeypatch.setattr(animate_node, "enqueue_retarget_job",
                        lambda **kw: calls.setdefault("enqueue", kw) and NS(id="q1"))
    monkeypatch.setitem(sys.modules, "mixar.modules.moodboard.core.node_job_bridge",
                        NS(ensure_graph_listener=lambda key: calls.setdefault("listener", key)))
    return calls


def _rigged_graph(skeleton="biped"):
    stamps = {ANIMATE_RIG_JOB_PROP: "job-1"}
    if skeleton:
        stamps[ANIMATE_RIG_SKELETON_PROP] = skeleton
    armature = _Object("Rig", 'ARMATURE', **stamps)
    body = _Object("Body", parent=armature)
    rig_card = _node('AUTO_RIG', "rig", result_names="Rig, Body")
    anim = _node('ANIMATE', "anim")
    node_schema.sync_node_schema(None, anim)
    scene = _scene(nodes=[rig_card, anim], links=[_link("rig", "anim")],
                   objects=[armature, body])
    return scene, anim


def test_run_submits_the_rig_job_id_and_the_ticked_presets(run_seams):
    scene, anim = _rigged_graph()
    anim.parameters[0].choices[1].selected = True
    anim.parameters[0].choices[0].selected = True
    anim.parameters[1].value_boolean = True
    job, params = animate_node.run_animate_node(NS(scene=scene), anim)
    assert job.id == "q1"
    assert params == {ANIMATE_PRESETS_PARAM: ["preset:biped:walk", "preset:biped:idle"],
                      ANIMATE_IN_PLACE_PARAM: True}
    kw = run_seams["enqueue"]
    assert kw["rig_job_id"] == "job-1" and kw["service_key"] == "tripo_retarget"
    assert kw["model"] == MODEL["slug"] and kw["params"] == params
    # The queue row and toasts name the character (its mesh), the merge
    # targets the armature.
    assert kw["label"] == "Body" and kw["rig_name"] == "Rig"
    assert kw["graph_node_id"] == "anim" and callable(kw["on_merged"])
    assert run_seams["listener"] == "animate"


@pytest.mark.parametrize("prepare, message", [
    (lambda s, n: None, "at least one animation preset"),
    (lambda s, n: setattr(n.parameters[0].choices[2], "selected", True),
     "not for a biped rig"),
])
def test_run_refuses_without_presets_or_with_another_skeletons(run_seams, prepare, message):
    scene, anim = _rigged_graph()
    prepare(scene, anim)
    with pytest.raises(ValueError, match=message):
        animate_node.run_animate_node(NS(scene=scene), anim)
    assert "enqueue" not in run_seams


def test_run_refuses_without_a_rig(run_seams):
    scene, anim = _rigged_graph()
    for obj in scene.objects.values():
        obj._props.clear()
    anim.parameters[0].choices[0].selected = True
    with pytest.raises(ValueError, match="Connect an Auto Rig result"):
        animate_node.run_animate_node(NS(scene=scene), anim)


def test_run_refuses_a_rig_without_its_skeleton_stamp(run_seams):
    scene, anim = _rigged_graph(skeleton="")
    anim.parameters[0].choices[2].selected = True
    with pytest.raises(ValueError, match="can't take preset animations"):
        animate_node.run_animate_node(NS(scene=scene), anim)
    assert "enqueue" not in run_seams


def test_run_explains_a_skeleton_the_catalog_has_no_presets_for(run_seams):
    scene, anim = _rigged_graph(skeleton="avian")
    with pytest.raises(ValueError, match="No preset animations are available for avian rigs"):
        animate_node.run_animate_node(NS(scene=scene), anim)
    assert "enqueue" not in run_seams


def test_the_merged_character_becomes_the_cards_result(monkeypatch):
    anim = _node('ANIMATE', "anim")
    scene = _scene(nodes=[anim])
    monkeypatch.setattr(animate_node, "bpy", NS(data=NS(scenes={"Scene": scene})), raising=False)
    monkeypatch.setitem(sys.modules, "bpy", NS(data=NS(scenes={"Scene": scene})))
    results = []
    monkeypatch.setattr(node_graph, "create_asset_result",
                        lambda s, n, names: results.append((n.node_id, names)))
    animate_node._node_result("Scene", "anim")(NS(), ["Rig", "Body"])
    assert results == [("anim", "Rig, Body")]


# --------------------------------------------------------------------------- #
# Surfaces
# --------------------------------------------------------------------------- #


def test_the_settings_popup_narrows_presets_before_it_draws():
    popup = (MOODBOARD / "ui/operators/node_settings_ops.py").read_text(encoding="utf-8")
    invoke = popup.split("def invoke(")[1].split("def draw(")[0]
    assert "refresh_preset_filter(context.scene, node)" in invoke
    draw_fn = popup.split("def _draw_parameter(")[1].split("def _draw_settings(")[0]
    assert "draw_multi_select(field, parameter, 'choices', 'active_choice', label)" in draw_fn


def test_the_output_kind_table_names_animate_as_a_mesh():
    socket_cc = (ROOT / "src/source/blender/editors/space_mixie/"
                 "mixie_draw_moodboard_graph_sockets.cc").read_text(encoding="utf-8")
    assert "ASSEMBLE, ANIMATE)" in socket_cc

