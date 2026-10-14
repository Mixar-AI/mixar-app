# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Assemble Character: append-only identity, local schema, dispatch and card text."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.core import assemble_schema
from mixar.modules.moodboard.core.assemble_constants import (
    PARAM_KINDS,
    PART_SOCKET_COUNT,
    param_name,
)
from mixar.modules.moodboard.core.node_action_types import ACTION_TYPES

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _Collection(list):
    def __init__(self, factory):
        super().__init__()
        self._factory = factory

    def add(self):
        item = self._factory()
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


def _parameter():
    return NS(name="", label="", description="", parameter_type='STRING', widget="text",
              group="", choices_json="[]", visible_if_json="{}", visible=True, required=False,
              order=0, minimum=-1.0e18, maximum=1.0e18, value_string="", value_integer=0,
              value_float=0.0, value_boolean=False, value_enum="", value_label="")


def _socket():
    return NS(socket_id="", label="", accepted_types="", required=False, group_id="",
              repeatable=False, visible=True)


def _node(node_id="assemble", action_type='ASSEMBLE', **kwargs):
    values = dict(
        node_id=node_id, action_type=action_type, label="", show_prompt=True, show_mode=True,
        schema_json="{}", width=700.0, height=560.0, preview_image=None, preview_object=None,
        state='DRAFT', params_json="{}", result_names="",
        input_sockets=_Collection(_socket), parameters=_Collection(_parameter),
    )
    values.update(kwargs)
    return NS(**values)


def _link(from_id, to_id, socket, order=0):
    return NS(from_node_id=from_id, to_node_id=to_id, to_socket=socket, input_order=order)


def _scene(nodes=(), links=(), assets=(), images=()):
    return NS(mixie_moodboard_action_nodes=list(nodes), mixie_moodboard_asset_nodes=list(assets),
              mixie_moodboard_images=list(images), mixie_moodboard_links=_Collection(dict))


# --------------------------------------------------------------------------- #
# Identity and the two capability maps
# --------------------------------------------------------------------------- #


def test_assemble_is_appended_as_index_eleven_with_a_mesh_output():
    from mixar.modules.moodboard.core.node_schema import _OUTPUT_TYPES, output_type_for_action

    assert ACTION_TYPES[11][0] == 'ASSEMBLE'
    assert ACTION_TYPES[11][1] == "Assemble Character"
    assert _OUTPUT_TYPES['ASSEMBLE'] == 'MESH'
    assert output_type_for_action('ASSEMBLE') == 'MESH'


def test_assemble_runs_no_catalog_service():
    from mixar.modules.moodboard.core.node_schema import (
        _MESH_FEATURE_CAPABILITY,
        _PROMPTLESS_ACTION_TYPES,
        _capability_for_action,
        services_for_action,
    )
    from mixar.modules.moodboard.ui.moodboard_graph_properties import capability_for_action

    assert capability_for_action('ASSEMBLE') is None
    assert _capability_for_action('ASSEMBLE') is None
    assert services_for_action('ASSEMBLE', [{'key': 'image_gen'}]) == []
    assert 'ASSEMBLE' in _PROMPTLESS_ACTION_TYPES
    # A lone injected `mesh` socket would replace body + parts.
    assert 'ASSEMBLE' not in _MESH_FEATURE_CAPABILITY


def test_graph_accepts_meshes_and_never_falls_back_to_the_selection():
    from mixar.modules.moodboard.core import node_graph
    from mixar.modules.moodboard.ui import moodboard_graph_properties as ui_props

    assert node_graph._ACCEPTED_SOURCE_TYPES['ASSEMBLE'] == {'MESH'}
    assert 'ASSEMBLE' in node_graph.MESH_FEATURE_ACTIONS
    assert 'ASSEMBLE' not in ui_props.MESH_FEATURE_ACTIONS
    still = NS(selected=True, image=NS(source='FILE'))
    with pytest.raises(ValueError, match='from a 3D mesh node'):
        node_graph.create_connected_action(NS(mixie_moodboard_images=[still]), 'ASSEMBLE')


