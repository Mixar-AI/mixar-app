# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unified ``enqueue_generation()`` entry-point.

Builds an ``AsyncGLBJob`` or ``SyncImageJob``, attaches a queue listener,
and submits to the correct ``FeatureQueue``.
"""

from typing import Callable, Optional

from mixar.config.logging_config import get_logger
from .generic_jobs import AsyncGLBJob, SyncImageJob
from .helpers import create_scene_flag_listener, get_queue_with_listener
from .job import Job

logger = get_logger(__name__)


def enqueue_generation(
    *,
    kind: str,
    feature_key: str,
    job_type: str,
    model: str,
    payload: dict,
    label: str,
    display_label: str = "",
    origin_capability_key: str = "",
    fail_message: str = "Generation failed",
    # GLB-only
    on_imported: Optional[Callable] = None,
    # Image-only
    name_prefix: str = "",
    prompt_text: str = "",
    undo_message: str = "",
    base_name: str = "",
    # Listener options
    scene_flag: str = "",
    batch_popup_title: str = "",
    listener: Optional[Callable] = None,
) -> Optional[Job]:
    """Build a generic Job and submit it to the queue.

    Parameters
    ----------
    kind : ``"glb"`` | ``"image"``
        Which generic Job class to use.
    feature_key : str
        Queue feature key (e.g. ``FEATURE_IMAGEGEN``).
    job_type, model, payload : str, str, dict
        Forwarded to ``JobQueueService.enqueue()``.
    label : str
        Stable job label used by queue dedup and downstream naming.
    display_label : str
        Optional clean queue-row title when ``label`` carries extra identity.
    origin_capability_key : str
        Optional backend catalog capability for composite workflow display.
    fail_message : str
        Shown when the backend returns FAILED.
    on_imported : callable, optional
        ``fn(job, object_names)`` — GLB post-import hook.
    name_prefix, prompt_text, undo_message : str
        Image-job parameters for moodboard download.
    scene_flag : str
        If set and no explicit *listener*, auto-creates a
        ``create_scene_flag_listener`` for this property.
    batch_popup_title : str
        Passed to ``create_scene_flag_listener`` if auto-created.
    listener : callable, optional
        Explicit queue listener (takes priority over *scene_flag*).

    Returns
    -------
    Job | None
        The enqueued job, or ``None`` if the queue rejected it as a duplicate.
    """
    if kind == "glb":
        job = AsyncGLBJob(
            feature_key=feature_key,
            label=label,
            display_label=display_label,
            service=job_type,
            origin_capability_key=origin_capability_key,
            job_type=job_type,
            model=model,
            payload=payload,
            fail_message=fail_message,
            _on_imported_hook=on_imported,
        )
    elif kind == "image":
        job = SyncImageJob(
            feature_key=feature_key,
            label=label,
            display_label=display_label,
            service=job_type,
            origin_capability_key=origin_capability_key,
            job_type=job_type,
            model=model,
            payload=payload,
            fail_message=fail_message,
            name_prefix=name_prefix,
            prompt_text=prompt_text,
            undo_message=undo_message,
            base_name=base_name,
        )
    else:
        raise ValueError(f"Unknown enqueue_generation kind: {kind!r}")

    resolved_listener = listener
    if resolved_listener is None and scene_flag:
        resolved_listener = create_scene_flag_listener(
            scene_flag, batch_popup_title=batch_popup_title,
        )

    if resolved_listener is not None:
        queue = get_queue_with_listener(feature_key, resolved_listener)
    else:
        from .queue_manager import get_queue
        queue = get_queue(feature_key)

    if not queue.submit(job):
        logger.warning("Duplicate job rejected: %s", label)
        return None
    return job
