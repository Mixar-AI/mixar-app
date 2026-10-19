# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake the materials ``bake_plan`` names, on a TEMPORARY COPY of the scene.

This module runs only in the background bake process (``bake_child``),
never in the user's session. The steps:

1. The meshes to bake (one per mesh data) are split into CHUNKS by world
   surface area (``TEXEL_DENSITY`` px/m, 512–2048 px, capped in total).
2. Each chunk gets a new ``MixarBake`` UV map from a joint Smart UV Project
   (multi-object edit packs every mesh into one 0–1 space, with no
   cross-object overlap).
3. One set of images is baked per chunk with Cycles (GPU when there is one):
   base colour, roughness and metallic (packed as ORM) and emission through
   an Emission-shader stand-in, and the tangent-space normal from the real
   surface. Meshes are joined into world-space proxies, so a pass is one
   Cycles session rather than one per mesh. Object / Generated coordinates
   and Object Info Random / Location / Color travel into the proxy as mesh
   attributes (``bake_attrs``); a mesh whose material reads another
   per-object input (camera / window / reflection coordinates, other Object
   Info outputs) is baked in place instead.
4. Every material on a chunk mesh is replaced by a Principled material
   reading the chunk's images through ``MixarBake``. That UV map becomes the
   only one, so it is TEXCOORD_0 in the GLB.

A chunk is cached under ``<cache>/<key>/``, with its images and its UV
coordinates. The key covers the material graphs and the images they read,
the mesh data, the world matrices, the resolution, Blender's version and
``BAKE_VERSION``. Entries are written to a temp directory and renamed into
place, so a killed bake never leaves half an entry behind. A cache hit
re-applies the cached UVs and images and skips the unwrap and the bake.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid

import bpy
import numpy as np

from . import bake_plan

BAKE_VERSION = 1
BAKE_UV = "MixarBake"
TEXEL_DENSITY = 128.0       # px per metre
PACK_EFFICIENCY = 0.4       # share of an atlas Smart UV Project fills
MIN_RES, MAX_RES = 512, 2048
TOTAL_PIXELS = 8 * 2048 * 2048
JPEG_QUALITY = 90


# --- chunking ---------------------------------------------------------------

def world_area(obj) -> float:
    mesh = obj.data
    areas = np.empty(len(mesh.polygons), np.float32)
    mesh.polygons.foreach_get("area", areas)
    scale = abs(obj.matrix_world.to_3x3().determinant()) ** (2.0 / 3.0)
    return float(areas.sum()) * scale


def resolution(area: float, density: float) -> int:
    side = math.sqrt(max(area, 1e-6) / PACK_EFFICIENCY) * density
    return int(min(MAX_RES, max(MIN_RES, 2 ** math.ceil(math.log2(max(side, 1.0))))))


def make_chunks(meshes) -> list[dict]:
    """Greedy, name order: ``[{"meshes": [obj], "area": m², "res": px}]``."""
    density = TEXEL_DENSITY
    while True:
        cap = (MAX_RES / density) ** 2 * PACK_EFFICIENCY
        chunks, current = [], {"meshes": [], "area": 0.0}
        for obj in sorted(meshes, key=lambda o: o.name):
            area = world_area(obj)
            if current["meshes"] and current["area"] + area > cap:
                chunks.append(current)
                current = {"meshes": [], "area": 0.0}
            current["meshes"].append(obj)
            current["area"] += area
        if current["meshes"]:
            chunks.append(current)
        for chunk in chunks:
            chunk["res"] = resolution(chunk["area"], density)
        if sum(c["res"] ** 2 for c in chunks) <= TOTAL_PIXELS or density <= 16:
            for chunk in chunks:
                chunk["density"] = round(density, 2)
            return chunks
        density *= 0.85  # fine steps, so the cap is used rather than halved past


# --- cache key ----------------------------------------------------------------

def _hash_array(h, collection, attr, dtype, width=1):
    data = np.empty(len(collection) * width, dtype)
    collection.foreach_get(attr, data)
    h.update(data.tobytes())


