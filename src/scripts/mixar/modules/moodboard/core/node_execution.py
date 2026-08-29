# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute moodboard inference nodes through the existing unified queue."""

from __future__ import annotations

import base64
import json
import os

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
            else:
                names = [n.strip() for n in result_names.split(",") if n.strip()]
                resolved = [n for n in names if bpy.data.objects.get(n) is not None]
                create_asset_result(scene, node, ", ".join(resolved or names))
        elif kind == 'IMAGE':
            connect_image_results(scene, node, result_names)
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


_MESH_FEATURE_ROUTING = {
    'PBR_GEN': {
        'capability': 'pbr_generation',
        'feature_key': 'pbr_generation',
        'scene_flag': 'mixie_pbr_gen_is_generating',
    },
    'RETOPOLOGY': {
        'capability': 'retopology',
        'feature_key': 'retopology',
        'scene_flag': 'mixie_retopology_is_generating',
    },
    'MESH_SEGMENT': {
        'capability': 'mesh_segmentation',
        'feature_key': 'hunyuan_part',
        'scene_flag': 'mixie_hunyuan_part_is_generating',
    },
    'AUTO_RIG': {
        'capability': 'animate',
        'feature_key': 'animate',
        'scene_flag': 'mixie_animate_is_generating',
        'import_options': {"bone_heuristic": "BLENDER", "guess_original_bind_pose": False},
    },
}


def _mesh_result_hook(scene_name: str, node_id: str,
                      texture_finalize: bool = False, base_name: str = ""):
    """Embed the imported result mesh INTO the producing node.

    Like Generate 3D, the feature node's generate UI is replaced by the result
    thumbnail (``create_asset_result`` sets ``preview_object`` + ``result_names``),
    rather than spawning a separate asset node. The node stays a MESH source so
    it can be chained onward.

    When *texture_finalize* is set (PBR Generation), the imported mesh is renamed
    (pose kept) and its material/images cleaned up + packed map split, then the
    node binds to the FINAL name.
    """
    def _hook(job, object_names: str):
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return
        node = action_node_by_id(scene, node_id)
        if node is None:
            return
        from .node_graph import create_asset_result

        result = object_names
        if texture_finalize:
            try:
                from mixar.modules.common.job_queue.core.model_io import (
                    rename_imported_object,
                )
                from mixar.modules.moodboard.core.imported_pbr_layers import (
                    convert_imported_material_to_paint_layers,
                )
                from mixar.modules.moodboard.core.generation_enqueue import (
                    _sanitize_label,
                )
                target = base_name or _sanitize_label(job.label)
                final = rename_imported_object(object_names, target)
                convert_imported_material_to_paint_layers(final or target)
                if final:
                    result = final
            except Exception as e:
                logger.warning(
                    "[TextureGen] node PBR post-import processing failed: %s", e)

        create_asset_result(scene, node, result)

    return _hook


def _attach_pbr_reference_images(scene, node, payload, operator):
    """Attach connected reference image(s) to a PBR texture payload.

    Mirrors ``enqueue_pbr_texture_job``'s guidance precedence: exactly four
    connected images become Tripo's turnaround views (by input order); one to
    three become a single reference image (the first). The mesh input is
    resolved separately and never appears here (``input_media_items`` yields
    only still images, not mesh nodes).
    """
    from mixar.modules.common.utils.image_utils import compress_image_for_upload

    images = [
        item.image for item in input_media_items(scene, node)
        if is_still_item(item)
    ]
    if not images:
        return
    if len(images) == 4:
        payload["reference_images_b64"] = [
            base64.b64encode(compress_image_for_upload(img)).decode()
            for img in images
        ]
        return
    if len(images) > 1 and operator is not None:
        operator.report(
            {'WARNING'},
            "PBR uses the first connected reference; connect exactly four for "
            "turnaround views",
        )
    payload["reference_image_bytes_b64"] = base64.b64encode(
        compress_image_for_upload(images[0])
    ).decode()


def _run_mesh_feature(context, node, operator):
    """Run a mesh -> mesh continuation (PBR / Retopology / Segment / Auto Rig).

    The input mesh comes from the connected 3D node; the result imports as a new
    standalone 3D asset node linked from this feature node. PBR additionally
    accepts optional reference image(s) from its image sockets.
    """
    import base64

    from mixar.modules.common.generation_params import (
        assemble_payload,
        resolve_model_slug,
        resolve_service_key,
    )
    from mixar.modules.common.job_queue.core.model_io import export_selected_mesh
    from .node_graph import input_source_object_names

    routing = _MESH_FEATURE_ROUTING[node.action_type]
    capability = routing['capability']
    service_key = resolve_service_key(capability, node_service_key(node))
    if not service_key:
        raise ValueError("This 3D feature is unavailable in the generation catalog")
    model = resolve_model_slug(service_key, node_model_slug(node))
    if not model:
        raise ValueError("No enabled model is available for this feature")

    names = input_source_object_names(context.scene, node)
    objects = [bpy.data.objects.get(name) for name in names]
    objects = [obj for obj in objects if obj is not None]
    meshes = [obj for obj in objects if obj.type == 'MESH']
    if not meshes:
        raise ValueError("Connect this node to a 3D mesh node")

    # Export the exact source objects, not whatever the user last clicked.
    view_layer = context.view_layer
    try:
        for obj in view_layer.objects:
            obj.select_set(False)
        for obj in objects:
            if obj.name in view_layer.objects:
                obj.select_set(True)
        view_layer.objects.active = meshes[0]
    except (AttributeError, RuntimeError) as exc:
        raise ValueError(f"Could not select the source mesh: {exc}")

    file_bytes, filename = export_selected_mesh(context, "GLB")
    payload = {
        "file_bytes_b64": base64.b64encode(file_bytes).decode(),
        "file_filename": filename,
    }
    if node.action_type == 'PBR_GEN':
        _attach_pbr_reference_images(context.scene, node, payload, operator)
    params = collect_node_params(node)
    prompt = node.prompt.strip()
    if prompt:
        params["prompt"] = prompt
    payload = assemble_payload(service_key, params, payload, model)

    ensure_graph_listener(routing['feature_key'])
    hook = _mesh_result_hook(
        context.scene.name, node.node_id,
        texture_finalize=(node.action_type == 'PBR_GEN'),
        base_name=meshes[0].name,
    )
    extra = {}
    if routing.get('import_options'):
        extra['import_options'] = routing['import_options']
    job = enqueue_generation(
        kind="glb",
        feature_key=routing['feature_key'],
        job_type=service_key,
        model=model,
        payload=payload,
        label=meshes[0].name,
        display_label=node.action_type.replace('_', ' ').title(),
        origin_capability_key=capability,
        graph_node_id=node.node_id,
        fail_message="3D generation failed",
        scene_flag=routing['scene_flag'],
        on_imported=hook,
        **extra,
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
    elif node.action_type == 'MASK_DETAIL':
        job, params = _run_mask_detail(context, node, operator)
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
