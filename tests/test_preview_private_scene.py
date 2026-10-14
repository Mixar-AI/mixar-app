# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent's preview renders a private copy, never the user's scene.

Rendering the user's scene switched its engine to Cycles for every inspection, and a
3D view in Rendered shading follows the scene engine: the viewport went black with
"Loading render kernels" and every object vanished until the job restored EEVEE.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_async_preview import KEY, _scene, preview  # noqa: F401

from mixar.modules.space_mixie_chat.core import render_scene
from mixar.modules.common.render_coordinator.constants import INTERNAL_RENDER_SCENE_PROP, is_internal_scene

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"


class FakeScene(dict):
    """dict = custom properties; registered properties are attributes."""

    def __init__(self, name, engine="BLENDER_EEVEE", compositing=False, group=None, **custom):
        super().__init__(**custom)
        self.name = name
        self.render = SimpleNamespace(engine=engine, use_compositing=compositing, use_sequencer=True)
        self.compositing_node_group = group
        self.unset = []

    def property_unset(self, name):
        self.unset.append(name)

    def copy(self):
        return FakeScene(self.name + ".001", self.render.engine, self.render.use_compositing,
                         self.compositing_node_group, **dict(self))

    __hash__ = object.__hash__
    __eq__ = object.__eq__


class FakeScenes(list):
    def remove(self, scene, do_unlink=True):
        list.remove(self, scene)


@pytest.fixture
def fake_bpy(monkeypatch):
    bpy = MagicMock()
    bpy.types.Scene.bl_rna.properties = [
        SimpleNamespace(identifier=name, is_runtime=runtime) for name, runtime in (
            ("render", False), ("camera", False), ("cycles", True), ("cycles_curves", True),
            ("mixie_session_id", True), ("mixie_chat_messages", True), ("mixie_moodboard_action_nodes", True),
            ("mixar_op_history_id", True))]
    bpy.data.scenes = FakeScenes()
    monkeypatch.setattr(render_scene, "bpy", bpy)
    return bpy


def test_copy_drops_mixar_identity_and_keeps_render_settings(fake_bpy):
    source = FakeScene("Hi", mixar_scene_id="doc-1", mixar_tab_order=0, _mixar_file_version=3, user_custom=7)
    fake_bpy.data.scenes.append(source)
    copy = render_scene.create(source, inspection=True)
    assert copy.unset == ["mixie_session_id", "mixie_chat_messages", "mixie_moodboard_action_nodes",
                          "mixar_op_history_id"]                # never cycles / cycles_curves / DNA
    assert dict(copy) == {"user_custom": 7, INTERNAL_RENDER_SCENE_PROP: True}
    assert is_internal_scene(copy) and not is_internal_scene(source)
    assert copy.name == render_scene.RENDER_SCENE_NAME and copy.name > "zzz"   # sorts after ASCII names
    assert copy.render.use_compositing is False and copy.render.use_sequencer is False
    assert source.unset == [] and source["mixar_scene_id"] == "doc-1"


def test_a_final_copy_keeps_compositing_and_sequencer_flags(fake_bpy):
    copy = render_scene.create(FakeScene("Hi"), inspection=False)
    assert copy.render.use_sequencer is True


@pytest.mark.parametrize("engine, compositing, group, isolated", [
    ("BLENDER_EEVEE", False, None, True),
    ("CYCLES", True, None, True),             # compositing on, but no node group
    ("CYCLES", True, "Compositing", False),   # a Render Layers node would name the user's scene
    ("CYCLES", False, "Compositing", True),
    ("OCTANE", False, None, False),           # third-party settings may live in reset properties
])
def test_which_finals_are_isolated(engine, compositing, group, isolated):
    assert render_scene.isolate_final(FakeScene("s", engine, compositing, group)) is isolated


def test_sweep_keeps_the_live_job_and_tolerates_freed_scenes(fake_bpy):
    live, stale, user = FakeScene("a"), FakeScene("b"), FakeScene("Hi")
    live[INTERNAL_RENDER_SCENE_PROP] = stale[INTERNAL_RENDER_SCENE_PROP] = True
    fake_bpy.data.scenes.extend([live, stale, user])
    assert render_scene.sweep(keep=live) == 1
    assert list(fake_bpy.data.scenes) == [live, user]
    fake_bpy.data.scenes.remove = MagicMock(side_effect=ReferenceError)
    render_scene.remove(live)                                   # freed by undo: no raise
    render_scene.remove(None)
    render_scene.remove(user)                                   # never a user scene
    assert fake_bpy.data.scenes.remove.call_count == 1


