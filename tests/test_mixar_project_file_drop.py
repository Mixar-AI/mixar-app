# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPACE_API = ROOT / "src/source/blender/editors/space_api"


def test_mixar_project_files_have_a_whole_window_dropbox():
    implementation = (SPACE_API / "mixar_file_drop.cc").read_text(encoding="utf-8")
    registration = (SPACE_API / "spacetypes.cc").read_text(encoding="utf-8")

    assert "WM_drag_get_path_file_type(drag) == FILE_TYPE_MIXAR" in implementation
    assert 'WM_dropboxmap_find("Window", SPACE_EMPTY, RGN_TYPE_WINDOW)' in implementation
    assert '"WM_OT_drop_blend_file"' in implementation
    assert "ED_keymap_screen(keyconf);\n  ED_dropboxes_mixar_file();" in registration
