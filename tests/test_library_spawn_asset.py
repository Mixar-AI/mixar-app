# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Add to Scene links the asset into a collection the viewport can see.

``bpy`` is mocked. The loader, the view layer and the frame override are
fakes, so this pins the placement rules without a Blender build.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.agent_bubble.core import spawn_asset


class _Loc:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class _Identity:
    def __matmul__(self, other):
        return other


class _Objects:
    def __init__(self):
        self._items = []

    def __iter__(self):
        return iter(self._items)

    def __contains__(self, name):
        return any(item.name == name for item in self._items)

    def link(self, item):
        self._items.append(item)


class _Obj:
    def __init__(self, name, bound_box=None):
        self.name = name
        self.type = "MESH"
        self.bound_box = bound_box if bound_box is not None else [(-1, -1, 0), (1, 1, 2)]
        self.matrix_world = _Identity()
        self.location = _Loc()
        self.parent = None
        self.hide_viewport = True
        self.hidden = True
        self.selected = False
        self.mode = "OBJECT"

    def select_set(self, value):
        self.selected = bool(value)

    def hide_set(self, value):
        self.hidden = bool(value)


class _Collection:
    def __init__(self, name):
        self.name = name
        self.objects = _Objects()
        self.children = _Objects()
        self.hide_viewport = False
        self.all_objects = []


class _LayerColl:
    def __init__(self, collection, exclude=False, hide=False, children=None):
        self.collection = collection
        self.exclude = exclude
        self.hide_viewport = hide
        self.children = children or []


class _ViewObjects:
    def __init__(self):
        self._items = []
        self.active = None

    def __iter__(self):
        return iter(list(self._items))


class _ViewLayer:
    def __init__(self, root, active, exclude=False):
        self.objects = _ViewObjects()
        active_layer = _LayerColl(active, exclude=exclude)
        self.layer_collection = _LayerColl(root, children=[active_layer])
        self.active_layer_collection = active_layer
        self.updates = 0

    def update(self):
        self.updates += 1


class _Region:
    type = "WINDOW"


class _Area:
    def __init__(self):
        self.type = "VIEW_3D"
        self.regions = [_Region()]
        self.spaces = []
        self.redraws = 0

    def tag_redraw(self):
        self.redraws += 1


class _Window:
    def __init__(self, scene, view_layer, view3d=True):
        self.scene = scene
        self.view_layer = view_layer
        self.screen = type("Screen", (), {"areas": [_Area()] if view3d else []})()


class _Override:
    def __init__(self, record, kwargs):
        self.record = record
        self.kwargs = kwargs

    def __enter__(self):
        self.record.append(self.kwargs)
        return self

    def __exit__(self, *_exc):
        return False


class _Load:
    def __init__(self, source, dest, make):
        self.source = source
        self.dest = dest
        self.make = make

    def __enter__(self):
        return self.source, self.dest

    def __exit__(self, *_exc):
        self.dest.objects = [self.make(name) for name in self.dest.objects]
        self.dest.collections = [self.make(name) for name in self.dest.collections]
        return False


class _From:
    def __init__(self, objects=(), collections=()):
        self.objects = list(objects)
        self.collections = list(collections)


class _To:
    def __init__(self):
        self.objects = []
        self.collections = []


def _world(scene, view_layer, *, bubble=None, main=None):
    bubble = bubble or _Window(scene, view_layer, view3d=False)
    main = main or _Window(scene, view_layer, view3d=True)
    overrides = []

    class _Context:
        def temp_override(self, **kwargs):
            return _Override(overrides, kwargs)

    # Assigned after the class body. A `scene = scene` statement inside the
    # class would bind the name locally and fail to see the argument.
    context = _Context()
    context.window = bubble
    context.window_manager = type("WM", (), {"windows": [bubble, main]})()
    context.scene = scene
    context.view_layer = view_layer
    return context, overrides, main


def _patch_load(monkeypatch, names, factory):
    calls = []

    def load(path, link=False):
        calls.append((path, link))
        return _Load(_From(objects=names, collections=names), _To(), factory)

    monkeypatch.setattr(spawn_asset.bpy.data.libraries, "load", load)
    framed = []
    monkeypatch.setattr(
        spawn_asset.bpy.ops.view3d, "view_selected", lambda: framed.append("framed")
    )
    monkeypatch.setattr(spawn_asset.bpy.ops.object, "mode_set", lambda **_kwargs: None)
    monkeypatch.setattr(
        spawn_asset.bpy.ops.object, "duplicates_make_real", lambda **_kwargs: None
    )
    return calls, framed


def test_a_mesh_lands_in_the_visible_collection_and_is_framed(tmp_path, monkeypatch):
    blend = tmp_path / "fox.blend"
    blend.write_bytes(b"blend")
    scene_coll = _Collection("Scene Collection")
    hidden = _Collection("Hidden")
    scene = type("Scene", (), {"collection": scene_coll, "cursor": type("C", (), {"location": _Loc(10, 20, 30)})()})()
    view_layer = _ViewLayer(scene_coll, hidden, exclude=True)
    context, overrides, main = _world(scene, view_layer)
    fox = _Obj("Fox 01abcd")
    calls, framed = _patch_load(monkeypatch, ["Fox 01abcd"], lambda _name: fox)

    ok, message = spawn_asset.spawn_library_asset(context, str(blend), "Object", "Fox 01abcd")

    assert ok, message
    assert calls == [(str(blend), False)]
    assert fox in scene_coll.objects._items
    assert fox not in hidden.objects._items
    assert fox.location == (10.0, 20.0, 30.0)
    assert fox.selected and not fox.hidden and not fox.hide_viewport
    assert view_layer.objects.active is fox
    assert framed == ["framed"]
    assert overrides and overrides[-1]["window"] is main
    assert overrides[-1]["area"].type == "VIEW_3D"
    assert main.screen.areas[0].redraws == 1