# --- the preview job renders the copy -------------------------------------------------

class Layers(list):
    def get(self, name):
        return next((layer for layer in self if layer.name == name), None)


class RecordingScenes:
    def __init__(self, isolate=True):
        self.isolate, self.created, self.removed = isolate, [], []

    def isolate_final(self, _source):
        return self.isolate

    def create(self, source, *, inspection):
        copy = _scene()
        copy.mixie_session_id = ""
        copy.render.engine = source.render.engine
        copy.render.use_single_layer = False
        copy.name = "~Mixar agent render"
        copy.view_layers = Layers([SimpleNamespace(name="Other"), SimpleNamespace(name="ViewLayer")])
        self.created.append((copy, inspection))
        return copy

    def remove(self, scene):
        self.removed.append(scene)

    def sweep(self, keep=None):
        return 0


@pytest.fixture
def isolated(preview, monkeypatch):
    scenes = RecordingScenes()
    monkeypatch.setattr(preview, "render_scene", scenes)
    preview.bpy.context.scene.render.engine = "BLENDER_EEVEE"
    preview.bpy.context.window = SimpleNamespace(view_layer=SimpleNamespace(name="ViewLayer"))
    return scenes


def test_final_switches_only_the_copy_to_cycles(preview, isolated):
    source = preview.bpy.context.scene
    assert preview.start(preview.bpy.context, KEY, engine="auto")["status"] == "running"
    copy, inspection = isolated.created[0]
    assert inspection is False
    assert copy.render.engine == "CYCLES" and source.render.engine == "BLENDER_EEVEE"
    assert source.render.resolution_x == 1200 and source.cycles.samples == 64   # untouched
    override = preview.bpy.context.temp_override.call_args.kwargs
    assert override["scene"] is source                      # context never names the copy
    call = preview.bpy.ops.render.render.call_args.kwargs
    assert call["scene"] == copy.name and "layer" not in call
    read = {}
    preview.bpy.data.images.get.return_value = SimpleNamespace(
        has_data=True, save_render=lambda path, scene: (read.setdefault("scene", scene), Path(path).write_bytes(b"x")))
    preview._finish(KEY, True)
    assert preview.poll(KEY)["status"] == "done" and read["scene"] is copy
    assert isolated.removed == [copy] and not preview.render_slot.busy()
    assert preview.poll(KEY)["scene_session"] == "sess-1"        # still reported for the user's scene


def test_a_single_layer_copy_names_its_own_matching_layer(preview, isolated):
    created = isolated.create

    def create(source, *, inspection):
        copy = created(source, inspection=inspection)
        copy.render.use_single_layer = True
        return copy

    isolated.create = create
    preview.start(preview.bpy.context, KEY, engine="auto")
    assert preview.bpy.ops.render.render.call_args.kwargs["layer"] == "ViewLayer"


def test_a_composited_final_still_renders_the_users_scene(preview, isolated):
    isolated.isolate = False
    source = preview.bpy.context.scene
    preview.start(preview.bpy.context, KEY, engine="auto")
    assert isolated.created == [] and source.render.engine == "CYCLES"
    assert "scene" not in preview.bpy.ops.render.render.call_args.kwargs
    preview.bpy.data.images.get.return_value = SimpleNamespace(
        has_data=True, save_render=lambda path, scene: Path(path).write_bytes(b"x"))
    preview._finish(KEY, True)
    assert source.render.engine == "BLENDER_EEVEE" and isolated.removed == [None]


