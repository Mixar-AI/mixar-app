# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Feature queues with their own listeners deliver to the job's tab.

Mesh segmentation, scene reconstruction and Lookdev360 each wrote progress flags, status text and results through
``bpy.context.scene`` from listeners and poll/result callbacks. With parallel
scene tabs that is whichever tab the window shows, not the tab that submitted
the job — the same defect as Detect Views in prod 4.2.3 (session 0eb90899),
where a multi-view group landed on another tab's moodboard and the agent's tab
stayed "Detecting views..." forever.
"""

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

from mixar.modules.common.job_queue.core import helpers as HELPERS
from mixar.modules.common.job_queue.core import queue_download
from mixar.modules.common.job_queue.core.job import Job, JobState


class _Scenes:
    def __init__(self, *scenes):
        self._by_name = {s.name: s for s in scenes}

    def get(self, name):
        return self._by_name.get(name)

    def __iter__(self):
        return iter(list(self._by_name.values()))

    def drop(self, name):
        self._by_name.pop(name)


def _sidebar():
    tab = SimpleNamespace(stage_name="", stage_detail="", error_text="")
    return SimpleNamespace(tab_scene_recon=tab)


def _tab(name):
    return SimpleNamespace(
        name=name, mixie_session_id="", mixie_moodboard_sidebar=_sidebar(),
    )


@pytest.fixture
def tabs(monkeypatch):
    """Job tab ``A`` is in the background; the window shows ``B``."""
    a, b = _tab("A"), _tab("B")
    scenes = _Scenes(a, b)
    bpy = queue_download.bpy
    window = SimpleNamespace(scene=b, screen=SimpleNamespace(areas=[]))
    monkeypatch.setattr(bpy.data, "scenes", scenes, raising=False)
    monkeypatch.setattr(bpy.context, "scene", b, raising=False)
    monkeypatch.setattr(bpy.context, "window", window, raising=False)
    monkeypatch.setattr(
        bpy.context, "window_manager", SimpleNamespace(windows=[window]), raising=False)
    return SimpleNamespace(a=a, b=b, scenes=scenes, window=window)


class _Queue:
    def __init__(self, *jobs):
        self.jobs = list(jobs)

    def snapshot(self):
        return list(self.jobs)

    def has_active_work(self):
        return any(j.state == JobState.RUNNING_POLL for j in self.jobs)


_LISTENERS = [
    ("mixar.modules.mesh_segment.core.mesh_segment_queue",
     "mixie_mesh_segment_is_processing"),
    ("mixar.modules.moodboard.core.scene_recon_queue",
     "mixie_scene_recon_is_generating"),
    ("mixar.modules.moodboard.core.lookdev360_queue",
     "mixie_lookdev360_is_generating"),
]


@pytest.mark.parametrize("module_name, flag", _LISTENERS)
def test_queue_flag_follows_the_job_tab_not_the_shown_tab(tabs, module_name, flag):
    import importlib

    module = importlib.import_module(module_name)
    job = Job(scene_name="A", state=JobState.RUNNING_POLL)
    queue = _Queue(job)

    module._on_queue_changed(queue)
    assert getattr(tabs.a, flag) is True
    assert getattr(tabs.b, flag, False) is False

    job.state = JobState.SUCCESS
    module._on_queue_changed(queue)
    assert getattr(tabs.a, flag) is False


def test_failed_job_callback_runs_once_in_its_own_tab(tabs):
    seen = []
    job = Job(scene_name="A", state=JobState.FAILED, error="boom")
    job._on_error_callback = lambda msg: seen.append((msg, tabs.window.scene.name))
    queue = _Queue(job)

    HELPERS.fire_failed_job_callbacks(queue, "default")
    HELPERS.fire_failed_job_callbacks(queue, "default")

    assert seen == [("boom", "A")]
    # The pin is released: the window shows the user's tab again.
    assert tabs.window.scene is tabs.b


def test_failed_job_of_a_closed_tab_reports_nowhere(tabs):
    seen = []
    job = Job(scene_name="A", state=JobState.FAILED, error="boom")
    job._on_error_callback = seen.append
    tabs.scenes.drop("A")

    HELPERS.fire_failed_job_callbacks(_Queue(job), "default")

    assert seen == []
    assert tabs.window.scene is tabs.b


def test_scene_recon_stage_text_goes_to_the_job_tab(tabs):
    from mixar.modules.moodboard.core import scene_recon_queue

    scene_recon_queue._update_tab_status(Job(scene_name="A"), stage_detail="Parsing scene...")

    assert tabs.a.mixie_moodboard_sidebar.tab_scene_recon.stage_detail == "Parsing scene..."
    assert tabs.b.mixie_moodboard_sidebar.tab_scene_recon.stage_detail == ""


def test_mesh_segment_progress_goes_to_the_job_tab(tabs):
    from mixar.modules.mesh_segment.core.mesh_segment_queue import MeshSegmentJob

    job = MeshSegmentJob(scene_name="A")
    job.parse_poll_response(SimpleNamespace(data={"data": {"status": "PENDING"}}))

    assert tabs.a.mixie_mesh_segment_status == "pending"
    assert not hasattr(tabs.b, "mixie_mesh_segment_status")


@pytest.fixture
def settle():
    """Drive the named module listeners idle at teardown: they keep state."""
    import importlib

    modules = []
    yield lambda name: modules.append(importlib.import_module(name)) or modules[-1]
    for module in modules:
        module._on_queue_changed(_Queue())


def test_hand_raised_recon_flag_survives_another_tabs_recon(tabs, settle):
    """Scene recon from a prompt raises the flag by hand while the image
    generates, before any recon job exists. A recon in another tab finishing
    must not drop it, or the chat poll announces success mid-run."""
    module = settle("mixar.modules.moodboard.core.scene_recon_queue")
    tabs.a.mixie_scene_recon_is_generating = True
    job_b = Job(scene_name="B", state=JobState.RUNNING_POLL)
    queue = _Queue(job_b)

    module._on_queue_changed(queue)
    assert tabs.a.mixie_scene_recon_is_generating is True
    assert tabs.b.mixie_scene_recon_is_generating is True

    job_b.state = JobState.SUCCESS
    module._on_queue_changed(queue)
    assert tabs.a.mixie_scene_recon_is_generating is True
    assert tabs.b.mixie_scene_recon_is_generating is False

    # A's chained recon job takes the flag over and releases it when done.
    job_a = Job(scene_name="A", state=JobState.RUNNING_POLL)
    queue.jobs.append(job_a)
    module._on_queue_changed(queue)
    job_a.state = JobState.SUCCESS
    module._on_queue_changed(queue)
    assert tabs.a.mixie_scene_recon_is_generating is False


@pytest.mark.parametrize("module_name, error_attr", [
    ("mixar.modules.moodboard.core.lookdev360_queue", "mixie_lookdev360_error"),
    ("mixar.modules.mesh_segment.core.mesh_segment_queue", "mixie_mesh_segment_error"),
])
def test_old_error_cleared_when_a_tab_starts_beside_a_running_one(
    tabs, settle, module_name, error_attr,
):
    module = settle(module_name)
    setattr(tabs.a, error_attr, "old failure")
    job_b = Job(scene_name="B", state=JobState.RUNNING_POLL)
    queue = _Queue(job_b)
    module._on_queue_changed(queue)
    assert getattr(tabs.a, error_attr) == "old failure"

    queue.jobs.append(Job(scene_name="A", state=JobState.RUNNING_POLL))
    module._on_queue_changed(queue)

    assert getattr(tabs.a, error_attr) == ""


def test_failure_keeps_the_jobs_own_error_text(tabs, settle):
    module = settle("mixar.modules.moodboard.core.lookdev360_queue")
    job = Job(scene_name="A", state=JobState.RUNNING_POLL)
    queue = _Queue(job)
    module._on_queue_changed(queue)

    tabs.a.mixie_lookdev360_error = "Failed to apply textures: no UVs"
    job.state = JobState.FAILED
    module._on_queue_changed(queue)

    assert tabs.a.mixie_lookdev360_is_generating is False
    assert tabs.a.mixie_lookdev360_error == "Failed to apply textures: no UVs"


def test_failure_replaces_an_error_from_before_the_run(tabs, settle):
    module = settle("mixar.modules.moodboard.core.scene_recon_queue")
    tabs.a.mixie_scene_recon_error = "last week's failure"
    job = Job(scene_name="A", state=JobState.RUNNING_POLL)
    queue = _Queue(job)
    module._on_queue_changed(queue)

    job.state = JobState.FAILED
    job.user_message = "Scene reconstruction failed"
    module._on_queue_changed(queue)

    assert tabs.a.mixie_scene_recon_error == "Scene reconstruction failed"


def test_failure_in_one_tab_is_reported_while_another_runs(tabs, settle):
    module = settle("mixar.modules.moodboard.core.lookdev360_queue")
    tabs.a.mixie_lookdev360_error = ""
    job_a = Job(scene_name="A", state=JobState.RUNNING_POLL)
    queue = _Queue(job_a, Job(scene_name="B", state=JobState.RUNNING_POLL))
    module._on_queue_changed(queue)

    job_a.state = JobState.FAILED
    job_a.user_message = "Texture generation failed"
    module._on_queue_changed(queue)

    assert tabs.a.mixie_lookdev360_is_generating is False
    assert tabs.a.mixie_lookdev360_error == "Texture generation failed"
    assert tabs.b.mixie_lookdev360_is_generating is True


class _CountingWindow:
    """A window that counts how often its shown scene is switched."""

    def __init__(self, scene):
        self._scene = scene
        self.switches = 0
        self.screen = SimpleNamespace(areas=[])

    @property
    def scene(self):
        return self._scene

    @scene.setter
    def scene(self, value):
        self.switches += 1
        self._scene = value


@pytest.fixture
def counting_window(tabs, monkeypatch):
    bpy = queue_download.bpy
    window = _CountingWindow(tabs.b)
    monkeypatch.setattr(bpy.context, "window", window, raising=False)
    monkeypatch.setattr(
        bpy.context, "window_manager", SimpleNamespace(windows=[window]), raising=False)
    return window


def test_scene_recon_imports_pin_the_job_tab_once_per_pass(tabs, counting_window, monkeypatch):
    from mixar.modules.moodboard.core import scene_recon_download_helpers as helpers
    from mixar.modules.moodboard.core.scene_recon_queue import SceneReconJob

    monkeypatch.setattr(helpers, "snapshot_object_uids", lambda: set())
    monkeypatch.setattr(helpers, "new_object_names", lambda before: [])
    seen = []
    job = SceneReconJob(scene_name="A")
    job._on_object_ready = lambda glb, pose, obj_id, label: seen.append(
        (obj_id, counting_window.scene.name))
    job._downloaded_glbs = {i: (b"glb", {}, f"obj{i}") for i in range(3)}

    helpers.try_import_next(job)

    assert seen == [(0, "A"), (1, "A"), (2, "A")]
    assert counting_window.switches == 2  # to A and back, once
    assert counting_window.scene is tabs.b


def test_scene_recon_imports_of_a_closed_tab_are_consumed(tabs, counting_window):
    from mixar.modules.moodboard.core import scene_recon_download_helpers as helpers
    from mixar.modules.moodboard.core.scene_recon_queue import SceneReconJob

    seen = []
    job = SceneReconJob(scene_name="A")
    job._on_object_ready = lambda *args: seen.append(args)
    job._downloaded_glbs = {i: (b"glb", {}, f"obj{i}") for i in range(2)}
    tabs.scenes.drop("A")

    helpers.try_import_next(job)

    assert seen == []
    assert job._downloaded_glbs == {} and job._next_import_id == 2
    assert counting_window.switches == 0


def test_scene_recon_bbox_placeholders_pin_the_job_tab_once(tabs, counting_window):
    from mixar.modules.moodboard.core.scene_recon_queue import SceneReconJob

    seen = []
    job = SceneReconJob(scene_name="A")
    job._on_bbox_ready = lambda *args: seen.append((args[4], counting_window.scene.name))
    objects = [{"center": [0, 0, 0], "dimensions": [1, 1, 1], "index": i} for i in range(3)]

    job._emit_bbox_placeholders(objects)

    assert seen == [(0, "A"), (1, "A"), (2, "A")]
    assert counting_window.switches == 2
    assert counting_window.scene is tabs.b
