# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generation model and display metadata in the unified queue UI."""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy

bpy.types.Panel.bl_rna = SimpleNamespace(
    properties={
        "bl_space_type": SimpleNamespace(enum_items=[]),
    }
)

from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.services import job_queue_service as JQS
from mixar.bootstrap import generation_catalog_cache as GCC
from mixar.modules.common.job_queue.core import enqueue as ENQUEUE
from mixar.modules.common.job_queue.core import helpers as HELPERS
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.generic_jobs import AsyncGLBJob, SyncImageJob
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.common.job_queue.ui.lists import queue_uilist as QUI
from mixar.modules.common.job_queue.ui.properties import queue_properties as QP


class FakeQueueJob(Job):
    def submit(self, on_success, on_error):
        on_success(
            APIResponse(
                success=True,
                status_code=202,
                data={
                    "status": "success",
                    "data": {"job_id": "job-ws", "state": "pending"},
                },
            )
        )

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(response)


def _disable_queue_timers(monkeypatch):
    QM._queues.clear()
    QM._sync_watchdog_registered = False
    monkeypatch.setattr(QM.bpy.app.timers, "register", lambda *args, **kwargs: None)


def _install_catalog(monkeypatch):
    monkeypatch.setattr(
        GCC,
        "_catalog",
        {
            "capabilities": [
                {
                    "key": "image_gen",
                    "label": "Image Gen",
                    "sort_order": 0,
                    "services": [
                        {
                            "key": "image_gen",
                            "label": "Text to Image",
                            "models": [
                                {"slug": "flux-fast", "label": "Flux Fast"}
                            ],
                        }
                    ],
                },
                {
                    "key": "model_gen",
                    "label": "Model Gen",
                    "sort_order": 1,
                    "services": [
                        {
                            "key": "image_to_3d",
                            "label": "Image to 3D Pro",
                            "models": [],
                        }
                    ],
                },
                {
                    "key": "scene_gen",
                    "label": "Scene Gen",
                    "sort_order": 2,
                    "services": [
                        {
                            "key": "scene_gen",
                            "label": "Segments to 3D",
                            "models": [],
                        }
                    ],
                },
            ],
        },
    )


def test_job_queue_response_preserves_model_when_present():
    response = JQS.JobQueueService._normalize_response(
        APIResponse(
            success=True,
            status_code=200,
            data={
                "status": "success",
                "data": {
                    "job_id": "job-1",
                    "state": "running",
                    "service": "image_gen",
                    "model": "flux-fast",
                },
            },
        )
    )

    assert response.data["data"]["service"] == "image_gen"
    assert response.data["data"]["model"] == "flux-fast"

    legacy_response = JQS.JobQueueService._normalize_response(
        APIResponse(
            success=True,
            status_code=200,
            data={"status": "success", "data": {"job_id": "legacy"}},
        )
    )
    assert "model" not in legacy_response.data["data"]


def test_submit_ack_applies_backend_generation_metadata(monkeypatch):
    _disable_queue_timers(monkeypatch)

    class MetadataSubmitJob(FakeQueueJob):
        def submit(self, on_success, on_error):
            on_success(
                APIResponse(
                    success=True,
                    status_code=202,
                    data={
                        "status": "success",
                        "data": {
                            "job_id": "job-ws",
                            "state": "pending",
                            "service": "image_gen",
                            "model": "flux-fast",
                        },
                    },
                )
            )

    job = MetadataSubmitJob(model="local-fallback")
    assert QM.get_queue("test_submit_metadata").submit(job) is True

    assert job.service == "image_gen"
    assert job.model == "flux-fast"


def test_enqueue_generation_carries_origin_capability(monkeypatch):
    class AcceptingQueue:
        @staticmethod
        def submit(_job):
            return True

    monkeypatch.setattr(QM, "get_queue", lambda _feature: AcceptingQueue())

    job = ENQUEUE.enqueue_generation(
        kind="glb",
        feature_key="scene_gen_hp",
        job_type="image_to_3d",
        model="hunyuan_pro_v3",
        payload={},
        label="Scene object",
        origin_capability_key="scene_gen",
    )

    assert job is not None
    assert job.service == "image_to_3d"
    assert job.origin_capability_key == "scene_gen"


