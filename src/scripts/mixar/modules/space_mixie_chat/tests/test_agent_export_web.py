# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ``web`` (three.js) glTF export: groups, cameras and punctual lights
staged with the meshes (``export_web``), what glTF cannot carry reported,
and the read-back counting lights and cameras — pinned on fake objects.
"""

from types import SimpleNamespace

from test_agent_export_workflow import (  # noqa: F401 — fake_scene is a fixture
    _Fake,
    _no_paths,
    agent_export,
    export_destination,
    fake_scene,
)
def _web_obj(name, kind, parent=None, light=None, visible=True):
    return _Fake(name=name, type=kind, parent=parent, hide_render=False,
                 data=SimpleNamespace(type=light) if light else None,
                 visible_get=lambda: visible, select_set=lambda *_: None)


def _web_scene(world=None):
    group = _web_obj("Props", "EMPTY", parent=_web_obj("Root", "EMPTY"))
    mesh = _web_obj("Chair", "MESH", parent=group)
    objects = [group, group.parent, mesh,
               _web_obj("Cam", "CAMERA"), _web_obj("Sun", "LIGHT", light="SUN"),
               _web_obj("Lamp", "LIGHT", light="POINT"), _web_obj("Softbox", "LIGHT", light="AREA"),
               _web_obj("HiddenCam", "CAMERA", visible=False)]
    return SimpleNamespace(objects=objects, world=world), mesh


def test_web_scene_export_stages_groups_cameras_and_punctual_lights():
    from mixar.modules.space_mixie_chat.core import export_web

    hdri = SimpleNamespace(use_nodes=True, node_tree=SimpleNamespace(
        nodes=[SimpleNamespace(type="TEX_ENVIRONMENT")]))
    scene, mesh = _web_scene(world=hdri)
    extra, counts, warning = export_web.web_scene_objects([mesh], "scene", scene)
    assert sorted(o.name for o in extra) == ["Cam", "Lamp", "Props", "Root", "Sun"]
    assert counts == {"lights": 2, "cameras": 1, "groups": 2,
                      "area_lights_skipped": 1, "world_lighting": True}
    assert "area light" in warning and "scene.environment" in warning
    # A named / selected export keeps the hierarchy but never drags in the
    # scene's camera and lights.
    extra, counts, warning = export_web.web_scene_objects([mesh], "named", scene)
    assert sorted(o.name for o in extra) == ["Props", "Root"]
    assert counts["lights"] == 0 and counts["cameras"] == 0 and warning == ""
    assert export_web.is_web_gltf("web", "glb") and export_web.is_web_gltf("WEB", "gltf")
    assert not export_web.is_web_gltf("web", "fbx") and not export_web.is_web_gltf("godot", "glb")


def test_web_run_export_selects_staged_objects_and_reports_them(fake_scene, monkeypatch):
    from mixar.modules.space_mixie_chat.core import export_web

    selected = []
    camera = _web_obj("Cam", "CAMERA")
    camera.select_set = lambda state: selected.append(("Cam", state))
    monkeypatch.setattr(agent_export, "web_scene_objects", lambda meshes, scope, scene: (
        {camera}, {"lights": 0, "cameras": 1, "groups": 0, "area_lights_skipped": 0},
        "The World (sky or HDRI) is not part of glTF."))
    assert export_web.is_web_gltf("web", "glb")
    dest = str(fake_scene.tmp / "Room.glb")
    export_destination.set_destination("sess", dest)
    result = agent_export.run_export("sess", {"format": "glb", "target_scope": "scene",
                                              "use_case": "web", "animations": []})
    assert result["success"] is True, result
    assert ("Cam", True) in selected
    assert result["scene_objects"]["cameras"] == 1
    assert "not part of glTF" in result["warning"]
    kwargs = fake_scene.calls["exporter"][0]
    assert kwargs["export_cameras"] is True and kwargs["export_lights"] is True
    # The fake GLB holds no camera, so the read-back flags the missing one.
    assert result["verification"]["cameras"] == 0
    assert any("camera" in issue for issue in result["verification"]["issues"])
    _no_paths(result)


def test_non_web_export_carries_no_scene_objects(fake_scene):
    export_destination.set_destination("sess", str(fake_scene.tmp / "Hero.glb"))
    result = agent_export.run_export("sess", {"format": "glb", "target_scope": "scene",
                                              "use_case": "godot"})
    assert result["success"] is True and "scene_objects" not in result
