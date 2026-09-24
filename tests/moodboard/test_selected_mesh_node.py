# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Selected viewport meshes become standalone, connectable Moodboard nodes."""

from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = (
    ROOT
    / "src/scripts/mixar/modules/moodboard/ui/operators/selected_mesh_node_ops.py"
)
NODE_UI = ROOT / "src/source/blender/editors/space_mixie/mixie_draw_moodboard_node_ui.cc"
DRAWER = (
    ROOT
    / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer_draw.cc"
)


class _Collection(list):
    def add(self):
        node = SimpleNamespace(
            node_id="",
            title="3D Asset",
            object_names="",
            preview_object=None,
            position_x=0.0,
            position_y=0.0,
            width=700.0,
            height=700.0,
            selected=False,
        )
        self.append(node)
        return node


class _RelocatingCollection(_Collection):
    """RNA collections can invalidate existing element wrappers when they grow."""

    def add(self):
        self[:] = [SimpleNamespace(**vars(node)) for node in self]
        return super().add()


class _Mesh:
    type = 'MESH'

    def __init__(self, name):
        self.name = name
        self.preview_requests = 0

    def asset_generate_preview(self):
        self.preview_requests += 1


class _Objects(list):
    def get(self, name):
        return next((obj for obj in self if obj.name == name), None)


def _scene():
    old = SimpleNamespace(
        node_id="old",
        title="Old",
        object_names="Old",
        preview_object=None,
        position_x=2000.0,
        position_y=2000.0,
        width=700.0,
        height=700.0,
        selected=True,
    )
    return SimpleNamespace(
        objects=_Objects(),
        mixie_moodboard_images=[],
        mixie_moodboard_textboxes=[],
        mixie_moodboard_action_nodes=[],
        mixie_moodboard_asset_nodes=_Collection([old]),
        mixie_moodboard_links=[],
        mixie_moodboard_active_node_id="old",
    )


def test_selected_mesh_becomes_the_active_asset_node():
    from mixar.modules.moodboard.core.asset_nodes import create_asset_node

    scene = _scene()
    mesh = _Mesh("Hero Head")

    node = create_asset_node(scene, mesh, center=(100.0, 200.0))

    assert node.title == "Hero Head"
    assert node.object_names == "Hero Head"
    assert node.preview_object is mesh
    assert (node.position_x, node.position_y) == (-250.0, -150.0)
    assert node.selected is True
    assert scene.mixie_moodboard_asset_nodes[0].selected is False
    assert scene.mixie_moodboard_active_node_id == node.node_id
    assert mesh.preview_requests == 1


def test_repeated_adds_do_not_stack_asset_cards():
    from mixar.modules.moodboard.core.asset_nodes import create_asset_node

    scene = _scene()
    first = create_asset_node(scene, _Mesh("First"), center=(0.0, 0.0))
    second = create_asset_node(scene, _Mesh("Second"), center=(0.0, 0.0))

    assert (second.position_x, second.position_y) != (
        first.position_x,
        first.position_y,
    )


def test_connections_follow_the_object_pointer_after_a_rename():
    from mixar.modules.moodboard.core.asset_nodes import create_asset_node
    from mixar.modules.moodboard.core.node_graph import mesh_source_object_names

    scene = _scene()
    mesh = _Mesh("Hero Head")
    node = create_asset_node(scene, mesh)
    scene.objects.append(mesh)
    mesh.name = "Hero, Final"

    assert mesh_source_object_names(scene, node.node_id) == ["Hero, Final"]


def test_non_mesh_objects_are_rejected():
    from mixar.modules.moodboard.core.asset_nodes import create_asset_node

    with pytest.raises(ValueError, match="Select a mesh object"):
        create_asset_node(_scene(), SimpleNamespace(type='CURVE'))


def test_readding_a_mesh_reuses_its_identity_position_and_links():
    from mixar.modules.moodboard.core.asset_nodes import create_asset_node

    scene, mesh = _scene(), _Mesh('Hero')
    node = create_asset_node(scene, mesh)
    node.title = 'Custom board title'
    node.position_x = 1234
    scene.mixie_moodboard_links.append(SimpleNamespace(from_node_id=node.node_id))
    mesh.name = 'Renamed, Mesh'
    repeated = create_asset_node(scene, mesh, center=(9999, 9999))
    assert repeated is node and len(scene.mixie_moodboard_asset_nodes) == 2
    assert node.position_x == 1234 and node.title == 'Custom board title'
    assert node.object_names == mesh.name and node.scene_mesh_reference
    assert scene.mixie_moodboard_links[0].from_node_id == node.node_id
    assert mesh.preview_requests == 1


