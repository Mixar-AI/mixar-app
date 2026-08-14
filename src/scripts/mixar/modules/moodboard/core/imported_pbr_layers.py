# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Convert an imported glTF material into a Mixar paint layer setup.

Takes a freshly-imported textured mesh (model gen / PBR gen / retopology), pulls
its PBR maps out of the plain Principled material (splitting a packed
metallicRoughness into separate images), then rebuilds that material AS the
Mixar paint layer system with a single fill layer holding those maps in their
channel slots — the same end state as the lookdev360 downloaded-texture path,
but sourced from imported-GLB textures.

Safety: ``finalize_generated_material`` runs first and leaves a clean PLAIN
material (renamed, packed map split) as a fallback. Only when maps are present
do we rebuild it as a paint layer; any failure there logs and keeps the plain
material. Meshes without textures are left plain (deliberate).
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def convert_imported_material_to_paint_layers(mesh_name):
    """Rebuild *mesh_name*'s textured material as a Mixar paint fill layer.

    Returns True when converted to a paint layer, False when left as a plain
    material (no textures present, or the paint build was unavailable/failed —
    the clean plain material from finalize remains).
    """
    obj = bpy.data.objects.get(mesh_name) if mesh_name else None
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return False

    # Extract the PBR maps (also renames material/images + splits packed MR),
    # leaving a clean PLAIN material as a safe fallback.
    from mixar.modules.common.job_queue.core.model_io import (
        finalize_generated_material,
    )
    images = finalize_generated_material(mesh_name)
    if not images or not any(images.values()):
        # Geometry-only / untextured — leave the plain material (user choice).
        return False

    try:
        return _build_paint_material(obj, images)
    except Exception as e:
        logger.warning(
            "[ImportedPBR] Paint-layer conversion failed for '%s': %s "
            "(left as plain material)", mesh_name, e)
        return False


def _build_paint_material(obj, images):
    """Rebuild *obj*'s active material as the paint system + one PBR fill layer."""
    # add_new_layer / get_active_mpaint_node read the ACTIVE object, so the
    # imported mesh must be the active/selected object here.
    view_layer = bpy.context.view_layer
    try:
        for o in list(view_layer.objects):
            if o.select_get():
                o.select_set(False)
    except Exception:
        pass
    obj.select_set(True)
    view_layer.objects.active = obj

    # Ensure a material slot exists for create_material to convert in place.
    if not obj.data.materials:
        mat = bpy.data.materials.new(name=obj.name)
        mat.use_nodes = True
        obj.data.materials.append(mat)

    # Build the MPaint layer system IN-PLACE on the active material. This WIPES
    # the imported glTF node graph (BSDF, tex nodes, etc.); the extracted Image
    # datablocks survive because we hold references to them in *images*. No
    # default empty layer — we add exactly one textured fill layer next.
    bpy.ops.layers.create_material(
        'EXEC_DEFAULT',
        type='BSDF_PRINCIPLED',
        color=True, ao=False, metallic=True, roughness=True, normal=True,
        create_default_layer=False,
    )

    from mixar.modules.paint.layered_build.pbr_layer import (
        build_pbr_layer_from_images,
    )
    layer = build_pbr_layer_from_images(images, obj=obj, layer_name=obj.name)
    if layer is None:
        logger.warning(
            "[ImportedPBR] Fill-layer build returned None for '%s'", obj.name)
        return False

    try:
        from mixar.modules.paint.ui.utils.ui_refresh import request_ui_refresh
        request_ui_refresh()
    except Exception:
        pass

    logger.info(
        "[ImportedPBR] '%s' converted to paint layer (maps: %s)",
        obj.name, ", ".join(k for k, v in images.items() if v))
    return True