def test_an_excluded_active_collection_is_not_where_it_links(tmp_path, monkeypatch):
    blend = tmp_path / "mesh.blend"
    blend.write_bytes(b"blend")
    scene_coll = _Collection("Scene Collection")
    active = _Collection("Active")
    scene = type("Scene", (), {"collection": scene_coll, "cursor": type("C", (), {"location": _Loc()})()})()
    view_layer = _ViewLayer(scene_coll, active, exclude=False)
    context, _overrides, _main = _world(scene, view_layer)
    mesh = _Obj("Mesh")
    _patch_load(monkeypatch, ["Mesh"], lambda _name: mesh)

    ok, message = spawn_asset.spawn_library_asset(context, str(blend), "", "Mesh")

    assert ok, message
    assert mesh in active.objects._items
    assert mesh not in scene_coll.objects._items


def test_a_name_with_a_slash_is_the_datablock_name(tmp_path, monkeypatch):
    blend = tmp_path / "odd.blend"
    blend.write_bytes(b"blend")
    scene_coll = _Collection("Scene Collection")
    scene = type("Scene", (), {"collection": scene_coll, "cursor": type("C", (), {"location": _Loc()})()})()
    view_layer = _ViewLayer(scene_coll, scene_coll)
    context, _overrides, _main = _world(scene, view_layer)
    asset = _Obj("a/b")
    calls, _framed = _patch_load(monkeypatch, ["a/b"], lambda _name: asset)

    ok, message = spawn_asset.spawn_library_asset(context, str(blend), "Object", "a/b")

    assert ok, message
    assert calls[0][0] == str(blend)
    assert asset in scene_coll.objects._items


def test_a_collection_is_linked_and_its_members_move(tmp_path, monkeypatch):
    blend = tmp_path / "kit.blend"
    blend.write_bytes(b"blend")
    scene_coll = _Collection("Scene Collection")
    scene = type("Scene", (), {"collection": scene_coll, "cursor": type("C", (), {"location": _Loc(0, 0, 5)})()})()
    view_layer = _ViewLayer(scene_coll, scene_coll)
    context, _overrides, _main = _world(scene, view_layer)
    member = _Obj("Part", bound_box=[(0, 0, 1), (2, 2, 3)])
    coll = _Collection("Kit")
    coll.all_objects = [member]

    def factory(name):
        return coll if name == "Kit" else member

    _patch_load(monkeypatch, ["Kit"], factory)

    ok, message = spawn_asset.spawn_library_asset(context, str(blend), "Collection", "Kit")

    assert ok, message
    assert coll in scene_coll.children._items
    assert member.location == (-1.0, -1.0, 4.0)
    assert member.selected


def test_materials_and_missing_files_are_refused(tmp_path, monkeypatch):
    blend = tmp_path / "mat.blend"
    blend.write_bytes(b"blend")
    calls, _framed = _patch_load(monkeypatch, ["Paint"], lambda name: _Obj(name))
    context, _overrides, _main = _world(
        type("Scene", (), {"collection": _Collection("Scene"), "cursor": type("C", (), {"location": _Loc()})()})(),
        _ViewLayer(_Collection("Scene"), _Collection("Scene")),
    )

    ok, message = spawn_asset.spawn_library_asset(context, str(blend), "Material", "Paint")
    assert not ok
    assert "objects and collections" in message
    assert calls == []

    ok, message = spawn_asset.spawn_library_asset(context, str(tmp_path / "gone.blend"), "Object", "Paint")
    assert not ok
    assert "missing" in message


def test_a_datablock_that_did_not_load_is_not_reported_as_added(tmp_path, monkeypatch):
    blend = tmp_path / "empty.blend"
    blend.write_bytes(b"blend")
    _patch_load(monkeypatch, ["Other"], lambda name: _Obj(name))
    scene_coll = _Collection("Scene")
    context, _overrides, _main = _world(
        type("Scene", (), {"collection": scene_coll, "cursor": type("C", (), {"location": _Loc()})()})(),
        _ViewLayer(scene_coll, scene_coll),
    )

    ok, message = spawn_asset.spawn_library_asset(context, str(blend), "Object", "Fox")

    assert not ok
    assert "not in that file" in message
    assert scene_coll.objects._items == []


def test_edit_mode_is_left_before_the_new_object_is_selected(tmp_path, monkeypatch):
    blend = tmp_path / "fox.blend"
    blend.write_bytes(b"blend")
    scene_coll = _Collection("Scene")
    scene = type("Scene", (), {"collection": scene_coll, "cursor": type("C", (), {"location": _Loc()})()})()
    view_layer = _ViewLayer(scene_coll, scene_coll)
    editing = _Obj("Cube")
    editing.mode = "EDIT"
    view_layer.objects.active = editing
    view_layer.objects._items = [editing]
    context, overrides, _main = _world(scene, view_layer)
    fox = _Obj("Fox")
    modes = []
    _patch_load(monkeypatch, ["Fox"], lambda _name: fox)
    monkeypatch.setattr(
        spawn_asset.bpy.ops.object,
        "mode_set",
        lambda **kwargs: modes.append(kwargs) or editing.__setattr__("mode", "OBJECT"),
    )

    ok, message = spawn_asset.spawn_library_asset(context, str(blend), "Object", "Fox")

    assert ok, message
    assert modes == [{"mode": "OBJECT"}]
    assert overrides[0]["area"].type == "VIEW_3D"
    assert fox.selected