def test_compact_job_update_merges_generation_metadata(monkeypatch):
    _disable_queue_timers(monkeypatch)
    queue = QM.get_queue("test_ws_metadata")
    job = FakeQueueJob(model="local-model")
    assert queue.submit(job) is True

    assert QM.handle_backend_job_update(
        {
            "job_id": "job-ws",
            "state": "running",
            "service": "image_gen",
            "model": "flux-fast",
        }
    )
    assert job.service == "image_gen"
    assert job.model == "flux-fast"

    assert QM.handle_backend_job_update({"job_id": "job-ws", "state": "running"})
    assert job.model == "flux-fast"

    assert QM.handle_backend_job_update(
        {
            "job_id": "job-ws",
            "state": "running",
            "service": "",
            "model": "",
        }
    )
    assert job.service == "image_gen"
    assert job.model == "flux-fast"


def test_job_sync_applies_full_snapshot_generation_metadata(monkeypatch):
    _disable_queue_timers(monkeypatch)
    queue = QM.get_queue("test_ws_full_metadata")
    job = FakeQueueJob(model="local-model")
    assert queue.submit(job) is True

    handled = QM.handle_backend_job_sync(
        {
            "jobs": [
                {
                    "job_id": "job-ws",
                    "state": "running",
                    "service": "image_gen",
                    "model": "server-model",
                }
            ]
        }
    )

    assert handled == 1
    assert job.service == "image_gen"
    assert job.model == "server-model"


def test_generation_labels_come_from_backend_catalog(monkeypatch):
    _install_catalog(monkeypatch)

    assert QUI._feature_label("", "image_gen", "imagegen") == "Image Gen"
    assert QUI._generation_model_label("image_gen", "flux-fast") == "Flux Fast"


def test_generation_labels_follow_catalog_changes_without_code_maps(monkeypatch):
    _install_catalog(monkeypatch)
    GCC._catalog["capabilities"][0]["label"] = "Generate Images"
    GCC._catalog["capabilities"][0]["services"][0]["models"][0]["label"] = (
        "Flux Turbo"
    )

    assert (
        QUI._feature_label("", "image_gen", "imagegen")
        == "Generate Images"
    )
    assert QUI._generation_model_label("image_gen", "flux-fast") == "Flux Turbo"


def test_origin_capability_uses_backend_label_for_composite_workflow(monkeypatch):
    _install_catalog(monkeypatch)

    assert (
        QUI._feature_label("scene_gen", "image_to_3d", "scene_gen_hp")
        == "Scene Gen"
    )

    GCC._catalog["capabilities"][2]["label"] = "Build Scene"
    assert (
        QUI._feature_label("scene_gen", "image_to_3d", "scene_gen_hp")
        == "Build Scene"
    )


def test_generation_labels_use_exact_identifiers_without_catalog(monkeypatch):
    monkeypatch.setattr(GCC, "_catalog", None)

    assert QUI._feature_label("", "image_gen", "imagegen") == "image_gen"
    assert (
        QUI._feature_label("scene_gen", "image_to_3d", "scene_gen_hp")
        == "scene_gen"
    )
    assert QUI._generation_model_label("image_gen", "flux-fast") == "flux-fast"
    assert QUI._generation_model_label("", "") == ""


def test_queue_title_preserves_colons_and_prefers_structured_display_label():
    assert QUI._display_title("", "Character: Hero") == "Character: Hero"
    assert (
        QUI._display_title("a hero", "ImageGen: a hero [abcd]")
        == "A hero"
    )


def test_queue_mirror_projects_generation_display_metadata(monkeypatch):
    class MirrorItems(list):
        def add(self):
            item = SimpleNamespace()
            self.append(item)
            return item

    QM._queues.clear()
    queue = QM.get_queue("test_mirror_metadata")
    job = FakeQueueJob(
        service="image_gen",
        model="flux-fast",
        display_label="A clean queue title",
        origin_capability_key="scene_gen",
    )
    queue._jobs.append(job)
    mirror = SimpleNamespace(items=MirrorItems(), active_index=0)
    monkeypatch.setattr(
        QP.bpy.context,
        "window_manager",
        SimpleNamespace(mixie_queue=mirror),
        raising=False,
    )

    QP._sync_mirror(queue)

    assert mirror.items[0].display_label == "A clean queue title"
    assert mirror.items[0].service == "image_gen"
    assert mirror.items[0].origin_capability_key == "scene_gen"
    assert mirror.items[0].model == "flux-fast"


