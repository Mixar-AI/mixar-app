# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Complex enqueue helpers for moodboard generation features.

Builds payloads and calls ``enqueue_generation()`` for:
- Image-to-3D Pro (with multi-view support)
- Scene Gen HP (per-image fan-out with chain_id)
- Scene Gen LP (per-object retopo fan-out with chain_id)
"""

import base64 as _b64
import os
import re
from typing import Callable, List, Optional, Tuple

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import (
    FEATURE_IMAGE_TO_3D_PRO,
    FEATURE_SCENE_GEN_HP,
    FEATURE_SCENE_GEN_LP,
)
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation
from mixar.modules.common.job_queue.core.job import Job
from mixar.modules.common.utils.image_utils import compress_image_for_upload
from mixar.modules.hunyuan.constants import (
    DEFAULT_FACE_COUNT,
    MAX_FILE_SIZE_TOPOLOGY,
    # Service key == job_queue job_type: a wire contract, not catalog data.
    RETOPOLOGY_HUNYUAN_SERVICE as RETOPOLOGY_JOB_TYPE,
    RETOPOLOGY_HUNYUAN_MODEL,
)
from mixar.modules.moodboard.constants import CHARACTER_PARTS_CAPABILITY_KEY

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


# Only these trailing extensions are stripped from a label — a bare "." in a
# name (e.g. "R2.D2", "v1.5") must NOT be treated as a file extension.
_STRIPPABLE_EXTS = (
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    ".glb", ".gltf", ".fbx", ".obj", ".usd", ".usdz",
)


def _sanitize_label(label: str) -> str:
    base = label or ""
    lower = base.lower()
    for ext in _STRIPPABLE_EXTS:
        if lower.endswith(ext):
            base = base[: -len(ext)]
            break
    base = re.sub(r'[^a-zA-Z0-9_]', '_', base)
    base = re.sub(r'_+', '_', base).strip('_') or "object"
    return base


def _slug_from_prompt(prompt: str, max_words: int = 6, max_len: int = 40) -> str:
    """Concise underscore slug from a prompt.

    Mirrors the backend imagegen naming (`_derive_image_name_from_prompt`)
    so a mesh generated from a prompt reads like its image-gen twin:
    'A red sports car on a road' -> 'red_sports_car_on_a_road'. Returns ''
    when the prompt has no usable words.
    """
    if not prompt:
        return ""
    words = re.findall(r"[a-z0-9]+", prompt.lower())
    # Drop a single leading article so 'a wizard' -> 'wizard'.
    if words and words[0] in ("a", "an", "the"):
        words = words[1:]
    name = ""
    for word in words[:max_words]:
        candidate = f"{name}_{word}" if name else word
        if len(candidate) > max_len:
            break
        name = candidate
    return name


def derive_model_name(image=None, prompt: str = "", explicit: str = "") -> str:
    """Resolve the object name for a generated 3D mesh.

    Priority: an explicit (agent-supplied) name, else the input image's
    name, else a semantic slug derived from the prompt. Returns '' when
    nothing usable is available — the caller's on_imported hook then falls
    back to the queue label.
    """
    if explicit and explicit.strip():
        return _sanitize_label(explicit)
    if image is not None and getattr(image, "name", ""):
        return _sanitize_label(image.name)
    slug = _slug_from_prompt(prompt or "")
    return _sanitize_label(slug) if slug else ""


def model_front_zrot(model_slug: str) -> float:
    """Z rotation (radians) that makes an engine's import face world -Y.

    Front-facing convention differs per engine: Tripo imports facing +X,
    while every other supported engine (Hunyuan, Trellis, Rodin) already
    imports facing -Y. Rotating +X onto -Y about world Z is -90 degrees.

    Assumes Rodin (and any future engine) faces -Y — only Tripo, the one
    known-offset engine, is corrected. Extend the check if another engine
    turns out to import on a different axis.
    """
    from math import radians

    if "tripo" in (model_slug or "").lower():
        return radians(-90)
    return 0.0


def make_model_rename_on_imported(
    mesh_name: str, front_zrot: float = 0.0,
) -> Callable:
    """Build an on_imported hook that renames + normalizes a Model Gen import.

    Handles both provider mesh shapes (single mesh for Hunyuan/Tripo, an
    Empty-parented mesh for Trellis) via ``rename_generated_model``. Falls
    back to the queue label when *mesh_name* is empty (e.g. an image whose
    name sanitized away). *front_zrot* (see :func:`model_front_zrot`) rotates
    the result about world Z so every engine's front faces -Y.
    """

    def _hook(job, object_names: str) -> None:
        target = mesh_name or _sanitize_label(job.label)
        try:
            from mixar.modules.common.job_queue.core.model_io import (
                rename_generated_model,
            )
            from mixar.modules.moodboard.core.imported_pbr_layers import (
                convert_imported_material_to_paint_layers,
            )
            final = rename_generated_model(
                object_names, target, front_zrot=front_zrot)
            convert_imported_material_to_paint_layers(final or target)
        except Exception as e:
            logger.warning(
                "[ModelGen] post-import processing failed: %s", e)

    return _hook


def make_texture_reimport_on_imported(mesh_name: str = "") -> Callable:
    """on_imported hook for re-texture imports (PBR Generation / Texture Edit).

    Renames the imported mesh to *mesh_name* (else the queue label, i.e. the
    source mesh name) and runs the material finalize (rename material + texture
    images, split any packed metallicRoughness map), but DELIBERATELY does not
    normalize placement or orientation: the geometry is the user's own mesh
    re-textured and must keep its pose.
    """

    def _hook(job, object_names: str) -> None:
        target = mesh_name or _sanitize_label(job.label)
        try:
            from mixar.modules.common.job_queue.core.model_io import (
                rename_imported_object,
            )
            from mixar.modules.moodboard.core.imported_pbr_layers import (
                convert_imported_material_to_paint_layers,
            )
            final = rename_imported_object(object_names, target)
            convert_imported_material_to_paint_layers(final or target)
        except Exception as e:
            logger.warning(
                "[TextureGen] post-import processing failed: %s", e)

    return _hook


def _make_hp_on_imported(chain_id: str) -> Callable:
    """Create an on_imported hook that renames + stamps chain_id."""

    def _hook(job, object_names: str) -> None:
        target = _sanitize_label(job.label) + "_high"
        try:
            from mixar.modules.common.job_queue.core.model_io import (
                post_import_rename_and_setup,
            )
            post_import_rename_and_setup(object_names, target)
        except Exception as e:
            logger.warning("[SceneGenHP] post_import_rename_and_setup failed: %s", e)

        if chain_id:
            names = [n.strip() for n in object_names.split(",") if n.strip()]
            for name in names:
                obj = bpy.data.objects.get(name)
                if obj is None:
                    obj = bpy.data.objects.get(target)
                if obj is not None:
                    obj["mixar_chain_id"] = chain_id

    return _hook


def _make_lp_on_imported(chain_id: str) -> Callable:
    """Create an on_imported hook that handles retopo mesh + stamps chain_id."""

    def _hook(job, object_names: str) -> None:
        names = [n.strip() for n in object_names.split(",") if n.strip()]
        has_low_suffix = any("_low" in n for n in names)

        if has_low_suffix:
            logger.info("[SceneGenLP] Post-processed mesh detected, skipping client-side cleanup")
        else:
            logger.warning("[SceneGenLP] Unprocessed mesh detected, applying client-side fallback")
            name = os.path.splitext(job.label)[0] if "." in job.label else job.label
            for suffix in ("_high", "_High", "_HIGH"):
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break
            target = name + "_low"
            try:
                from mixar.modules.common.job_queue.core.model_io import (
                    post_import_rename_and_setup,
                )
                post_import_rename_and_setup(object_names, target, smart_uv=True)
            except Exception as e:
                logger.warning("[SceneGenLP] post_import_rename_and_setup failed: %s", e)

        if chain_id:
            base = _sanitize_label(job.label)
            for suffix in ("_high", "_High", "_HIGH"):
                if base.endswith(suffix):
                    base = base[:-len(suffix)]
                    break
            possible_names = list(names) + [base + "_low"]
            for name in possible_names:
                obj = bpy.data.objects.get(name)
                if obj is not None:
                    obj["mixar_chain_id"] = chain_id

    return _hook


# ---------------------------------------------------------------------------
# Pro shared param snapshot
# ---------------------------------------------------------------------------


def snapshot_shared_params(pro) -> dict:
    """Capture the Pro UI's shared (non-image) params into a dict."""
    return {
        "generate_type": pro.generate_type,
        "model_version": pro.model_version,
        "enable_pbr": pro.enable_pbr,
        "face_count": (
            pro.face_count if pro.face_count != DEFAULT_FACE_COUNT else None
        ),
        "polygon_type": (
            pro.polygon_type if pro.generate_type == 'LowPoly' else None
        ),
        "prompt": pro.prompt.strip() if pro.prompt else None,
    }


