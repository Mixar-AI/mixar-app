# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Inspect Operators

Operators for inspecting and rendering preview images of marked assets
(objects and collections) across all custom asset libraries.
"""

from math import radians
from pathlib import Path

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.utils.preview_render import (
    compute_bounds as _compute_bounds,  # noqa: F401 — re-exported for callers
    frame_camera as _frame_camera,
    remove_collection as _remove_collection,
    remove_objects as _remove_objects,
    render_to_image as _render_to_image,
)

logger = get_logger(__name__)

# Module-level storage for collected asset data (populated by inspect operator)
_collected_assets = []

# Render filter: None = render all, set = only matching identities
_render_filter = None


def get_collected_asset_data():
    """Return the list of asset metadata dicts collected by the last inspect run."""
    return list(_collected_assets)


def set_render_filter(asset_identities):
    """Set filter so only matching assets (name/library/blend_file dicts) are rendered."""
    global _render_filter
    if asset_identities is None:
        _render_filter = None
    else:
        _render_filter = {
            f"{a['name']}|{a['library']}|{a['blend_file']}"
            for a in asset_identities
        }


def clear_render_filter():
    global _render_filter
    _render_filter = None


def _matches_render_filter(name, library_name, blend_rel_path):
    if _render_filter is None:
        return True
    return f"{name}|{library_name}|{blend_rel_path}" in _render_filter


# _DATA_COLLECTIONS / _compute_bounds / _frame_camera / _render_to_image /
# _remove_objects / _remove_collection moved to
# asset_search/utils/preview_render.py (shared with the chat asset-picker's
# thumbnail generation) — imported above under their original names.


def _convert_idprop_to_py(value):
    """Convert Blender IDProperty types to Python-native JSON-serializable types."""
    # Check type name to handle IDPropertyArray without importing it
    type_name = type(value).__name__

    if type_name == 'IDPropertyArray':
        return list(value)
    elif isinstance(value, dict):
        return {k: _convert_idprop_to_py(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [_convert_idprop_to_py(item) for item in value]
    else:
        return value


def _collect_asset_metadata(asset_id, library_name, blend_rel_path):
    """Collect and log metadata for an asset datablock. Returns a dict."""
    asset_type = asset_id.type if hasattr(asset_id, 'type') else type(asset_id).__name__
    meta = asset_id.asset_data

    info = {
        'name': asset_id.name,
        'type': asset_type,
        'library': library_name,
        'blend_file': str(blend_rel_path),
        'author': '',
        'description': '',
        'copyright': '',
        'license': '',
        'catalog_id': '',
        'catalog_name': '',
        'tags': [],
        'custom_props': {},
        'image_name': '',
    }

    logger.debug("[Asset Inspector] Name: %s", asset_id.name)
    logger.debug("[Asset Inspector] Type: %s", asset_type)
    logger.debug("[Asset Inspector] Library: %s", library_name)
    logger.debug("[Asset Inspector] Blend file: %s", blend_rel_path)

    if meta is not None:
        info['author'] = meta.author or ''
        info['description'] = meta.description or ''
        info['copyright'] = meta.copyright or ''
        info['license'] = meta.license or ''
        info['catalog_id'] = meta.catalog_id or ''
        info['catalog_name'] = meta.catalog_simple_name or ''
        info['tags'] = [tag.name for tag in meta.tags] if meta.tags else []

        # Convert custom properties to JSON-serializable types
        raw_props = dict(meta.items()) if hasattr(meta, 'items') else {}
        info['custom_props'] = {
            k: _convert_idprop_to_py(v) for k, v in raw_props.items()
        }

        logger.debug("[Asset Inspector] Author: %s", info['author'])
        logger.debug("[Asset Inspector] Description: %s", info['description'])
        logger.debug("[Asset Inspector] Catalog ID: %s", info['catalog_id'])
        logger.debug("[Asset Inspector] Catalog Name: %s", info['catalog_name'])
        tags_str = ', '.join(info['tags']) if info['tags'] else '(none)'
        logger.debug("[Asset Inspector] Tags: %s", tags_str)
    else:
        logger.debug("[Asset Inspector] (no asset metadata)")
    return info


class MIXIE_OT_inspect_asset_libraries(Operator):
    """Scan custom asset libraries, render EEVEE previews for each asset"""

    bl_idname = "mixie.inspect_asset_libraries"
    bl_label = "Inspect Asset Libraries"
    bl_description = (
        "Scan all custom asset libraries, render 512x512 EEVEE previews "
        "for each object and collection asset, and store them in memory"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        _collected_assets.clear()

        asset_libraries = context.preferences.filepaths.asset_libraries
        if not asset_libraries:
            self.report({"WARNING"}, "No custom asset libraries found")
            return {"CANCELLED"}

        scene = context.scene

        # --- Store original settings ---
        orig = {
            'engine': scene.render.engine,
            'res_x': scene.render.resolution_x,
            'res_y': scene.render.resolution_y,
            'res_pct': scene.render.resolution_percentage,
            'camera': scene.camera,
            'film_transparent': scene.render.film_transparent,
        }

        # --- Setup EEVEE 512x512 render ---
        try:
            scene.render.engine = 'BLENDER_EEVEE_NEXT'
        except Exception:
            scene.render.engine = 'BLENDER_EEVEE'
        scene.render.resolution_x = 512
        scene.render.resolution_y = 512
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True

        # --- Create temp camera ---
        cam_data = bpy.data.cameras.new("_asset_preview_cam")
        cam_obj = bpy.data.objects.new("_asset_preview_cam", cam_data)
        scene.collection.objects.link(cam_obj)
        scene.camera = cam_obj

        # --- Create temp lights (key + fill) ---
        key_data = bpy.data.lights.new("_asset_preview_key", 'SUN')
        key_data.energy = 3.0
        key_obj = bpy.data.objects.new("_asset_preview_key", key_data)
        key_obj.rotation_euler = (radians(50), 0, radians(30))
        scene.collection.objects.link(key_obj)

        fill_data = bpy.data.lights.new("_asset_preview_fill", 'SUN')
        fill_data.energy = 1.0
        fill_obj = bpy.data.objects.new("_asset_preview_fill", fill_data)
        fill_obj.rotation_euler = (radians(30), 0, radians(-150))
        scene.collection.objects.link(fill_obj)

        temp_objs = {cam_obj, key_obj, fill_obj}

        # --- Hide all existing scene objects from render ---
        hidden_from_render = []
        for obj in list(scene.objects):
            if obj not in temp_objs and not obj.hide_render:
                obj.hide_render = True
                hidden_from_render.append(obj)

        total_rendered = 0

        try:
            for lib in asset_libraries:
                library_name = lib.name
                library_path = Path(lib.path)
                if not library_path.exists() or not library_path.is_dir():
                    continue

                logger.debug("[Asset Inspector] === Library: %s ===", library_name)

                blend_files = sorted(library_path.glob("**/*.blend"))
                if not blend_files:
                    logger.debug("[Asset Inspector] No .blend files found")
                    continue

                for blend_file in blend_files:
                    rel_path = blend_file.relative_to(library_path)
                    blend_str = str(blend_file)

                    # Discover asset-marked names
                    try:
                        with bpy.data.libraries.load(
                            blend_str, assets_only=True
                        ) as (data_from, _):
                            object_names = list(data_from.objects)
                            collection_names = list(data_from.collections)
                    except Exception as e:
                        logger.error("[Asset Inspector] Error reading %s: %s", rel_path, e)
                        continue

                    if not object_names and not collection_names:
                        continue

                    logger.debug("[Asset Inspector] File: %s", rel_path)

                    # --- Render each object asset ---
                    for obj_name in object_names:
                        total_rendered += self._render_object_asset(
                            scene, cam_obj, blend_str, obj_name,
                            library_name, rel_path,
                        )

                    # --- Render each collection asset ---
                    for coll_name in collection_names:
                        total_rendered += self._render_collection_asset(
                            scene, cam_obj, blend_str, coll_name,
                            library_name, rel_path,
                        )

        finally:
            # --- Restore hidden objects ---
            for obj in hidden_from_render:
                if obj.name in bpy.data.objects:
                    obj.hide_render = False

            # --- Remove temp objects ---
            for obj, data_coll, data in [
                (cam_obj, bpy.data.cameras, cam_data),
                (key_obj, bpy.data.lights, key_data),
                (fill_obj, bpy.data.lights, fill_data),
            ]:
                bpy.data.objects.remove(obj, do_unlink=True)
                data_coll.remove(data)

            # --- Restore render settings ---
            scene.render.engine = orig['engine']
            scene.render.resolution_x = orig['res_x']
            scene.render.resolution_y = orig['res_y']
            scene.render.resolution_percentage = orig['res_pct']
            scene.render.film_transparent = orig['film_transparent']
            scene.camera = orig['camera']

        summary = f"Rendered {total_rendered} asset preview(s) to memory"
        logger.debug("[Asset Inspector] %s", summary)
        self.report({"INFO"}, summary)
        return {"FINISHED"}

    def _render_object_asset(self, scene, cam_obj, blend_str, obj_name,
                             library_name, blend_rel_path):
        """Import one object asset, render it, clean up. Returns 1 on success."""
        if not _matches_render_filter(obj_name, library_name, blend_rel_path):
            return 0
        try:
            with bpy.data.libraries.load(blend_str, link=False) as (_, data_to):
                data_to.objects = [obj_name]

            obj = data_to.objects[0]
            if obj is None:
                return 0

            logger.debug("[Asset Inspector] --- Object: %s ---", obj_name)
            info = _collect_asset_metadata(obj, library_name, blend_rel_path)
            # Use original file name — Blender may rename on append (e.g. Cube -> Cube.001)
            info['name'] = obj_name

            scene.collection.objects.link(obj)
            bpy.context.view_layer.update()

            _frame_camera(cam_obj, [obj])
            img_name = f"asset_preview_{obj_name}"
            img = _render_to_image(scene, img_name)

            scene.collection.objects.unlink(obj)
            _remove_objects([obj])

            if img:
                info['image_name'] = img_name
                _collected_assets.append(info)
                logger.debug("[Asset Inspector] Rendered object: %s", obj_name)
                return 1

            logger.error("[Asset Inspector] Render failed: %s", obj_name)
        except Exception as e:
            logger.error("[Asset Inspector] Error rendering %s: %s", obj_name, e)
        return 0

    def _render_collection_asset(self, scene, cam_obj, blend_str, coll_name,
                                 library_name, blend_rel_path):
        """Import one collection asset, render it, clean up. Returns 1 on success."""
        if not _matches_render_filter(coll_name, library_name, blend_rel_path):
            return 0
        try:
            with bpy.data.libraries.load(blend_str, link=False) as (_, data_to):
                data_to.collections = [coll_name]

            coll = data_to.collections[0]
            if coll is None:
                return 0

            logger.debug("[Asset Inspector] --- Collection: %s ---", coll_name)
            info = _collect_asset_metadata(coll, library_name, blend_rel_path)
            # Use original file name — Blender may rename on append
            info['name'] = coll_name

            scene.collection.children.link(coll)
            bpy.context.view_layer.update()

            objects = list(coll.all_objects)
            if not objects:
                logger.debug("[Asset Inspector] Collection '%s' empty, skipping", coll_name)
                scene.collection.children.unlink(coll)
                _remove_collection(coll)
                return 0

            logger.debug("[Asset Inspector] Object count: %d", len(objects))
            for obj in objects:
                logger.debug("[Asset Inspector] - %s (%s)", obj.name, obj.type)

            _frame_camera(cam_obj, objects)
            img_name = f"asset_preview_{coll_name}"
            img = _render_to_image(scene, img_name)

            scene.collection.children.unlink(coll)
            _remove_collection(coll)

            if img:
                info['image_name'] = img_name
                _collected_assets.append(info)
                logger.debug("[Asset Inspector] Rendered collection: %s", coll_name)
                return 1

            logger.error("[Asset Inspector] Render failed: %s", coll_name)
        except Exception as e:
            logger.error("[Asset Inspector] Error rendering %s: %s", coll_name, e)
        return 0


classes = (
    MIXIE_OT_inspect_asset_libraries,
)


def register():
    """Register operator classes"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    """Unregister operator classes"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
