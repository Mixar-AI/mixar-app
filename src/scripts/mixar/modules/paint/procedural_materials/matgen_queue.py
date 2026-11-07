# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MatGen job queue adapter for AI procedural materials.

Connects the procedural material AI Generate popup to the shared job
queue. The backend returns script text inline when the queued mat_gen job
completes; this adapter persists it to user data, refreshes the local material
registry, optionally applies the generated material to objects as a procedural
layer, and updates the popup's session-only "Just Generated" list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.analytics.draft_events import note_generation_submitted
from mixar.modules.common.api.services.job_queue_service import (
    get_job_queue_service,
)
from mixar.modules.common.i18n import n_, rpt_
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.core.job import FAILED_BACKEND_STATUSES
from mixar.modules.common.job_queue.constants import FEATURE_MATGEN
from mixar.modules.common.job_queue.core.error_helpers import sanitize_message
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued

from . import material_registry
from .matgen_persistence import save_generated_material
from .script_preprocessor import _fix_rgb_to_rgba

logger = get_logger(__name__)

_SERVICE_KEY = "mat_gen"
_SUPPORTED_PIPELINES = {"fast", "detailed"}


def _normalize_pipeline(pipeline: str) -> str:
    value = (pipeline or "fast").lower()
    return value if value in _SUPPORTED_PIPELINES else "fast"


def _unwrap_response(response) -> dict:
    data = getattr(response, "data", None) or {}
    if not isinstance(data, dict):
        return {}
    inner = data.get("data", data)
    return inner if isinstance(inner, dict) else {}


def _extract_result(payload: dict) -> dict:
    result = payload.get("result") or {}
    if isinstance(result, dict):
        nested = result.get("data")
        if isinstance(nested, dict):
            return nested
        return result
    return {}


def _redraw_ui() -> None:
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _set_status(status: str) -> None:
    try:
        wm = bpy.context.window_manager
        if hasattr(wm, "mixar_matgen_status"):
            wm.mixar_matgen_status = status
    except Exception:
        logger.debug("Could not set MatGen status", exc_info=True)
    _redraw_ui()


def _add_recent(material_id: str, display_name: str) -> None:
    try:
        recent = bpy.context.window_manager.mixar_matgen_recent
    except Exception:
        return

    # De-dup: refresh an existing entry instead of appending a duplicate.
    for item in recent:
        if item.material_id == material_id:
            item.display_name = display_name
            return

    item = recent.add()
    item.material_id = material_id
    item.display_name = display_name

    # Keep the UI compact. Remove oldest entries after the newest append.
    while len(recent) > 8:
        recent.remove(0)


