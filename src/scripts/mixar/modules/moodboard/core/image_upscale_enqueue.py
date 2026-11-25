# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Submit an Image Upscale job — the ONE enqueue path every surface shares.

The canvas node (``IMAGE_UPSCALE`` in ``node_execution.run_action_node``) and
the agent operator (``mixie.agent_image_upscale``) find their source still
differently (the connected input socket vs. a datablock name) but must stage
and submit it identically: the full-resolution file streamed through
``POST /job-queue/uploads/image?purpose=image_upscale`` (``StagedImageJob``),
landing in the payload as the single ``image_s3_key`` the backend contract
reads, plus the catalog params. The result is a NEW Moodboard image; the
source is never modified.
"""

from __future__ import annotations

import os
import re

from mixar.modules.common.i18n import iface_, n_, rpt_
from mixar.modules.common.job_queue.constants import FEATURE_IMAGE_UPSCALE

from .image_upscale_catalog import (
    CAPABILITY_KEY,
    FACTOR_PARAM,
    IMAGE_KEY_FIELD,
    SERVICE_KEY,
    get_image_upscale_limits,
    image_upscale_source_error,
)

#: Formats the backend uploader accepts, by magic bytes (its own sniff list).
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
    (b"II*\x00", "tif", "image/tiff"),
    (b"MM\x00*", "tif", "image/tiff"),
    (b"BM", "bmp", "image/bmp"),
)
_FILE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff",
    ".tiff": "image/tiff", ".gif": "image/gif",
}


def resolve_image_upscale_target(mode: str, model_choice: str) -> tuple[str, str]:
    """Resolve (service_key, model_slug) for a node/agent selection, or raise."""
    from mixar.modules.common.generation_params import (
        resolve_model_slug,
        resolve_service_key,
    )

    service_key = resolve_service_key(CAPABILITY_KEY, mode)
    if not service_key:
        raise ValueError(rpt_("Image Upscale is not available right now"))
    if service_key != SERVICE_KEY:
        raise ValueError(rpt_("The selected upscale service needs a newer app version"))
    model = resolve_model_slug(service_key, model_choice)
    if not model:
        raise ValueError(rpt_("No enabled image upscale model is available"))
    return service_key, model


def sniff_image(data: bytes):
    """``(extension, mime_type)`` the backend will accept for these bytes, or None."""
    header = bytes(data[:16])
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp", "image/webp"
    for magic, ext, mime in _SIGNATURES:
        if header.startswith(magic):
            return ext, mime
    return None


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(name)[0]).strip("._")
    return stem[:64] or "image"


def build_source_input(image, limits: dict) -> dict:
    """The upload description for one Blender image, cheapest path first.

    A packed image uploads its original file bytes (a memory copy); an
    unmodified image on disk streams from its file on the upload thread; only
    a generated, edited or non-uploadable format (EXR, HDR, ...) is re-encoded
    as a lossless PNG here.
    """
    import bpy

    stem = _safe_stem(getattr(image, "name", "") or "image")
    source = None
    packed = getattr(image, "packed_file", None)
    if packed is not None and not image.is_dirty:
        data = bytes(packed.data or b"")
        kind = sniff_image(data)
        if kind:
            source = {"filename": f"{stem}.{kind[0]}", "mime_type": kind[1], "bytes": data}
    if source is None and image.source == 'FILE' and not image.is_dirty and packed is None:
        path = bpy.path.abspath(image.filepath_raw or image.filepath or "")
        ext = os.path.splitext(path)[1].lower()
        if ext in _FILE_TYPES and os.path.isfile(path):
            source = {
                "filename": f"{stem}{ext}",
                "mime_type": _FILE_TYPES[ext],
                "filepath": path,
                "file_size_bytes": os.path.getsize(path),
            }
    if source is None:
        from mixar.modules.common.utils.image_utils import image_to_png_bytes

        data = image_to_png_bytes(image)
        source = {"filename": f"{stem}.png", "mime_type": "image/png", "bytes": data}

    size = len(source["bytes"]) if "bytes" in source else source["file_size_bytes"]
    if size > limits["max_bytes"]:
        raise ValueError(rpt_(
            "The image file is {size} MB; Image Upscale takes files up to {limit} MB"
        ).format(size=f"{size / (1024 * 1024):.1f}",
                 limit=limits["max_bytes"] // (1024 * 1024)))
    return source


def prepare_image_upscale_source(image, params: dict) -> tuple[dict, dict]:
    """Return ``(source_input, limits)`` for one still, or raise ``ValueError``."""
    limits = get_image_upscale_limits(SERVICE_KEY)
    if limits is None:
        raise ValueError(rpt_("Image upscale catalog config is incomplete"))
    if image is None:
        raise ValueError(rpt_("Choose one image to upscale"))
    width, height = (int(v) for v in tuple(image.size)[:2])
    error = image_upscale_source_error(width, height, (params or {}).get(FACTOR_PARAM), limits)
    if error:
        raise ValueError(error)
    return build_source_input(image, limits), limits


def enqueue_image_upscale(
    *,
    service_key: str,
    model: str,
    params: dict,
    source_input: dict,
    limits: dict,
    source_name: str,
    graph_node_id: str = "",
    on_imported=None,
):
    """Stage the source and submit through the unified queue (image kind)."""
    from mixar.modules.common.job_queue import enqueue_generation

    tag = f":{graph_node_id[:8]}" if graph_node_id else ""
    name = str(source_name or "image")
    return enqueue_generation(
        kind="image",
        feature_key=FEATURE_IMAGE_UPSCALE,
        job_type=service_key,
        model=model,
        payload={"params": dict(params or {})},
        label=f"ImageUpscale{tag}: {name[:40]}",
        display_label=iface_("Upscale {name}").format(name=name[:32]),
        origin_capability_key=CAPABILITY_KEY,
        graph_node_id=graph_node_id,
        fail_message=n_("Image upscale failed"),
        name_prefix="upscale",
        base_name=f"{os.path.splitext(name)[0][:48]}_upscaled",
        undo_message="Upscale Image",
        source_image=source_input,
        upload_purpose=limits["upload_purpose"],
        source_key_field=IMAGE_KEY_FIELD,
        on_imported=on_imported,
    )


def run_image_upscale_node(context, node):
    """Node-graph runner for ``IMAGE_UPSCALE`` (called by ``run_action_node``)."""
    from .media_utils import is_still_item
    from .node_execution import _result_hook
    from .node_graph import input_media_items
    from .node_job_bridge import ensure_graph_listener
    from .node_schema import collect_node_params, node_model_slug, node_service_key

    service_key, model = resolve_image_upscale_target(
        node_service_key(node), node_model_slug(node)
    )
    stills = [
        item for item in input_media_items(context.scene, node) if is_still_item(item)
    ]
    if not stills:
        raise ValueError(rpt_("Connect one image to the Upscale Image node"))
    image = stills[0].image
    params = collect_node_params(node)
    source_input, limits = prepare_image_upscale_source(image, params)
    ensure_graph_listener(FEATURE_IMAGE_UPSCALE)
    job = enqueue_image_upscale(
        service_key=service_key,
        model=model,
        params=params,
        source_input=source_input,
        limits=limits,
        source_name=image.name,
        graph_node_id=node.node_id,
        on_imported=_result_hook(context.scene.name, node.node_id, 'IMAGE'),
    )
    return job, params