def test_inspection_reads_the_source_and_renders_the_copy(preview, isolated, monkeypatch):
    import sys
    seen = {}

    class Inspection:
        def __init__(self, source, scene, params, set_value):
            seen.update(source=source, scene=scene)
            self.metadata = {}

        def prepare(self, context):
            raise ValueError("inspection_focus_not_found")

        def cleanup(self):
            seen["cleaned"] = True

    monkeypatch.setitem(sys.modules, "mixar.modules.space_mixie_chat.core.inspection_preview",
                        SimpleNamespace(Inspection=Inspection))
    result = preview.start(preview.bpy.context, KEY, inspection={"view": "hero"})
    copy, inspection = isolated.created[0]
    assert inspection is True and seen["source"] is preview.bpy.context.scene and seen["scene"] is copy
    assert result["error"] == "inspection_focus_not_found" and seen["cleaned"]
    assert isolated.removed == [copy] and not preview.render_slot.busy()
    preview.bpy.ops.render.render.assert_not_called()


def test_leftover_copies_are_swept_after_undo_and_load():
    src = (CHAT / "core/preview_render.py").read_text()
    for handler in ("load_post", "undo_post", "redo_post"):
        assert f"(bpy.app.handlers.{handler}, _sweep_render_scenes)" in src
    assert "render_scene.remove(job.get('render_scene'))" in src[src.index("def _restore("):]
    rig = (CHAT / "core/inspection_preview.py").read_text()
    assert "_instance_corners(context, source)" in rig and "for o in source.objects" in rig
    assert "camera = source.camera" in rig
    # The rig camera lives only in the copy, which no viewport evaluates: its world
    # matrix is synced by hand before framing and after placement (labels read it).
    assert rig.count("camera.matrix_world = camera.matrix_basis.copy()") == 2


# --- scene scans skip the copy --------------------------------------------------------

def _internal(name="~Mixar agent render"):
    scene = FakeScene(name)
    scene[INTERNAL_RENDER_SCENE_PROP] = True
    scene.mixie_session_id = ""
    return scene


def test_tabs_adoption_document_and_history_skip_the_copy(monkeypatch):
    from mixar.modules.space_mixie_chat.ui.operators import scene_tab_ops
    from mixar.modules.space_mixie_chat.core import scene_identity
    from mixar.modules.common.agent_execution import document
    from mixar.modules.operation_history.core import capture_service

    user = FakeScene("hi")
    user.mixie_session_id = "s-1"
    copy = _internal("_first by name")
    fake = SimpleNamespace(data=SimpleNamespace(scenes=[copy, user]), context=SimpleNamespace(scene=user))
    monkeypatch.setattr(scene_tab_ops, "bpy", fake)
    monkeypatch.setattr(capture_service, "bpy", fake)
    assert scene_tab_ops.real_scenes() == [user]
    assert document._first_scene(fake) is user
    assert capture_service._iter_scenes() == [user]
    assert scene_identity.adopt_scene(copy) is False


def test_lane_teardown_never_points_a_window_at_the_copy(monkeypatch):
    import sys
    from mixar.modules.space_mixie_chat.core import lane_scene_sweep
    lane = FakeScene("lane")
    lane.mixie_session_id = "agent-lane-x"
    copy, user = _internal(), FakeScene("Hi")
    user.mixie_session_id = "s-1"
    window = SimpleNamespace(scene=lane)
    fake = SimpleNamespace(data=SimpleNamespace(scenes=[copy, lane, user],
                                                window_managers=[SimpleNamespace(windows=[window])]))
    monkeypatch.setitem(sys.modules, "bpy", fake)
    monkeypatch.setattr(lane_scene_sweep, "_is_leaked_lane_scene", lambda s: s is lane)
    lane_scene_sweep._point_windows_away_from(lane)
    assert window.scene is user


def test_undo_settles_the_job_before_data_is_freed(preview, isolated):
    """Undo kills the job, runs undo_pre, then frees the copy: everything must be
    restored and removed in undo_pre (a later timer wrote into freed memory)."""
    preview.start(preview.bpy.context, KEY, engine="auto")
    copy, _ = isolated.created[0]
    preview._schedule(False)                     # render_cancel from WM_jobs_kill_all
    preview.bpy.app.is_job_running.return_value = False
    preview._before_undo(None)                   # undo_pre
    assert preview._job is None and isolated.removed == [copy]
    assert copy.render.engine == "BLENDER_EEVEE" and preview.poll(KEY)["status"] == "cancelled"
    assert preview._finish(KEY, False) is None   # the queued timer finds nothing to do
    src = (CHAT / "core/preview_render.py").read_text()
    for handler in ("undo_pre", "redo_pre"):
        assert f"(bpy.app.handlers.{handler}, _before_undo)" in src
