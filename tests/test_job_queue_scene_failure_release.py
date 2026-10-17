# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-scene failure release in the scene-flag listener (bug hunt P4a).

A scene whose generation FAILED while another scene's continues gets its
error written the moment its flag clears, and its ``on_finish`` runs then;
an old failure outside the batch never taints a later successful batch.
Shares the bpy mock and module handles with ``test_job_queue_display_metadata``.
"""

from types import SimpleNamespace

from test_job_queue_display_metadata import HELPERS, Job, JobState  # noqa: F401


class _ListQueue:
    """Minimal queue stand-in: the listener reads snapshot/has_active_work."""

    _ACTIVE = {
        JobState.PENDING,
        JobState.PAUSED_AUTH,
        JobState.RUNNING_SUBMIT,
        JobState.RUNNING_POLL,
        JobState.RUNNING_DOWNLOAD,
    }

    def __init__(self, jobs):
        self.jobs = list(jobs)

    def snapshot(self):
        return list(self.jobs)

    def has_active_work(self):
        return any(job.state in self._ACTIVE for job in self.jobs)


def _flag_scene(name):
    return SimpleNamespace(name=name, mixie_t_is_generating=False, mixie_t_error="")


def test_scene_released_early_records_its_failure_and_runs_on_finish(monkeypatch):
    """A scene whose job FAILED while another scene's continues gets its error
    written before its flag clears, and its on_finish runs then."""
    scene_a, scene_b = _flag_scene("Scene A"), _flag_scene("Scene B")
    monkeypatch.setattr(HELPERS.bpy.data, "scenes", [scene_a, scene_b], raising=False)
    finished = []

    job_a = Job(scene_name="Scene A", state=JobState.RUNNING_POLL)
    job_b = Job(scene_name="Scene B", state=JobState.RUNNING_POLL)
    queue = _ListQueue([job_a, job_b])
    listener = HELPERS.create_scene_flag_listener(
        "mixie_t_is_generating",
        on_finish=lambda scene: finished.append(
            (scene.name, scene.mixie_t_is_generating, scene.mixie_t_error)
        ),
    )

    listener(queue)
    assert scene_a.mixie_t_is_generating and scene_b.mixie_t_is_generating

    job_a.state = JobState.FAILED
    job_a.user_message = "Vendor rejected the image"
    listener(queue)
    assert scene_a.mixie_t_is_generating is False
    assert scene_a.mixie_t_error == "Vendor rejected the image"
    assert scene_b.mixie_t_is_generating is True
    assert scene_b.mixie_t_error == ""
    assert finished == [("Scene A", False, "Vendor rejected the image")]

    # (b) A new, successful batch in scene A: the flag rise clears the old
    # error, the stale failure is not in the new batch, and is not re-reported.
    job_a2 = Job(scene_name="Scene A", state=JobState.RUNNING_POLL)
    queue.jobs.append(job_a2)
    listener(queue)
    assert scene_a.mixie_t_is_generating is True
    assert scene_a.mixie_t_error == ""

    job_a2.state = JobState.SUCCESS
    listener(queue)
    assert scene_a.mixie_t_is_generating is False
    assert scene_a.mixie_t_error == ""
    assert finished[-1] == ("Scene A", False, "")

    # (c) The idle path still releases the last scene, reporting its failure.
    job_b.state = JobState.FAILED
    job_b.user_message = "Out of memory"
    listener(queue)
    assert scene_b.mixie_t_is_generating is False
    assert scene_b.mixie_t_error == "Out of memory"
    assert finished[-1] == ("Scene B", False, "Out of memory")
    assert [name for name, *_ in finished] == ["Scene A", "Scene A", "Scene B"]


def test_idle_release_ignores_a_failure_from_an_earlier_batch(monkeypatch):
    """An old unreported failure outside the batch never taints a later,
    successful batch in the same scene (scoped by job id, not finished_at)."""
    scene = _flag_scene("Scene")
    monkeypatch.setattr(HELPERS.bpy.data, "scenes", [scene], raising=False)

    stale = Job(scene_name="Scene", state=JobState.FAILED, user_message="old")
    fresh = Job(scene_name="Scene", state=JobState.RUNNING_POLL)
    assert fresh.finished_at == 0
    queue = _ListQueue([stale, fresh])
    listener = HELPERS.create_scene_flag_listener("mixie_t_is_generating")

    listener(queue)
    fresh.state = JobState.SUCCESS
    listener(queue)

    assert scene.mixie_t_is_generating is False
    assert scene.mixie_t_error == ""
