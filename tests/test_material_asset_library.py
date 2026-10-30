# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material assets in the asset library: indexing, search hits, apply.

Runs outside Blender (``bpy`` is the conftest stub); bpy-shaped inputs are
plain stand-ins.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.agent_bubble.core import apply_material, library_search
from mixar.modules.asset_search.core import asset_kinds, material_summary, preview_worker, search_api

ROOT = Path(__file__).resolve().parents[1]
ASSET_SEARCH = ROOT / "src" / "scripts" / "mixar" / "modules" / "asset_search"


# ---------------------------------------------------------------------------
# Node-graph summary (the text half of a material embedding)
# ---------------------------------------------------------------------------


def _socket(name, value=None, linked=False):
    return SimpleNamespace(name=name, default_value=value, is_linked=linked)


def _node(kind, inputs=(), **extra):
    return SimpleNamespace(type=kind, inputs=list(inputs), **extra)


def _material(*nodes, use_nodes=True):
    return SimpleNamespace(node_tree=SimpleNamespace(nodes=list(nodes)), use_nodes=use_nodes)


def test_principled_values_become_words():
    mat = _material(_node("BSDF_PRINCIPLED", [
        _socket("Base Color", (0.3, 0.08, 0.02, 1.0)),
        _socket("Metallic", 1.0),
        _socket("Roughness", 0.8),
    ]))
    text = material_summary.material_summary(mat)
    assert text.startswith("Brown base colour") or "brown" in text
    assert "metallic" in text and "rough" in text


def test_textures_and_procedurals_are_named():
    mat = _material(
        _node("BSDF_PRINCIPLED", [_socket("Base Color", (1, 1, 1, 1), linked=True),
                                  _socket("Roughness", 0.5, linked=True)]),
        _node("TEX_IMAGE", image=SimpleNamespace(name="Bricks_Albedo.png", filepath="")),
        _node("TEX_IMAGE", image=SimpleNamespace(name="bricks_normal.png", filepath="")),
        _node("TEX_NOISE"),
        _node("NORMAL_MAP"),
    )
    text = material_summary.material_summary(mat)
    assert "textured base colour" in text.lower() and "textured roughness" in text
    assert "Image textures: colour, normal" in text
    assert "Procedural: noise" in text


def test_glass_and_emission_are_detected():
    mat = _material(_node("BSDF_PRINCIPLED", [
        _socket("Transmission Weight", 1.0),
        _socket("Emission Strength", 4.0),
        _socket("Emission Color", (1.0, 0.5, 0.0, 1.0)),
    ]))
    text = material_summary.material_summary(mat)
    assert "glass" in text and "emissive" in text


def test_groups_are_walked():
    inner = SimpleNamespace(nodes=[_node("TEX_VORONOI")])
    mat = _material(_node("GROUP", node_tree=inner))
    assert "voronoi" in material_summary.material_summary(mat)


def test_colour_names_cover_greys_and_hues():
    assert material_summary.colour_name((0.0, 0.0, 0.0)) == "black"
    assert material_summary.colour_name((1.0, 1.0, 1.0)) == "white"
    assert material_summary.colour_name((0.05, 0.05, 0.6)).endswith("blue")


def test_missing_textures_are_counted():
    missing = SimpleNamespace(source="FILE", has_data=False, size=(0, 0), packed_file=None)
    loaded = SimpleNamespace(source="FILE", has_data=True, size=(512, 512), packed_file=None)
    mat = _material(_node("TEX_IMAGE", image=missing), _node("TEX_IMAGE", image=loaded))
    assert material_summary.missing_texture_count(mat) == 1


