# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The "My Cameras" card lists the SCENE's cameras, not Director's shots.

A shot-based list could only show cameras Director had already adopted, so a
fresh scene's own camera was missing from the box, and a camera added,
imported or deleted anywhere else never appeared or disappeared. Reading the
scene each draw fixes all three, and taking the highlight from `scene->camera`
means the live row follows a change made from the outliner or a script.

Source-level because the surface is C++ and this container has no `upstream/`
to build against; every assertion pins something the compiler accepts either
way.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"

CAMERAS = (VIEW3D / "view3d_director_cinema_cameras.cc").read_text(encoding="utf-8")
RIGHT = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")
HEADER = (VIEW3D / "view3d_director_cinema.hh").read_text(encoding="utf-8")
CMAKE = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")


def test_the_painter_is_built():
    assert "view3d_director_cinema_cameras.cc" in CMAKE
    assert "void cinema_draw_camera_list(" in HEADER


def test_the_right_column_delegates_the_card():
    """The card moved out of the right column, which was at the 500-line rule."""
    assert "cinema_draw_camera_list(\n      block, C, region, state, column_card(region, CINEMA_COLUMN_TOP, CINEMA_CAMERAS_H));" in RIGHT
    assert 'cinema_qa_record(region, row, "director_camera"' not in RIGHT
    assert len(RIGHT.splitlines()) < 500
    assert len(CAMERAS.splitlines()) < 500


def test_rows_come_from_the_scenes_objects_not_the_shots_collection():
    assert 'RNA_struct_find_property(&scene_ptr, "objects")' in CAMERAS
    assert "object->type == OB_CAMERA" in CAMERAS
    # The old source of rows. Its absence is the fix.
    assert '"shots"' not in CAMERAS
    assert "active_shot_index" not in CAMERAS


def test_rows_are_sorted_so_they_do_not_move_under_the_cursor():
    assert "std::sort(r_cameras->begin(), r_cameras->end()" in CAMERAS
    assert "BLI_strcasecmp(a->id.name + 2, b->id.name + 2)" in CAMERAS


def test_the_highlight_follows_the_scenes_active_camera():
    """Whoever changed it — the outliner, a shot switch, a script."""
    assert "const Object *live = scene ? scene->camera : nullptr;" in CAMERAS
    assert "const bool active = camera == live;" in CAMERAS
    body = CAMERAS[CAMERAS.index("int active_index = 0;") :]
    assert "if (cameras[index] == live)" in body


def test_clicking_a_row_directs_that_camera_by_name():
    """`pick_camera` switches to the newest take of that camera, or mints a
    shot for one that has none — it never reassigns the active shot's camera
    and collapses two camera timelines."""
    assert '"MIXAR_OT_director_pick_camera"' in CAMERAS
    assert 'RNA_string_set(ui::button_operator_ptr_ensure(but), "camera_name", name);' in CAMERAS


def test_the_empty_state_still_reads_as_empty():
    assert '"No cameras yet"' in CAMERAS
    assert "if (cameras.is_empty())" in CAMERAS


def test_add_camera_still_starts_a_session_before_it_mints_shots():
    """With nothing directed yet the chip must be `director_start`, which
    adopts a camera the scene already has; `new_shot` always mints another."""
    assert 'state.has_shot ? "MIXAR_OT_director_new_shot" : "MIXAR_OT_director_start"' in CAMERAS
