# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""STANDALONE headless preview-render worker.

Executed as::

    mixar -b --factory-startup --python preview_worker_script.py -- <plan.json>

The plan is {"items": [...], "out_dir": "..."} (same work-item dicts as
core/render_session.build_render_plan). For each item the worker extracts the
asset's embedded preview when present, otherwise renders a 512x512 preview,
saves it as ``out_dir/<idx>.jpg``, and appends one JSON line to
``out_dir/results.jsonl`` (flushed per item — the parent tails this file for
real-time progress). ``out_dir/done.marker`` is written at the end.

DELIBERATELY self-contained: no mixar imports (runs under --factory-startup
where the addon is not loaded), only bpy + stdlib + numpy. The small rig /
framing / preview helpers are duplicated from
asset_search/utils/preview_render.py — keep the two in sync.
"""

import json
import os
import sys
import time
from math import cos, radians, sin, tan

import bpy
from mathutils import Vector


# ----------------------------------------------------------------------- #
# Helpers (mirrors utils/preview_render.py — keep in sync)
# ----------------------------------------------------------------------- #

def _compute_bounds(objects):
    corners = [
        obj.matrix_world @ Vector(c) for obj in objects for c in obj.bound_box
    ]
    if not corners:
        return Vector((0, 0, 0)), 1.0
    min_co = Vector((min(c[i] for c in corners) for i in range(3)))
    max_co = Vector((max(c[i] for c in corners) for i in range(3)))
    center = (min_co + max_co) / 2
    return center, max((max_co - min_co).length / 2, 0.001)


def _frame_camera(camera_obj, objects):
    center, radius = _compute_bounds(objects)
    fov = camera_obj.data.angle
    distance = (radius / tan(fov / 2)) * 1.2
    elev, azim = radians(25), radians(45)
    offset = Vector((
        cos(elev) * sin(azim), -cos(elev) * cos(azim), sin(elev),
    )) * distance
    camera_obj.location = center + offset
    direction = center - camera_obj.location
    camera_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def _collect_metadata(asset_id, library_name, blend_rel_path):
    asset_type = asset_id.type if hasattr(asset_id, 'type') else type(asset_id).__name__
    meta = asset_id.asset_data
    info = {
        'name': asset_id.name, 'type': asset_type, 'library': library_name,
        'blend_file': str(blend_rel_path), 'author': '', 'description': '',
        'copyright': '', 'license': '', 'catalog_id': '', 'catalog_name': '',
        'tags': [], 'custom_props': {}, 'image_name': '',
    }
    if meta is not None:
        info['author'] = meta.author or ''
        info['description'] = meta.description or ''
        info['copyright'] = meta.copyright or ''
        info['license'] = meta.license or ''
        info['catalog_id'] = meta.catalog_id or ''
        info['catalog_name'] = meta.catalog_simple_name or ''
        info['tags'] = [t.name for t in meta.tags] if meta.tags else []
        raw = dict(meta.items()) if hasattr(meta, 'items') else {}
        info['custom_props'] = {k: _to_py(v) for k, v in raw.items()}
    return info


def _to_py(value):
    if type(value).__name__ == 'IDPropertyArray':
        return list(value)
    if isinstance(value, dict):
        return {k: _to_py(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_py(v) for v in value]
    return value


def _save_preview_jpg(datablock, out_path, min_size=32):
    """Embedded asset preview -> JPEG file. True on success."""
    preview = getattr(datablock, "preview", None)
    if preview is None:
        return False
    w, h = preview.image_size
    if w < min_size or h < min_size:
        return False
    import numpy as np
    buf = np.empty(w * h * 4, dtype=np.float32)
    try:
        preview.image_pixels_float.foreach_get(buf)
    except Exception:
        return False
    if float(buf[3::4].max(initial=0.0)) < 0.05:
        return False
    img = None
    try:
        img = bpy.data.images.new("_preview_src", width=w, height=h, alpha=True)
        img.pixels.foreach_set(buf)
        img.file_format = 'JPEG'
        img.filepath_raw = out_path
        img.save()
        return True
    except Exception:
        return False
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass


def _render_jpg(scene, out_path):
    """Render the staged scene to a JPEG file. True on success."""
    orig_fmt = scene.render.image_settings.file_format
    orig_q = scene.render.image_settings.quality
    scene.render.image_settings.file_format = 'JPEG'
    scene.render.image_settings.quality = 80
    try:
        bpy.ops.render.render()
        result = bpy.data.images.get('Render Result')
        if not result:
            return False
        result.save_render(filepath=out_path, scene=scene)
        return True
    finally:
        scene.render.image_settings.file_format = orig_fmt
        scene.render.image_settings.quality = orig_q


def _remove_appended(objects=(), collections=()):
    for coll in collections:
        objs = list(coll.all_objects)
        bpy.data.collections.remove(coll)
        objects = list(objects) + objs
    for obj in objects:
        data, obj_type = obj.data, obj.type
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            continue
        if data is not None and data.users == 0:
            coll_attr = {
                'MESH': 'meshes', 'CURVE': 'curves', 'FONT': 'curves',
                'SURFACE': 'curves', 'META': 'metaballs', 'ARMATURE': 'armatures',
                'LIGHT': 'lights', 'CAMERA': 'cameras', 'LATTICE': 'lattices',
                'VOLUME': 'volumes', 'POINTCLOUD': 'pointclouds',
            }.get(obj_type)
            if coll_attr and hasattr(bpy.data, coll_attr):
                try:
                    getattr(bpy.data, coll_attr).remove(data)
                except Exception:
                    pass


# ----------------------------------------------------------------------- #
# Scene staging
# ----------------------------------------------------------------------- #

def _stage_scene():
    scene = bpy.context.scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    # EEVEE ONLY — never Workbench (thumbnail look must match the in-app
    # renders the embeddings were trained on). If no EEVEE variant can be
    # set headless, DIE EARLY (nonzero exit, no results): the parent then
    # falls back to the in-process session, which renders EEVEE in-app.
    for engine in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    else:
        raise RuntimeError("No EEVEE render engine available in background mode")
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True

    cam_data = bpy.data.cameras.new("_preview_cam")
    cam = bpy.data.objects.new("_preview_cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    key = bpy.data.lights.new("_preview_key", 'SUN')
    key.energy = 3.0
    key_obj = bpy.data.objects.new("_preview_key", key)
    key_obj.rotation_euler = (radians(50), 0, radians(30))
    scene.collection.objects.link(key_obj)

    fill = bpy.data.lights.new("_preview_fill", 'SUN')
    fill.energy = 1.0
    fill_obj = bpy.data.objects.new("_preview_fill", fill)
    fill_obj.rotation_euler = (radians(30), 0, radians(-150))
    scene.collection.objects.link(fill_obj)
    return scene, cam


def _process_item(scene, cam, item, out_path):
    """One asset: append -> preview-or-render JPEG -> cleanup. Returns info."""
    with bpy.data.libraries.load(item['blend_str'], link=False) as (_, data_to):
        if item['kind'] == 'OBJECT':
            data_to.objects = [item['name']]
        else:
            data_to.collections = [item['name']]

    if item['kind'] == 'OBJECT':
        obj = data_to.objects[0]
        if obj is None:
            raise RuntimeError("not found in .blend")
        info = _collect_metadata(obj, item['library'], item['rel_path'])
        info['name'] = item['name']
        try:
            if _save_preview_jpg(obj, out_path):
                info['reused_preview'] = True
                return info
            scene.collection.objects.link(obj)
            bpy.context.view_layer.update()
            _frame_camera(cam, [obj])
            if not _render_jpg(scene, out_path):
                raise RuntimeError("render produced no image")
            scene.collection.objects.unlink(obj)
            return info
        finally:
            _remove_appended(objects=[obj] if obj.name in bpy.data.objects else [])
    else:
        coll = data_to.collections[0]
        if coll is None:
            raise RuntimeError("not found in .blend")
        info = _collect_metadata(coll, item['library'], item['rel_path'])
        info['name'] = item['name']
        try:
            if _save_preview_jpg(coll, out_path):
                info['reused_preview'] = True
                return info
            scene.collection.children.link(coll)
            bpy.context.view_layer.update()
            objects = list(coll.all_objects)
            if not objects:
                raise RuntimeError("empty collection")
            _frame_camera(cam, objects)
            if not _render_jpg(scene, out_path):
                raise RuntimeError("render produced no image")
            scene.collection.children.unlink(coll)
            return info
        finally:
            if coll.name in bpy.data.collections:
                if coll.name in {c.name for c in scene.collection.children}:
                    try:
                        scene.collection.children.unlink(coll)
                    except Exception:
                        pass
                _remove_appended(collections=[coll])


# ----------------------------------------------------------------------- #
# Thumbnail backfill — write renders back as the assets' previews
# ----------------------------------------------------------------------- #

def _touch(path):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(time.time()))


def _apply_preview_from_jpg(datablock, jpg_path):
    """Load a JPEG and set it as ``datablock``'s embedded preview."""
    import numpy as np
    img = bpy.data.images.load(jpg_path)
    try:
        w, h = img.size
        if not (w and h):
            return False
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        preview = datablock.preview_ensure()
        preview.image_size = (w, h)
        preview.image_pixels_float.foreach_set(buf)
        return True
    finally:
        bpy.data.images.remove(img)


