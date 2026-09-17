# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Submit a Video Upscale job — the ONE enqueue path both surfaces share.

The sidebar operator (``mixie.video_upscale_generate``) and the canvas node
(``VIDEO_UPSCALE`` in ``node_execution.run_action_node``) resolve their
source clip differently (the selection vs. the connected input socket) but
must stage and submit it identically: one ``video_inputs`` entry streamed
through ``POST /job-queue/uploads/video?purpose=video_upscale``, landing in
the payload as the single ``video_s3_key`` the backend contract expects, an
optional ``prompt``, and the catalog params. Two copies of that would drift
the way the Video Gen validators once did.
"""

from __future__ import annotations

from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_UPSCALE

from .video_upscale_catalog import (
    CAPABILITY_KEY,
    SERVICE_KEY,
    build_video_upscale_input,
    get_video_upscale_limits,
    video_upscale_source_error,
)

#: Top-level payload field the backend reads the staged source from.
VIDEO_KEY_FIELD = "video_s3_key"


def resolve_video_upscale_target(mode: str, model_choice: str) -> tuple[str, str]:
    """Resolve (service_key, model_slug) for a tab/node selection, or raise."""
    from mixar.modules.common.generation_params import (
        resolve_model_slug,
        resolve_service_key,
    )

    service_key = resolve_service_key(CAPABILITY_KEY, mode)
    if service_key != SERVICE_KEY:
        raise ValueError("The selected upscale service needs a newer app version")
    model = resolve_model_slug(service_key, model_choice)
    if not model:
        raise ValueError("No enabled video upscale model is available")
    return service_key, model


def prepare_video_upscale_source(videos, limits=None) -> tuple[dict, dict]:
    """Return ``(video_input, limits)`` for exactly one described movie, or raise."""
    limits = limits or get_video_upscale_limits(SERVICE_KEY)
    if limits is None:
        raise ValueError("Video upscale catalog config is incomplete")
    error = video_upscale_source_error(limits, video_count=len(videos))
    if error:
        raise ValueError(error)
    return build_video_upscale_input(videos[0], limits), limits


def enqueue_video_upscale(
    *,
    service_key: str,
    model: str,
    prompt: str,
    params: dict,
    video_input: dict,
    limits: dict,
    scene_flag: str = "mixie_video_upscale_is_generating",
    graph_node_id: str = "",
    on_imported=None,
):
    """Stage the source and submit through the unified queue (video kind)."""
    from mixar.modules.common.job_queue import enqueue_generation

    prompt = str(prompt or "").strip()
    payload = {"params": dict(params or {})}
    if prompt:
        payload["prompt"] = prompt
    source_name = str(video_input.get("filename") or "video")
    tag = f":{graph_node_id[:8]}" if graph_node_id else ""
    return enqueue_generation(
        kind="video",
        feature_key=FEATURE_VIDEO_UPSCALE,
        job_type=service_key,
        model=model,
        payload=payload,
        label=f"VideoUpscale{tag}: {source_name[:40]}",
        display_label=f"Upscale {source_name[:32]}",
        origin_capability_key=CAPABILITY_KEY,
        graph_node_id=graph_node_id,
        fail_message="Video upscale failed",
        prompt_text=prompt,
        video_inputs=[video_input],
        max_video_duration_seconds=limits["max_seconds"],
        upload_purpose=limits["upload_purpose"],
        video_key_field=VIDEO_KEY_FIELD,
        single_video_key=True,
        scene_flag=scene_flag,
        batch_popup_title="Video Upscale Complete",
        on_imported=on_imported,
    )


def run_video_upscale_node(context, node):
    """Node-graph runner for ``VIDEO_UPSCALE`` (called by ``run_action_node``)."""
    from .media_utils import describe_moodboard_media
    from .node_execution import _result_hook
    from .node_graph import input_media_items
    from .node_job_bridge import ensure_graph_listener
    from .node_schema import collect_node_params, node_model_slug, node_service_key

    service_key, model = resolve_video_upscale_target(
        node_service_key(node), node_model_slug(node)
    )
    videos = [
        item for item in (
            describe_moodboard_media(media)
            for media in input_media_items(context.scene, node)
        )
        if item["media_type"] == "VIDEO"
    ]
    if not videos:
        raise ValueError("Connect one video to the Upscale Video node")
    video_input, limits = prepare_video_upscale_source(videos)
    params = collect_node_params(node)
    ensure_graph_listener(FEATURE_VIDEO_UPSCALE)
    job = enqueue_video_upscale(
        service_key=service_key,
        model=model,
        prompt=node.prompt,
        params=params,
        video_input=video_input,
        limits=limits,
        graph_node_id=node.node_id,
        on_imported=_result_hook(context.scene.name, node.node_id, 'VIDEO'),
    )
    return job, params