# ---------------------------------------------------------------------------
# Image-to-3D Pro
# ---------------------------------------------------------------------------


def _build_pro_payload(
    image_bytes: bytes,
    shared: dict,
    multi_views: Optional[List[Tuple[bytes, str, str]]] = None,
    turnaround: Optional[dict] = None,
) -> tuple:
    """Build (payload, model_key) for a Pro job.

    Catalog-schema params only — the backend HunyuanAdapter maps them to
    Tencent SDK keys and derives the Model version from the catalog row
    (selected here via the model_key slug).

    *turnaround* is a pre-built S3-key fragment from
    ``moodboard.core.turnaround_views.build_multi_view_payload`` — crops that
    the detect-views endpoint already staged in S3. When present it REPLACES
    the inline image / multi-view bytes entirely: the keys are forwarded
    verbatim instead of the pixels being uploaded a second time.
    """
    params = {
        "generate_type": shared.get("generate_type", "Normal"),
        "enable_pbr": bool(shared.get("enable_pbr", False)),
    }
    if shared.get("prompt"):
        params["prompt"] = shared["prompt"]
    if shared.get("face_count") is not None:
        params["face_count"] = shared["face_count"]
    if shared.get("polygon_type"):
        params["polygon_type"] = shared["polygon_type"]

    payload = {"params": params}
    if turnaround:
        # Already-staged crops: image_s3_key + multi_view_images[{s3_key,...}]
        payload.update(turnaround)
    else:
        if image_bytes:
            payload["image_bytes_b64"] = _b64.b64encode(image_bytes).decode()
            payload["image_filename"] = "image.png"
        if multi_views:
            payload["multi_view_images"] = [
                {
                    "image_bytes_b64": _b64.b64encode(img_bytes).decode(),
                    "filename": fname,
                    "view_type": vtype,
                }
                for img_bytes, fname, vtype in multi_views
            ]

    version = shared.get("model_version", "3.0")
    model_key = "hunyuan_pro_v3.1" if version == "3.1" else "hunyuan_pro_v3"
    return payload, model_key


