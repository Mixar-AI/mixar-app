# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Blender's built-in Gaussian splats: lookup and import.

Blender 5.3 imports a 3DGS PLY (``wm.ply_import``) or an SPZ
(``wm.spz_import``) as a ``POINTCLOUD`` object whose data ``type`` is
``GAUSSIAN_SPLAT``, and EEVEE, Cycles and Workbench
render it from the active camera like any other object. So a splat is an
ordinary object: hide, select, delete and F12 need no Mixar code.

Must run on the main thread (it calls ``bpy.ops``).
"""

import bpy

from mixar.modules.common.i18n import rpt_

SPLAT_TYPE = "GAUSSIAN_SPLAT"


def is_splat(obj) -> bool:
    """True for a built-in Gaussian splat object."""
    try:
        return obj.type == "POINTCLOUD" and getattr(obj.data, "type", "") == SPLAT_TYPE
    except (AttributeError, ReferenceError):
        return False


def splat_objects(scene) -> list:
    """Every Gaussian splat object linked into ``scene``."""
    if scene is None:
        return []
    return [obj for obj in scene.objects if is_splat(obj)]


def scene_has_splats(scene) -> bool:
    """True when ``scene`` holds at least one splat that renders."""
    return any(not obj.hide_render for obj in splat_objects(scene))


def import_splat_ply(ply_path: str) -> None:
    """Import a 3DGS PLY as a built-in splat.

    The importer recognises a vertex-only PLY carrying ``f_dc_*``,
    ``opacity``, ``scale_*`` and ``rot_*`` and builds a splat point cloud; any
    other PLY becomes a mesh, which callers report as a non-splat file.
    """
    bpy.ops.wm.ply_import(filepath=ply_path)


def import_splat_spz(spz_path: str) -> None:
    """Import an SPZ with Blender's native importer (``io_spz``).

    The importer lands the SPZ spec's RUB frame Z-up; callers add the object
    rotation their source needs (World Labs Marble files: 180 deg X).
    Raises ``ValueError`` when this build has no SPZ importer.
    """
    if not getattr(bpy.app.build_options, "io_spz", False):
        raise ValueError(rpt_("This build has no SPZ importer"))
    bpy.ops.wm.spz_import(filepath=spz_path)
