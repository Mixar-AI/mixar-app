# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI layer-mask generation.

A ``brush_gen`` backend job with ``purpose="layer_mask"`` (the backend swaps in
its tileable grayscale layer-mask prompt; same models and price as brush
generation). The image lands on the moodboard like every image job, then is
added as an IMAGE mask on the paint layer it was requested for. The layer is
found again by its node tree and ``group_node`` (stable across reorders); when
it is gone, the image stays on the moodboard and a toast says so.
"""

import hashlib

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

logger = get_logger(__name__)

SERVICE = "brush_gen"
PURPOSE = "layer_mask"
NAME_PREFIX = "layer_mask"

# (identifier, label, description) — identifiers are the backend's placement
# hints (image_generation.prompts.LAYER_MASK_LOCATIONS); "" = anywhere worn.
LOCATION_ITEMS = (
    ('ANY', n_("Anywhere"), n_("Natural patches in worn, recessed and edge areas")),
    ('CAVITY', n_("Crevices"), n_("Inside cracks, crevices and recessed grooves")),
    ('AO', n_("Corners"), n_("Occluded corners, seams and contact areas")),
    ('DUST', n_("Upward Faces"), n_("A thin layer on flat, upward-facing areas")),
    ('POINTINESS', n_("Edges"), n_("Worn onto raised edges, ridges and high points")),
)


def default_model(item_ids):
    """The model the dialog opens on, from the model dropdown's ``item_ids``.

    The catalog's default ``brush_gen`` model when the dropdown offers it,
    else the dropdown's first item (the fail-closed NO_BRUSH_MODEL placeholder
    before the catalog loads). None for an empty dropdown.
    """
    ids = [item_id for item_id in item_ids if item_id]
    if not ids:
        return None
    try:
        from mixar.bootstrap.generation_catalog_cache import get_default_model_slug
        slug = get_default_model_slug(SERVICE)
    except Exception:
        slug = None
    return slug if slug in ids else ids[0]


def job_label(*, tree_name: str, group_node: str, layer_name: str, prompt: str) -> str:
    """Queue dedup key: one active job per target layer and description.

    The queue refuses a second active job with the same label, so the label
    ends with the target, like ``stackable_job_identity``'s suffix: the layer's
    stable identity (node tree + group node) as a short digest. The mask lands
    on that layer, so objects sharing one paint material are one target and the
    same description is refused for the second; same-named layers in two
    materials never collide. The Queue shows ``display_label`` instead.
    """
    target = "\x1f".join((tree_name, group_node))
    digest = hashlib.sha256(target.encode("utf-8")).hexdigest()[:8]
    return f"Mask: {layer_name}: {prompt[:40]} [{digest}]"


def find_layer(tree_name: str, group_node: str):
    """The paint layer whose group node is ``group_node`` in ``tree_name``, or None."""
    tree = bpy.data.node_groups.get(tree_name)
    mp = getattr(tree, "mp", None) if tree else None
    if mp is None:
        return None
    for layer in mp.layers:
        if layer.group_node == group_node:
            return layer
    return None


def attach_mask_image(tree_name: str, group_node: str, uv_name: str, image_name: str):
    """Add ``image_name`` as an IMAGE mask on the target layer; returns the mask.

    Raises LookupError when the layer or the image no longer exists.
    """
    from ...ui.mask.mask_creation import add_new_mask
    from ...utils.blender_commons import get_noncolor_name
    from ..io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
    from ..io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes

    layer = find_layer(tree_name, group_node)
    if layer is None:
        raise LookupError("target layer no longer exists")
    image = bpy.data.images.get(image_name)
    if image is None:
        raise LookupError("generated image is missing")
    if image.colorspace_settings.name != get_noncolor_name():
        image.colorspace_settings.name = get_noncolor_name()

    mask = add_new_mask(layer, image.name, 'IMAGE', 'UV', uv_name, image)
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)
    reconnect_mp_nodes(layer.id_data)
    rearrange_mp_nodes(layer.id_data)

    wm = bpy.context.window_manager
    mpui = getattr(wm, "mpui", None)
    if mpui is not None:
        mpui.need_update = True
        mpui.layer_ui.expand_masks = True
    return mask


def _notify_unattached(layer_gone: bool) -> None:
    body = (
        n_("The layer was deleted. The generated mask is on the moodboard.")
        if layer_gone else
        n_("It could not be added to the layer. The generated mask is on the moodboard.")
    )
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push('warning', n_("Mask not added to the layer"), body=body)
    except Exception as exc:  # a toast failure must not hide the log line
        logger.debug("[LayerMaskGen] toast failed: %s", exc)


def enqueue_layer_mask(*, layer, uv_name: str, prompt: str, location: str, model: str):
    """Queue a layer-mask job for ``layer``; returns the Job, or None if a duplicate."""
    from mixar.modules.common.job_queue import enqueue_generation
    from mixar.modules.common.job_queue.constants import FEATURE_LAYER_MASK_GEN

    tree_name = layer.id_data.name
    group_node = layer.group_node
    layer_name = layer.name

    def _on_imported(_job, image_names: str) -> None:
        image_name = (image_names or "").split(", ")[0]
        try:
            attach_mask_image(tree_name, group_node, uv_name, image_name)
        except Exception as exc:
            logger.warning("[LayerMaskGen] could not attach mask to '%s': %s", layer_name, exc)
            _notify_unattached(find_layer(tree_name, group_node) is None)

    payload = {"prompt": prompt, "purpose": PURPOSE}
    if location and location != 'ANY':
        payload["location_hint"] = location

    return enqueue_generation(
        kind="image",
        feature_key=FEATURE_LAYER_MASK_GEN,
        job_type=SERVICE,
        model=model,
        payload=payload,
        label=job_label(tree_name=tree_name, group_node=group_node,
                        layer_name=layer_name, prompt=prompt),
        display_label=prompt[:40],
        fail_message=n_("Mask generation failed"),
        name_prefix=NAME_PREFIX,
        prompt_text=prompt,
        on_imported=_on_imported,
    )
