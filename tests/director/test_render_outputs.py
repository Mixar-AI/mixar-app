# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pure and source-level contracts for Director shot video renders."""

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
DIRECTOR = SCRIPTS / "mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
MOODBOARD_IMPORT = SCRIPTS / "mixar/modules/moodboard/core/media_import.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core.render_spec import (  # noqa: E402
    ordered_render_kinds,
    render_duration_seconds,
    render_frame_bounds,
)


def _read(relative: str) -> str:
    return (DIRECTOR / relative).read_text(encoding="utf-8")


def test_render_selections_have_stable_production_order():
    assert ordered_render_kinds({"DEPTH", "BEAUTY"}) == ("BEAUTY", "DEPTH")
    assert ordered_render_kinds({"CLAY"}) == ("CLAY",)
    assert ordered_render_kinds(set()) == ()


def test_render_span_requires_two_distinct_keyframes():
    assert render_frame_bounds([49, 1, 25, 25]) == (1, 49)
    with pytest.raises(ValueError, match="at least two keyframes"):
        render_frame_bounds([25, 25])


def test_render_duration_honors_fractional_frame_rate():
    assert render_duration_seconds(1, 31, 30, 1.0) == 1.0
    assert render_duration_seconds(1, 31, 30, 1.001) == pytest.approx(1.001)


def test_render_choices_and_results_live_on_each_shot():
    properties = _read("ui/properties/director_properties.py")
    shot_api = _read("core/shot_api.py")

    assert "render_output_types: EnumProperty(" in properties
    assert "options={'ENUM_FLAG'}" in properties
    assert "render_outputs: CollectionProperty(" in properties
    assert "type=MixarDirectorRenderOutput" in properties
    assert "shot.render_output_types = set(parent.render_output_types)" in shot_api
    assert "shot.render_resolution_percentage =" in shot_api


def test_render_job_builds_movies_and_restores_temporary_scene_state():
    passes = _read("core/render_passes.py")
    job = _read("core/render_outputs.py")

    assert "snapshot_render_settings" in passes
    assert "restore_render_settings" in passes
    assert "render.engine = 'BLENDER_WORKBENCH'" in passes
    assert "render.image_settings.media_type = 'VIDEO'" in passes
    assert "render.image_settings.file_format = 'FFMPEG'" in passes
    assert passes.index("media_type = 'VIDEO'") < passes.index("file_format = 'FFMPEG'")
    assert "render.ffmpeg.codec = 'H264'" in passes
    assert '"show_object_outline"' in passes
    assert "show_outline" not in passes
    assert 'view_layer.use_pass_z = kind == "DEPTH"' in passes
    assert "CompositorNodeRLayers" in passes
    assert "ShaderNodeMapRange" in passes
    assert "bpy.app.handlers.render_complete" in job
    assert "bpy.app.handlers.render_cancel" in job
    assert "bpy.app.handlers.render_write" in job
    assert "restore_render_settings(" in job
    assert "_queue_next_pass(shot)" in job
    assert "_start_next_pass_when_idle" in job
    assert 'bpy.app.is_job_running("RENDER")' in job
    assert "return _NEXT_PASS_POLL_SECONDS" in job


def test_completed_movies_are_persisted_and_placed_on_originating_moodboard():
    job = _read("core/render_outputs.py")
    media_import = MOODBOARD_IMPORT.read_text(encoding="utf-8")

    assert "import_generated_video" in job
    assert "scene_name=scene.name" in job
    assert "display_name=display_name" in job
    assert "selected=False" in job
    # Guides land as loose board items, never a formal group.
    assert "group_name=shot.name" not in job
    assert "shutil.move(source_path, destination)" in media_import
    assert "scene.mixie_moodboard_images.add()" in media_import
    assert "place_new_moodboard_item" in media_import


def test_native_surface_hosts_the_export_popup_natively():
    """Export to Moodboard is a native block popup like the lens dropdown.

    The Python popover and its `mixar.director_show_render` opener are gone.
    Presentation stays native (kind toggles and the resolution slider bind
    shot RNA directly); behavior keeps its single Python owner because the
    action rows invoke `mixar.director_send_keyframes` and
    `mixar.director_render_videos`.
    """
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(
        encoding="utf-8"
    )
    popup = (VIEW3D / "view3d_director_popup_render.cc").read_text(
        encoding="utf-8"
    )
    operators = _read("ui/operators/render_ops.py")

    assert "view3d_director_render_popup_create" in overlay
    assert "MIXAR_OT_director_show_render" not in overlay
    assert not (DIRECTOR / "ui/panels/render_popover.py").exists()
    assert "show_render" not in operators
    assert '"render_output_types"' in popup
    assert '"render_resolution_percentage"' in popup
    assert '"render_status"' in popup
    assert '"MIXAR_OT_director_render_videos"' in popup
    assert "to Moodboard" in popup
    # Multi-select contract: picking a render kind must not dismiss the
    # popup (KEEP_OPEN); only click-outside, Esc, or an action closes it —
    # Export/Render via their explicit close callback, since KEEP_OPEN would
    # otherwise keep the popup up after the action too.
    assert "BLOCK_KEEP_OPEN" in popup
    assert "render_popup_close" in popup
    assert "popup_menu_retval_set" in popup
    assert "classes = (" in operators
    assert "MIXAR_OT_director_render_videos," in operators


def test_native_export_is_a_single_moodboard_menu():
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(
        encoding="utf-8"
    )
    capture_ops = _read("ui/operators/capture_ops.py")
    popup = (VIEW3D / "view3d_director_popup_render.cc").read_text(
        encoding="utf-8"
    )

    # One combined Export button opens the native popup; the old separate
    # Moodboard and Video Gen overlay buttons are gone.
    assert '"Export to Moodboard"' in overlay
    assert '"MIXAR_OT_director_send_keyframes"' not in overlay
    assert '"MIXAR_OT_director_send_video"' not in overlay
    # Keyframe export now lives inside the Export popup.
    assert '"MIXAR_OT_director_send_keyframes"' in popup
    assert "MIXAR_OT_director_send_keyframes," in capture_ops
    assert "director_send_moodboard" not in capture_ops
