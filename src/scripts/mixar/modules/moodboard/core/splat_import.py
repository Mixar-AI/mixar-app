# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Import a local Gaussian-splat file (.spz or 3DGS .ply) into the scene.

Shares the World Labs splat pipeline (``world_labs_importer``): SPZ is
converted to a 3DGS PLY in pure Python (``world_labs_spz.spz_to_ply``), the
PLY is imported through the bundled KIRI 3DGS Render addon (real-time splat
rendering via its geometry-nodes proxy), oriented into Blender's Z-up frame
and optionally grounded at the origin — exactly what the Director flow needs
to place cameras and characters inside a splat environment.

Must run on the main thread (it calls ``bpy.ops``).
"""

import os
import tempfile

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.world_labs_importer import (
    _enable_splat_render,
    _ensure_object_mode,
    _finalize_visibility,
    _frame_objects,
    _import_splat_ply,
    _import_tracked,
    _move_to_collection,
    _orient_splats,
    _recenter_world_to_ground,
)

logger = get_logger(__name__)

SPLAT_EXTENSIONS = (".spz", ".ply")


def import_splat_file(filepath: str, name: str = "", recenter: bool = True) -> list:
    """Import one ``.spz`` / 3DGS ``.ply`` file as a splat environment.

    Parameters
    ----------
    filepath : str
        Path to the splat file on disk.
    name : str, optional
        Collection name stem; defaults to the file name.
    recenter : bool
        Ground the splat (floor -> z=0, footprint centre -> origin) the same
        way generated World Labs worlds are grounded.

    Returns
    -------
    list[str]
        Names of the imported objects (splat mesh + KIRI proxy).

    Raises
    ------
    ValueError
        On unsupported extension, unreadable file, or malformed SPZ.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in SPLAT_EXTENSIONS:
        raise ValueError(f"Unsupported splat file type '{ext}' (expected .spz or .ply)")
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")

    stem = name or os.path.splitext(os.path.basename(filepath))[0] or "Splat"

    ply_path = filepath
    temp_dir = ""
    if ext == ".spz":
        from mixar.modules.moodboard.core.world_labs_spz import spz_to_ply

        with open(filepath, "rb") as f:
            spz_bytes = f.read()
        ply_bytes = spz_to_ply(spz_bytes)  # raises SpzError (a ValueError)
        # KIRI names the imported object after the PLY file, so the temp PLY
        # keeps the source stem (a mkstemp name leaks gibberish object names).
        temp_dir = tempfile.mkdtemp(prefix="splat_import_")
        ply_path = os.path.join(temp_dir, f"{stem}.ply")
        with open(ply_path, "wb") as f:
            f.write(ply_bytes)

    try:
        _ensure_object_mode()
        collection = _new_splat_collection(stem)

        splat_objs = _import_tracked(lambda: _import_splat_ply(ply_path))
        if not splat_objs:
            raise ValueError(f"No objects imported from {os.path.basename(filepath)}")
        # Converted .spz (our decoder negates Y/Z → effectively y-up) takes the
        # World Labs +90 X; a raw 3DGS .ply keeps the vendor y-DOWN frame and
        # needs the opposite rotation (KIRI's "Rotate for Blender Axes").
        from mixar.modules.moodboard.core.world_labs_importer import (
            RAW_PLY_ROT_EULER_DEG,
        )
        _orient_splats(
            splat_objs,
            RAW_PLY_ROT_EULER_DEG if ext == ".ply" else None,
        )
        if recenter:
            _recenter_world_to_ground(splat_objs, [])

        # Build the KIRI render proxy on the splat in its FINAL pose (same
        # ordering rule as the World Labs import).
        proxy_objs = _enable_splat_render(splat_objs)

        new_objects = splat_objs + proxy_objs
        _move_to_collection(new_objects, collection)
        _finalize_visibility(splat_objs, [], proxy_objs)
        _frame_objects(proxy_objs or splat_objs)

        logger.info(
            "[SplatImport] imported '%s' into '%s' (%d splat, %d proxy)",
            os.path.basename(filepath), collection.name,
            len(splat_objs), len(proxy_objs),
        )
        return [o.name for o in new_objects]
    finally:
        if temp_dir:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)


def _new_splat_collection(name: str) -> bpy.types.Collection:
    base = f"Splat_{name}"[:60]
    collection = bpy.data.collections.new(base)
    bpy.context.scene.collection.children.link(collection)
    return collection