def _backfill_previews(entries, heartbeat_path):
    """Write rendered thumbnails back into their source .blend files.

    Assets that had NO usable embedded preview were rendered this run — save
    that render as their preview so they show a real thumbnail in the asset
    browser and the NEXT training run takes the fast reuse path. Groups by
    .blend (one open + save per file); Blender's save writes via a temp file,
    so a killed worker can't corrupt a library.
    """
    by_blend = {}
    for e in entries:
        by_blend.setdefault(e["blend_str"], []).append(e)

    for blend_path, blend_entries in by_blend.items():
        _touch(heartbeat_path)  # keep the parent's stall watchdog fed
        try:
            bpy.ops.wm.open_mainfile(filepath=blend_path, load_ui=False)
        except Exception as exc:  # noqa: BLE001 — skip unopenable files
            print(f"[backfill] cannot open {blend_path}: {exc}")
            continue
        changed = False
        for e in blend_entries:
            datablock = (bpy.data.objects.get(e["name"])
                         or bpy.data.collections.get(e["name"]))
            if datablock is None or not os.path.isfile(e["jpg"]):
                continue
            try:
                if _apply_preview_from_jpg(datablock, e["jpg"]):
                    changed = True
            except Exception as exc:  # noqa: BLE001
                print(f"[backfill] preview failed for {e['name']}: {exc}")
        if changed:
            try:
                bpy.ops.wm.save_mainfile(filepath=blend_path)
                print(f"[backfill] saved previews into {blend_path}")
            except Exception as exc:  # noqa: BLE001
                print(f"[backfill] cannot save {blend_path}: {exc}")


