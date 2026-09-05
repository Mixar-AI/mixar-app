# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Post-add callback behavior for generic image queue jobs."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock


install_bpy_mock()

from mixar.modules.common.job_queue.core import enqueue as ENQUEUE
from mixar.modules.common.job_queue.core import generic_jobs as GENERIC_JOBS
from mixar.modules.common.job_queue.core import queue_manager as QUEUE_MANAGER
from mixar.modules.common.job_queue.core.generic_jobs import SyncImageJob
from mixar.modules.common.job_queue.core.job import JobState


def _run_image_result(monkeypatch, job, events):
    """Simulate the helper's main-thread post-moodboard callback."""

    def _download_images_to_moodboard(**kwargs):
        events.append(("moodboard_added", "Armor, Armor.001"))
        try:
            kwargs["on_added"]("Armor, Armor.001")
        except Exception as exc:
            kwargs["on_error"](f"Could not finalize generated images: {exc}")
            return
        kwargs["on_done"]("Armor, Armor.001")

    monkeypatch.setattr(
        GENERIC_JOBS,
        "download_images_to_moodboard",
        _download_images_to_moodboard,
    )

    def _complete(names):
        events.append(("complete", names, job.state))
        job.state = JobState.SUCCESS

    def _fail(error):
        events.append(("error", error, job.state))
        job.state = JobState.FAILED

    assert job.handle_result([], _complete, _fail) is True


def test_image_hook_runs_after_add_and_before_normal_completion(monkeypatch):
    events = []
    job = SyncImageJob(
        state=JobState.RUNNING_DOWNLOAD,
        scene_name="Origin Scene",
        _image_urls=["https://example.invalid/image.png"],
        _on_images_added_hook=lambda actual_job, names: events.append(
            ("hook", actual_job, names, actual_job.state)
        ),
    )

    _run_image_result(monkeypatch, job, events)

    assert events[0] == ("moodboard_added", "Armor, Armor.001")
    assert events[1] == (
        "hook",
        job,
        "Armor, Armor.001",
        JobState.RUNNING_DOWNLOAD,
    )
    assert events[2] == (
        "complete",
        "Armor, Armor.001",
        JobState.RUNNING_DOWNLOAD,
    )
    assert job.state == JobState.SUCCESS


def test_image_result_targets_origin_scene_and_has_cancel_guard(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        GENERIC_JOBS,
        "download_images_to_moodboard",
        lambda **kwargs: captured.update(kwargs),
    )
    job = SyncImageJob(
        state=JobState.RUNNING_DOWNLOAD,
        scene_name="Character Workshop",
        _image_urls=["https://example.invalid/image.png"],
    )

    assert job.handle_result([], lambda _names: None, lambda _error: None)
    assert captured["scene_name"] == "Character Workshop"
    assert captured["should_apply"]() is True

    job.state = JobState.CANCELLED
    assert captured["should_apply"]() is False


def test_post_add_metadata_precedes_undo_snapshot_and_completion():
    source = Path(GENERIC_JOBS.__file__).with_name(
        "image_results.py"
    ).read_text()
    apply_body = source[source.index("def _apply():"):]

    assert apply_body.index("on_added(names)") < apply_body.index(
        "bpy.ops.ed.undo_push"
    ) < apply_body.index("on_done(names)")


def test_required_image_hook_exception_fails_before_completion(monkeypatch):
    events = []

    def _raise(_job, _names):
        events.append(("hook", "raised"))
        raise RuntimeError("post-add failed")

    job = SyncImageJob(
        state=JobState.RUNNING_DOWNLOAD,
        _image_urls=["https://example.invalid/image.png"],
        _on_images_added_hook=_raise,
    )

    _run_image_result(monkeypatch, job, events)

    assert events[-1] == (
        "error",
        "Could not finalize generated images: post-add failed",
        JobState.RUNNING_DOWNLOAD,
    )
    assert not any(event[0] == "complete" for event in events)
    assert job.state == JobState.FAILED


def test_enqueue_generation_wires_and_releases_image_hook(monkeypatch):
    class AcceptingQueue:
        @staticmethod
        def submit(_job):
            return True

    callback = lambda _job, _names: None
    monkeypatch.setattr(
        QUEUE_MANAGER,
        "get_queue",
        lambda _feature_key: AcceptingQueue(),
    )

    job = ENQUEUE.enqueue_generation(
        kind="image",
        feature_key="image_gen",
        job_type="image_gen",
        model="catalog-model",
        payload={"prompt": "armor"},
        label="Armor detail",
        on_images_added=callback,
    )

    assert isinstance(job, SyncImageJob)
    assert job._on_images_added_hook is callback

    job.release_resources()
    job.release_resources()

    assert job._on_images_added_hook is None
    assert job.payload == {}