@dataclass
class MatGenJob(Job):
    """Concrete Job for AI procedural material generation."""

    prompt: str = ""
    model: str = ""
    pipeline: str = "fast"
    apply_to_object_names: list[str] = field(default_factory=list)
    planned_object_names: list[str] = field(default_factory=list)
    scene_material_key: str = ""
    layer_name: str = ""
    apply_to_existing: bool = False

    material_id: str = ""
    material_name: str = ""
    _result: dict = field(default_factory=dict, repr=False)

    def submit(self, on_success, on_error) -> None:
        service = get_job_queue_service()
        payload = {
            "prompt": self.prompt,
            "pipeline": self.pipeline,
        }
        if getattr(self, "agent_context", None) is not None:
            payload["agent_context"] = dict(self.agent_context)
        service.enqueue(
            job_type=_SERVICE_KEY,
            model=self.model,
            payload=payload,
            on_success=on_success,
            on_error=on_error,
            timeout=120.0,
        )

    def poll(self, on_success, on_error) -> None:
        service = get_job_queue_service()
        service.get_job_status(
            self.backend_job_id,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        inner = _unwrap_response(response)
        self.backend_job_id = inner.get("job_id", "") or ""
        self.backend_status = inner.get("status", "") or ""
        self.queue_position = int(inner.get("queue_position", 0) or 0)
        if self.backend_status == "DONE":
            self._result = _extract_result(inner)
        if not self.backend_job_id and not self._result:
            raise ValueError("MatGen enqueue response missing job_id")

    def should_skip_poll(self) -> bool:
        return bool(self._result)

    def parse_poll_response(self, response):
        inner = _unwrap_response(response)
        status = inner.get("status", "") or ""
        self.backend_status = status
        self.queue_position = int(inner.get("queue_position", 0) or 0)

        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            return ("RUN", [])
        if status == "DONE":
            self._result = _extract_result(inner)
            return ("DONE", [])
        if status in FAILED_BACKEND_STATUSES:
            self.error = inner.get("error", "") or "Material generation failed"
            self.user_message = (
                inner.get("user_message", "") or "Material generation failed"
            )
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        """Persist and register the generated material on the main thread."""
        del result_files
        try:
            script = self._result.get("script", "") or ""
            if not script:
                msg = n_("Generated material response did not include a script")
                _set_status("error:" + rpt_(msg))
                on_error(msg)
                return True

            fixed_script = _fix_rgb_to_rgba(script)
            info = save_generated_material(
                script=fixed_script,
                query=self.prompt,
                archetype=self._result.get("archetype", "") or "",
            )
            node_group_name = self._result.get("node_group_name") or info.node_group_name
            material = material_registry.ProceduralMaterial(
                material_id=info.material_id,
                name=info.name,
                category=info.category,
                script_path=info.script_path,
                thumbnail_path=info.thumbnail_path,
                node_group_name=node_group_name,
            )
            material_registry.register_material(material)

            self.material_id = material.material_id
            self.material_name = material.name
            _add_recent(material.material_id, material.name)

            done_label = material.name
            if self.apply_to_object_names:
                from mixar.modules.paint.core.agent_tools import (
                    add_procedural_material_layer,
                )

                apply_result = add_procedural_material_layer(
                    material_id=material.material_id,
                    object_names=self.apply_to_object_names,
                    layer_name=self.layer_name or material.name,
                    apply_to_existing=self.apply_to_existing,
                    initialize_if_needed=True,
                )
                if not apply_result.get("success"):
                    template = n_("Generated material but failed to apply it: {result}")
                    _set_status("error:" + rpt_(template).format(result=apply_result))
                    on_error(template.format(result=apply_result))
                    return True
                done_label = (
                    f"{material.name} applied to "
                    f"{len(apply_result.get('applied', []))} object(s)"
                )

            # The step belongs to the tab the job came from, not to the tab the
            # window shows when the result lands (per-tab undo).
            from mixar.modules.common.job_queue.core.queue_download import (
                _job_session_id, resolve_job_scene,
            )
            from mixar.modules.common.utils.undo import push_undo_step
            push_undo_step(
                "Generate Procedural Material",
                scene=resolve_job_scene(self.scene_name, _job_session_id(self)),
            )

            _set_status(f"done:{material.name}")
            on_done(done_label)
            return True
        except Exception as exc:
            logger.error("MatGen result handling failed: %s", exc, exc_info=True)
            _set_status(f"error:{exc}")
            on_error(str(exc))
            return True

    def get_poll_interval(self):
        return 3.0


def enqueue_matgen_job(
    *,
    prompt: str,
    model: Optional[str] = None,
    pipeline: str = "fast",
    apply_to_object_names: Optional[list[str]] = None,
    planned_object_names: Optional[list[str]] = None,
    scene_material_key: str = "",
    layer_name: str = "",
    apply_to_existing: bool = False,
) -> Optional[MatGenJob]:
    """Build a MatGenJob and submit it to the shared feature queue."""
    pipeline = _normalize_pipeline(pipeline)
    clean_prompt = (prompt or "").strip()
    label = f"MatGen: {clean_prompt[:40]}"
    if scene_material_key:
        label = f"{label} [{scene_material_key[:24]}]"
    job = MatGenJob(
        feature_key=FEATURE_MATGEN,
        label=label,
        display_label=clean_prompt[:40],
        service=_SERVICE_KEY,
        prompt=clean_prompt,
        # Forward the explicit model identifier (or "" to let the backend pick by
        # pipeline). _normalize_pipeline only returns "fast"/"detailed", so wrapping
        # model in it sent a pipeline label to service.enqueue(model=...).
        model=model or "",
        pipeline=pipeline,
        apply_to_object_names=list(apply_to_object_names or []),
        planned_object_names=list(planned_object_names or []),
        scene_material_key=scene_material_key,
        layer_name=layer_name,
        apply_to_existing=bool(apply_to_existing),
    )
    queue = _get_matgen_queue()
    # Non-emitting marker only — the backend emits generation.submitted
    # at the job-queue submit endpoint (feeds draft-abandonment suppression).
    note_generation_submitted("texture_gen")
    if not queue.submit(job):
        logger.warning("[MatGen] duplicate job rejected: %s", job.label)
        return None
    try:
        mark_enqueued(FEATURE_MATGEN)
    except Exception as exc:
        logger.debug("[MatGen] queue flash marker failed: %s", exc)
    return job


_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    if queue.has_active_work():
        _set_status("generating")
        return

    jobs = queue.snapshot()
    if not jobs:
        return
    latest = max(jobs, key=lambda job: job.created_at)
    if latest.state == JobState.SUCCESS:
        name = getattr(latest, "material_name", "") or latest.imported_object_names
        if name:
            _set_status("done:{}".format(name))
        return
    if latest.state == JobState.FAILED:
        message = latest.user_message or sanitize_message(latest.error)
        _set_status("error:{}".format(message or rpt_("Material generation failed")))
    elif latest.state == JobState.CANCELLED:
        _set_status("error:" + rpt_("Cancelled"))


def _get_matgen_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_MATGEN)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
