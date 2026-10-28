# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tripo Smart UV helpers — shared by the Moodboard node and the agent.

Smart UV (``tripo_uv``, backend ``/v3/mesh/uv``) re-unwraps a mesh and, with
``bake``, remaps its textures onto the new layout. The result is a NEW object
named ``<source>_uv``; the source is left untouched. Tripo returns the mesh
centred on the origin and normalised to 1 m, so the source's world box is
recorded at submit and the result is fitted back onto it after import
(:mod:`.tripo_uv_placement`).

Tripo refuses meshes above 80,000 equivalent triangles (a quad counts as two)
only after the task starts, so :func:`check_triangle_limit` refuses them before
the export and upload. It counts the base mesh, which is what the export
sends. The backend also returns a UV atlas preview
(``result_data["uv_render_url"]``), which :func:`add_uv_atlas_to_board` drops
on the Moodboard beside the producing node.
"""

import base64 as _b64

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_, rpt_
from mixar.modules.common.job_queue.constants import FEATURE_TRIPO_UV
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation
from ..constants import (
    MAX_FILE_SIZE_TRIPO_UV,
    TRIPO_UV_MAX_TRIANGLES,
    TRIPO_UV_MODEL,
    TRIPO_UV_RESULT_SUFFIX,
    TRIPO_UV_SERVICE,
)
from .retopology_enqueue import _export_single_object
from .tripo_uv_placement import place_over_source, source_world_bounds

logger = get_logger(__name__)

# Gap between the producing node's right edge and the atlas card, canvas units.
_ATLAS_GAP = 40.0


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def equivalent_triangles(objects) -> int:
    """Triangles Tripo counts for *objects*: an n-gon is n - 2 triangles.

    Reads each object's base mesh (``obj.data``, modifiers NOT applied), which
    is what the GLB export sends: ``model_io`` exports without ``export_apply``.
    """
    import numpy as np

    total = 0
    for obj in objects:
        if getattr(obj, "type", None) != 'MESH':
            continue
        mesh = obj.data
        count = len(mesh.polygons)
        if not count:
            continue
        sizes = np.empty(count, dtype=np.int32)
        mesh.polygons.foreach_get("loop_total", sizes)
        total += int(sizes.sum()) - 2 * count
    return total


def check_triangle_limit(objects) -> None:
    """Raise ``ValueError`` when *objects* exceed Tripo's Smart UV limit."""
    triangles = equivalent_triangles(objects)
    if triangles > TRIPO_UV_MAX_TRIANGLES:
        raise ValueError(rpt_(
            "Smart UV takes at most {limit:,} triangles; this mesh has {count:,}. "
            "Retopologize it first to lower the polycount."
        ).format(limit=TRIPO_UV_MAX_TRIANGLES, count=triangles))


def check_export_size(file_bytes: bytes) -> None:
    """Raise ``ValueError`` when the exported GLB is over the upload cap."""
    if len(file_bytes) > MAX_FILE_SIZE_TRIPO_UV:
        raise ValueError(rpt_(
            "The exported mesh is {size_mb:.1f} MB; Smart UV accepts up to {max_mb} MB."
        ).format(size_mb=len(file_bytes) / (1024 * 1024),
                 max_mb=MAX_FILE_SIZE_TRIPO_UV // (1024 * 1024)))


# ---------------------------------------------------------------------------
# Result handling
# ---------------------------------------------------------------------------


def finalize_uv_import(object_names: str, source_name: str, bake: bool,
                       source_bounds=None) -> str:
    """Fit the import over its source, rename it ``<source>_uv``, return its names.

    Tripo returns the mesh centred on the origin and normalised to 1 m, so the
    import is scaled and moved onto *source_bounds*, the source's world box
    recorded at submit (:func:`~.tripo_uv_placement.place_over_source`; ``None``
    leaves it where it landed). Placement runs first, while *object_names*
    still name the import. A baked result carries a textured material, rebuilt
    as a paint fill layer like the other textured Tripo imports.
    """
    from mixar.modules.common.job_queue.core.model_io import rename_imported_object

    if source_bounds is not None:
        place_over_source(object_names, source_bounds)
    final = None
    try:
        final = rename_imported_object(
            object_names, f"{source_name}{TRIPO_UV_RESULT_SUFFIX}")
    except Exception as e:  # noqa: BLE001
        logger.warning("[SmartUV] rename failed: %s", e)
    if final and bake:
        try:
            from mixar.modules.moodboard.core.imported_pbr_layers import (
                convert_imported_material_to_paint_layers,
            )
            convert_imported_material_to_paint_layers(final)
        except Exception as e:  # noqa: BLE001
            logger.warning("[SmartUV] material finalize failed: %s", e)
    return final or object_names


def add_uv_atlas_to_board(job, scene_name: str, source_name: str, node=None) -> None:
    """Download the UV atlas preview onto the Moodboard, beside *node* if given.

    Best effort: the atlas is auxiliary, so a missing URL or failed download
    only logs. The download runs off the main thread.
    """
    url = (getattr(job, "result_data", None) or {}).get("uv_render_url")
    if not url:
        return
    from mixar.modules.common.job_queue.core.image_results import (
        download_images_to_moodboard,
    )

    anchor = None
    if node is not None:
        anchor = (float(node.position_x) + float(node.width) + _ATLAS_GAP,
                  float(node.position_y))

    def _place(names: str) -> None:
        if anchor is None:
            return
        import bpy

        scene = bpy.data.scenes.get(scene_name)
        wanted = {name.strip() for name in names.split(",") if name.strip()}
        for item in getattr(scene, "mixie_moodboard_images", ()):
            if item.image is not None and item.image.name in wanted:
                item.position_x, item.position_y = anchor

    download_images_to_moodboard(
        urls=[url],
        name_prefix="uv_atlas",
        prompt="",
        job_id=job.id,
        on_added=_place,
        on_done=lambda _names: None,
        on_error=lambda error: logger.warning("[SmartUV] atlas download failed: %s", error),
        base_name=f"{source_name}_uv_atlas",
        scene_name=scene_name,
    )


# ---------------------------------------------------------------------------
# Agent enqueue
# ---------------------------------------------------------------------------


def enqueue_tripo_uv_job(*, context, obj, bake: bool = True, model: str = ""):
    """Export *obj* alone and queue a Smart UV job for it.

    Returns the job, or ``None`` when the queue rejected a duplicate. Raises
    ``ValueError`` with a user-facing reason when the mesh is refused.
    """
    from mixar.modules.common.generation_params import (
        assemble_payload, resolve_model_slug,
    )

    check_triangle_limit([obj])
    # Recorded now: the result comes back normalised and is fitted onto it.
    source_bounds = source_world_bounds([obj])
    file_bytes, filename = _export_single_object(context, obj)
    check_export_size(file_bytes)

    model = model or resolve_model_slug(TRIPO_UV_SERVICE, "", TRIPO_UV_MODEL)
    payload = assemble_payload(
        TRIPO_UV_SERVICE,
        {"bake": bool(bake)},
        {
            "input_name": obj.name,
            "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
            "file_filename": filename,
        },
        model,
    )
    source_name = obj.name
    scene_name = context.scene.name

    def _on_imported(job, object_names: str):
        result = finalize_uv_import(
            object_names, source_name, bake, source_bounds=source_bounds)
        add_uv_atlas_to_board(job, scene_name, source_name)
        return result  # see AsyncGLBJob.on_imported

    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_TRIPO_UV,
        job_type=TRIPO_UV_SERVICE,
        model=model,
        payload=payload,
        label=source_name,
        fail_message=n_("Smart UV failed"),
        on_imported=_on_imported,
    )
