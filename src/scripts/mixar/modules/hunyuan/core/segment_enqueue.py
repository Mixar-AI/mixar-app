# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Segmentation enqueue helpers — Tripo mesh segment and smart segment.

Two job kinds, split by what the user starts from:

* **Mesh Segmentation** (``tripo_segment``): each selected mesh is exported
  alone as GLB and submitted through the unified queue. The backend calls
  ``/v3/mesh/segment``, which only splits the mesh it is given.

* **Smart Segmentation** (``tripo_smart_segment``): a moodboard image is
  submitted and the backend calls ``/v3/mesh/smartsegment``, which *generates*
  a 3D model from the image and segments it in the same task — so there is no
  source object in the scene, and the parts come back semantically named.

Both import as one GLB containing every part. :func:`segment_on_imported`
rehomes the imported objects into a ``<label>_parts`` collection, names them
from the backend's ``part_names`` when it supplied any, and HIDES (never
deletes) the source mesh so the split stays comparable and undoable.
"""

import base64 as _b64

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import (
    FEATURE_SMART_SEGMENT,
    FEATURE_TRIPO_SEGMENT,
)
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation
from ..constants import (
    MAX_FILE_SIZE_SEGMENT,
    SEGMENT_JOB_PROP,
    SEGMENT_PARTS_SUFFIX,
    SEGMENT_SERVICE,
    SMART_SEGMENT_SERVICE,
)
from .retopology_enqueue import _export_single_object

logger = get_logger(__name__)

SEGMENT_SCENE_FLAG = "mixie_tripo_segment_is_generating"
SMART_SEGMENT_SCENE_FLAG = "mixie_smart_segment_is_generating"


# ---------------------------------------------------------------------------
# Import hook
# ---------------------------------------------------------------------------


def _unique_collection_name(base: str) -> str:
    import bpy

    if base not in bpy.data.collections:
        return base
    index = 1
    while f"{base}.{index:03d}" in bpy.data.collections:
        index += 1
    return f"{base}.{index:03d}"


def _rehome(objects, collection) -> None:
    """Move ``objects`` out of whatever collections they landed in and into
    ``collection``, so the parts read as one unit in the outliner."""
    for obj in objects:
        for existing in list(obj.users_collection):
            try:
                existing.objects.unlink(obj)
            except (RuntimeError, ReferenceError):
                pass
        try:
            collection.objects.link(obj)
        except (RuntimeError, ReferenceError) as e:
            logger.warning("[Segment] Could not link %s: %s", obj.name, e)


def _apply_part_names(objects, part_names, prefix: str) -> None:
    """Rename imported parts from the backend's ``part_names``.

    Only applied when the counts match exactly. Tripo returns the names in
    part order, but if the importer produced a different number of objects we
    have no way to line them up — and a WRONG part name is worse than a
    generic one, because the agent and the user both act on these names.
    """
    if not part_names:
        return
    if len(part_names) != len(objects):
        logger.info(
            "[Segment] %d part name(s) but %d imported object(s) — keeping "
            "importer names rather than risk mislabelling",
            len(part_names), len(objects),
        )
        return
    for obj, name in zip(objects, part_names):
        slug = str(name).strip().replace(" ", "_")
        if not slug:
            continue
        try:
            obj.name = f"{prefix}_{slug}"
        except (RuntimeError, ReferenceError) as e:
            logger.warning("[Segment] Could not rename %s: %s", obj.name, e)


def _hide(obj) -> None:
    """Hide the source mesh in viewport and render without deleting it."""
    try:
        obj.hide_set(True)
        obj.hide_render = True
    except (RuntimeError, ReferenceError) as e:
        logger.warning("[Segment] Could not hide %s: %s", obj.name, e)


def segment_on_imported(job, object_names: str) -> None:
    """Group the imported parts, name them, and hide the source object.

    ``job.result_data`` carries the backend's full result — ``part_names`` is
    populated by smart segmentation and by mesh segmentation on the semantic
    (v2) model; the geometry model sends none, in which case the importer's
    own names stand.
    """
    import bpy

    names = [n.strip() for n in object_names.split(",") if n.strip()]
    objects = [o for o in (bpy.data.objects.get(n) for n in names) if o is not None]
    if not objects:
        logger.warning("[Segment] Import produced no resolvable objects")
        return

    source_name = str(getattr(job, "label", "") or "").strip()
    result = getattr(job, "result_data", None) or {}
    part_names = result.get("part_names") or []

    base = source_name or "segmentation"
    collection = bpy.data.collections.new(
        _unique_collection_name(f"{base}{SEGMENT_PARTS_SUFFIX}")
    )
    try:
        bpy.context.scene.collection.children.link(collection)
    except (RuntimeError, ReferenceError) as e:
        logger.warning("[Segment] Could not link parts collection: %s", e)

    _rehome(objects, collection)
    _apply_part_names(objects, part_names, base)

    for obj in objects:
        try:
            obj[SEGMENT_JOB_PROP] = str(job.backend_job_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[Segment] Could not stamp %s: %s", obj.name, e)

    # Mesh segmentation replaces a scene object; smart segmentation created the
    # model from an image, so there is nothing to hide.
    source = bpy.data.objects.get(source_name) if source_name else None
    if source is not None and source not in objects:
        _hide(source)

    logger.info(
        "[Segment] Imported %d part(s) into '%s'%s",
        len(objects), collection.name,
        " (source hidden)" if source is not None else "",
    )


# ---------------------------------------------------------------------------
# Enqueue — mesh segmentation
# ---------------------------------------------------------------------------


def _ref_image_payload(ref_image) -> dict:
    """Encode a segmentation mask for the ``ref_image`` param.

    Deliberately LOSSLESS PNG, not the usual ``compress_for_service`` JPEG:
    Tripo reads discrete colours out of this mask to decide the parts, and
    JPEG ringing around the colour boundaries corrupts exactly that signal.
    """
    if ref_image is None:
        return {}
    from mixar.modules.common.utils.image_utils import image_to_png_bytes

    try:
        data = image_to_png_bytes(ref_image)
    except Exception as e:  # noqa: BLE001
        logger.warning("[Segment] Could not encode ref_image: %s", e)
        return {}
    return {
        "reference_image_bytes_b64": _b64.b64encode(data).decode(),
        "reference_image_filename": f"{ref_image.name}.png",
    }


def enqueue_segment_jobs(
    *,
    context,
    objects: list,
    service_key: str,
    model: str,
    params: dict,
    ref_image=None,
    operator=None,
) -> list:
    """Fan out selected meshes into per-object Tripo segmentation jobs."""
    from mixar.modules.common.generation_params import assemble_payload

    ref_payload = _ref_image_payload(ref_image)
    enqueued: list = []
    for obj in objects:
        if obj.type != 'MESH':
            continue
        try:
            file_bytes, filename = _export_single_object(context, obj)
        except Exception as e:  # noqa: BLE001
            msg = f"Failed to export '{obj.name}': {e}"
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        if len(file_bytes) > MAX_FILE_SIZE_SEGMENT:
            size_mb = len(file_bytes) / (1024 * 1024)
            msg = (
                f"Skipping '{obj.name}': exported file is {size_mb:.1f}MB "
                f"(max {MAX_FILE_SIZE_SEGMENT // (1024 * 1024)}MB)"
            )
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        payload = assemble_payload(
            service_key,
            dict(params),
            {
                "input_name": obj.name,
                "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
                "file_filename": filename,
                **ref_payload,
            },
            model,
        )
        job = enqueue_generation(
            kind="glb",
            feature_key=FEATURE_TRIPO_SEGMENT,
            job_type=service_key or SEGMENT_SERVICE,
            model=model,
            payload=payload,
            label=obj.name,
            fail_message="Mesh segmentation failed",
            on_imported=segment_on_imported,
            scene_flag=SEGMENT_SCENE_FLAG,
            batch_popup_title="Mesh segmentation batch complete",
        )
        if job is not None:
            enqueued.append(job)
    return enqueued


# ---------------------------------------------------------------------------
# Enqueue — smart segmentation (image in)
# ---------------------------------------------------------------------------


def enqueue_smart_segment_job(
    *,
    image,
    service_key: str,
    model: str,
    params: dict,
    operator=None,
):
    """Enqueue one image → segmented-3D job.

    No mesh export: smartsegment does the modelling itself, so the only input
    is the image. The result still imports as a single GLB of parts and goes
    through the same import hook.
    """
    from mixar.modules.common.generation_params import assemble_payload
    from mixar.modules.common.utils.image_utils import compress_for_service

    try:
        image_bytes = compress_for_service(image, "image_to_3d")
    except Exception as e:  # noqa: BLE001
        msg = f"Failed to read image '{image.name}': {e}"
        logger.warning(msg)
        if operator is not None:
            operator.report({'WARNING'}, msg)
        return None

    payload = assemble_payload(
        service_key,
        dict(params),
        {
            "input_name": image.name,
            "image_bytes_b64": _b64.b64encode(image_bytes).decode(),
            "image_filename": f"{image.name}.jpg",
        },
        model,
    )
    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_SMART_SEGMENT,
        job_type=service_key or SMART_SEGMENT_SERVICE,
        model=model,
        payload=payload,
        label=image.name,
        fail_message="Smart segmentation failed",
        on_imported=segment_on_imported,
        scene_flag=SMART_SEGMENT_SCENE_FLAG,
        batch_popup_title="Smart segmentation complete",
    )