def test_legacy_multi_object_asset_is_not_repurposed_as_a_single_mesh_reference():
    from mixar.modules.moodboard.core.asset_nodes import create_asset_node

    scene, mesh = _scene(), _Mesh('First')
    legacy = scene.mixie_moodboard_asset_nodes[0]
    legacy.preview_object = mesh
    legacy.object_names = 'First,Second'
    node = create_asset_node(scene, mesh)
    assert node is not legacy and node.scene_mesh_reference
    assert legacy.object_names == 'First,Second'


def test_batch_add_keeps_every_mesh_selected_and_the_active_mesh_active():
    from mixar.modules.moodboard.core.asset_nodes import add_mesh_references

    scene, first, second = _scene(), _Mesh('First'), _Mesh('Second')
    scene.mixie_moodboard_asset_nodes = _RelocatingCollection(scene.mixie_moodboard_asset_nodes)
    nodes = add_mesh_references(scene, [first, second, first], active=first)
    assert len(nodes) == 2 and all(n.selected for n in nodes)
    assert all(n.selected for n in scene.mixie_moodboard_asset_nodes[1:])
    assert scene.mixie_moodboard_active_node_id == nodes[0].node_id
    assert (nodes[0].position_x, nodes[0].position_y) != (nodes[1].position_x, nodes[1].position_y)
    assert not scene.mixie_moodboard_asset_nodes[0].selected
    assert add_mesh_references(scene, [first, second]) == nodes
    assert len(scene.mixie_moodboard_asset_nodes) == 3


def test_invalid_batch_is_rejected_before_any_mesh_is_added():
    from mixar.modules.moodboard.core.asset_nodes import add_mesh_references

    scene = _scene()
    with pytest.raises(ValueError):
        add_mesh_references(scene, [_Mesh('Valid'), SimpleNamespace(type='CAMERA')])
    assert len(scene.mixie_moodboard_asset_nodes) == 1


def test_selection_filters_non_meshes_without_requiring_an_active_mesh():
    from mixar.modules.moodboard.core.asset_nodes import selected_mesh_objects

    mesh, camera = _Mesh('Selected'), SimpleNamespace(type='CAMERA')
    context = SimpleNamespace(selected_objects=[camera, mesh], active_object=camera, mode='OBJECT')
    assert selected_mesh_objects(context) == [mesh]
    context.mode = 'EDIT_MESH'
    assert selected_mesh_objects(context) == []


def test_deleted_scene_reference_cannot_bind_to_a_replacement_with_the_same_name():
    from mixar.modules.moodboard.core.asset_nodes import create_asset_node
    from mixar.modules.moodboard.core.node_graph import mesh_source_object_names, node_output_type

    scene = _scene()
    node = create_asset_node(scene, _Mesh('Hero'))
    node.preview_object = None
    assert node.object_names == 'Hero'
    assert mesh_source_object_names(scene, node.node_id) == []
    assert node_output_type(scene, node.node_id) == ''


def test_empty_card_can_be_bound_later_to_the_same_output_as_viewport_add():
    from mixar.modules.moodboard.core.asset_nodes import (
        assign_mesh_reference, create_asset_node, create_empty_mesh_node,
    )
    from mixar.modules.moodboard.core.node_graph import mesh_source_object_names, node_output_type

    scene, mesh = _scene(), _Mesh('Chosen, Mesh')
    scene.objects.append(mesh)
    draft = create_empty_mesh_node(scene, center=(100, 200))
    identity, position = draft.node_id, (draft.position_x, draft.position_y)
    assert draft.title == 'Add Mesh' and draft.preview_object is None
    assert node_output_type(scene, identity) == ''
    assert mesh_source_object_names(scene, identity) == []
    assign_mesh_reference(draft, mesh)
    direct = create_asset_node(_scene(), mesh)
    assert (draft.title, draft.object_names, draft.preview_object, draft.scene_mesh_reference) == (
        direct.title, direct.object_names, direct.preview_object, direct.scene_mesh_reference)
    assert draft.node_id == identity and (draft.position_x, draft.position_y) == position
    assert mesh_source_object_names(scene, identity) == ['Chosen, Mesh']
    assert node_output_type(scene, identity) == 'MESH'
    assert create_asset_node(scene, mesh) is draft


