# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent export workflow (export contract §1–§6): the ``export_scene``
runner, its ``use_case`` presets, clip selection and the picker-less
folder kinds — pinned outside Blender on fake objects.
"""

import ast
import os
import sys
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import (  # noqa: E402
    agent_export,
    export_clips,
    export_destination,
    export_presets,
)
from _export_support import write_glb  # noqa: E402

_OPS_DIR = os.path.join(os.path.dirname(__file__), "..", "ui", "operators")


class _Fake:
    """Attribute bag that is hashable like a real bpy ID (set membership)."""

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def _no_paths(value):
    """Every string in a result must be a basename / kind, never a path."""
    if isinstance(value, dict):
        for v in value.values():
            _no_paths(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _no_paths(v)
    elif isinstance(value, str):
        assert "/" not in value and "\\" not in value, value


# ---------------------------------------------------------------------------
# §4 presets
# ---------------------------------------------------------------------------


def test_presets_cover_every_use_case_and_exporter():
    assert set(export_presets.PRESETS) == set(export_presets.USE_CASES)
    for use_case, table in export_presets.PRESETS.items():
        assert set(table) == {"fbx", "gltf", "usd"}, use_case
        for fmt in ("fbx", "glb", "gltf", "obj", "usd", "usdz"):
            kwargs = export_presets.preset_kwargs(use_case, fmt)
            family = export_presets.exporter_family(fmt)
            if family == "fbx":
                assert kwargs["use_selection"] and kwargs["object_types"] == {"MESH", "ARMATURE"}
                assert kwargs["path_mode"] == "COPY" and kwargs["embed_textures"] is True
                assert kwargs["axis_forward"] == "-Z" and kwargs["axis_up"] == "Y"
            elif family == "gltf":
                assert kwargs["use_selection"] and kwargs["export_yup"] is True
                assert kwargs["export_cameras"] is False and kwargs["export_lights"] is False
                assert kwargs["export_draco_mesh_compression_enable"] is False
            elif family == "usd":
                assert kwargs["selected_objects_only"] and kwargs["export_cameras"] is False
            else:
                assert kwargs["export_selected_objects"] is True
    assert agent_export.PRESETS is export_presets.PRESETS


def test_preset_table_matches_the_contract_rows():
    unreal = export_presets.preset_kwargs("unreal", "fbx")
    assert unreal["apply_scale_options"] == "FBX_SCALE_NONE"
    assert unreal["primary_bone_axis"] == "Y" and unreal["secondary_bone_axis"] == "X"
    assert unreal["bake_anim_use_all_bones"] is True and unreal["add_leaf_bones"] is False
    unity = export_presets.preset_kwargs("unity", "fbx")
    assert unity["apply_scale_options"] == "FBX_SCALE_UNITS"
    assert unity["bake_anim_use_all_bones"] is False
    assert export_presets.preset_kwargs("godot", "fbx") == unity
    godot = export_presets.preset_kwargs("godot", "glb")
    assert godot["export_apply"] is True and godot["export_tangents"] is True
    assert godot["export_image_format"] == "AUTO"
    assert export_presets.preset_kwargs("web", "glb") == godot
    assert export_presets.preset_kwargs("other", "fbx")["apply_scale_options"] == "FBX_SCALE_ALL"
    ar = export_presets.preset_kwargs("ar", "usdz")
    assert ar["convert_orientation"] is True and ar["export_textures_mode"] == "NEW"
    assert "export_textures" not in ar  # not a Blender 5.2 usd_export property
    assert "convert_orientation" not in export_presets.preset_kwargs("other", "usd")
    # Unknown use cases fall back to "other" instead of failing the export.
    assert export_presets.preset_kwargs("vr", "fbx") == export_presets.preset_kwargs("other", "fbx")


def test_preset_report_carries_the_documented_keys():
    kwargs = export_presets.preset_kwargs("unreal", "fbx")
    report = export_presets.preset_report("unreal", "fbx", kwargs, "all")
    for key in ("use_case", "axis_forward", "axis_up", "scale", "leaf_bones",
                "animation_mode", "tangents"):
        assert key in report
    assert report["use_case"] == "unreal" and report["scale"] == "FBX_SCALE_NONE"
    assert report["axis_up"] == "Y" and report["leaf_bones"] is False
    glb = export_presets.preset_report("web", "glb", export_presets.preset_kwargs("web", "glb"), "none")
    assert glb["axis_up"] == "Y" and glb["draco"] is False and glb["embed_textures"] is True


# ---------------------------------------------------------------------------
# §3 clip selection
# ---------------------------------------------------------------------------


class _Strips(list):
    def new(self, name, start, action):
        strip = SimpleNamespace(name=name, action=action, frame_start=start, mute=False)
        self.append(strip)
        return strip


class _Tracks(list):
    def new(self):
        track = SimpleNamespace(name="", mute=False, strips=_Strips())
        self.append(track)
        return track

    def remove(self, track):
        list.remove(self, track)


def _action(name):
    return SimpleNamespace(name=name, frame_range=(1.0, 24.0))


def _armature(action=None, tracks=()):
    nla = _Tracks()
    for track_name, strips in tracks:
        track = nla.new()
        track.name = track_name
        for strip_name, strip_action in strips:
            track.strips.new(strip_name, 1, strip_action)
    anim = SimpleNamespace(action=action, nla_tracks=nla)
    return _Fake(name="Rig", type="ARMATURE", animation_data=anim, select_set=lambda *_: None)


def test_select_clips_matches_case_sensitive_then_insensitive():
    walk, run = _action("Walk"), _action("Run")
    rig = _armature(action=run, tracks=[("Locomotion", [("Walk", walk)]), ("Idle", [("idle_loop", _action("Idle"))])])
    assert export_clips.scene_clips([rig]) == ["Run", "Walk", "idle_loop", "Idle"]
    assert export_clips.select_clips([rig], None) == (["Run", "Walk", "idle_loop", "Idle"], [])
    assert export_clips.select_clips([rig], []) == ([], [])
    assert export_clips.select_clips([rig], ["walk", "Idle", "Jump"]) == (["Walk", "Idle"], ["Jump"])
    # No armature: every requested clip is missing.
    assert export_clips.select_clips([], ["Walk"]) == ([], ["Walk"])


def test_clip_selection_mutes_non_matching_tracks_and_restores_everything():
    walk, run = _action("Walk"), _action("Run")
    rig = _armature(action=run, tracks=[("Locomotion", [("Walk", walk)]), ("Idle", [("Idle", _action("Idle"))])])
    rig.animation_data.nla_tracks[1].mute = True  # already muted by the user
    scene = SimpleNamespace(frame_current=17, frame_set=lambda f: setattr(scene, "frame_current", f))
    with export_clips.clip_selection([rig], ["Walk"], scene) as (selected, missing):
        assert selected == ["Walk"] and missing == []
        tracks = rig.animation_data.nla_tracks
        assert [t.mute for t in tracks[:2]] == [False, True]
        # The active action (Run) was not requested: it must not be written.
        assert rig.animation_data.action is None
        assert len(tracks) == 2  # Walk is on a track already: nothing pushed
        scene.frame_current = 3
    tracks = rig.animation_data.nla_tracks
    assert [t.mute for t in tracks] == [False, True]
    assert rig.animation_data.action is run
    assert scene.frame_current == 17


def test_clip_selection_unmutes_the_matching_track_and_restores_it():
    # The normal state after the character-to-game workflow: every clip is
    # on a MUTED track. The FBX exporter skips a muted track, so a requested
    # clip must be force-unmuted for the export and put back afterwards.
    walk, run = _action("Walk"), _action("Run")
    rig = _armature(action=None, tracks=[("Walk", [("Walk", walk)]), ("Run", [("Run", run)])])
    for track in rig.animation_data.nla_tracks:
        track.mute = True
        for strip in track.strips:
            strip.mute = True
    with export_clips.clip_selection([rig], ["Walk"], None) as (selected, missing):
        assert selected == ["Walk"] and missing == []
        walk_track, run_track = rig.animation_data.nla_tracks
        assert walk_track.mute is False and run_track.mute is True
        assert walk_track.strips[0].mute is False and run_track.strips[0].mute is True
    walk_track, run_track = rig.animation_data.nla_tracks
    assert walk_track.mute is True and run_track.mute is True
    assert walk_track.strips[0].mute is True and run_track.strips[0].mute is True


def test_clip_selection_pushes_a_matching_active_action_temporarily():
    run = _action("Run")
    rig = _armature(action=run, tracks=[("Locomotion", [("Walk", _action("Walk"))])])
    with export_clips.clip_selection([rig], ["Run"], None) as (selected, missing):
        tracks = rig.animation_data.nla_tracks
        assert selected == ["Run"] and missing == []
        assert len(tracks) == 2 and tracks[1].strips[0].action is run
        assert tracks[0].mute is True and tracks[1].mute is False
        assert rig.animation_data.action is None
    assert len(rig.animation_data.nla_tracks) == 1
    assert rig.animation_data.nla_tracks[0].mute is False
    assert rig.animation_data.action is run


def test_clip_selection_restores_on_exporter_failure():
    rig = _armature(action=None, tracks=[("A", [("A", _action("A"))]), ("B", [("B", _action("B"))])])
    with pytest.raises(RuntimeError):
        with export_clips.clip_selection([rig], ["A"], None):
            assert rig.animation_data.nla_tracks[1].mute is True
            raise RuntimeError("exporter blew up")
    assert [t.mute for t in rig.animation_data.nla_tracks] == [False, False]


def test_animation_kwargs_per_format():
    assert export_clips.animation_kwargs("glb", None) == ({"export_animations": True}, "all", "")
    assert export_clips.animation_kwargs("glb", []) == ({"export_animations": False}, "none", "")
    assert export_clips.animation_kwargs("gltf", ["Walk"])[0] == {
        "export_animations": True, "export_animation_mode": "ACTIONS"}
    assert export_clips.animation_kwargs("fbx", ["Walk"])[0] == {
        "bake_anim": True, "bake_anim_use_nla_strips": True, "bake_anim_use_all_actions": False}
    assert export_clips.animation_kwargs("fbx", [])[0] == {"bake_anim": False}
    kwargs, mode, warning = export_clips.animation_kwargs("usdz", ["Walk"])
    assert kwargs == {"export_animation": True} and mode == "selected" and "USD" in warning
    assert export_clips.animation_kwargs("usd", [])[0] == {"export_animation": False}
    assert export_clips.animation_kwargs("obj", ["Walk"]) == ({}, "none", "")


# ---------------------------------------------------------------------------
# folders + unique names
# ---------------------------------------------------------------------------


def test_unique_path_never_overwrites(tmp_path):
    first = agent_export._unique_path(str(tmp_path), "Hero", ".glb")
    assert first == str(tmp_path / "Hero.glb")
    (tmp_path / "Hero.glb").write_bytes(b"x")
    (tmp_path / "Hero_2.glb").write_bytes(b"x")
    assert agent_export._unique_path(str(tmp_path), "Hero", ".glb") == str(tmp_path / "Hero_3.glb")


def test_safe_stem_strips_extension_and_junk():
    assert agent_export.safe_stem("../Hero.glb", ".glb") == "_Hero"
    assert "/" not in agent_export.safe_stem("/etc/passwd", "")
    assert agent_export.safe_stem("", ".glb") == "export"
    assert agent_export.safe_stem("a" * 100, "")[:72] == "a" * 72


def test_resolve_export_folder_kinds(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(agent_export.os.path, "expanduser", lambda p: str(home))
    lib = SimpleNamespace(path=str(tmp_path / "lib"))
    fake_bpy = SimpleNamespace(
        context=SimpleNamespace(preferences=SimpleNamespace(filepaths=SimpleNamespace(asset_libraries=[lib]))),
        path=SimpleNamespace(abspath=lambda p: p),
        app=SimpleNamespace(tempdir=str(tmp_path / "tmp")),
    )
    monkeypatch.setattr(agent_export, "bpy", fake_bpy)
    assert agent_export.resolve_export_folder("downloads") == str(home / "Downloads")
    assert agent_export.resolve_export_folder("library") == str(tmp_path / "lib" / "exports")
    assert agent_export.resolve_export_folder("temp") == str(tmp_path / "tmp" / "mixar_exports")
    fake_bpy.context.preferences.filepaths.asset_libraries = []
    assert agent_export.resolve_export_folder("library") == str(tmp_path / "tmp" / "mixar_exports")
    assert set(agent_export.FOLDER_KINDS) == {"downloads", "library", "temp"}


# ---------------------------------------------------------------------------
# run_export / run_export_to on a fake scene
# ---------------------------------------------------------------------------


def _mesh(name):
    return _Fake(name=name, type="MESH", parent=None, modifiers=[], mode="OBJECT",
                 active_material_index=0, data=SimpleNamespace(materials=[]),
                 select_set=lambda *_: None)


@pytest.fixture
def fake_scene(monkeypatch, tmp_path):
    meshes = [_mesh("Hero"), _mesh("Sword")]
    calls = {"exporter": []}
    fake_bpy = SimpleNamespace(
        context=SimpleNamespace(
            view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
            selected_objects=[], scene=SimpleNamespace(frame_current=1),
        ),
        ops=SimpleNamespace(object=SimpleNamespace(
            select_all=MagicMock(poll=lambda: True), mode_set=MagicMock())),
        data=SimpleNamespace(materials=MagicMock()),
    )
    monkeypatch.setattr(agent_export, "bpy", fake_bpy)
    monkeypatch.setattr(agent_export, "resolve_targets", lambda scope, names: meshes)
    monkeypatch.setattr(agent_export, "run_preflight", lambda spec: {"ready": False})
    monkeypatch.setattr(agent_export, "_temporary_export_materials", lambda meshes: nullcontext())

    def exporter(filepath, **kwargs):
        calls["exporter"].append(kwargs)
        write_glb(filepath, meshes=2, animations=["Walk"])
        return {"FINISHED"}

    monkeypatch.setattr(agent_export, "_exporter", lambda fmt: exporter)
    monkeypatch.setattr(agent_export, "_required_armatures", lambda meshes: {
        _armature(action=_action("Walk"), tracks=[("T", [("Idle", _action("Idle"))])])})
    export_destination.clear_all_destinations()
    yield SimpleNamespace(bpy=fake_bpy, meshes=meshes, calls=calls, tmp=tmp_path)
    export_destination.clear_all_destinations()


def test_run_export_reports_basename_preset_clips_and_verification(fake_scene, monkeypatch):
    events = []
    from mixar.modules.common.analytics import export_events
    monkeypatch.setattr(export_events, "capture", lambda e, p, context=None: events.append((e, p)))
    dest = str(fake_scene.tmp / "Hero.glb")
    export_destination.set_destination("sess", dest)
    spec = {"format": "glb", "target_scope": "scene", "use_case": "unreal",
            "suggested_filename": "Hero", "destination": "ask", "animations": ["walk", "Jump"]}
    result = agent_export.run_export("sess", spec)
    assert result["success"] is True, result
    assert result["filepath_basename"] == "Hero.glb" and result["format"] == "glb"
    assert result["mesh_count"] == 2 and result["armature_count"] == 1
    assert result["mesh_names"] == ["Hero", "Sword"]
    assert result["file_size_bytes"] == os.path.getsize(dest)
    assert result["clips"] == ["Walk"] and result["clips_requested"] == ["walk", "Jump"]
    assert result["clips_missing"] == ["Jump"]
    assert result["preset"]["use_case"] == "unreal" and result["preset"]["animation_mode"] == "selected"
    assert result["verification"]["checked"] is True and result["verification"]["passed"] is True
    assert isinstance(result["duration_ms"], int)
    assert "folder" not in result
    _no_paths(result)
    kwargs = fake_scene.calls["exporter"][0]
    assert kwargs["export_format"] == "GLB" and kwargs["export_animation_mode"] == "ACTIONS"
    assert kwargs["export_yup"] is True and kwargs["use_selection"] is True
    # The destination is consumed once.
    assert export_destination.pop_destination("sess") is None
    # §6 telemetry: initiated + completed, content-free.
    names = [e for e, _ in events]
    assert names == ["export.initiated", "export.completed"]
    initiated, completed = events[0][1], events[1][1]
    assert initiated == {"format": "glb", "via": "agent", "tool": "export_scene"}
    for key in ("format", "success", "extension", "via", "tool", "scope", "use_case",
                "destination_kind", "mesh_count", "armature_count", "clip_count",
                "readiness_bypassed", "verification_checked", "verification_passed",
                "issue_count", "duration_ms", "file_size_kb"):
        assert key in completed, key
    assert completed["success"] is True and completed["readiness_bypassed"] is True
    assert completed["extension"] == "glb" and completed["clip_count"] == 1
    blob = repr(events)
    assert "Hero" not in blob and str(fake_scene.tmp) not in blob


def test_run_export_to_uses_folder_kind_and_never_overwrites(fake_scene, monkeypatch):
    folder = fake_scene.tmp / "downloads"
    folder.mkdir()
    (folder / "Hero.glb").write_bytes(b"keep me")
    monkeypatch.setattr(agent_export, "resolve_export_folder", lambda kind: str(folder))
    spec = {"format": "glb", "target_scope": "scene", "use_case": "web", "suggested_filename": "Hero"}
    result = agent_export.run_export_to("sess", spec, "downloads")
    assert result["success"] is True, result
    assert result["folder"] == "downloads" and result["filepath_basename"] == "Hero_2.glb"
    assert (folder / "Hero.glb").read_bytes() == b"keep me"
    assert result["clips"] == ["Walk"] and result["clips_requested"] is None
    _no_paths(result)
    assert agent_export.run_export_to("sess", spec, "cloud")["success"] is False
    assert agent_export.run_export_to("sess", {"format": "step"}, "downloads")["success"] is False


def test_run_export_failure_is_scrubbed_of_paths(fake_scene, monkeypatch):
    dest = str(fake_scene.tmp / "Hero.fbx")
    export_destination.set_destination("sess", dest)

    def exploding(filepath, **kwargs):
        raise RuntimeError(f"cannot write {filepath} (permission denied)")

    monkeypatch.setattr(agent_export, "_exporter", lambda fmt: exploding)
    result = agent_export.run_export("sess", {"format": "fbx", "target_scope": "scene"})
    assert result["success"] is False
    assert str(fake_scene.tmp) not in result["error"] and "Hero.fbx" not in result["error"]
    assert "permission denied" in result["error"]
    _no_paths(result)


def test_run_export_refuses_missing_or_mismatched_destination(fake_scene):
    assert agent_export.run_export("sess", {"format": "glb"})["success"] is False
    export_destination.set_destination("sess", str(fake_scene.tmp / "Hero.fbx"))
    result = agent_export.run_export("sess", {"format": "glb"})
    assert result == {"success": False, "error": "Export destination extension mismatch"}


def test_inspect_export_reports_readiness_without_paths(monkeypatch):
    monkeypatch.setattr(agent_export, "run_preflight", lambda spec: {"success": True, "ready": True})
    assert agent_export.inspect_export({})["ready"] is True

    def boom(spec):
        raise ValueError("Named object(s) not found: /Users/x/Hero")

    monkeypatch.setattr(agent_export, "run_preflight", boom)
    result = agent_export.inspect_export({})
    assert result["success"] is False and "/Users" not in result["error"]


# ---------------------------------------------------------------------------
# registration of the picker operator (bootstrap auto-discovery of ui/**)
# ---------------------------------------------------------------------------


def _classes_tuple(filename):
    path = os.path.join(_OPS_DIR, filename)
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "classes" for t in node.targets
        ):
            return [elt.id for elt in node.value.elts if isinstance(elt, ast.Name)]
    return None


def test_choose_export_location_is_registered_like_its_siblings():
    # Bootstrap registers every `classes` tuple under modules/**/ui/ — the
    # export picker must expose one exactly as the import picker and the
    # slot-action operators do (none of them hand-write register()).
    assert _classes_tuple("agent_export_ops.py") == ["MIXIE_CHAT_OT_choose_export_location"]
    assert _classes_tuple("agent_import_ops.py") == ["MIXIE_CHAT_OT_choose_import_file"]
    assert "MIXIE_CHAT_OT_select_slot_action" in _classes_tuple("chat_special_ops.py")
    for filename in ("agent_export_ops.py", "agent_import_ops.py", "chat_special_ops.py"):
        src = open(os.path.join(_OPS_DIR, filename), encoding="utf-8").read()
        assert "def register(" not in src, filename
        assert "ui" in os.path.normpath(os.path.join(_OPS_DIR, filename)).split(os.sep)


def test_picker_accepts_every_contract_format():
    src = open(os.path.join(_OPS_DIR, "agent_export_ops.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    table = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "_EXTENSIONS" for t in node.targets))
    keys = {k.value for k in table.keys}
    assert keys == set(agent_export.EXTENSIONS)
    assert 'text=self.filepath' not in src


# ---------------------------------------------------------------------------
# OBJ texture staging + re-import verification shape
# ---------------------------------------------------------------------------


class _FakeImage(_Fake):
    def copy(self):
        return _FakeImage(name=self.name, size=self.size, saved=[], filepath_raw="", file_format="")

    def save(self):
        with open(self.filepath_raw, "wb") as handle:
            handle.write(b"\x89PNG")
        self.saved.append(self.filepath_raw)


def test_staged_obj_textures_writes_beside_the_obj_and_restores(tmp_path, monkeypatch):
    from mixar.modules.space_mixie_chat.core import export_obj_textures
    removed, loaded = [], []

    def load(path):
        image = _FakeImage(name=os.path.basename(path), size=(16, 16), filepath=path, source="FILE")
        loaded.append(image)
        return image

    monkeypatch.setattr(export_obj_textures, "bpy", SimpleNamespace(
        data=SimpleNamespace(images=SimpleNamespace(remove=removed.append, load=load))))
    packed = _FakeImage(name="Skin Tex.png", size=(16, 16))
    empty = _FakeImage(name="Broken", size=(0, 0))
    node_a = SimpleNamespace(image=packed, node_tree=None)
    node_b = SimpleNamespace(image=empty, node_tree=None)
    material = _Fake(name="Skin", use_nodes=True, node_tree=SimpleNamespace(nodes=[node_a, node_b]))
    mesh = _Fake(name="Hero", data=SimpleNamespace(materials=[material, None]))
    obj_path = str(tmp_path / "Hero_2.obj")
    (tmp_path / "Hero_2_textures").mkdir()  # already taken → unique sibling
    with export_obj_textures.staged_obj_textures([mesh], obj_path) as (count, folder):
        assert count == 1 and folder == "Hero_2_textures_2"
        assert node_a.image is loaded[0] and node_a.image.name == "Skin Tex.png_objtex"
        assert node_a.image.filepath == str(tmp_path / folder / "Skin_Tex.png")
        assert node_b.image is empty
        assert (tmp_path / folder / "Skin_Tex.png").read_bytes() == b"\x89PNG"
    assert node_a.image is packed
    # the packed copy used for saving AND the on-disk image are both gone
    assert len(removed) == 2 and removed[1] is loaded[0]
    with export_obj_textures.staged_obj_textures([_Fake(data=SimpleNamespace(materials=[]))], obj_path) as staged:
        assert staged == (0, "")


def test_obj_export_stages_textures_and_uses_relative_paths(fake_scene, monkeypatch):
    seen = {}

    @contextmanager
    def fake_stage(meshes, path):
        seen["path"] = path
        yield 2, "Hero_textures"

    monkeypatch.setattr(agent_export, "staged_obj_textures", fake_stage)
    monkeypatch.setattr(agent_export, "verify_export", lambda p, f, e: {**seen.setdefault("expected", e),
                                                                        "checked": True, "issues": [], "passed": True, "animations": []})
    calls = fake_scene.calls

    def obj_exporter(filepath, **kwargs):
        calls["exporter"].append(kwargs)
        open(filepath, "w").write("o Hero\n")
        return {"FINISHED"}

    monkeypatch.setattr(agent_export, "_exporter", lambda fmt: obj_exporter)
    dest = str(fake_scene.tmp / "Hero.obj")
    export_destination.set_destination("sess", dest)
    result = agent_export.run_export("sess", {"format": "obj", "target_scope": "scene", "use_case": "other"})
    assert result["success"] is True, result
    assert seen["path"] == dest
    assert calls["exporter"][-1]["path_mode"] == "RELATIVE"
    assert seen["expected"]["images_expected"] == 2
    assert result["textures_folder"] == "Hero_textures" and result["clips"] == []
    assert "static-only" in result["warning"]
    _no_paths(result)


def test_reimport_uses_the_active_scene_not_a_temp_scene():
    # The FBX importer evaluates pose bones, which never happens in a
    # non-active scene under temp_override (KeyError: 'Bone'); the import
    # lands in a temporary collection of the active scene instead.
    src = open(os.path.join(os.path.dirname(__file__), "..", "core", "export_reimport.py"), encoding="utf-8").read()
    assert "bpy.data.scenes.new(" not in src and "temp_override(" not in src
    assert 'collections.new(_TEMP_COLLECTION)' in src
    for block in ("objects", "meshes", "armatures", "actions", "materials", "images",
                  "collections", "cameras", "lights", "node_groups", "textures"):
        assert f'"{block}"' in src
    assert "REIMPORT_SIZE_CAP = 250 * 1024 * 1024" in src
    assert "state.restore()" in src
