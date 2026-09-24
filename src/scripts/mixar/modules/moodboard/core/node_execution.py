# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute moodboard inference nodes through the existing unified queue."""

from __future__ import annotations

import base64
import json

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue import enqueue_generation
from mixar.modules.common.utils.image_utils import compress_for_service
from .media_utils import describe_moodboard_media, is_still_item
from .node_graph import (
    action_node_by_id,
    connect_image_results,
    connect_video_result,
    create_asset_result,
    input_media_items,
)
from .node_job_bridge import ensure_graph_listener
from .node_mesh_execution import _MESH_FEATURE_ROUTING, _run_mesh_feature
from .node_run_helpers import grow_owner_frame, label_image_name, require_upstream_results
from .node_schema import collect_node_params, node_model_slug, node_service_key

logger = get_logger(__name__)


def _result_hook(scene_name: str, node_id: str, kind: str,
                 mesh_name: str = "", front_zrot: float = 0.0):
    def _hook(job, result_names: str):
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return
        node = action_node_by_id(scene, node_id)
        if node is None:
            return
        if kind == 'ASSET':
            # Name + normalize (placement + -Y orientation) the imported mesh
            # exactly like the sidebar/chat paths, then bind the node's asset
            # result to the FINAL object name (rename may add a .NNN suffix).
            from mixar.modules.common.job_queue.core.model_io import (
                rename_generated_model,
            )
            from mixar.modules.moodboard.core.imported_pbr_layers import (
                convert_imported_material_to_paint_layers,
            )
            from mixar.modules.moodboard.core.generation_enqueue import (
                _sanitize_label,
            )
            target = mesh_name or _sanitize_label(job.label)
            final = None
            try:
                final = rename_generated_model(result_names, target, front_zrot)
                convert_imported_material_to_paint_layers(final or target)
            except Exception as e:
                logger.warning(
                    "[NodeGraph] post-import processing failed: %s", e)
            if final:
                create_asset_result(scene, node, final)
                # Also re-point the JOB at the renamed mesh (see
                # AsyncGLBJob.on_imported) — the generations-library archiver
                # and the queue list resolve job.imported_object_names.
                return final
            names = [n.strip() for n in result_names.split(",") if n.strip()]
            resolved = [n for n in names if bpy.data.objects.get(n) is not None]
            create_asset_result(scene, node, ", ".join(resolved or names))
        elif kind == 'IMAGE':
            connect_image_results(scene, node, result_names)
            grow_owner_frame(scene, node)
        else:
            connect_video_result(scene, node, result_names)
            grow_owner_frame(scene, node)

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
    if getattr(node, "requires_reference", False) and not references:
        raise ValueError("Connect your character sheet to this card first")
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
    name = label_image_name(node)  # the backend names the result image after the card
    if name:
        payload["image_name"] = name

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
        detail = "connect one image" if not stills else "connect only one image"
        raise ValueError(
            f"Generate to 3D needs exactly one image connection ({detail}; "
            f"found {len(stills)})"
        )
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

    from mixar.modules.moodboard.core.generation_enqueue import (
        derive_model_name, model_front_zrot,
    )

    route = _routing(service_key)
    feature_key = route.pop("feature_key")
    route.pop("on_imported", None)  # _routing never sets it; drop if it ever does
    ensure_graph_listener(feature_key)
    mesh_name = derive_model_name(image, prompt or "")
    hook = _result_hook(
        context.scene.name, node.node_id, 'ASSET',
        mesh_name, model_front_zrot(model))
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
    limits = get_video_generation_limits(service_key, model)
    if limits is None:
        raise ValueError("Video generation catalog config is incomplete")
    params = collect_node_params(node)
    from .video_generation_catalog import video_reference_count_error

    count_error = video_reference_count_error(
        limits,
        image_count=len(images),
        video_count=len(videos),
        image_mode=(params or {}).get("image_mode"),
    )
    if count_error:
        raise ValueError(count_error)
    if any(not item["source_available"] for item in videos):
        raise ValueError("A connected video was moved or deleted")

    from .video_generation_catalog import (
        build_image_reference_inputs,
        build_video_reference_inputs,
    )

    video_inputs = build_video_reference_inputs(videos, limits)
    image_inputs = build_image_reference_inputs(images, limits, compress_for_service)
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
        on_imported=hook,
    )
    return job, params


def _mask_result_hook(scene_name: str, node_id: str):
    """Attach mask-detail outputs as standalone nodes linked from the mask node.

    Additive: each generation adds new output image nodes; the mask node keeps
    its own mask tile rather than swallowing the result.
    """
    def _hook(job, result_names: str):
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return
        node = action_node_by_id(scene, node_id)
        if node is None:
            return
        from .node_graph import connect_image_outputs_as_nodes

        connect_image_outputs_as_nodes(scene, node, result_names)

    return _hook