def test_changing_mesh_preserves_custom_title_and_downstream_links():
    from mixar.modules.moodboard.core.asset_nodes import assign_mesh_reference, create_asset_node
    from mixar.modules.moodboard.core.node_graph import mesh_source_object_names

    scene = _scene()
    node = create_asset_node(scene, _Mesh('First'))
    node.title = 'My reference'
    node.frame_id = 'frame'
    link = SimpleNamespace(from_node_id=node.node_id, to_node_id='consumer')
    scene.mixie_moodboard_links.append(link)
    before = (node.node_id, node.position_x, node.position_y, node.width, node.height)
    second = _Mesh('Second')
    scene.objects.append(second)
    assign_mesh_reference(node, second)
    assert mesh_source_object_names(scene, link.from_node_id) == ['Second']
    assert node.title == 'My reference' and node.frame_id == 'frame'
    assert before == (node.node_id, node.position_x, node.position_y, node.width, node.height)
    assert scene.mixie_moodboard_links == [link]
    with pytest.raises(ValueError):
        assign_mesh_reference(node, SimpleNamespace(type='LIGHT'))
    assert mesh_source_object_names(scene, node.node_id) == ['Second']


def test_empty_mesh_template_is_offline_and_does_not_capture_selection(monkeypatch):
    from mixar.modules.moodboard.core import node_templates

    monkeypatch.setattr(node_templates, 'capability_available', lambda key: False)
    scene = _scene()
    first = node_templates.create_template(scene, 'MESH_REFERENCE', (100, 200))
    second = node_templates.create_template(scene, 'MESH_REFERENCE', (100, 200))
    assert first.preview_object is second.preview_object is None
    assert first.node_id != second.node_id
    assert (first.position_x, first.position_y) != (second.position_x, second.position_y)
    exact = node_templates.create_template(scene, 'MESH_REFERENCE', (123, 456), exact_position=True)
    assert exact.position_x + exact.width / 2 == 123
    assert exact.position_y + exact.height / 2 == 456


def test_viewport_object_menu_registers_the_mesh_action():
    source = OPERATOR.read_text(encoding="utf-8")

    assert 'bl_idname = "mixie.add_selected_mesh_to_moodboard"' in source
    assert "VIEW3D_MT_object_context_menu.prepend(_draw_object_context_menu)" in source
    assert "VIEW3D_MT_object_context_menu.remove(_draw_object_context_menu)" in source
    draw = source.split("def _draw_object_context_menu")[1].split("classes =")[0]
    assert draw.index("self.layout.operator(") < draw.index("self.layout.separator()")
    assert "selected_mesh_objects(context)" in source
    assert "cls.poll_message_set(\"Select a mesh in Object Mode\")" in source
    assert "bpy.ops.view3d.moodboard_drawer_reveal('EXEC_DEFAULT')" in source


def test_asset_node_draws_its_object_preview_and_suppresses_the_empty_hint():
    node_ui = NODE_UI.read_text(encoding="utf-8")
    drawer = (NODE_UI.parent / "mixie_draw_moodboard_chrome.cc").read_text(encoding="utf-8")

    assert '"mixie_moodboard_asset_nodes"' in node_ui
    assert "add_asset_preview(C, v2d, region, block, &iter.ptr, object_previews)" in node_ui
    preview = node_ui.split("static void add_asset_preview(", 1)[1].split(
        "void mixie_draw_moodboard_graph_controls(", 1)[0]
    assert preview.index("moodboard_node_controls_rect(") < preview.index(
        '"MIXIE_OT_moodboard_select_mesh"')
    assert '"mixie_moodboard_asset_nodes"' in drawer


def test_a_short_mesh_list_uses_a_sized_menu():
    source = (
        ROOT / "src/scripts/mixar/modules/moodboard/ui/operators/mesh_reference_ops.py"
    ).read_text(encoding="utf-8")
    assert "_COMPACT_MESH_MENU_LIMIT = 8" in source
    assert "popup_menu(draw, title=\"Select Mesh\")" in source
    assert "return {'INTERFACE'}" in source
    assert "invoke_search_popup(self)" in source
