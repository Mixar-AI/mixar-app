# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mesh continuations share source validation, export and queue submission."""

import base64

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue import enqueue_generation
from .media_utils import is_still_item
from .node_graph import action_node_by_id, input_media_items
from .node_job_bridge import ensure_graph_listener
from .node_schema import collect_node_params, node_model_slug, node_service_key
from .mesh_sources import mesh_input_objects

logger = get_logger(__name__)


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
        return result  # see AsyncGLBJob.on_imported

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

    The input mesh comes from the connected 3D node; the result becomes this
    feature node's mesh output. PBR also accepts reference image sockets.
    """
    from mixar.modules.common.generation_params import (
        assemble_payload,
        resolve_model_slug,
        resolve_service_key,
    )
    from mixar.modules.common.job_queue.core.model_io import export_selected_mesh

    objects = mesh_input_objects(context, node)
    meshes = [obj for obj in objects if obj.type == 'MESH']

    routing = _MESH_FEATURE_ROUTING[node.action_type]
    capability = routing['capability']
    service_key = resolve_service_key(capability, node_service_key(node))
    if not service_key:
        raise ValueError("This 3D feature is unavailable in the generation catalog")
    model = resolve_model_slug(service_key, node_model_slug(node))
    if not model:
        raise ValueError("No enabled model is available for this feature")

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
        logger.warning("[NodeGraph] source mesh selection failed: %s", exc)
        raise ValueError(
            'The source mesh cannot be selected. Make it selectable in the '
            'Outliner or choose another mesh on its Moodboard node.'
        ) from exc

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

