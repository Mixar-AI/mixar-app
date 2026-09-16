# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Result consumers must not link stale, partial, or same-name replacement objects."""
import json
from types import SimpleNamespace

import bpy
import pytest

from mixar.modules.common.render_visibility.result import read_result, resolve_meshes
from mixar.modules.common.render_visibility.collect import create_collection


def capture(status="complete", **changes):
    result = dict(schema_version=1, status=status, scene_session_uid=10,
                  objects=[dict(session_uid=20, name="Original name")])
    result.update(changes)
    return result


def scene_for(result):
    return SimpleNamespace(session_uid=10, render=SimpleNamespace(
        visible_objects_json=json.dumps(result)))


@pytest.mark.parametrize("status", ["disabled", "unavailable", "capturing", "cancelled", "error"])
def test_partial_results_are_not_empty_success(status):
    with pytest.raises(RuntimeError, match="No completed"):
        read_result(scene_for(capture(status)))


def test_empty_completed_capture_is_valid():
    assert read_result(scene_for(capture(objects=[])))["objects"] == []


def test_wrong_scene_is_rejected():
    with pytest.raises(RuntimeError, match="different scene"):
        read_result(scene_for(capture(scene_session_uid=11)))


def test_renamed_mesh_resolves_by_identity(monkeypatch):
    mesh = SimpleNamespace(session_uid=20, name="Renamed", type="MESH")
    monkeypatch.setattr(bpy.data, "objects", [mesh])
    assert resolve_meshes(scene_for(capture())) == [mesh]


def test_same_name_replacement_is_rejected_before_collection_creation(monkeypatch):
    mesh = SimpleNamespace(session_uid=99, name="Original name", type="MESH")
    monkeypatch.setattr(bpy.data, "objects", [mesh])
    created = []
    monkeypatch.setattr(bpy.data.collections, "new", lambda name: created.append(name))
    with pytest.raises(RuntimeError, match="no longer exist"):
        create_collection(scene_for(capture()))
    assert created == []


def test_collection_links_original_mesh_without_duplication(monkeypatch):
    mesh = SimpleNamespace(session_uid=20, name="Original name", type="MESH")
    monkeypatch.setattr(bpy.data, "objects", [mesh])
    linked_objects, linked_collections = [], []
    collection = SimpleNamespace(objects=SimpleNamespace(link=linked_objects.append))
    monkeypatch.setattr(bpy.data.collections, "new", lambda name: collection)
    scene = scene_for(capture())
    scene.collection = SimpleNamespace(children=SimpleNamespace(link=linked_collections.append))
    assert create_collection(scene) is collection
    assert linked_objects == [mesh]
    assert linked_collections == [collection]
