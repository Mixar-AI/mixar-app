# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute moodboard inference nodes through the existing unified queue."""

from __future__ import annotations

import base64
import json
import os
import re

import bpy

from mixar.modules.common.job_queue import enqueue_generation
from mixar.modules.common.utils.image_utils import compress_for_service
from .media_utils import describe_moodboard_media, is_still_item
from .node_graph import (
    action_node_by_id,
    connect_image_result,
    connect_video_result,
    create_asset_result,
    input_media_items,
)
from .node_job_bridge import ensure_graph_listener
from .node_schema import collect_node_params, node_model_slug, node_service_key


def _result_hook(scene_name: str, node_id: str, kind: str, prior_hook=None):
    def _hook(job, result_names: str):
        if prior_hook is not None:
            prior_hook(job, result_names)
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return
        node = action_node_by_id(scene, node_id)
        if node is None:
            return
        if kind == 'ASSET':
            names = [name.strip() for name in result_names.split(",") if name.strip()]
            resolved = [name for name in names if bpy.data.objects.get(name) is not None]
            if not resolved and prior_hook is not None:
                base = re.sub(r'[^a-zA-Z0-9_]', '_', job.label)
                base = re.sub(r'_+', '_', base).strip('_') or "object"
                renamed = f"{base}_high"
                if bpy.data.objects.get(renamed) is not None:
                    resolved = [renamed]
            create_asset_result(scene, node, ", ".join(resolved or names))
        elif kind == 'IMAGE':
            connect_image_result(scene, node, result_names)
        else:
            connect_video_result(scene, node, result_names)

    return _hook


def _run_image(context, node, operator):
    from mixar.bootstrap.generation_catalog_cache import get_model
    from mixar.modules.common.generation_params import (
        resolve_model_slug,
        resolve_service_key,
    )
    from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN

    prompt = node.prompt.strip()
    if not prompt:
        raise ValueError("Enter a prompt in the image node")
    service_key = resolve_service_key("image_gen", node_service_key(node))
    if service_key != "image_gen":
        raise ValueError("The selected image service needs a newer app version")
    model = resolve_model_slug(service_key, node_model_slug(node))
    if not model:
        raise ValueError("No enabled image model is available")

    references = [
        item for item in input_media_items(context.scene, node)
        if is_still_item(item)
    ]
    model_spec = get_model(service_key, model) or {}
    # Fail closed: a catalog that publishes no reference limit takes no
    # references. Guessing a client-side default here would burn a queue slot
    # and the user's wait on a 422 the vendor raises after credits are held.
    max_refs = int(model_spec.get("max_reference_images") or 0)
    if len(references) > max_refs:
        raise ValueError(
            f"This model accepts at most {max_refs} reference images"
            if max_refs
            else "This model does not accept reference images"
        )
    reference_b64 = [
        base64.b64encode(compress_for_service(item.image, "imagegen")).decode()
        for item in references
    ]
    params = collect_node_params(node)
    params.setdefault("number_of_images", 1)
    payload = {"prompt": prompt, "params": params}
    if reference_b64:
        payload["reference_images_b64"] = reference_b64

    ensure_graph_listener(FEATURE_IMAGEGEN)
    hook = _result_hook(context.scene.name, node.node_id, 'IMAGE')
    job = enqueue_generation(
        kind="image",
        feature_key=FEATURE_IMAGEGEN,
        job_type=service_key,
        model=model,
        payload=payload,
        label=f"ImageNode:{node.node_id[:8]}:{prompt[:32]}",
        display_label=prompt[:40],
        origin_capability_key="image_gen",
        graph_node_id=node.node_id,
        fail_message="Image generation failed",
        name_prefix="imagegen",
        prompt_text=prompt,
        undo_message="Generate Image Node",
        scene_flag="mixie_imagegen_is_generating",
        on_imported=hook,
    )
    return job, params