def test_material_modules_are_self_contained_for_the_headless_worker():
    """The worker runs under --factory-startup: no mixar package exists there."""
    for name in ("material_preview.py", "material_summary.py", "preview_backfill.py"):
        tree = ast.parse((ASSET_SEARCH / "core" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                assert not (module or "").startswith("mixar"), (name, module)


# ---------------------------------------------------------------------------
# Identity and wire format
# ---------------------------------------------------------------------------


def test_legacy_identity_keys_are_unchanged():
    assert asset_kinds.identity_key("Chair", "Props", "a.blend") == "Chair|Props|a.blend"
    assert asset_kinds.identity_key("Chair", "Props", "a.blend", "OBJECT") == "Chair|Props|a.blend"
    assert asset_kinds.identity_entry("Chair", "Props", "a.blend", "COLLECTION") == {
        "name": "Chair", "library": "Props", "blend_file": "a.blend"}


def test_material_identity_carries_its_kind():
    assert asset_kinds.identity_key("Rust", "Mats", "r.blend", "MATERIAL") == "Rust|Mats|r.blend|MATERIAL"
    assert asset_kinds.identity_entry("Rust", "Mats", "r.blend", "material")["kind"] == "MATERIAL"
    assert json.loads(asset_kinds.kinds_form_value()) == ["OBJECT", "COLLECTION", "MATERIAL"]


def test_worker_material_lines_expand_to_one_row_per_view(tmp_path):
    for name in ("00001_swatch.jpg", "00001_sphere.jpg", "00002.jpg"):
        (tmp_path / name).write_bytes(b"jpg")
    results = [
        {"ok": True, "_dir": str(tmp_path), "file": "00001_swatch.jpg",
         "info": {"name": "Rust", "kind": "MATERIAL", "view": "swatch"},
         "extra": [{"file": "00001_sphere.jpg",
                    "info": {"name": "Rust", "kind": "MATERIAL", "view": "sphere"}}]},
        {"ok": True, "_dir": str(tmp_path), "file": "00002.jpg", "info": {"name": "Chair"}},
    ]
    infos = preview_worker.results_to_infos(results, set())
    assert [i["image_name"] for i in infos] == [
        "asset_preview_Rust__swatch", "asset_preview_Rust__sphere", "asset_preview_Chair"]


def test_index_scans_and_uploads_materials():
    session = (ASSET_SEARCH / "core" / "render_session.py").read_text(encoding="utf-8")
    scan = (ASSET_SEARCH / "ui" / "operators" / "asset_search_ops.py").read_text(encoding="utf-8")
    assert "material_names = list(data_from.materials)" in session
    assert "def _render_material" in session
    assert "for name in data_from.materials:" in scan
    for name in ("train_api.py", "train_stream.py"):
        assert '"kinds": kinds_form_value()' in (ASSET_SEARCH / "core" / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status=200, data=None, message=""):
        self.status_code, self.data, self.message = status, data, message
        self.success = 200 <= status < 300


def test_search_sends_the_type_filter_and_parses_rows(monkeypatch):
    sent = {}

    class Client:
        def post(self, endpoint, data=None, files=None, **_kw):
            sent.update(data=data, files=files)
            return _Resp(data={"data": {"results": [
                {"model_name": "Rust", "similarity_score": 0.61, "asset_type": "material",
                 "metadata": {"name": "Rust", "library": "Mats", "blend_file": "r.blend",
                              "type": "Material", "kind": "MATERIAL"}},
            ]}})

    monkeypatch.setattr(search_api, "metered_client", lambda: Client())
    out = search_api.search("rusty metal", b"img", "ref.png", top_k=50, asset_type="material")
    assert sent["data"] == {"prompt": "rusty metal", "top_k": "20", "asset_type": "material"}
    assert sent["files"]["image"][0] == "ref.png"
    assert out["success"] and out["results"][0]["kind"] == "MATERIAL"


def test_search_reports_an_untrained_library(monkeypatch):
    class Client:
        def post(self, *_a, **_kw):
            return _Resp(400, message="No embeddings found. Please train first.")

    monkeypatch.setattr(search_api, "metered_client", lambda: Client())
    out = search_api.search("brick")
    assert not out["success"] and "Train" in out["message"]


def test_hit_lines_match_the_cpp_format():
    text = library_search.format_hits([
        {"score": 0.61234, "library": "Mats", "blend_file": "sub\\r.blend", "kind": "MATERIAL",
         "name": "Rust"},
        {"score": 0.5, "library": "Props", "blend_file": "c.blend", "type": "Collection", "name": "Set"},
        {"score": 0.4, "library": "Props", "blend_file": "o.blend", "type": "MESH", "name": "Chair"},
        {"score": 0.3, "library": "Bad", "blend_file": "x.blend", "type": "MESH", "name": "tab\tname"},
    ])
    assert text.split("\n") == [
        "0.6123\tMats\tsub/r.blend\tMaterial\tRust",
        "0.5000\tProps\tc.blend\tCollection\tSet",
        "0.4000\tProps\to.blend\tObject\tChair",
    ]


# ---------------------------------------------------------------------------
# Apply to Selected
# ---------------------------------------------------------------------------


def _obj(kind="MESH", slots=(), active=0):
    materials = []
    return SimpleNamespace(
        type=kind, data=SimpleNamespace(materials=materials),
        material_slots=[SimpleNamespace(material=m) for m in slots],
        active_material_index=active,
    )


def _layered():
    group = SimpleNamespace(mp=SimpleNamespace(channels=[1, 2]))
    return SimpleNamespace(node_tree=SimpleNamespace(nodes=[SimpleNamespace(node_tree=group)]))


def test_layer_stacks_are_never_replaced():
    plain = SimpleNamespace(node_tree=SimpleNamespace(nodes=[]))
    a, b, lamp = _obj(slots=[plain]), _obj(slots=[_layered()]), _obj(kind="LIGHT")
    targets, layered = apply_material.split_targets([a, b, lamp])
    assert targets == [a] and layered == [b]


def test_active_slot_is_replaced_or_one_is_added():
    mat = object()
    empty = _obj()
    apply_material.assign_to_active_slot(empty, mat)
    assert empty.data.materials == [mat]
    two = _obj(slots=[None, None], active=1)
    apply_material.assign_to_active_slot(two, mat)
    assert two.material_slots[0].material is None and two.material_slots[1].material is mat


@pytest.mark.parametrize("name", ["apply_material.py", "library_search.py"])
def test_island_modules_stay_under_the_size_rule(name):
    path = ROOT / "src" / "scripts" / "mixar" / "modules" / "agent_bubble" / "core" / name
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 500


# ---------------------------------------------------------------------------
# In-app preview renders leave nothing behind in the user's file
# ---------------------------------------------------------------------------


class _Blocks(list):
    def remove(self, block):
        list.remove(self, block)


class _ID:
    """Hashable like a real datablock (SimpleNamespace is not)."""

    def __init__(self, name, users, fake):
        self.name, self.users, self.use_fake_user = name, users, fake


def _block(name, users=0, fake=False):
    return _ID(name, users, fake)


def test_appended_data_removes_new_blocks_held_only_by_a_fake_user(monkeypatch):
    from mixar.modules.asset_search.core import material_preview

    old_mat = _block("UserMaterial", users=1)
    data = SimpleNamespace(materials=_Blocks([old_mat]), node_groups=_Blocks(),
                           textures=_Blocks(), images=_Blocks(), meshes=_Blocks())
    monkeypatch.setattr(material_preview.bpy, "data", data)
    with material_preview.AppendedData():
        asset_mat = _block("Oak_Wood_Planks", users=1, fake=True)   # marked as an asset
        in_use = _block("StillUsed", users=2, fake=True)
        orphan_img = _block("oak.png")
        data.materials += [asset_mat, in_use]
        data.images.append(orphan_img)
    assert [m.name for m in data.materials] == ["UserMaterial", "StillUsed"]
    assert not data.images


def test_object_renders_clean_up_their_materials():
    session = (ASSET_SEARCH / "core" / "render_session.py").read_text(encoding="utf-8")
    assert "with AppendedData():\n            self._render_appended_asset(" in session


def test_material_previews_link_instead_of_append():
    """Blender moves a library ID's weak reference to the newest APPENDED
    copy; a preview append would strip it from a material the user applied,
    so the next Apply made a `.001` copy instead of reusing it."""
    src = (ASSET_SEARCH / "core" / "material_preview.py").read_text(encoding="utf-8")
    cls = src.split("class AppendedMaterial", 1)[1]
    assert "libraries.load(self.blend_path, link=True)" in cls
    assert "link=False" not in cls
    assert "bpy.data.libraries.remove(library)" in cls


# ---------------------------------------------------------------------------
# Thumbnails: a material with no preview gets its sphere render, like objects
# ---------------------------------------------------------------------------


def _item():
    return {"blend_str": "D:/lib/mats.blend", "name": "Rust"}


def test_material_without_a_preview_gets_its_sphere_as_thumbnail():
    from mixar.modules.asset_search.core import material_preview as mp

    paths = {"swatch": "a_swatch.jpg", "sphere": "a_sphere.jpg"}
    entry = mp.thumbnail_entry(_item(), paths, ["swatch", "sphere"], has_preview=False)
    assert entry == {"blend_str": "D:/lib/mats.blend", "name": "Rust",
                     "jpg": "a_sphere.jpg", "kind": "MATERIAL"}


def test_existing_preview_is_never_overwritten_and_failed_sphere_skips():
    from mixar.modules.asset_search.core import material_preview as mp

    paths = {"swatch": "a_swatch.jpg", "sphere": "a_sphere.jpg"}
    assert mp.thumbnail_entry(_item(), paths, ["swatch", "sphere"], has_preview=True) is None
    assert mp.thumbnail_entry(_item(), paths, ["swatch"], has_preview=False) is None


def test_embedded_preview_needs_size_and_visible_pixels():
    import numpy as np

    from mixar.modules.asset_search.core import material_preview as mp

    def preview(size, alpha):
        class _Pixels:
            def foreach_get(self, buf):
                buf[:] = np.tile([0.5, 0.5, 0.5, alpha], len(buf) // 4)
        return SimpleNamespace(preview=SimpleNamespace(image_size=size, image_pixels_float=_Pixels()))

    assert mp.has_embedded_preview(preview((128, 128), 1.0))
    assert not mp.has_embedded_preview(preview((128, 128), 0.0))   # blank
    assert not mp.has_embedded_preview(preview((16, 16), 1.0))     # too small
    assert not mp.has_embedded_preview(SimpleNamespace(preview=None))


def test_backfill_finds_materials_by_kind(monkeypatch):
    from mixar.modules.asset_search.core import preview_backfill as pb

    rust_mat, rust_obj = object(), object()
    data = SimpleNamespace(materials={"Rust": rust_mat}, objects={"Rust": rust_obj},
                           collections={})
    monkeypatch.setattr(pb.bpy, "data", data, raising=False)
    assert pb._datablock({"name": "Rust", "kind": "MATERIAL"}) is rust_mat
    assert pb._datablock({"name": "Rust"}) is rust_obj


def test_both_render_paths_queue_material_thumbnails():
    session = (ASSET_SEARCH / "core" / "render_session.py").read_text(encoding="utf-8")
    worker = (ASSET_SEARCH / "core" / "preview_worker_script.py").read_text(encoding="utf-8")
    support = (ASSET_SEARCH / "core" / "train_support.py").read_text(encoding="utf-8")
    assert "thumbnail_entry(item, paths, views, has_preview)" in session
    assert "self.rendered_items.append(thumb)" in session
    assert "backfill_entries.append(thumb)" in worker
    assert 'entry["kind"] = item["kind"]' in support


def test_backfill_exit_tells_the_library_pane_to_reload(monkeypatch):
    """Thumbnails land in the .blend after training; without this edge the
    island kept its cached, preview-less asset list until a restart."""
    from mixar.modules.asset_search.core import train_support
    from mixar.modules.agent_bubble.ui.properties import generations_props

    timers = []
    bumps = []
    monkeypatch.setattr(train_support, "logger", SimpleNamespace(debug=lambda *a, **k: None))
    import bpy
    monkeypatch.setattr(bpy.app, "timers", SimpleNamespace(
        register=lambda fn, first_interval: timers.append(fn)), raising=False)
    monkeypatch.setattr(generations_props, "bump_library_revision", lambda: bumps.append(1))

    state = {"done": None}
    proc = SimpleNamespace(poll=lambda: state["done"])
    train_support.watch_backfill(proc)
    poll = timers[0]
    assert poll() == 2.0 and poll() == 5.0 and not bumps   # still running: back off
    state["done"] = 0
    assert poll() is None and bumps == [1]                  # exited: one reload, stop
    train_support.watch_backfill(None)                      # nothing launched
    assert len(timers) == 1


def test_library_pane_reloads_every_library_on_the_library_edge():
    native = ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
    data = (native / "agent_ui_generations_data.cc").read_text(encoding="utf-8")
    libs = (native / "agent_ui_generations_libraries.cc").read_text(encoding="utf-8")
    assert "agent_ui_generations_reload_user_libraries(C, &wm_ptr);" in data
    assert '"mixar_generations_library_revision"' in libs
    assert "for (const bUserAssetLibrary &lib : U.asset_libraries)" in libs
    assert "list::clear(&ref, C);" in libs