def mesh_hash(mesh) -> str:
    h = hashlib.sha1()
    _hash_array(h, mesh.vertices, "co", np.float32, 3)
    _hash_array(h, mesh.loops, "vertex_index", np.int32)
    _hash_array(h, mesh.polygons, "loop_start", np.int32)
    _hash_array(h, mesh.polygons, "material_index", np.int32)
    for layer in mesh.uv_layers:
        if layer.name != BAKE_UV:
            h.update(layer.name.encode())
            _hash_array(h, layer.data, "uv", np.float32, 2)
    return h.hexdigest()


def _value(value):
    if isinstance(value, (str, bool)) or value is None:
        return value
    try:
        return [round(float(v), 6) for v in value]
    except (TypeError, ValueError):
        pass
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


_image_ids: dict = {}


def image_identity(image) -> str:
    """What the image's pixels are: a digest of the packed bytes (the child
    repacks painted-but-unsaved images, so a paint changes it), or the
    file's path, size and time."""
    packed = getattr(image, "packed_file", None)
    if packed is not None:
        key = (image.name, packed.size)
        if key not in _image_ids:
            _image_ids[key] = hashlib.sha1(bytes(packed.data)).hexdigest()
        return _image_ids[key]
    path = bpy.path.abspath(image.filepath) if image.filepath else ""
    try:
        stat = os.stat(path)
        return f"{path}|{stat.st_size}|{int(stat.st_mtime)}"
    except OSError:
        return f"{path}|missing|{image.source}"


def _tree_signature(tree, depth=0) -> list:
    if tree is None or depth > 8:
        return []
    out = []
    for node in sorted(tree.nodes, key=lambda n: n.name):
        row = [node.bl_idname, node.name]
        for prop in ("operation", "blend_type", "data_type", "interpolation", "projection", "extension",
                     "noise_dimensions", "feature", "distance", "wave_type", "uv_map", "space",
                     "normalize", "use_clamp", "clamp_factor", "color_ramp"):
            if hasattr(node, prop):
                value = getattr(node, prop)
                if prop == "color_ramp" and value is not None:
                    value = [(e.position, tuple(e.color)) for e in value.elements]
                row.append((prop, _value(value) if prop != "color_ramp" else value))
        image = getattr(node, "image", None)
        if image is not None:
            row.append(("image", image.name, tuple(image.size), image_identity(image)))
        for socket in node.inputs:
            if not socket.is_linked and hasattr(socket, "default_value"):
                row.append((socket.identifier, _value(socket.default_value)))
        if getattr(node, "node_tree", None) is not None:
            row.append(_tree_signature(node.node_tree, depth + 1))
        out.append(row)
    out.append(sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
                      for l in tree.links))
    return out


def material_hash(material) -> str:
    return hashlib.sha1(json.dumps(_tree_signature(material.node_tree), default=str).encode()).hexdigest()


def modifier_signature(obj) -> list:
    out = []
    for mod in obj.modifiers:
        props = []
        for prop in mod.bl_rna.properties:
            if prop.is_readonly or prop.identifier in ("rna_type", "name", "show_expanded"):
                continue
            value = getattr(mod, prop.identifier, None)
            props.append((prop.identifier, getattr(value, "name", None) or _value(value)))
        out.append((mod.type, mod.name, mod.show_render, props))
    return out


def chunk_key(chunk) -> str:
    h = hashlib.sha1(f"v{BAKE_VERSION}|{bpy.app.version_string}|{chunk['res']}".encode())
    for obj in chunk["meshes"]:
        h.update(obj.data.name.encode())
        h.update(mesh_hash(obj.data).encode())
        h.update(np.asarray(obj.matrix_world, np.float32).tobytes())
        h.update(json.dumps(modifier_signature(obj), default=str).encode())
        for material in bake_plan._materials(obj):
            h.update(material.name.encode())
            h.update(material_hash(material).encode())
    return h.hexdigest()[:24]


# --- cache entries --------------------------------------------------------------

def cache_entry(cache_dir: str, key: str) -> str | None:
    path = os.path.join(cache_dir, key)
    return path if os.path.isfile(os.path.join(path, "meta.json")) else None