def test_dropdown_labels_name_the_attachment_settings():
    from mixar.modules.moodboard.ui.moodboard_graph_properties import refresh_node_dropdown_labels

    node = NS(action_type='ASSEMBLE', service_key_id="", model_slug="",
              service_label="stale", model_label="stale")
    refresh_node_dropdown_labels(node)
    assert (node.service_label, node.model_label) == ("", "Attachment settings")


# --------------------------------------------------------------------------- #
# Local schema
# --------------------------------------------------------------------------- #


def test_contract_is_one_body_and_eight_progressive_parts():
    contract = assemble_schema.assemble_contract()
    sockets = contract["sockets"]
    assert contract["limits"] == {'MESH': 9}
    assert [socket["id"] for socket in sockets] == ["body"] + [f"parts:{i}" for i in range(8)]
    body, *parts = sockets
    assert body["required"] and not body["repeatable"] and body["label"] == "Body"
    assert all(socket["accepted_types"] == ["MESH"] for socket in sockets)
    assert all(part["group_id"] == "parts" and part["repeatable"] for part in parts)
    assert not any(part["required"] for part in parts)
    assert set(body) == {"id", "label", "accepted_types", "required", "group_id", "repeatable"}


def test_sync_mints_sockets_and_rows_and_keeps_edits():
    node = _node()
    assemble_schema.sync_assemble_schema(None, node)
    assert not node.show_prompt and not node.show_mode
    assert len(node.input_sockets) == 1 + PART_SOCKET_COUNT
    assert node.input_sockets[0].socket_id == "body"
    assert node.input_sockets[1].accepted_types == "MESH"
    assert len(node.parameters) == PART_SOCKET_COUNT * len(PARAM_KINDS) == 32
    assert json.loads(node.schema_json)["local"] == "assemble/v1"
    rows = {parameter.name: parameter for parameter in node.parameters}
    slot = rows[param_name("slot", 0)]
    assert slot.parameter_type == 'ENUM' and slot.value_enum == "AUTO"
    assert slot.value_label == "Auto (from name)"
    assert "HAND_R" in {choice["value"] for choice in json.loads(slot.choices_json)}
    size = rows[param_name("size", 7)]
    assert size.parameter_type == 'FLOAT' and (size.minimum, size.maximum) == (0.0, 250.0)
    assert rows[param_name("flip", 3)].parameter_type == 'BOOLEAN'
    assert all(parameter.visible_if_json == "{}" for parameter in node.parameters)

    slot.value_enum = "HAND_L"
    size.value_float = 52.0
    sockets = list(node.input_sockets)
    assemble_schema.sync_assemble_schema(None, node)
    assert len(node.parameters) == 32
    assert slot.value_enum == "HAND_L" and size.value_float == 52.0
    assert list(node.input_sockets) == sockets  # unchanged schema: sockets are kept


def test_sync_adds_missing_rows_without_touching_existing_ones():
    node = _node()
    assemble_schema.sync_assemble_schema(None, node)
    kept = node.parameters[0]
    kept.value_enum = "BACK"
    del node.parameters[4:]
    assemble_schema.sync_assemble_schema(None, node)
    assert len(node.parameters) == 32 and node.parameters[0] is kept
    assert kept.value_enum == "BACK"


def test_catalog_sync_and_reset_delegate_to_the_local_schema():
    from mixar.modules.moodboard.core.node_schema import reset_node_parameters, sync_node_schema

    node = _node()
    sync_node_schema(None, node)
    assert len(node.parameters) == 32
    rows = {parameter.name: parameter for parameter in node.parameters}
    rows["slot:1"].value_enum, rows["hold:1"].value_enum = "HAND_L", "UPRIGHT"
    rows["size:1"].value_float, rows["flip:1"].value_boolean = 72.0, True
    reset_node_parameters(node)
    assert (rows["slot:1"].value_enum, rows["hold:1"].value_enum) == ("AUTO", "AUTO")
    assert rows["slot:1"].value_label == "Auto (from name)"
    assert rows["size:1"].value_float == 0.0 and rows["flip:1"].value_boolean is False


