# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Queue job for segmented SceneGen multi-object results."""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import bpy
import requests

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN
from ..constants import SCENE_GEN_JOB_TYPE, SCENE_GEN_MODEL
from mixar.modules.common.job_queue.core.helpers import (
    create_scene_flag_listener,
    get_queue_with_listener,
)
from mixar.modules.common.job_queue.core.job import (
    FAILED_BACKEND_STATUSES,
    Job,
    JobState,
)

logger = get_logger(__name__)


_scene_gen_listener = None


@dataclass
class SceneGenQueueJob(Job):
    """SceneGen job with a custom multi-object GLB download/import phase."""

    payload: dict = field(default_factory=dict)
    fail_message: str = "Scene generation failed"
    _on_object_ready: Optional[Callable] = field(default=None, repr=False)
    _on_download_failed: Optional[Callable] = field(default=None, repr=False)
    _objects: list = field(default_factory=list, repr=False)
    _processing_started: bool = False

    def submit(self, on_success, on_error) -> None:
        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )

        get_job_queue_service().enqueue(
            job_type=SCENE_GEN_JOB_TYPE,
            model=SCENE_GEN_MODEL,
            payload=self.payload,
            idempotency_key=self.submit_idempotency_key,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)
        self.payload = {}

    def parse_poll_response(self, response):
        inner = self._unwrap_response(response)
        status = inner.get("status", "") or ""
        self.backend_status = status
        self.queue_position = inner.get("queue_position") or 0

        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            if not self._processing_started:
                self._processing_started = True
                self.poll_start_time = time.time()
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            self._objects = list(result.get("objects") or []) if isinstance(result, dict) else []
            return ("DONE", [])
        if status in FAILED_BACKEND_STATUSES:
            self.error = inner.get("error", "") or self.fail_message
            self.user_message = inner.get("user_message", "") or self.fail_message
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        objects = [
            obj for obj in self._objects
            if isinstance(obj, dict)
            and obj.get("status", "completed") == "completed"
            and (obj.get("glb_url") or obj.get("download_url"))
        ]
        objects.sort(key=lambda obj: int(obj.get("object_id") or 0))
        if not objects:
            on_error("No completed SceneGen objects were returned")
            return True

        def _bg_download_and_import():
            imported_names: list[str] = []
            failures: list[str] = []

            for obj in objects:
                object_id = int(obj.get("object_id") or 0)
                url = obj.get("glb_url") or obj.get("download_url")
                pose = obj.get("pose")
                try:
                    started = time.time()
                    response = requests.get(url, timeout=120)
                    response.raise_for_status()
                    glb_bytes = response.content
                    logger.debug(
                        "[SceneGen] object download completed job=%s object=%s bytes=%d duration=%.3fs",
                        self.id,
                        object_id,
                        len(glb_bytes),
                        time.time() - started,
                    )
                except Exception as exc:
                    msg = f"Object {object_id} download failed: {exc}"
                    failures.append(msg)
                    self._notify_download_failed(object_id, msg)
                    continue

                done = threading.Event()

                # Loop variables are bound as defaults: with plain closure
                # capture, a timed-out done.wait() lets the loop rebind them,
                # and a late-firing callback would import the NEXT object's
                # data under this object's id (and signal the wrong Event).
                def _import_cb(glb_bytes=glb_bytes, pose=pose,
                               object_id=object_id, done=done):
                    try:
                        callback = self._on_object_ready
                        result = callback(glb_bytes, pose, object_id) if callback else None
                        if result:
                            imported_names.extend(
                                getattr(obj, "name", str(obj)) for obj in result
                            )
                        else:
                            imported_names.append(f"SceneGen_Object_{object_id}")
                    except Exception as exc:
                        msg = f"Object {object_id} import failed: {exc}"
                        failures.append(msg)
                        logger.error("[SceneGen] %s", msg)
                    finally:
                        done.set()
                    return None

                bpy.app.timers.register(_import_cb, first_interval=0.0)
                if not done.wait(timeout=300):
                    failures.append(f"Object {object_id} import timed out")

            def _finish_cb():
                if imported_names:
                    on_done(", ".join(imported_names))
                else:
                    on_error("; ".join(failures) or "SceneGen import failed")
                return None

            bpy.app.timers.register(_finish_cb, first_interval=0.0)

        threading.Thread(target=_bg_download_and_import, daemon=True).start()
        return True

    def _notify_download_failed(self, object_id: int, message: str) -> None:
        if self._on_download_failed is None:
            return
        try:
            self._on_download_failed(object_id, message)
        except Exception as exc:
            logger.error("[SceneGen] download failure callback failed: %s", exc)


def _get_scene_gen_listener():
    global _scene_gen_listener
    if _scene_gen_listener is not None:
        return _scene_gen_listener

    def _on_start(scene):
        try:
            from mixar.modules.moodboard.core.generate_progress import start_progress

            start_progress("segment_to_3d")
        except Exception:
            pass

    def _on_finish(scene):
        try:
            from mixar.modules.moodboard.core.generate_progress import complete_progress

            complete_progress("segment_to_3d")
        except Exception:
            pass

    _scene_gen_listener = create_scene_flag_listener(
        "mixie_segment_to_3d_is_generating",
        on_start=_on_start,
        on_finish=_on_finish,
        batch_popup_title="Scene generation complete",
    )
    return _scene_gen_listener


def enqueue_scene_gen_job(
    *,
    label: str,
    payload: dict,
    on_object_ready: Optional[Callable] = None,
    on_download_failed: Optional[Callable] = None,
) -> Optional[SceneGenQueueJob]:
    job = SceneGenQueueJob(
        feature_key=FEATURE_SCENE_GEN,
        label=label,
        service=SCENE_GEN_JOB_TYPE,
        payload=payload,
        _on_object_ready=on_object_ready,
        _on_download_failed=on_download_failed,
    )
    queue = get_queue_with_listener(FEATURE_SCENE_GEN, _get_scene_gen_listener())
    if not queue.submit(job):
        logger.warning("[SceneGen] duplicate queue job rejected: %s", label)
        return None
    return job


def find_scene_gen_job(label: str):
    from mixar.modules.common.job_queue.core.queue_manager import get_queue

    queue = get_queue(FEATURE_SCENE_GEN)
    for job in queue.snapshot():
        if job.label == label and job.state not in {
            JobState.SUCCESS,
            JobState.FAILED,
            JobState.CANCELLED,
        }:
            return queue, job
    return queue, None
