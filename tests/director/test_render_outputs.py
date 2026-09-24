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
    assert "_queue_next_pass(target)" in job
    assert "_start_next_pass_when_idle" in job
    assert 'bpy.app.is_job_running("RENDER")' in job
    assert "return _NEXT_PASS_POLL_SECONDS" in job


def _beauty_scene(engine="BLENDER_EEVEE", cycles_samples=4096, eevee_samples=4096):
    from types import SimpleNamespace

    return SimpleNamespace(
        render=SimpleNamespace(engine=engine),
        eevee=SimpleNamespace(taa_render_samples=eevee_samples),
        cycles=SimpleNamespace(samples=cycles_samples),
        # No splats: the splat guard walks the scene's objects.
        objects=(),
    )


def test_the_color_pass_is_a_render_not_a_workbench_guide():
    """Workbench's MATERIAL colour mode paints each object's VIEWPORT DISPLAY
    colour — no textures, no lights, no world — so the Color video came out as
    the Clay pass with a tint. It renders with the scene's real engine now."""
    from mixar.modules.director.core.render_passes import beauty_engine

    # A scene parked on Workbench has nothing to show: fall back to EEVEE.
    assert beauty_engine("BLENDER_WORKBENCH") == "BLENDER_EEVEE"
    assert beauty_engine("") == "BLENDER_EEVEE"
    # A real engine is KEPT — Cycles because a panoramic shot renders in
    # nothing else (`core/panoramic.py`).
    assert beauty_engine("BLENDER_EEVEE") == "BLENDER_EEVEE"
    assert beauty_engine("CYCLES") == "CYCLES"

    passes = _read("core/render_passes.py")
    assert "shading.color_type = 'MATERIAL'" not in passes
    # The guides stay Workbench; only Color overrides the engine.
    assert "render.engine = 'BLENDER_WORKBENCH'" in passes
    assert "scene_engine = scene.render.engine" in passes
    assert passes.index("scene_engine = scene.render.engine") < passes.index(
        "_configure_common(scene, target, frame_start, frame_end, path)"
    )


def test_the_color_pass_caps_samples_and_restores_them():
    from mixar.modules.director.core import render_passes

    scene = _beauty_scene(engine="BLENDER_EEVEE")
    render_passes._configure_beauty(scene, scene.render.engine)
    assert scene.render.engine == "BLENDER_EEVEE"
    assert scene.eevee.taa_render_samples == render_passes.BEAUTY_EEVEE_SAMPLES

    cycles_scene = _beauty_scene(engine="CYCLES")
    render_passes._configure_beauty(cycles_scene, cycles_scene.render.engine)
    assert cycles_scene.render.engine == "CYCLES"
    assert cycles_scene.cycles.samples == render_passes.BEAUTY_CYCLES_SAMPLES

    # A scene already under the cap keeps its own count.
    modest = _beauty_scene(engine="BLENDER_EEVEE", eevee_samples=8)
    render_passes._configure_beauty(modest, modest.render.engine)
    assert modest.eevee.taa_render_samples == 8

    # Both are snapshotted, so the user's scene comes back.
    source = _read("core/render_passes.py")
    assert '"cycles": _property_snapshot(' in source
    assert 'for name, value in saved.get("cycles", {}).items():' in source


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
    Presentation stays native (the toggles and the size cells bind shot RNA
    directly); behavior keeps its single Python owner because the one Send
    action invokes `mixar.director_export_to_moodboard`.
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
    assert '"export_images"' in popup
    assert '"render_status"' in popup
    assert '"MIXAR_OT_director_export_to_moodboard"' in popup
    assert "class MIXAR_OT_director_export_to_moodboard" in operators
    # Multi-select contract: a toggle must not dismiss the popup
    # (KEEP_OPEN); only click-outside, Esc, or the Send action closes it —
    # via its explicit close callback, since KEEP_OPEN would otherwise keep
    # the popup up after the action too.
    assert "BLOCK_KEEP_OPEN" in popup
    assert "render_popup_close" in popup
    assert "popup_menu_retval_set" in popup
    assert "classes = (" in operators
    assert "MIXAR_OT_director_render_videos," in operators
    assert "MIXAR_OT_director_export_to_moodboard," in operators


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
    # Keyframe images go through the popup's one Send action; the images-only
    # operator stays for scripts.
    assert '"MIXAR_OT_director_export_to_moodboard"' in popup
    assert '"MIXAR_OT_director_send_keyframes"' not in popup
    assert "MIXAR_OT_director_send_keyframes," in capture_ops
    assert "director_send_moodboard" not in capture_ops