def test_sync_keeps_body_and_part_links_on_their_sockets():
    rig = _node("rig", 'AUTO_RIG')
    part = _node("part", 'MODEL_3D')
    node = _node()
    scene = _scene(nodes=[rig, part, node])
    scene.mixie_moodboard_links.extend([
        _link("rig", "assemble", "body", 0), _link("part", "assemble", "parts:0", 1),
    ])
    assemble_schema.sync_assemble_schema(scene, node)
    assert [link.to_socket for link in scene.mixie_moodboard_links] == ["body", "parts:0"]
    assert assemble_schema.body_link(scene, node).from_node_id == "rig"
    assert [link.from_node_id for link in assemble_schema.part_links(scene, node)] == ["part"]


def test_an_assemble_card_cannot_feed_another_assemble_card():
    from mixar.modules.moodboard.core import node_graph

    first, second, part = _node("first"), _node("second"), _node("part", 'MODEL_3D')
    scene = _scene(nodes=[first, second, part])
    scene.mixie_moodboard_links = _Collection(NS)
    for node in (first, second):
        assemble_schema.sync_assemble_schema(scene, node)
    for socket in ("body", "parts:0"):
        with pytest.raises(ValueError, match="cannot feed another Assemble"):
            node_graph.connect_nodes(scene, "first", "second", socket)
    node_graph.connect_nodes(scene, "part", "second", "parts:0")
    assert [link.from_node_id for link in scene.mixie_moodboard_links] == ["part"]


class _Reallocating(_Collection):
    """``.add()`` moves every item, as RNA does: old references go empty."""

    def add(self):
        for index, old in enumerate(self):
            self[index] = NS(**vars(old))
            old.__dict__.clear()
        return super().add()


def test_a_continuation_reads_an_action_node_source_by_id(monkeypatch):
    from mixar.modules.moodboard.core import node_graph

    monkeypatch.setattr(node_graph, "_initialize_catalog_selection",
                        lambda scene, node: assemble_schema.sync_assemble_schema(scene, node))
    monkeypatch.setattr(node_graph, "refresh_node_height", lambda node: None)
    scene = _scene()
    scene.mixie_moodboard_links = _Collection(NS)
    scene.mixie_moodboard_action_nodes = _Reallocating(lambda: _node(""))
    rig = scene.mixie_moodboard_action_nodes.add()
    rig.node_id, rig.action_type, rig.position_x, rig.position_y = "rig", 'AUTO_RIG', 0.0, 0.0
    node = node_graph.create_connected_action(scene, 'ASSEMBLE', source_node_id="rig")
    assert [(link.from_node_id, link.to_node_id, link.to_socket)
            for link in scene.mixie_moodboard_links] == [("rig", node.node_id, "body")]
    assert node.position_x == 700.0 + node_graph.ACTION_NODE_GAP


# --------------------------------------------------------------------------- #
# Labels and the last run's report
# --------------------------------------------------------------------------- #


def test_part_label_prefers_names_the_user_gave():
    reference = _node("ref", 'IMAGE_GEN', label="Talwar")
    unnamed_ref = _node("ref2", 'IMAGE_GEN', preview_image=NS(name="Left_hand_item"))
    mesh = _node("m3d", 'MODEL_3D')
    mesh2 = _node("m3d2", 'MODEL_3D', result_names="Dhal_mesh, Dhal_mesh.001")
    rig = _node("rig", 'AUTO_RIG', label="Rig Body")
    asset = NS(node_id="asset", title="Warrior", object_names="Warrior_mesh")
    scene = _scene(nodes=[reference, unnamed_ref, mesh, mesh2, rig], assets=[asset])
    scene.mixie_moodboard_links.extend([
        _link("ref", "m3d", "image"), _link("ref2", "m3d2", "image"),
    ])
    assert assemble_schema.part_label(scene, "m3d") == "Talwar"
    assert assemble_schema.part_label(scene, "m3d2") == "Left_hand_item"
    assert assemble_schema.part_label(scene, "rig") == "Rig Body"
    assert assemble_schema.part_label(scene, "asset") == "Warrior"
    asset.title = ""
    assert assemble_schema.part_label(scene, "asset") == "Warrior_mesh"
    scene.mixie_moodboard_links.clear()
    assert assemble_schema.part_label(scene, "m3d2") == "Dhal_mesh"
    assert assemble_schema.part_label(scene, "missing") == ""