def enqueue_pro_job(
    *,
    image: Optional["bpy.types.Image"],
    shared: dict,
    label: str,
    multi_views: Optional[List[Tuple[bytes, str, str]]] = None,
    turnaround: Optional[dict] = None,
    mesh_name: str = "",
) -> Optional[Job]:
    """Build an Image-to-3D Pro job and submit it to the queue.

    Pass *turnaround* (see :func:`_build_pro_payload`) to submit already-staged
    turnaround crops by S3 key; *image* is then only used for the queue label
    and is never re-uploaded.

    The imported mesh is named from *mesh_name* (agent-supplied) when given,
    else derived from the input *image* name, else from the prompt — see
    :func:`derive_model_name`. Pro always returns a single mesh, so it takes
    the standalone-mesh naming + origin/world-origin normalization path.
    """
    image_bytes = b""
    if image is not None and not turnaround:
        image_bytes = compress_image_for_upload(image)

    payload, model_key = _build_pro_payload(
        image_bytes, shared, multi_views, turnaround)

    resolved_name = derive_model_name(
        image, shared.get("prompt") or "", explicit=mesh_name)

    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_IMAGE_TO_3D_PRO,
        job_type="image_to_3d",
        model=model_key,
        payload=payload,
        label=label,
        fail_message="Image to 3D failed",
        on_imported=make_model_rename_on_imported(
            resolved_name, model_front_zrot(model_key)),
        scene_flag="mixie_image_to_3d_is_generating",
        batch_popup_title="Image to 3D batch complete",
    )


# ---------------------------------------------------------------------------
# Scene Gen HP
# ---------------------------------------------------------------------------


