# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""My Libraries: folder media, multi-select and removing a library.

Three user-facing failures are pinned here:

* A connected folder of plain images/videos listed as EMPTY, because
  Blender's asset list only sees datablocks marked inside ``.blend`` files.
  ``core/library_media.py`` now mirrors the folder's media into
  ``wm.mixar_generations_files`` and the C++ pane paints it.
* Tiles could only be selected one at a time, so several pictures could not
  be added together. Ctrl/Cmd/Shift-click builds ``mixar_generations_multi``
  and "Add N" boards every selected file.
* A connected folder could not be removed, and the auto-archive "Mixar
  Generations" was listed among the user's folders as a stray duplicate.
"""

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.agent_bubble.core import library_media
from mixar.modules.agent_bubble.ui.properties import generations_files_props

from test_agent_bubble_generations import OPS, _op_self

CPP = ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
LIBRARIES_CC = (CPP / "agent_ui_generations_libraries.cc").read_text(encoding="utf-8")
DATA_CC = (CPP / "agent_ui_generations_data.cc").read_text(encoding="utf-8")
GRID_CC = (CPP / "agent_ui_generations_grid.cc").read_text(encoding="utf-8")
PANE_CC = (CPP / "agent_ui_generations.cc").read_text(encoding="utf-8")
DETAIL_CC = (CPP / "agent_ui_generations_detail.cc").read_text(encoding="utf-8")
SELECTION_CC = (CPP / "agent_ui_generations_selection.cc").read_text(encoding="utf-8")
LAYOUT_HH = (CPP / "agent_ui_generations_layout.hh").read_text(encoding="utf-8")
CMAKE = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")


def _touch(path: Path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ---------------------------------------------------------------------------
# Scanning a folder
# ---------------------------------------------------------------------------


def test_a_folder_of_pictures_and_movies_is_listed(tmp_path):
    _touch(tmp_path / "a.png")
    _touch(tmp_path / "sub" / "b.JPG")
    _touch(tmp_path / "clip.mp4")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "scene.blend")
    _touch(tmp_path / ".hidden.png")
    _touch(tmp_path / ".cache" / "c.png")

    _signature, entries = library_media.scan_folder(str(tmp_path))
    found = {os.path.relpath(path, tmp_path): kind for path, kind, _mtime in entries}

    assert found == {
        "a.png": "IMAGE",
        os.path.join("sub", "b.JPG"): "IMAGE",
        "clip.mp4": "VIDEO",
    }


def test_the_scan_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(library_media, "MAX_FILES", 3)
    for i in range(10):
        _touch(tmp_path / f"{i}.png")
    _signature, entries = library_media.scan_folder(str(tmp_path))
    assert len(entries) == 3


def test_the_signature_notices_a_new_file(tmp_path):
    _touch(tmp_path / "a.png")
    before = library_media.folder_signature(str(tmp_path))
    assert before == library_media.scan_folder(str(tmp_path))[0]
    _touch(tmp_path / "b.png")
    os.utime(tmp_path, (1, 1))
    assert library_media.folder_signature(str(tmp_path)) != before


class _Files(list):
    def add(self):
        row = SimpleNamespace(library="", path="", name="", kind="", mtime=0, icon_id=0)
        self.append(row)
        return row


def _context(tmp_path, libs):
    wm = SimpleNamespace(mixar_generations_files=_Files())
    prefs = SimpleNamespace(filepaths=SimpleNamespace(asset_libraries=[
        SimpleNamespace(name=name, path=str(path)) for name, path in libs
    ]))
    return SimpleNamespace(window_manager=wm, preferences=prefs)


def test_refresh_mirrors_user_folders_but_not_the_generations_archive(tmp_path, monkeypatch):
    mine = tmp_path / "mine"
    archive = tmp_path / "archive"
    _touch(mine / "ref.png")
    _touch(archive / "preview.png")
    monkeypatch.setattr(library_media.bpy.path, "abspath", lambda p: p)
    monkeypatch.setattr(library_media, "_icon_id", lambda _path, _kind: 7)
    library_media._scan_cache.clear()
    context = _context(tmp_path, [("Mine", mine), ("Mixar Generations", archive)])

    assert library_media.refresh(context, force=True) is True
    rows = context.window_manager.mixar_generations_files
    assert [(r.library, r.name, r.kind, r.icon_id) for r in rows] == [
        ("Mine", "ref.png", "IMAGE", 7)
    ]
    assert library_media.refresh(context, force=True) is False, (
        "an unchanged folder must not rewrite the collection"
    )


def test_refresh_is_throttled(tmp_path, monkeypatch):
    monkeypatch.setattr(library_media.bpy.path, "abspath", lambda p: p)
    context = _context(tmp_path, [])
    library_media.refresh(context, force=True)
    calls = []
    monkeypatch.setattr(library_media, "_user_libraries", lambda _c: calls.append(1) or [])
    library_media.refresh(context)
    assert calls == []


def test_the_pane_reads_every_file_field():
    for field in generations_files_props.FIELD_NAMES:
        assert f'"{field}"' in LIBRARIES_CC
    assert f'"{generations_files_props.FILES_PROP}"' in LIBRARIES_CC
    assert "agent_ui_generations_gather_files(C, r_data, only)" in DATA_CC


def test_a_folder_file_has_its_own_thumbnail_path():
    assert "draw_file_thumb(C, item, box)" in GRID_CC
    body = GRID_CC[GRID_CC.index("void draw_file_thumb("):]
    body = body[:body.index("\n}\n")]
    assert body.index("icon_ensure_deferred(") < body.index("icon_draw_preview(")


# ---------------------------------------------------------------------------
# The rail
# ---------------------------------------------------------------------------


def test_the_generations_archive_is_not_listed_among_the_users_folders():
    gather = DATA_CC[DATA_CC.index("void gather_libraries("):]
    gather = gather[:gather.index("\n}\n")]
    assert "GENERATIONS_LIBRARY_NAME" in gather
    assert re.search(r"STREQ\(lib->name, GENERATIONS_LIBRARY_NAME\)", DATA_CC)


def test_the_library_source_reads_as_the_users_folders():
    assert '"My Libraries"' in LAYOUT_HH
    assert '"Asset Library"' not in LAYOUT_HH


def test_every_library_row_offers_remove():
    assert '"mixar.generations_remove_library"' in LIBRARIES_CC
    assert '"library_name"' in LIBRARIES_CC
    assert "AGENT_ICON_CROSS" in LIBRARIES_CC


def _libs_context(names, browsing=""):
    libs = [SimpleNamespace(name=n) for n in names]
    wm = SimpleNamespace(mixar_generations_library=browsing,
                         mixar_generations_selected="x", mixar_generations_multi="x\ny")
    prefs = SimpleNamespace(filepaths=SimpleNamespace(asset_libraries=libs))
    return SimpleNamespace(window_manager=wm, preferences=prefs)


def test_removing_a_library_uses_blenders_operator(monkeypatch):
    calls = []
    monkeypatch.setattr(OPS.bpy.ops.preferences, "asset_library_remove",
                        lambda **kw: calls.append(kw))
    monkeypatch.setattr(OPS, "_refresh_media", lambda *_a, **_k: None)
    context = _libs_context(["User Library", "SKU1"], browsing="SKU1")
    op = _op_self(library_name="SKU1")

    assert OPS.MIXAR_OT_generations_remove_library.execute(op, context) == {'FINISHED'}
    assert calls == [{"index": 1}]
    wm = context.window_manager
    assert wm.mixar_generations_library == "", "still browsing a removed folder"
    assert wm.mixar_generations_multi == ""
    assert "not deleted" in op.reports[0][1]


def test_the_generations_archive_cannot_be_removed(monkeypatch):
    calls = []
    monkeypatch.setattr(OPS.bpy.ops.preferences, "asset_library_remove",
                        lambda **kw: calls.append(kw))
    op = _op_self(library_name="Mixar Generations")
    result = OPS.MIXAR_OT_generations_remove_library.execute(
        op, _libs_context(["Mixar Generations"]))
    assert result == {'CANCELLED'} and calls == []


# ---------------------------------------------------------------------------
# Multi-select
# ---------------------------------------------------------------------------


def _wm(selected="", multi=""):
    return SimpleNamespace(mixar_generations_selected=selected, mixar_generations_multi=multi)


def test_ctrl_click_builds_and_shrinks_a_selection():
    wm = _wm("file:/a.png")
    OPS.toggle_selection(wm, "file:/b.png")
    assert OPS.selected_keys(wm) == ["file:/a.png", "file:/b.png"]
    assert wm.mixar_generations_selected == "file:/b.png"

    OPS.toggle_selection(wm, "file:/b.png")
    assert OPS.selected_keys(wm) == ["file:/a.png"]
    assert wm.mixar_generations_multi == "", "one item is a plain selection"
    assert wm.mixar_generations_selected == "file:/a.png"


def test_a_plain_click_replaces_the_selection():
    wm = _wm("file:/a.png", "file:/a.png\nfile:/b.png")
    op = _op_self(value="file:/c.png", extend=False)
    OPS.MIXAR_OT_generations_select.execute(op, SimpleNamespace(window_manager=wm))
    assert OPS.selected_keys(wm) == ["file:/c.png"]


@pytest.mark.parametrize("modifier", ["ctrl", "oskey", "shift"])
def test_every_platform_modifier_extends(modifier):
    wm = _wm("file:/a.png")
    event = SimpleNamespace(ctrl=False, oskey=False, shift=False)
    setattr(event, modifier, True)
    op = _op_self(value="file:/b.png", extend=False)
    op.execute = lambda ctx: OPS.MIXAR_OT_generations_select.execute(op, ctx)
    OPS.MIXAR_OT_generations_select.invoke(op, SimpleNamespace(window_manager=wm), event)
    assert len(OPS.selected_keys(wm)) == 2


def test_an_asset_key_resolves_to_its_blend():
    folders = {"SKU1": "/libs/sku1"}
    assert OPS.resolve_asset_key("asset:SKU1:sub/chair.blend/Object/Chair 01", folders) == (
        os.path.join("/libs/sku1", "sub/chair.blend"), "Object", "Chair 01")
    assert OPS.resolve_asset_key("asset:SKU1:chair.blend\\Collection\\Set", folders)[1] == "Collection"
    assert OPS.resolve_asset_key("asset:Gone:chair.blend/Object/C", folders) is None
    assert OPS.resolve_asset_key("file:/a.png", folders) is None


def test_add_selected_boards_files_and_spawns_assets(tmp_path, monkeypatch):
    import mixar.modules.agent_bubble.core.spawn_asset as spawn
    import mixar.modules.moodboard.core.media_import as media

    a = tmp_path / "a.png"
    b = tmp_path / "b.mp4"
    _touch(a)
    _touch(b)
    boarded, spawned = [], []
    monkeypatch.setattr(media, "load_media_file_to_board",
                        lambda _scene, path: boarded.append(path) or object())
    monkeypatch.setattr(spawn, "spawn_library_asset",
                        lambda _ctx, *asset: spawned.append(asset) or (True, "ok"))
    monkeypatch.setattr(OPS, "_library_folders", lambda: {"SKU1": "/libs"})
    wm = _wm(f"file:{a}", f"file:{a}\nfile:{b}\nasset:SKU1:c.blend/Object/Chair")
    op = _op_self()
    context = SimpleNamespace(window_manager=wm, scene=object())

    assert OPS.MIXAR_OT_generations_add_selected.execute(op, context) == {'FINISHED'}
    assert sorted(boarded) == sorted([str(a), str(b)])
    assert spawned == [(os.path.join("/libs", "c.blend"), "Object", "Chair")]
    assert op.reports[-1] == ({'INFO'}, "Added 2 to the moodboard; 1 to the scene")


def test_add_selected_with_nothing_selected_says_so():
    op = _op_self()
    context = SimpleNamespace(window_manager=_wm(), scene=object())
    assert OPS.MIXAR_OT_generations_add_selected.execute(op, context) == {'CANCELLED'}


def test_the_pane_paints_a_ring_for_every_selected_tile():
    assert "agent_ui_generations_is_selected(data, item.key)" in GRID_CC
    assert "for (const rctf &tile : selected_tiles)" in PANE_CC
    assert '"mixar_generations_multi"' in SELECTION_CC
    assert "agent_ui_generations_detail_multi(block, panel, frame, data)" in DETAIL_CC
    assert "agent_ui_generations_selection.cc" in CMAKE


def test_a_folder_file_is_added_to_the_moodboard_from_the_detail_column():
    block = DETAIL_CC[DETAIL_CC.index("if (gen_item_is_file(item))"):]
    assert '"mixar.generations_add_selected"' in block[:600]
