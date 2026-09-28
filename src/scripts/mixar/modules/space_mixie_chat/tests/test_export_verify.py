# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``export_verify`` (contract §5) and the package exporter's contract
surface (§2), pinned outside Blender."""

import ast
import inspect
import json
import os
import sys
import zipfile
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import (  # noqa: E402
    export_gltf_bounds,
    export_package,
    export_reimport,
    export_verify,
)
from _export_support import glb_bytes, write_glb  # noqa: E402

_CORE = os.path.join(os.path.dirname(__file__), "..", "core")
VERIFICATION_KEYS = {
    "checked", "method", "file_size_bytes", "meshes", "nodes", "materials", "images",
    "images_embedded", "animations", "triangles", "dimensions_m", "up_axis", "draco",
    "issues", "passed",
}


def test_glb_parse_reads_counts_names_bounds_and_clips(tmp_path):
    path = write_glb(tmp_path / "hero.glb", meshes=2, animations=["Walk", "Run"])
    result = export_verify.verify_export(path, "glb", {
        "mesh_count": 2, "armature_count": 1, "clips": ["walk"], "joined": False,
        "images_expected": 1,
    })
    assert VERIFICATION_KEYS <= set(result)
    assert result["checked"] is True and result["passed"] is True, result["issues"]
    assert result["method"] == "gltf_json"
    assert result["meshes"] == 2 and result["nodes"] == 2
    assert result["materials"] == ["Mat"]
    assert result["images"] == 1 and result["images_embedded"] is True
    assert result["animations"] == ["Walk", "Run"]
    assert result["triangles"] == 24  # 36 indices / 3 per mesh, two meshes
    assert result["dimensions_m"] == [2.0, 1.0, 0.5]
    assert result["up_axis"] == "+Y" and result["draco"] is False
    assert result["file_size_bytes"] == os.path.getsize(path)


def test_glb_issues_for_every_documented_mismatch(tmp_path):
    path = write_glb(tmp_path / "a.glb", meshes=2, animations=["Walk"], images=2,
                     embedded=False, draco=True)
    result = export_verify.verify_export(path, "glb", {
        "mesh_count": 3, "clips": ["Walk", "Jump"], "images_expected": 2, "compression": "none",
    })
    assert result["checked"] is True and result["passed"] is False
    joined = " ".join(result["issues"])
    assert "2 mesh(es); 3 were expected" in joined
    assert "1 requested clip(s) are not in the file" in joined
    assert "embedded" in joined
    assert "Draco" in joined
    # joined → exactly one mesh expected regardless of the input count
    joined_result = export_verify.verify_export(path, "glb", {"mesh_count": 5, "joined": True})
    assert any("1 were expected" in issue for issue in joined_result["issues"])
    # no textures at all when some were expected
    none = write_glb(tmp_path / "b.glb", images=0)
    assert any("has none" in issue for issue in
               export_verify.verify_export(none, "glb", {"images_expected": 3})["issues"])


def test_verify_never_raises(tmp_path):
    missing = export_verify.verify_export(str(tmp_path / "nope.glb"), "glb", {})
    assert missing["checked"] is False and missing["passed"] is False and missing["issues"]
    garbage = tmp_path / "bad.glb"
    garbage.write_bytes(b"not a glb" * 300)
    result = export_verify.verify_export(str(garbage), "glb", {})
    assert result["checked"] is False and any("container" in i for i in result["issues"])
    tiny = tmp_path / "tiny.glb"
    tiny.write_bytes(glb_bytes()[:100])
    result = export_verify.verify_export(str(tiny), "glb", {"mesh_count": 1})
    assert any("empty" in issue for issue in result["issues"]) and result["passed"] is False
    # Text formats are legitimately small: a ~900-byte cube OBJ is not "empty".
    small = tmp_path / "cube.obj"
    small.write_text("o Cube\n" + "".join(f"v {i} {i} {i}\n" for i in range(8)) + "f 1 2 3 4\n" * 6)
    assert os.path.getsize(small) < 512
    result = export_verify.verify_export(str(small), "obj", {"mesh_count": 1})
    assert result["passed"] is True, result["issues"]
    faceless = tmp_path / "points.obj"
    faceless.write_text("o P\n" + "".join(f"v {i} 0 0\n" for i in range(30)))
    assert any("no faces" in issue for issue in export_verify.verify_export(str(faceless), "obj", {})["issues"])
    unknown = export_verify.verify_export(str(garbage), "step", {})
    assert unknown["checked"] is False and unknown["issues"]


def test_gltf_separate_checks_sidecar_files(tmp_path):
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "hero.bin", "byteLength": 4}],
        "images": [{"uri": "textures/albedo.png"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"count": 3, "type": "VEC3", "componentType": 5126,
                       "min": [0, 0, 0], "max": [1, 2, 3]}],
        "nodes": [{"mesh": 0}],
    }
    path = tmp_path / "hero.gltf"
    path.write_text(json.dumps(doc) + " " * 1100)
    result = export_verify.verify_export(str(path), "gltf", {"mesh_count": 1, "images_expected": 1})
    assert result["checked"] is True
    assert any("missing beside it" in issue for issue in result["issues"])
    assert result["images_embedded"] is False and result["dimensions_m"] == [1.0, 2.0, 3.0]
    (tmp_path / "hero.bin").write_bytes(b"\0" * 4)
    (tmp_path / "textures").mkdir()
    (tmp_path / "textures" / "albedo.png").write_bytes(b"\x89PNG")
    result = export_verify.verify_export(str(path), "gltf", {"mesh_count": 1, "images_expected": 1})
    assert result["passed"] is True, result["issues"]


def test_obj_text_scan_and_mtl_textures(tmp_path):
    lines = ["mtllib hero.mtl", "o Hero", "usemtl Skin"]
    lines += [f"v {i} {i * 2} {i * 3}" for i in range(4)]
    lines += ["f 1 2 3 4"] * 40
    (tmp_path / "hero.obj").write_text("\n".join(lines) + "\n")
    result = export_verify.verify_export(str(tmp_path / "hero.obj"), "obj", {"mesh_count": 1, "images_expected": 1})
    assert result["method"] == "obj_text" and result["checked"] is True
    assert any(".mtl" in issue for issue in result["issues"])
    (tmp_path / "hero.mtl").write_text("newmtl Skin\nmap_Kd Hero Cube_textures/skin.png\n")
    result = export_verify.verify_export(str(tmp_path / "hero.obj"), "obj", {"mesh_count": 1, "images_expected": 1})
    assert result["meshes"] == 1 and result["materials"] == ["Skin"] and result["triangles"] == 80
    assert result["dimensions_m"] == [3.0, 6.0, 9.0] and result["images"] == 1
    assert any("texture" in issue for issue in result["issues"])
    (tmp_path / "Hero Cube_textures").mkdir()
    (tmp_path / "Hero Cube_textures" / "skin.png").write_bytes(b"\x89PNG")
    assert export_verify.verify_export(str(tmp_path / "hero.obj"), "obj", {"mesh_count": 1, "images_expected": 1})["passed"]


def test_headers_and_size_cap_before_reimport(tmp_path):
    fbx = tmp_path / "hero.fbx"
    fbx.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00" + (7400).to_bytes(4, "little") + b"\0" * 1100)
    assert export_reimport.check_fbx_header(str(fbx)) == (True, 7400)
    ascii_fbx = tmp_path / "ascii.fbx"
    ascii_fbx.write_bytes(b"; FBX 7.4.0 project file" + b"\0" * 1100)
    result = export_verify.verify_export(str(ascii_fbx), "fbx", {})
    assert result["checked"] is False and any("Kaydara" in i for i in result["issues"])
    usd = tmp_path / "hero.usdc"
    usd.write_bytes(b"PXR-USDC" + b"\0" * 1100)
    assert export_reimport.check_usd_header(str(usd)) == "usdc"
    export_reimport.REIMPORT_SIZE_CAP, cap = 16, export_reimport.REIMPORT_SIZE_CAP
    try:
        result = export_verify.verify_export(str(usd), "usdc", {})
    finally:
        export_reimport.REIMPORT_SIZE_CAP = cap
    assert result["checked"] is False and any("too large" in i for i in result["issues"])
    assert result["method"] == "reimport"


def test_usdz_listing_flags_missing_layer(tmp_path):
    path = tmp_path / "hero.usdz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("textures/albedo.png", b"\x89PNG" * 400)
    export_reimport.REIMPORT_SIZE_CAP, cap = 0, export_reimport.REIMPORT_SIZE_CAP
    try:
        result = export_verify.verify_export(str(path), "usdz", {})
    finally:
        export_reimport.REIMPORT_SIZE_CAP = cap
    assert result["method"] == "usdz_zip"
    assert any("no USD layer" in issue for issue in result["issues"])
    assert result["images"] == 1


# ---------------------------------------------------------------------------
# export_package (§2) — contract surface, no Blender needed
# ---------------------------------------------------------------------------


def test_export_package_signature_and_isolation():
    params = inspect.signature(export_package.export_package).parameters
    assert list(params) == ["names", "fmt", "filename", "where", "folder", "join", "texture_tiers",
                            "include_source", "manifest", "readme", "extra_files", "animations"]
    assert params["animations"].default is None
    src = open(os.path.join(_CORE, "export_package.py"), encoding="utf-8").read()
    assert "uv_bake" not in src.replace("uv_bake.export_package", "")  # legacy manifest tag only
    assert export_package.GENERATOR == "Mixar export_package"
    assert set(export_package.DESTINATIONS) == {"mixar_exports", "downloads", "documents", "desktop", "project"}
    # The return dict carries both the verifier's dict and the legacy glb_check.
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "export_package")
    returned = next(n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
    keys = {k.value for k in returned.value.keys if isinstance(k, ast.Constant)}
    assert {"destination", "folder", "files", "main_file", "glb_check", "verification",
            "animations", "triangles", "dimensions_m", "textures", "tiers", "seconds"} <= keys


def test_export_package_exporter_kwargs_follow_clip_request():
    kwargs, mode, _ = export_package.exporter_kwargs("glb", [])
    assert kwargs["export_animations"] is False and mode == "none"
    assert kwargs["export_draco_mesh_compression_enable"] is False and kwargs["export_yup"] is True
    kwargs, mode, _ = export_package.exporter_kwargs("fbx", ["Walk"])
    assert kwargs["bake_anim_use_nla_strips"] is True and mode == "selected"
    assert kwargs["object_types"] == {"MESH", "ARMATURE"}
    kwargs, _, warning = export_package.exporter_kwargs("usdz", ["Walk"])
    assert kwargs["export_textures_mode"] == "NEW" and "USD" in warning


def test_export_package_clears_only_its_own_previous_files(tmp_path):
    (tmp_path / "hero.glb").write_bytes(b"old")
    (tmp_path / "keep.txt").write_bytes(b"user file")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "generator": "Mixar uv_bake.export_package",
        "files": [{"file": "hero.glb"}, {"file": "../outside.txt"}, {"file": "keep.txt"}],
    }).replace('"keep.txt"', '"gone.txt"'))
    assert export_package._clear_previous(str(tmp_path)) == 1
    assert not (tmp_path / "hero.glb").exists() and (tmp_path / "keep.txt").exists()
    assert not (tmp_path / "manifest.json").exists()
    (tmp_path / "manifest.json").write_text(json.dumps({"generator": "someone else", "files": [{"file": "keep.txt"}]}))
    assert export_package._clear_previous(str(tmp_path)) == 0
    assert (tmp_path / "keep.txt").exists()


def test_inspect_glb_stays_compatible(tmp_path):
    path = write_glb(tmp_path / "hero.glb", draco=True)
    check = export_package.inspect_glb(path)
    assert check["valid"] is True and check["draco"] is True and check["images_embedded"] is True
    assert export_package.inspect_glb(str(tmp_path / "missing.glb")) == {"valid": False}


def test_fbx_style_clip_names_map_back_to_scene_clips():
    file_names = ["Hero_Rig.001|Hero_Rig|Run", "Hero_Rig.001|Hero_Rig|Walk", "Extra"]
    assert export_verify.clip_in_file("walk", file_names) is True
    assert export_verify.clip_in_file("Jump", file_names) is False
    assert export_verify.file_clip_names(["Walk", "Run"], file_names) == ["Run", "Walk", "Extra"]
    assert export_verify.file_clip_names([], ["Walk"]) == ["Walk"]


# ---------------------------------------------------------------------------
# Data-safety regressions (PR #1662 review): the user's scene, selection and
# previous package survive a failed or repeated export.
# ---------------------------------------------------------------------------


def test_clear_previous_runs_after_the_new_files_and_keeps_rewritten_ones(tmp_path):
    src = open(os.path.join(_CORE, "export_package.py"), encoding="utf-8").read()
    fn_src = src[src.index("def export_package("):]
    assert fn_src.index("_export(fmt, main") < fn_src.index("_clear_previous(root")
    assert fn_src.index("_clear_previous(root") < fn_src.index('"manifest.json"), "w"')
    assert fn_src.index("prev_sel = ") < fn_src.index("_copies(meshes")
    (tmp_path / "hero.glb").write_bytes(b"new")
    (tmp_path / "stale.png").write_bytes(b"old")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "generator": export_package.GENERATOR,
        "files": [{"file": "hero.glb"}, {"file": "stale.png"}],
    }))
    assert export_package._clear_previous(str(tmp_path), keep=["hero.glb"]) == 1
    assert (tmp_path / "hero.glb").read_bytes() == b"new"
    assert not (tmp_path / "stale.png").exists() and not (tmp_path / "manifest.json").exists()


def test_texture_file_names_keep_blender_suffix_and_never_collide(tmp_path):
    stem = export_package._texture_stem
    assert stem("Wood") == "Wood" and stem("Wood.001") == "Wood.001"
    assert stem("Wood.png") == "Wood" and stem("Wood.png.001") == "Wood.001"
    assert stem("") == "texture"

    class Image:
        def __init__(self, name):
            self.name, self.size = name, (4, 4)
            self.filepath_raw = self.file_format = None

        def copy(self):
            return Image(self.name)

        def save(self):
            pass

    images = [Image("Wood"), Image("Wood.001"), Image("A/B"), Image("A_B")]
    saved = export_package._save_textures(images, str(tmp_path / "textures"))
    names = [fname for _, fname in saved.values()]
    assert names == ["Wood.png", "Wood.001.png", "A_B.png", "A_B_2.png"]
    assert len(set(n.lower() for n in names)) == len(images)


def test_copies_undo_renames_and_drop_the_temp_collection_on_failure(monkeypatch):
    import pytest

    bpy = export_package.bpy  # the module's own binding, whatever the session swapped in

    class Obj:
        def __init__(self, name):
            self.name, self.material_slots = name, []
            self.matrix_world = MagicMock(is_negative=False)

        def evaluated_get(self, deps):
            return self

    chair, table = Obj("Chair"), Obj("Table")
    monkeypatch.setattr(bpy.data.meshes, "new_from_object",
                        MagicMock(side_effect=[MagicMock(materials=[]), RuntimeError("boom")]))
    monkeypatch.setattr(bpy.data.collections, "remove", removed := MagicMock())
    with pytest.raises(RuntimeError):
        export_package._copies([chair, table], join=False)
    assert (chair.name, table.name) == ("Chair", "Table")
    assert removed.call_count == 1


def test_reimport_restores_timing_and_mode_and_keeps_the_usd_frame_range(tmp_path, monkeypatch):
    from types import SimpleNamespace

    bpy = export_reimport.bpy
    path = tmp_path / "hero.fbx"
    path.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00" + (7400).to_bytes(4, "little") + b"\0" * 1100)
    render = SimpleNamespace(fps=24, fps_base=1.0)
    scene = SimpleNamespace(render=render, frame_start=1, frame_end=250, frame_current=10,
                            collection=MagicMock())
    active = SimpleNamespace(name="Hero", mode="EDIT")
    view_layer = MagicMock()
    view_layer.objects.active = active

    def fake_import(**_kw):  # what the real FBX importer does to the scene
        render.fps, render.fps_base, scene.frame_end = 30, 1.001, 0
        return {"FINISHED"}

    def fake_mode_set(mode):
        active.mode = mode

    monkeypatch.setattr(bpy.context, "scene", scene)
    monkeypatch.setattr(bpy.context, "view_layer", view_layer)
    monkeypatch.setattr(bpy.context, "selected_objects", [])
    monkeypatch.setattr(bpy.ops.import_scene, "fbx", MagicMock(side_effect=fake_import))
    monkeypatch.setattr(bpy.ops.wm, "usd_import", usd_import := MagicMock(return_value={"FINISHED"}))
    monkeypatch.setattr(bpy.ops.object, "mode_set", mode_set := MagicMock(side_effect=fake_mode_set))
    monkeypatch.setattr(bpy.data.collections, "get", MagicMock(return_value=None))
    monkeypatch.setattr(bpy.data, "objects", MagicMock(__contains__=MagicMock(return_value=True)))
    result = {"issues": [], "file_size_bytes": path.stat().st_size}
    export_reimport.verify_by_reimport(str(path), "fbx", result)
    export_reimport._import(str(path), "usd", MagicMock())
    assert result["checked"] is True and result["issues"] == []
    assert (render.fps, render.fps_base, scene.frame_end) == (24, 1.0, 250)
    assert [c.kwargs["mode"] for c in mode_set.call_args_list] == ["OBJECT", "EDIT"]
    assert usd_import.call_args.kwargs["set_frame_range"] is False


def test_glb_with_a_second_scene_is_flagged(tmp_path):
    # glTF walks every scene unless use_active_scene: a selected object in
    # another scene rides along as a second glTF scene.
    path = write_glb(tmp_path / "plant.glb", scenes=2)
    result = export_verify.verify_export(path, "glb", {"mesh_count": 1, "images_expected": 1})
    assert result["scenes"] == 2 and result["passed"] is False
    assert any("holds 2 scenes" in issue for issue in result["issues"])
    assert export_verify.verify_export(write_glb(tmp_path / "one.glb"), "glb", {"mesh_count": 1})["scenes"] == 1


def test_glb_dimensions_are_world_space(tmp_path):
    # Two 2x1x0.5 boxes, the second translated 3 m along X and 2 m up: the
    # asset is 5 m long, not the size of one part.
    path = write_glb(tmp_path / "parts.glb", meshes=2, node_translations=[(0, 0, 0), (3, 2, 0)])
    result = export_verify.verify_export(path, "glb", {"mesh_count": 2})
    assert result["dimensions_m"] == [5.0, 3.0, 0.5]
    # Rotation via quaternion (90 deg about Z swaps X/Y extents) and a parent
    # node without a mesh whose matrix scales the child; an instanced mesh
    # counted where each instance sits.
    doc = {
        "accessors": [{"count": 8, "type": "VEC3", "componentType": 5126, "min": [0, 0, 0], "max": [2, 1, 1]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [
            {"children": [1, 2], "matrix": [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 10, 0, 0, 1]},
            {"mesh": 0, "rotation": [0, 0, 0.7071068, 0.7071068]},
            {"mesh": 0, "translation": [0, 0, 5]},
            {"mesh": 0, "translation": [100, 100, 100]},  # not in the scene
        ],
        "scenes": [{"nodes": [0]}],
    }
    lo, hi = export_gltf_bounds.gltf_world_bounds(doc)
    assert [round(v, 4) for v in lo] == [8.0, 0.0, 0.0]
    assert [round(v, 4) for v in hi] == [14.0, 4.0, 12.0]
    assert export_gltf_bounds.gltf_world_bounds({"nodes": [{"name": "empty"}], "scenes": [{"nodes": [0]}]}) is None
