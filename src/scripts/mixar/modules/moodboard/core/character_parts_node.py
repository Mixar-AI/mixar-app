# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Character Parts nodes submit existing component masks through SceneGen."""

from ..constants import CHARACTER_PARTS_CAPABILITY_KEY, SCENE_GEN_JOB_TYPE
from .media_utils import is_still_item
from .node_schema import collect_node_params, node_model_slug, node_service_key


def source_item(scene, node):
    """The connected still owns the masks; current canvas selection is irrelevant."""
    from .node_graph import input_media_items

    inputs = input_media_items(scene, node)
    if len(inputs) != 1 or not is_still_item(inputs[0]):
        raise ValueError("Connect one image with component masks to Character Parts")
    return inputs[0]


def active_masks(item):
    masks = [segment for segment in item.segments if segment.active and segment.mask_image]
    if not masks:
        raise ValueError("Create masks with Box Mask, Multi-Lasso Mask or Magic Select, then enable a component")
    return masks


def resolve_target(node):
    """Saved selections must still be enabled in the owning catalog capability."""
    from mixar.bootstrap.generation_catalog_cache import (
        get_capability, get_model, get_services, is_loaded,
    )
    from .capabilities import _enabled

    key, model = node_service_key(node), node_model_slug(node)
    capability = get_capability(CHARACTER_PARTS_CAPABILITY_KEY) if is_loaded() else None
    services = get_services(CHARACTER_PARTS_CAPABILITY_KEY, surface='moodboard') if capability else []
    if (not capability or not _enabled(capability) or key != SCENE_GEN_JOB_TYPE
            or not any(service.get('key') == key and _enabled(service) for service in services)):
        raise ValueError("Character Parts is unavailable in the generation catalog")
    model_record = get_model(key, model) if model else None
    if not model_record or not _enabled(model_record):
        raise ValueError("Choose an enabled Character Parts model")
    return key, model


def _import_callbacks(scene_name, scene_uid, node_id, job_ref):
    """Keep import state per run without retaining RNA pointers across callbacks."""
    state = {'collection_name': '', 'z_offset': 0.0, 'z_offset_locked': False}

    def live_owner():
        import bpy
        from .node_graph import action_node_by_id

        scene = bpy.data.scenes.get(scene_name)
        # A new file can reuse both scene and node names. Session identity
        # fences late downloads from the Main that submitted this request.
        if scene is None or scene.session_uid != scene_uid:
            return None, None
        node = action_node_by_id(scene, node_id)
        job = job_ref.get('job')
        if (node is None or job is None or job.state != 'RUNNING_DOWNLOAD'
                or node.state not in {'QUEUED', 'RUNNING'}
                or node.job_id not in {job.id, job.backend_job_id}):
            return None, None
        return scene, node

    def import_object(glb_bytes, pose_data, object_id):
        import bpy
        from . import scene_importer
        scene, node = live_owner()
        if scene is None:
            raise ValueError("The originating Character Parts run is no longer active")
        collection = bpy.data.collections.get(state['collection_name'])
        if collection is None:
            collection = bpy.data.collections.new(f'CharacterParts_{node_id[:8]}')
            scene.collection.children.link(collection)
            state['collection_name'] = collection.name
        previous = scene_importer._scene_state
        owned = {
            'collection': collection, 'camera': None,
            'objects': list(collection.objects),
            'z_offset': state['z_offset'], 'z_offset_locked': state['z_offset_locked'],
        }
        view_layer = scene.view_layers[0]
        selected = [obj for obj in view_layer.objects if obj.select_get(view_layer=view_layer)]
        active = view_layer.objects.active
        try:
            scene_importer._scene_state = owned
            with bpy.context.temp_override(scene=scene, view_layer=view_layer):
                obj = scene_importer.add_object(
                    glb_bytes, pose_data, object_id, auto_adjust_camera=False,
                )
            if obj is None:
                raise ValueError(f'Character part {object_id} could not be imported')
            state['z_offset'] = owned['z_offset']
            state['z_offset_locked'] = owned['z_offset_locked']
            return [obj]
        finally:
            scene_importer._scene_state = previous
            # GLTF selects its imports; background results must not take over
            # the user's active edit selection in the originating scene.
            for obj in view_layer.objects:
                obj.select_set(obj in selected, view_layer=view_layer)
            view_layer.objects.active = active

    def imported(_job, names):
        from .node_graph import create_asset_result

        scene, node = live_owner()
        if node is not None:
            create_asset_result(scene, node, names)

    return import_object, imported


def run_character_parts_node(context, node):
    from mixar.modules.common.generation_params import assemble_payload
    from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN
    from mixar.modules.common.utils.image_utils import image_to_png_bytes
    from .node_job_bridge import ensure_graph_listener
    from .scene_gen_queue import enqueue_scene_gen_job

    key, model = resolve_target(node)
    item = source_item(context.scene, node)
    masks = active_masks(item)
    # Preserve a common pixel coordinate system. Lossy/resized image uploads
    # would misalign the source against the lossless SAM masks.
    source = item.image
    from .character_parts_payload import encode_source_and_masks

    source_b64, mask_b64 = encode_source_and_masks(
        image_to_png_bytes(source),
        [image_to_png_bytes(segment.mask_image) for segment in masks],
    )
    params = collect_node_params(node)
    payload = assemble_payload(key, params, {
        'image_bytes_b64': source_b64,
        'mask_bytes_list_b64': mask_b64,
        'total_objects': len(masks),
    }, model)
    job_ref = {}
    object_ready, imported = _import_callbacks(
        context.scene.name, context.scene.session_uid, node.node_id, job_ref,
    )
    ensure_graph_listener(FEATURE_SCENE_GEN)
    job = enqueue_scene_gen_job(
        label=f'CharacterParts:{node.node_id}', payload=payload, model=model,
        graph_node_id=node.node_id, scene_name=context.scene.name,
        on_object_ready=object_ready, on_imported=imported,
    )
    job_ref['job'] = job
    return job, params