def enqueue_scene_gen_hp_jobs(
    *,
    images_with_chain_ids: List[Tuple["bpy.types.Image", str]],
    shared_params: dict,
    operator=None,
) -> list:
    """Submit one SceneGenHP job per (image, chain_id) tuple."""
    enqueued: list = []

    for image, chain_id in images_with_chain_ids:
        try:
            image_bytes = compress_image_for_upload(image)
        except Exception as e:
            msg = f"Failed to compress '{image.name}': {e}"
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        face_count = shared_params.get("face_count")
        if face_count == DEFAULT_FACE_COUNT:
            face_count = None

        params = {
            "generate_type": shared_params.get("generate_type", "Normal"),
            "enable_pbr": bool(shared_params.get("enable_pbr", False)),
        }
        if face_count is not None:
            params["face_count"] = face_count
        polygon_type = (
            shared_params.get("polygon_type")
            if shared_params.get("generate_type") == "LowPoly"
            else None
        )
        if polygon_type:
            params["polygon_type"] = polygon_type

        payload = {"params": params}
        if image_bytes:
            payload["image_bytes_b64"] = _b64.b64encode(image_bytes).decode()
            payload["image_filename"] = "image.png"

        version = shared_params.get("model_version", "3.0")
        model_key = "hunyuan_pro_v3.1" if version == "3.1" else "hunyuan_pro_v3"

        job = enqueue_generation(
            kind="glb",
            feature_key=FEATURE_SCENE_GEN_HP,
            job_type="image_to_3d",
            model=model_key,
            payload=payload,
            label=image.name,
            origin_capability_key=CHARACTER_PARTS_CAPABILITY_KEY,
            fail_message="Scene generation failed",
            on_imported=_make_hp_on_imported(chain_id),
            scene_flag="mixie_scene_gen_hp_is_generating",
            batch_popup_title="Scene Gen HP batch complete",
        )
        if job is not None:
            enqueued.append(job)

    return enqueued


# ---------------------------------------------------------------------------
# Scene Gen LP
# ---------------------------------------------------------------------------


def enqueue_scene_gen_lp_jobs(
    *,
    context,
    objects_with_chain_ids: list,
    shared_params: dict,
    operator=None,
) -> list:
    """Fan out selected mesh objects into per-object LP queue jobs."""
    from mixar.modules.hunyuan.core.retopology_enqueue import _export_single_object

    enqueued: list = []

    # Scene Gen LP pins Hunyuan Topology deliberately: `shared_params` carries
    # polygon_type / face_level / post_process, which are that engine's knobs.
    # Taking the `retopology` service default instead would hand those params
    # to whichever engine happens to be default — a silent engine swap, and a
    # submit-validation failure if that engine's schema doesn't define them.
    # Left as a literal on purpose; see the de-hardcoding review.
    model = RETOPOLOGY_HUNYUAN_MODEL

    for obj, chain_id in objects_with_chain_ids:
        if obj.type != 'MESH':
            continue
        try:
            file_bytes, filename = _export_single_object(context, obj)
        except Exception as e:
            msg = f"Failed to export '{obj.name}': {e}"
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        if len(file_bytes) > MAX_FILE_SIZE_TOPOLOGY:
            size_mb = len(file_bytes) / (1024 * 1024)
            msg = (
                f"Skipping '{obj.name}': exported file is {size_mb:.1f}MB "
                f"(max {MAX_FILE_SIZE_TOPOLOGY // (1024 * 1024)}MB)"
            )
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        params = {"post_process": bool(shared_params.get("post_process", True))}
        if shared_params.get("polygon_type"):
            params["polygon_type"] = shared_params["polygon_type"]
        if shared_params.get("face_level"):
            params["face_level"] = shared_params["face_level"]

        payload = {
            "params": params,
            "input_name": obj.name,
            "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
            "file_filename": filename,
        }

        job = enqueue_generation(
            kind="glb",
            feature_key=FEATURE_SCENE_GEN_LP,
            job_type=RETOPOLOGY_JOB_TYPE,
            model=model,
            payload=payload,
            label=obj.name,
            origin_capability_key=CHARACTER_PARTS_CAPABILITY_KEY,
            fail_message="Scene generation failed",
            on_imported=_make_lp_on_imported(chain_id),
            scene_flag="mixie_scene_gen_lp_is_generating",
            batch_popup_title="Scene Gen LP batch complete",
        )
        if job is not None:
            enqueued.append(job)

    return enqueued