def _run_model_3d(context, node, operator):
    from mixar.modules.common.generation_params import (
        assemble_payload,
        model_supports_multi_view,
        resolve_model_slug,
        resolve_service_key,
    )
    from mixar.modules.common.utils.image_utils import compress_image_for_upload
    from mixar.modules.moodboard.ui.operators.model_gen_ops import _routing

    inputs = input_media_items(context.scene, node)
    stills = [item for item in inputs if is_still_item(item)]
    if len(stills) != 1:
        raise ValueError("Generate to 3D currently requires exactly one image connection")
    image = stills[0].image

    service_key = resolve_service_key("model_gen", node_service_key(node))
    if not service_key:
        raise ValueError("Model Gen is unavailable in the generation catalog")
    if service_key not in {'model_3d', 'image_to_3d', 'hunyuan_rapid'}:
        raise ValueError("This Model Gen mode is not supported by inference nodes yet")
    model = resolve_model_slug(service_key, node_model_slug(node))
    if not model:
        raise ValueError("No enabled 3D generation model is available")

    turnaround = None
    # A multi-view set that cannot be honoured raises a TERMINAL ValueError and
    # is deliberately allowed to propagate: degrading to a single image would
    # build the model from less data than the user believes they supplied.
    from .turnaround_views import build_active_group_payload

    result = build_active_group_payload(context.scene, image, service_key, model)
    if result is not None:
        turnaround, warnings = result
        for warning in warnings:
            operator.report({'WARNING'}, warning)

    prompt = node.prompt.strip() or None
    supports_mv = model_supports_multi_view(service_key, model)
    if not turnaround and service_key != "model_3d" and not (image or prompt or supports_mv):
        raise ValueError("Provide an image or prompt")

    payload = dict(turnaround or {})
    if not turnaround:
        image_bytes = (
            compress_for_service(image, "image_to_3d")
            if service_key == "model_3d"
            else compress_image_for_upload(image)
        )
        payload["image_bytes_b64"] = base64.b64encode(image_bytes).decode()
        payload["image_filename"] = f"{image.name}.png"

    params = collect_node_params(node)
    if prompt:
        if service_key == "image_to_3d":
            params["prompt"] = prompt
        elif service_key == "hunyuan_rapid":
            if image is None:
                params["prompt"] = prompt
        else:
            payload["prompt"] = prompt
    payload = assemble_payload(service_key, params, payload, model)

    route = _routing(service_key)
    feature_key = route.pop("feature_key")
    prior_hook = route.pop("on_imported", None)
    ensure_graph_listener(feature_key)
    hook = _result_hook(context.scene.name, node.node_id, 'ASSET', prior_hook)
    job = enqueue_generation(
        kind="glb",
        feature_key=feature_key,
        job_type=service_key,
        model=model,
        payload=payload,
        label=image.name,
        display_label=image.name,
        origin_capability_key="model_gen",
        graph_node_id=node.node_id,
        on_imported=hook,
        **route,
    )
    return job, params


def _run_video(context, node, operator):
    from mixar.modules.common.generation_params import (
        resolve_model_slug,
        resolve_service_key,
    )
    from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_GEN
    from .video_generation_catalog import get_video_generation_limits

    prompt = node.prompt.strip()
    if not prompt:
        raise ValueError("Enter a video prompt in the Node panel")
    service_key = resolve_service_key("video_gen", node_service_key(node))
    if service_key != "video_gen":
        raise ValueError("The selected video service needs a newer app version")
    model = resolve_model_slug(service_key, node_model_slug(node))
    if not model:
        raise ValueError("No enabled video model is available")

    descriptions = [
        describe_moodboard_media(item)
        for item in input_media_items(context.scene, node)
    ]
    images = [item for item in descriptions if item["media_type"] == "IMAGE"]
    videos = [item for item in descriptions if item["media_type"] == "VIDEO"]
    limits = get_video_generation_limits(service_key)
    if limits is None:
        raise ValueError("Video generation catalog config is incomplete")
    if len(images) > limits["max_images"] or len(videos) > limits["max_videos"]:
        raise ValueError("Connected references exceed this model's limits")
    if len(descriptions) > limits["max_materials"]:
        raise ValueError("Connected references exceed the total material limit")
    if any(not item["source_available"] for item in videos):
        raise ValueError("A connected video was moved or deleted")

    video_inputs = []
    for video in videos:
        if video["file_size_bytes"] > limits["max_video_bytes"]:
            raise ValueError(f"Video is too large: {video['filename']}")
        if os.path.splitext(video["filename"])[1].lower() not in limits["video_extensions"]:
            raise ValueError(f"Unsupported video reference: {video['filename']}")
        video_inputs.append({
            "filename": video["filename"],
            "mime_type": video["mime_type"],
            "filepath": video["resolved_filepath"],
            "file_size_bytes": video["file_size_bytes"],
        })

    image_inputs = [
        {
            "filename": f"reference_{index + 1}.jpg",
            "mime_type": "image/jpeg",
            "bytes": compress_for_service(item["image"], "video_gen"),
        }
        for index, item in enumerate(images)
    ]
    params = collect_node_params(node)
    ensure_graph_listener(FEATURE_VIDEO_GEN)
    hook = _result_hook(context.scene.name, node.node_id, 'VIDEO')
    job = enqueue_generation(
        kind="video",
        feature_key=FEATURE_VIDEO_GEN,
        job_type=service_key,
        model=model,
        payload={"prompt": prompt, "params": params},
        label=f"VideoGen:{node.node_id[:8]}:{prompt[:32]}",
        display_label=prompt[:40],
        origin_capability_key="video_gen",
        graph_node_id=node.node_id,
        fail_message="Video generation failed",
        prompt_text=prompt,
        image_inputs=image_inputs,
        video_inputs=video_inputs,
        max_video_duration_seconds=limits["max_video_seconds"],
        scene_flag="mixie_video_gen_is_generating",
        batch_popup_title="Video Generation Complete",
        on_imported=hook,
    )
    return job, params


def run_action_node(context, node, operator):
    if node.state in {'QUEUED', 'RUNNING'}:
        raise ValueError("This node is already running")
    node.error = ""
    if node.action_type == 'IMAGE_GEN':
        job, params = _run_image(context, node, operator)
    elif node.action_type == 'VIDEO_GEN':
        job, params = _run_video(context, node, operator)
    else:
        job, params = _run_model_3d(context, node, operator)
    if job is None:
        raise ValueError("A duplicate generation is already queued")
    node.params_json = json.dumps(params, separators=(",", ":"), sort_keys=True)
    node.job_id = job.id
    node.state = 'QUEUED'
    return job