def main():
    argv = sys.argv
    plan_path = argv[argv.index("--") + 1]
    with open(plan_path, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    out_dir = plan["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    heartbeat_path = os.path.join(out_dir, "heartbeat")

    # Backfill-only mode: the in-process (small-plan) session rendered in the
    # app and hands us jpgs to write back — no render pass, no parent polling.
    if plan.get("backfill") is not None and "items" not in plan:
        _backfill_previews(plan["backfill"], heartbeat_path)
        if plan.get("cleanup_self"):
            import shutil
            shutil.rmtree(out_dir, ignore_errors=True)
        return

    items = plan["items"]
    results_path = os.path.join(out_dir, "results.jsonl")
    scene, cam = _stage_scene()

    backfill_entries = []
    with open(results_path, "a", encoding="utf-8") as results:
        for i, item in enumerate(items):
            label = f"{item.get('name', '?')} ({item.get('library', '?')})"
            out_path = os.path.join(out_dir, f"{i:05d}.jpg")
            entry = {"idx": i, "ok": False, "label": label}
            try:
                info = _process_item(scene, cam, item, out_path)
                entry.update(ok=True, file=f"{i:05d}.jpg", info=info)
                if not info.get("reused_preview"):
                    backfill_entries.append({
                        "blend_str": item["blend_str"],
                        "name": item["name"],
                        "jpg": out_path,
                    })
            except Exception as e:  # noqa: BLE001 — record and continue
                entry["reason"] = str(e)[:150]
            results.write(json.dumps(entry) + "\n")
            results.flush()
            os.fsync(results.fileno())
            _touch(heartbeat_path)

    # Backfill BEFORE done.marker: the parent deletes out_dir (our jpgs)
    # right after it sees done. The heartbeat keeps its watchdog satisfied.
    if backfill_entries:
        _backfill_previews(backfill_entries, heartbeat_path)

    with open(os.path.join(out_dir, "done.marker"), "w", encoding="utf-8") as fh:
        fh.write("done")


if __name__ == "__main__":
    main()
