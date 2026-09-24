# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Viewport deletion retains IDs: source validity must follow scene membership."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.moodboard.core.mesh_sources import mesh_input_objects
from mixar.modules.moodboard.core.node_graph import mesh_source_object_names, node_output_type


class Objects(list):
    def get(self, name):
        return next((obj for obj in self if obj.name == name), None)


def fixture():
    mesh = NS(name='Cone', type='MESH', select_set=Mock())
    source = NS(node_id='source', scene_mesh_reference=True,
                preview_object=mesh, object_names='Cone')
    node = NS(node_id='consumer', action_type='MESH_SEGMENT')
    scene = NS(objects=Objects([mesh]), mixie_moodboard_images=[],
               mixie_moodboard_asset_nodes=[source], mixie_moodboard_action_nodes=[node],
               mixie_moodboard_links=[NS(from_node_id='source', to_node_id='consumer')])
    context = NS(scene=scene, view_layer=NS(objects=Objects([mesh])))
    return context, source, node, mesh


def test_unlinked_mesh_keeps_its_identity_but_loses_output_until_undo():
    context, source, node, mesh = fixture()
    context.scene.objects.clear()
    assert source.preview_object is mesh  # Blender's retained ID, not a null pointer.
    assert mesh_source_object_names(context.scene, source.node_id) == []
    assert node_output_type(context.scene, source.node_id) == ''
    with pytest.raises(ValueError, match='Mesh "Cone" was removed from this scene'):
        mesh_input_objects(context, node)
    context.scene.objects.append(mesh)  # Undo restores the original scene link.
    assert mesh_source_object_names(context.scene, source.node_id) == ['Cone']
    assert node_output_type(context.scene, source.node_id) == 'MESH'
    assert mesh_input_objects(context, node) == [mesh]


@pytest.mark.parametrize('kind', ['PBR_GEN', 'RETOPOLOGY', 'MESH_SEGMENT', 'AUTO_RIG'])
def test_removed_source_fails_before_selection_export_or_enqueue(kind, monkeypatch):
    from mixar.modules.moodboard.core import node_mesh_execution
    from mixar.modules.common.job_queue.core import model_io

    context, source, node, mesh = fixture()
    context.scene.objects.clear()
    node.action_type = kind
    export, enqueue = Mock(), Mock()
    monkeypatch.setattr(model_io, 'export_selected_mesh', export)
    monkeypatch.setattr(node_mesh_execution, 'enqueue_generation', enqueue)
    with pytest.raises(ValueError, match='Select another mesh on its Moodboard node'):
        node_mesh_execution._run_mesh_feature(context, node, None)
    mesh.select_set.assert_not_called()
    export.assert_not_called()
    enqueue.assert_not_called()


def test_same_name_replacement_cannot_revive_an_unlinked_reference():
    context, source, node, mesh = fixture()
    replacement = NS(name='Cone', type='MESH')
    context.scene.objects[:] = [replacement]
    assert mesh_source_object_names(context.scene, source.node_id) == []
    with pytest.raises(ValueError, match='removed from this scene'):
        mesh_input_objects(context, node)


def test_purged_id_retains_a_named_recovery_message():
    context, source, node, mesh = fixture()
    source.preview_object = None
    with pytest.raises(ValueError, match='Mesh "Cone" was removed from this scene'):
        mesh_input_objects(context, node)


def test_empty_reference_explains_how_to_choose_a_mesh():
    context, source, node, mesh = fixture()
    source.preview_object = None
    source.object_names = ''
    with pytest.raises(ValueError, match='Use Select Mesh on the connected Moodboard node'):
        mesh_input_objects(context, node)


def test_excluded_collection_is_not_reported_as_deletion():
    context, source, node, mesh = fixture()
    context.view_layer.objects.clear()
    assert mesh_source_object_names(context.scene, source.node_id) == ['Cone']
    with pytest.raises(ValueError, match='Enable its collection in the Outliner'):
        mesh_input_objects(context, node)