def write_entry(cache_dir: str, key: str, files: dict, uvs: dict, meta: dict) -> str:
    """Atomically store ``files`` ({name: temp path}), the per-mesh bake UVs
    and ``meta`` as ``<cache_dir>/<key>/``."""
    os.makedirs(cache_dir, exist_ok=True)
    temp = os.path.join(cache_dir, f".tmp-{key}-{uuid.uuid4().hex[:8]}")
    os.makedirs(temp)
    try:
        for name, source in files.items():
            shutil.copyfile(source, os.path.join(temp, name))
        np.savez_compressed(os.path.join(temp, "uvs.npz"), **uvs)
        with open(os.path.join(temp, "meta.json"), "w", encoding="utf-8") as handle:
            json.dump(meta, handle)
        final = os.path.join(cache_dir, key)
        if os.path.isdir(final):
            shutil.rmtree(final, ignore_errors=True)
        os.replace(temp, final)
        return final
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


CACHE_SPARE = 8  # entries kept beyond the current build's (recent edits to undo)


def prune_cache(cache_dir: str, keep) -> int:
    """Remove stale entries: everything but ``keep`` and the ``CACHE_SPARE``
    most recent others, plus abandoned temp directories."""
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return 0
    removed = 0
    others = []
    for name in names:
        path = os.path.join(cache_dir, name)
        if name.startswith(".tmp-"):
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        elif name not in keep and os.path.isdir(path):
            others.append((os.path.getmtime(path), path))
    for _mtime, path in sorted(others, reverse=True)[CACHE_SPARE:]:
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


# --- the whole bake ----------------------------------------------------------------

def bake_scene(scene, objects, cache_dir: str, progress=lambda pct, message: None) -> dict:
    """Bake every material ``bake_plan`` names on the in-game ``objects`` of
    this (temporary) ``scene``. Returns stats for the job result."""
    from . import bake_passes
    planned = bake_plan.plan(objects)
    stats = {"materials": planned["materials"], "meshes": len(planned["meshes"]), "chunks": [],
             "cache_hits": 0, "baked": 0, "unsupported": planned["unsupported"],
             "character_materials": planned["character_materials"]}
    if not planned["meshes"]:
        return stats
    chunks = make_chunks(planned["meshes"])
    users = bake_passes.mesh_users(objects, {o.data.name for o in planned["meshes"]})
    hidden = {obj.name: obj.hide_render for obj in scene.objects}
    bake_passes.setup_cycles(scene)
    # Every key before any bake: baking a chunk rewires shared materials
    # (``bake_attrs``), which would change the keys of later chunks.
    keys = [chunk_key(chunk) for chunk in chunks]
    try:
        for index, chunk in enumerate(chunks):
            chunk["index"] = index
            low, span = 100.0 * index / len(chunks), 100.0 / len(chunks)
            key = keys[index]
            entry = cache_entry(cache_dir, key)
            hit = entry is not None
            label = f"Baking materials, part {index + 1} of {len(chunks)}"
            progress(low, label + (" (cached)" if entry else ""))
            if entry:
                images = bake_passes.apply_cached(chunk, entry)
                stats["cache_hits"] += 1
            else:
                bake_passes.unwrap(scene, chunk["meshes"])
                files, meta = bake_passes.bake_chunk(scene, chunk, index,
                                                     lambda f, m: progress(low + span * f, m))
                uvs = {obj.data.name: bake_passes.read_uv(obj.data) for obj in chunk["meshes"]}
                entry = write_entry(cache_dir, key, files, uvs, meta)
                images = bake_passes.load_images(entry, index)
                stats["baked"] += 1
            bake_passes.assign(chunk, index, images, users)
            stats["chunks"].append({"meshes": len(chunk["meshes"]), "res": chunk["res"],
                                    "density_px_m": chunk["density"],
                                    "area_m2": round(chunk["area"], 1), "key": key,
                                    "cached": hit})
        stats["cache_pruned"] = prune_cache(cache_dir, {c["key"] for c in stats["chunks"]})
        return stats
    finally:
        for obj in scene.objects:
            if obj.name in hidden:
                obj.hide_render = hidden[obj.name]
        bake_passes.cleanup_proxies()
