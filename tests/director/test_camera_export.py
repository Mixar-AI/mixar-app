# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Readiness rules and reachability for the camera-first Moodboard export.

A Blender power user keyframes a camera through the native timeline and has no
Director shot, so the Director's own export button — poll-gated on
``is_directing`` plus a shot with beats — can never fire for them. These pin
the replacement: who the camera is, which frames it covers, why a blocked
state says so out loud, and that both menu entry points actually exist.
"""

from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


# The render stack imports mathutils, which the root conftest does not stub.
sys.modules.setdefault("mathutils", MagicMock(name="mathutils"))

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
DIRECTOR = SCRIPTS / "mixar/modules/director"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core.render_request import (  # noqa: E402
    REASON_BUSY,
    REASON_EMPTY_RANGE,
    REASON_NO_CAMERA,
    REASON_NO_KINDS,
    build_export_plan,
    describe_range,
    resolve_export_camera,
    resolve_frame_range,
)


def _read(relative: str) -> str:
    return (DIRECTOR / relative).read_text(encoding="utf-8")


def _camera(name="Camera"):
    return SimpleNamespace(type="CAMERA", name=name)


def _scene(
    *,
    camera=None,
    objects=(),
    frame_start=1,
    frame_end=250,
    use_preview_range=False,
    preview=(10, 20),
):
    return SimpleNamespace(
        camera=camera,
        objects=list(objects),
        frame_start=frame_start,
        frame_end=frame_end,
        use_preview_range=use_preview_range,
        frame_preview_start=preview[0],
        frame_preview_end=preview[1],
    )


# --- camera resolution -----------------------------------------------------


def test_explicit_override_beats_every_other_candidate():
    override, active, scene_cam = _camera("A"), _camera("B"), _camera("C")
    scene = _scene(camera=scene_cam)
    picked = resolve_export_camera(
        scene, override=override, active=active, selected=[scene_cam]
    )
    assert picked is override


def test_active_and_selected_cameras_beat_the_scene_camera():
    # A user with several cameras is asking about the one they are looking at.
    active, scene_cam = _camera("Active"), _camera("Scene")
    scene = _scene(camera=scene_cam)
    assert resolve_export_camera(scene, active=active) is active

    selected = _camera("Selected")
    assert (
        resolve_export_camera(scene, selected=[SimpleNamespace(type="MESH"), selected])
        is selected
    )


def test_scene_camera_then_the_lone_camera_are_the_fallbacks():
    scene_cam = _camera("Scene")
    assert resolve_export_camera(_scene(camera=scene_cam)) is scene_cam

    only = _camera("Only")
    assert resolve_export_camera(_scene(objects=[only])) is only


def test_two_cameras_and_no_active_or_scene_camera_resolves_to_nothing():
    # Guessing between them would render the wrong one; the surface asks.
    scene = _scene(objects=[_camera("One"), _camera("Two")])
    assert resolve_export_camera(scene) is None


# --- frame range -----------------------------------------------------------


def test_camera_keys_span_first_to_last_key():
    scene = _scene()
    assert resolve_frame_range(scene, [40, 1, 12], "CAMERA_KEYS") == (1, 40)


def test_scene_and_preview_ranges_come_from_the_scene():
    scene = _scene(frame_start=5, frame_end=60, use_preview_range=True,
                   preview=(10, 20))
    assert resolve_frame_range(scene, [1, 40], "SCENE") == (5, 60)
    assert resolve_frame_range(scene, [1, 40], "PREVIEW") == (10, 20)


def test_preview_range_falls_back_to_the_scene_range_when_unset():
    # This is what the Timeline itself shows in that state.
    scene = _scene(frame_start=5, frame_end=60, use_preview_range=False)
    assert resolve_frame_range(scene, [1, 40], "PREVIEW") == (5, 60)


# --- readiness -------------------------------------------------------------


def test_missing_camera_is_reported_before_anything_else():
    plan = build_export_plan(_scene(), None, [], {"CLAY"})
    assert not plan.ok
    assert plan.reason == REASON_NO_CAMERA


def test_an_unanimated_camera_names_itself_in_the_reason():
    camera = _camera("Shot Cam")
    plan = build_export_plan(_scene(camera=camera), camera, [], {"CLAY"})
    assert not plan.ok
    assert "Shot Cam" in plan.reason
    assert plan.key_count == 0


def test_one_keyframe_is_not_an_animation():
    camera = _camera()
    plan = build_export_plan(_scene(camera=camera), camera, [7, 7], {"CLAY"})
    assert not plan.ok
    assert "one keyframe" in plan.reason
    assert plan.key_count == 1


def test_keyframes_are_required_even_for_the_scene_range():
    # Rendering a still camera over the scene range is a video of nothing.
    camera = _camera()
    plan = build_export_plan(
        _scene(camera=camera), camera, [], {"CLAY"}, range_source="SCENE"
    )
    assert not plan.ok
    assert plan.reason != REASON_NO_KINDS


def test_an_empty_scene_range_names_which_range_is_empty():
    camera = _camera()
    scene = _scene(camera=camera, frame_start=100, frame_end=100)
    plan = build_export_plan(
        scene, camera, [1, 50], {"CLAY"}, range_source="SCENE"
    )
    assert not plan.ok
    assert plan.reason == REASON_EMPTY_RANGE.format(label="scene frame range")


def test_no_selected_pass_blocks_but_keeps_the_resolved_span():
    camera = _camera()
    plan = build_export_plan(_scene(camera=camera), camera, [1, 48], set())
    assert not plan.ok
    assert plan.reason == REASON_NO_KINDS
    # The span is still reported so the surface can show it while blocked.
    assert (plan.frame_start, plan.frame_end) == (1, 48)


def test_a_running_render_blocks_last_of_all():
    camera = _camera()
    plan = build_export_plan(
        _scene(camera=camera), camera, [1, 48], {"CLAY"}, render_busy=True
    )
    assert not plan.ok
    assert plan.reason == REASON_BUSY


def test_a_ready_plan_carries_the_span_and_ordered_passes():
    camera = _camera()
    plan = build_export_plan(
        _scene(camera=camera), camera, [48, 1, 24], {"DEPTH", "BEAUTY"}
    )
    assert plan.ok
    assert plan.reason == ""
    assert (plan.frame_start, plan.frame_end) == (1, 48)
    assert plan.key_count == 3
    assert plan.frame_count == 48
    # Production order, not set order.
    assert plan.kinds == ("BEAUTY", "DEPTH")


def test_range_summary_reports_duration_at_the_scene_frame_rate():
    camera = _camera()
    plan = build_export_plan(_scene(camera=camera), camera, [1, 25], {"CLAY"})
    assert describe_range(plan, 24, 1.0) == "1 – 25 · 1.0s"


# --- reachability ----------------------------------------------------------


def test_the_row_lands_in_the_render_menu_and_both_animation_editors():
    menu = _read("ui/menus/camera_export_menu.py")

    # The Render menu is the discovery surface and is never camera-gated.
    assert 'ALWAYS_MENUS = ("TOPBAR_MT_render",)' in menu
    assert '"TIME_MT_view"' in menu
    assert '"DOPESHEET_MT_view"' in menu
    # Missing upstream menus are skipped, never raised: a rename must not
    # break module import.
    assert "getattr(bpy.types, menu_name, None)" in menu
    assert "def unregister()" in menu


def test_both_rows_open_the_one_shared_popup():
    menu = _read("ui/menus/camera_export_menu.py")
    panel = _read("ui/panels/camera_export_panel.py")

    assert '"wm.call_panel"' in menu
    assert "props.keep_open = True" in menu
    assert "CAMERA_EXPORT_PANEL_ID" in menu
    assert "class MIXAR_PT_camera_export(Panel)" in panel
    assert "bl_space_type = 'TOPBAR'" in panel
    assert "draw_camera_export(self.layout, context)" in panel


def test_the_controls_have_exactly_one_definition():
    drawer = _read("ui/camera_export_drawer.py")
    panel = _read("ui/panels/camera_export_panel.py")

    assert "def draw_camera_export(layout, context)" in drawer
    assert "from ..camera_export_drawer import draw_camera_export" in panel
    # The popup is the only host; nothing rebuilds these controls elsewhere.
    for surface in ("ui/menus/camera_export_menu.py",):
        assert "render_output_types" not in _read(surface)


def test_the_operator_reports_blockers_instead_of_polling_them_away():
    ops = _read("ui/operators/camera_export_ops.py")

    # poll() guards only what is genuinely un-invokable.
    assert "return context.scene is not None and not render_busy()" in ops
    assert "self.report({'ERROR'}, plan.reason" in ops
    assert "start_camera_render(" in ops


def test_the_surface_states_its_blocker_and_offers_the_fix():
    drawer = _read("ui/camera_export_drawer.py")

    assert "box.label(text=plan.reason, icon='ERROR')" in drawer
    assert '"object.camera_add"' in drawer
    assert '"mixar.director_enter"' in drawer


def test_camera_export_state_is_scene_local_and_never_saved_as_running():
    properties = _read("ui/properties/camera_export_properties.py")

    assert "bpy.types.Scene.mixar_camera_export = PointerProperty" in properties
    assert "render_output_types: EnumProperty(" in properties
    assert "options={'ENUM_FLAG'}" in properties
    assert properties.count("options={'SKIP_SAVE', 'HIDDEN'}") == 3


# --- shared render engine --------------------------------------------------


def test_one_render_job_serves_both_shots_and_bare_cameras():
    outputs = _read("core/render_outputs.py")
    passes = _read("core/render_passes.py")

    assert "def start_shot_render(" in outputs
    assert "def start_camera_render(" in outputs
    # Both go through the same starter, so the job, handlers and restore path
    # can never diverge between the two callers.
    assert outputs.count("def _start_render(") == 1
    assert outputs.count("return _start_render(context, scene, target,") == 2
    # The passes read the target, never a shot's own RNA.
    assert "def configure_render_pass(scene, view_layer, target," in passes
    assert "shot." not in passes
    assert ".beats" not in passes


def test_the_render_span_is_frozen_when_the_job_starts():
    target = _read("core/render_target.py")
    outputs = _read("core/render_outputs.py")

    # A span re-read from live beats would shift under a Dope Sheet edit made
    # while the render runs.
    assert "frame_start" in target and "frame_end" in target
    assert "def target_ref(" in target
    assert "frame_start, frame_end = target.frame_start, target.frame_end" in _read(
        "core/render_passes.py"
    )
    # The job holds a serialisable ref, re-resolved on every callback rather
    # than a Python reference to RNA that can outlive its datablock.
    assert '"target": target_ref(target)' in outputs
    assert "def _job_target(job)" in outputs


def test_camera_keys_have_one_definition_shared_with_the_beat_strip():
    curves = _read("core/anim_curves.py")
    beat_sync = _read("core/beat_sync.py")
    camera_export = _read("core/camera_export.py")

    assert "def camera_key_frames(camera," in curves
    assert "CAMERA_MOTION_PATHS" in curves
    # Slotted actions: Blender 4.4+ removed Action.fcurves, and a silent
    # zero-curve read would report every animated camera as unanimated. The
    # channelbag resolution lives once, in the shared helper Director's
    # anim_curves re-exports.
    assert re.search(r"common\.utils\.animation import [^\n]*\bassigned_fcurves\b", curves)
    shared = (SCRIPTS / "mixar/modules/common/utils/animation.py").read_text(
        encoding="utf-8"
    )
    assert "animdata_get_channelbag_for_assigned_slot" in shared
    for consumer in (beat_sync, camera_export):
        assert "camera_key_frames" in consumer
    # The old private copy is gone from beat_sync.
    assert '_CAMERA_PATHS = {' not in beat_sync


# --- the draw path actually runs -------------------------------------------


class _FakeLayout:
    """Records what a draw produced. `bpy` is a mock in tests, so a real
    layout never runs — without this, a typo in the draw path ships."""

    def __init__(self, sink=None):
        self.sink = sink if sink is not None else []
        self.alert = False
        self.enabled = True
        self.scale_y = 1.0

    def _child(self, kind):
        self.sink.append((kind,))
        return _FakeLayout(self.sink)

    def row(self, **_kwargs):
        return self._child("row")

    def column(self, **_kwargs):
        return self._child("column")

    def box(self):
        return self._child("box")

    def separator(self, **_kwargs):
        self.sink.append(("separator",))

    def label(self, text="", icon=""):
        self.sink.append(("label", text, icon))

    def prop(self, _data, name, **_kwargs):
        self.sink.append(("prop", name))

    def progress(self, **kwargs):
        self.sink.append(("progress", kwargs.get("text", "")))

    def operator(self, idname, **_kwargs):
        self.sink.append(("operator", idname))
        return SimpleNamespace()

    def texts(self):
        return [item[1] for item in self.sink if item[0] == "label"]

    def operators(self):
        return [item[1] for item in self.sink if item[0] == "operator"]

    def props(self):
        return [item[1] for item in self.sink if item[0] == "prop"]


def _settings(**overrides):
    values = {
        "camera_override": None,
        "range_source": "CAMERA_KEYS",
        "render_output_types": {"CLAY"},
        "render_resolution_percentage": 50,
        "render_is_running": False,
        "render_progress": 0.0,
        "render_status": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _draw_scene(camera=None, objects=(), settings=None, **scene_kwargs):
    from mixar.modules.director.ui import camera_export_drawer

    scene = _scene(camera=camera, objects=objects, **scene_kwargs)
    scene.mixar_camera_export = settings if settings is not None else _settings()
    scene.mixar_director = SimpleNamespace(shots=[])
    scene.render = SimpleNamespace(fps=24, fps_base=1.0)
    context = SimpleNamespace(
        scene=scene, active_object=camera, selected_objects=[]
    )
    layout = _FakeLayout()
    camera_export_drawer.draw_camera_export(layout, context)
    return layout


def _animated_camera(frames, name="Camera"):
    curve = SimpleNamespace(
        data_path="location",
        keyframe_points=[SimpleNamespace(co=(float(f), 0.0)) for f in frames],
    )
    action = SimpleNamespace(fcurves=[curve])
    return SimpleNamespace(
        type="CAMERA",
        name=name,
        animation_data=SimpleNamespace(action=action),
        data=SimpleNamespace(animation_data=None),
    )


def test_an_empty_scene_draws_the_reason_and_an_add_camera_button():
    layout = _draw_scene()

    assert REASON_NO_CAMERA in layout.texts()
    assert "object.camera_add" in layout.operators()
    # No half-usable form behind a blocker that cannot be cleared here.
    assert "render_output_types" not in layout.props()


def test_an_unanimated_camera_is_offered_director():
    camera = SimpleNamespace(
        type="CAMERA", name="Camera", animation_data=None, data=None
    )
    layout = _draw_scene(camera=camera)

    assert any("no camera keyframes" in text for text in layout.texts())
    assert "mixar.director_enter" in layout.operators()


def test_an_animated_camera_draws_the_full_form_and_the_render_action():
    layout = _draw_scene(camera=_animated_camera([1, 48]))

    assert "mixar.render_camera_to_moodboard" in layout.operators()
    assert "render_output_types" in layout.props()
    assert "range_source" in layout.props()
    assert "render_resolution_percentage" in layout.props()
    # The resolved span is stated, so the user knows what they will get.
    assert "1 – 48 · 2.0s" in layout.texts()


def test_a_running_render_replaces_the_form_with_live_progress():
    settings = _settings(render_is_running=True, render_progress=0.45,
                         render_status="Rendering Clay 1/2")
    layout = _draw_scene(camera=_animated_camera([1, 48]), settings=settings)

    assert ("progress", "Rendering Clay 1/2") in layout.sink
    # Starting a second render from here is impossible, not merely discouraged.
    assert "mixar.render_camera_to_moodboard" not in layout.operators()


def test_a_bare_camera_export_never_rewrites_the_users_animation():
    """Export-to-Moodboard renders whatever camera the user picked; only a
    Director-owned shot camera gets its rotation keys normalised."""
    outputs = _read("core/render_outputs.py")
    start = outputs.split("def _start_render(")[1].split("\ndef ")[0]
    assert "repair_rotation_continuity" not in start
    shot = outputs.split("def start_shot_render(")[1].split("\ndef ")[0]
    assert "repair_rotation_continuity(shot.camera)" in shot
    camera = outputs.split("def start_camera_render(")[1].split("\ndef ")[0]
    assert "repair_rotation_continuity" not in camera