def test_queue_status_text_remains_accessible_when_icons_fall_back():
    assert QUI._status_word(JobState.SUCCESS.value, "Done") == "Done"
    assert QUI._status_word(JobState.SUCCESS.value, "Done: Cube") == "Done"
    assert QUI._status_word(JobState.RUNNING_POLL.value, "Processing") == "Processing"
    assert QUI._status_word(JobState.RUNNING_POLL.value, "Queued (#2)") == "Queued (#2)"
    assert QUI._status_word(JobState.RUNNING_DOWNLOAD.value, "Downloading…") == "Downloading…"
    assert QUI._status_word(JobState.PAUSED_AUTH.value, "") == "Waiting for sign-in"
    assert QUI._status_word(JobState.FAILED.value, "") == "Failed"
    assert QUI._status_word(JobState.CANCELLED.value, "") == "Cancelled"


def test_cancelled_generic_jobs_release_large_payloads(monkeypatch):
    monkeypatch.setattr(QM, "redraw_3d_views", lambda: None)
    queue = QM.FeatureQueue("resource-release-cancel")
    glb = AsyncGLBJob(payload={"file_bytes_b64": "x" * 4096})
    image = SyncImageJob(
        payload={"reference_image": "y" * 4096},
        _image_urls=["https://example.invalid/large-result.png"],
    )
    queue._jobs.extend([glb, image])

    queue.cancel_all()

    assert glb.state == JobState.CANCELLED
    assert image.state == JobState.CANCELLED
    assert glb.payload == {}
    assert image.payload == {}
    assert image._image_urls == []


def test_failed_generic_job_release_is_idempotent(monkeypatch):
    monkeypatch.setattr(QM, "redraw_3d_views", lambda: None)
    queue = QM.FeatureQueue("resource-release-failure")
    job = AsyncGLBJob(
        payload={"file_bytes_b64": "x" * 4096},
        state=JobState.FAILED,
    )
    queue._jobs.append(job)

    queue._notify()
    queue._notify()

    assert job.payload == {}


def test_scene_flag_releases_finished_scene_while_other_scene_runs(monkeypatch):
    scene_a = SimpleNamespace(name="Scene A", is_generating=False)
    scene_b = SimpleNamespace(name="Scene B", is_generating=False)
    monkeypatch.setattr(HELPERS.bpy.data, "scenes", [scene_a, scene_b], raising=False)
    monkeypatch.setattr(HELPERS.bpy.context, "scene", scene_a, raising=False)

    job_a = Job(scene_name="Scene A", state=JobState.RUNNING_POLL)
    job_b = Job(scene_name="Scene B", state=JobState.RUNNING_DOWNLOAD)

    class QueueSnapshot:
        jobs = [job_a, job_b]

        def snapshot(self):
            return list(self.jobs)

        def has_active_work(self):
            return any(
                job.state in {
                    JobState.PENDING,
                    JobState.PAUSED_AUTH,
                    JobState.RUNNING_SUBMIT,
                    JobState.RUNNING_POLL,
                    JobState.RUNNING_DOWNLOAD,
                }
                for job in self.jobs
            )

    queue = QueueSnapshot()
    listener = HELPERS.create_scene_flag_listener("is_generating")

    listener(queue)
    assert scene_a.is_generating is True
    assert scene_b.is_generating is True

    job_a.state = JobState.SUCCESS
    listener(queue)
    assert scene_a.is_generating is False
    assert scene_b.is_generating is True

    job_b.state = JobState.SUCCESS
    listener(queue)
    assert scene_a.is_generating is False
    assert scene_b.is_generating is False


def test_legacy_fallback_flag_survives_pyrna_wrapper_identity(monkeypatch):
    """PyRNA wrappers are not identity-stable: ``bpy.context.scene`` is a
    different Python object than the matching ``bpy.data.scenes`` item, so the
    legacy no-scene-name fallback must match scenes by name, not ``id()``."""
    scene_data = SimpleNamespace(name="Scene", is_generating=False)
    scene_context = SimpleNamespace(name="Scene", is_generating=False)
    other = SimpleNamespace(name="Other", is_generating=True)
    monkeypatch.setattr(
        HELPERS.bpy.data, "scenes", [scene_data, other], raising=False
    )
    monkeypatch.setattr(HELPERS.bpy.context, "scene", scene_context, raising=False)

    legacy_job = Job(scene_name="", state=JobState.RUNNING_POLL)

    class QueueSnapshot:
        def snapshot(self):
            return [legacy_job]

        def has_active_work(self):
            return True

    listener = HELPERS.create_scene_flag_listener("is_generating")
    listener(QueueSnapshot())

    assert scene_data.is_generating is True
    assert other.is_generating is False