def test_last_outcome_and_summary_read_the_run_report():
    node = _node(params_json=json.dumps({
        "version": 1, "summary": "2 parts on bones, 1 skipped",
        "parts": [{"socket": "parts:0", "status": "attached"}, "junk", {"status": "x"}],
    }))
    assert assemble_schema.assemble_summary(node) == "2 parts on bones, 1 skipped"
    assert list(assemble_schema.last_outcome(node)) == ["parts:0"]
    for broken in ("{}", "not json", "[]", '{"parts": {}}'):
        node.params_json = broken
        assert assemble_schema.last_outcome(node) == {}
        assert assemble_schema.assemble_summary(node) == "Assembled character"


def test_outcome_lines_name_the_bone_or_the_estimate():
    from mixar.modules.moodboard.ui.assemble_node_drawer import outcome_text

    assert outcome_text({"status": "attached", "bone": "mixamorig:RightHand", "bone_how": "name",
                         "size_m": 0.93, "size_pct": 52.0}) == "→ mixamorig:RightHand · 0.93 m (52%)"
    assert outcome_text({"status": "placed", "slot": "HAND_L", "bone": "",
                         "bone_how": "estimated", "slot_guessed": True}) == (
        "→ Left hand (estimated, no hand bone found) (guessed)")
    assert outcome_text({"status": "skipped", "notes": ["not generated yet"]}) == (
        "skipped: not generated yet")


def test_drawer_is_read_only():
    tree = ast.parse(_read(MOODBOARD / "ui/assemble_node_drawer.py"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            for target in getattr(node, "targets", [getattr(node, "target", None)]):
                if isinstance(target, ast.Attribute):
                    # Operator properties on the button, never scene data.
                    assert ast.unparse(target) == "op.node_id", ast.unparse(node)


# --------------------------------------------------------------------------- #
# Dispatch, operator report and settings popup
# --------------------------------------------------------------------------- #


def _function_source(path: Path, name: str) -> str:
    tree = ast.parse(_read(path))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    return ast.unparse(function)


def test_dispatch_runs_assemble_locally_before_the_mesh_feature_routing():
    run = _function_source(MOODBOARD / "core/node_execution.py", "run_action_node")
    assemble_at = run.index("node.action_type == 'ASSEMBLE'")
    assert assemble_at < run.index("node.action_type in _MESH_FEATURE_ROUTING")
    branch = run[assemble_at:run.index("_MESH_FEATURE_ROUTING")]
    assert "from .assemble_node import run_assemble_node" in branch
    assert "run_assemble_node(context, node)" in branch
    assert "return None" in branch


def test_run_operator_reports_the_assemble_summary():
    ops = _read(MOODBOARD / "ui/operators/node_graph_ops.py")
    run_op = ops.split("class MIXIE_OT_moodboard_run_action_node")[1].split("\nclass ")[0]
    assert "job = run_action_node(context, node, self)" in run_op
    assert "assemble_summary(node) if job is None" in run_op
    assert "mark_run_failed(node" in run_op
    assert "'UNDO'" not in run_op


def test_settings_popup_hands_assemble_to_its_drawer():
    settings = _function_source(MOODBOARD / "ui/operators/node_settings_ops.py", "_draw_settings")
    assert settings.index("'ASSEMBLE'") < settings.index("draw_section_box(layout)")
    assert "draw_assemble_node(layout, scene, node)" in settings
    drawer = _read(MOODBOARD / "ui/assemble_node_drawer.py")
    assert "'mixie.moodboard_run_action_node'" in drawer
    assert "'mixie.moodboard_reset_node_params'" in drawer


# --------------------------------------------------------------------------- #
# Native card text
# --------------------------------------------------------------------------- #


def test_card_text_names_assemble_in_cpp():
    graph = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    hint = graph.split("static void draw_draft_hint(")[1].split("\nstatic ")[0]
    assert "== 11" in hint and "Attach parts to the body" in hint
    assert hint.index("== 11") < hint.index("== 10") < hint.index('"show_prompt"')
    assert hint.index('"show_prompt"') < hint.index("action_type == 2")
    assert "action_type == 10 || action_type == 11" in graph
    tile = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc")
    assert '"Assemble"' in tile and '"Generate"' in tile
    # Assemble is local: it must not inherit the run operator's queue tooltip.
    run_button = tile.split('"MIXIE_OT_moodboard_run_action_node"')[1]
    assert "if (assemble)" in run_button and "Uses no credits." in run_button