def _run_mask_detail(context, node, operator):
    from mixar.bootstrap.generation_catalog_cache import get_model, is_loaded
    from mixar.modules.common.generation_params import (
        resolve_model_slug,
        resolve_service_key,
    )
    from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN
    from mixar.modules.common.utils.image_utils import image_to_png_bytes
    from mixar.modules.moodboard.constants import (
        CHARACTER_COMPONENT_FULL_CONTEXT_REFERENCES,
    )
    from .character_components import (
        build_component_payload,
        component_output_name,
        model_reference_limit,
        model_supports_component_details,
        prepare_component_references,
    )

    scene = context.scene
    service_key = resolve_service_key("image_gen", node_service_key(node))
    if service_key != "image_gen":
        raise ValueError("Mask detail generation runs on the image service")
    model_slug = resolve_model_slug(service_key, node_model_slug(node))
    if not model_slug:
        raise ValueError("No enabled image model is available")
    if not is_loaded():
        raise ValueError("Load the generation catalog before generating details")
    model = get_model(service_key, model_slug)
    if not model_supports_component_details(model):
        raise ValueError(
            "Choose an Image Gen model with mask guidance and two references"
        )

    sources = [item for item in input_media_items(scene, node) if is_still_item(item)]
    if not sources:
        raise ValueError("Connect the source image to this mask node")
    source_item = sources[0]
    segment = next(
        (
            seg for seg in source_item.segments
            if str(getattr(seg, "component_id", "")) == node.component_id
            and seg.mask_image
        ),
        None,
    )
    if segment is None:
        raise ValueError("The lasso mask for this node no longer exists")

    # This node's own catalog params (edited in its panel); views/full-context
    # are per-node props. number_of_images is driven by Views per Component.
    params = collect_node_params(node)
    params.pop("number_of_images", None)
    try:
        views = max(1, min(int(node.views_per_component), 4))
    except (TypeError, ValueError):
        views = 3
    include_full_context = bool(node.include_full_context) and (
        model_reference_limit(model) >= CHARACTER_COMPONENT_FULL_CONTEXT_REFERENCES
    )

    source_bytes = image_to_png_bytes(source_item.image)
    mask_bytes = image_to_png_bytes(segment.mask_image)
    references = prepare_component_references(
        source_bytes, mask_bytes, include_full_context=include_full_context
    )
    component_name = str(segment.name or "Component").strip() or "Component"
    output_name = component_output_name(source_item.image.name, component_name)
    payload = build_component_payload(
        references,
        component_name=component_name,
        extra_instructions=node.prompt,
        params=params,
        image_name=output_name,
        views_per_component=views,
    )

    ensure_graph_listener(FEATURE_IMAGEGEN)
    hook = _mask_result_hook(scene.name, node.node_id)
    job = enqueue_generation(
        kind="image",
        feature_key=FEATURE_IMAGEGEN,
        job_type=service_key,
        model=model_slug,
        payload=payload,
        label=f"MaskNode:{node.node_id[:8]}:{component_name[:24]}",
        display_label=f"{component_name} detail",
        origin_capability_key="image_gen",
        graph_node_id=node.node_id,
        fail_message="Component detail generation failed",
        name_prefix="component_detail",
        prompt_text=payload["prompt"],
        undo_message="Generate Mask Detail",
        base_name=output_name,
        on_imported=hook,
    )
    return job, params


def mark_run_failed(node, message: str) -> bool:
    """Record a submit failure on a node, unless it is genuinely generating.

    The run operator catches EVERY submission error — including a second
    click on a node whose job is already queued ("This node is already
    running"). Demoting that node to FAILED would flash a bogus failure on a
    live job, so a generating node keeps its state; the message still reaches
    the user through the operator's own report.
    """
    if node.state in {'QUEUED', 'RUNNING'}:
        return False
    node.state = 'FAILED'
    node.error = message
    return True


def run_action_node(context, node, operator):
    if node.state in {'QUEUED', 'RUNNING'}:
        raise ValueError("This node is already running")
    node.error = ""
    require_upstream_results(context.scene, node)
    if node.action_type == 'IMAGE_GEN':
        job, params = _run_image(context, node, operator)
    elif node.action_type == 'VIDEO_GEN':
        job, params = _run_video(context, node, operator)
    elif node.action_type == 'VIDEO_UPSCALE':
        from .video_upscale_enqueue import run_video_upscale_node

        job, params = run_video_upscale_node(context, node)
    elif node.action_type == 'WORLD_LABS':
        from .world_labs_enqueue import run_world_labs_node

        job, params = run_world_labs_node(context, node)
    elif node.action_type == 'CHARACTER_PARTS':
        from .character_parts_node import run_character_parts_node

        job, params = run_character_parts_node(context, node)
    elif node.action_type == 'MASK_DETAIL':
        job, params = _run_mask_detail(context, node, operator)
    elif node.action_type == 'ASSEMBLE':
        from .assemble_node import run_assemble_node

        run_assemble_node(context, node)
        return None
    elif node.action_type in _MESH_FEATURE_ROUTING:
        job, params = _run_mesh_feature(context, node, operator)
    else:
        job, params = _run_model_3d(context, node, operator)
    if job is None:
        raise ValueError("A duplicate generation is already queued")
    node.params_json = json.dumps(params, separators=(",", ":"), sort_keys=True)
    node.job_id = job.id
    node.state = 'QUEUED'
    return job
