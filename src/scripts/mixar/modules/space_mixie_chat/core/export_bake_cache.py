# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Baked textures kept between exports, so a bake the time budget cut short
continues on the next export instead of starting over.

An entry is keyed by everything its pixels depend on: the material's node
tree (recursively, with groups, ramps, curves and image identities), the bake
plan and texture size, and the exact geometry of the faces it covers on each
package copy (world-baked positions, face corners, smooth flags). The faces'
``MixarBake`` UVs come from the same deterministic unwrap of that geometry,
so a hit lines up with the export's own layout. Any change misses and bakes.

Entries live under Mixar's per-user data folder (``bake_cache/<key>/``),
written atomically, pruned oldest-first past ``MAX_BYTES``. Local only.
"""

import hashlib
import json
import os
import shutil
import time

import bpy

VERSION = 1
MAX_BYTES = 2 * 1024 ** 3
_SKIP_PROPS = {"rna_type", "name", "label", "location", "width", "height", "select", "show_options",
               "show_preview", "hide", "mute", "show_texture", "color", "use_custom_color", "parent",
               "dimensions", "inputs", "outputs", "internal_links", "bl_idname", "bl_label",
               "bl_description", "bl_icon", "bl_static_type", "bl_width_default", "bl_width_min",
               "bl_width_max", "bl_height_default", "bl_height_min", "bl_height_max", "type",
               "location_absolute", "warning_propagation", "color_tag", "is_active_output"}


def root():
    from mixar.modules.common.agent_execution.paths import cache_root
    path = os.path.join(cache_root(), "bake_cache")
    os.makedirs(path, exist_ok=True)
    return path


def _value(value):
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, bpy.types.ID):
        return _id(value)
    try:
        return [_value(v) for v in value]
    except TypeError:
        return repr(value)


def _id(datablock):
    if isinstance(datablock, bpy.types.Image):
        return ["image", datablock.name, datablock.filepath, list(datablock.size),
                datablock.source, datablock.colorspace_settings.name]
    if isinstance(datablock, bpy.types.NodeTree):
        return ["group", _tree(datablock)]
    return [type(datablock).__name__, datablock.name]


def _struct(item):
    """Every plain property of a node (enums, numbers, ramps, curves, ids)."""
    out = {}
    for prop in item.bl_rna.properties:
        key = prop.identifier
        if key in _SKIP_PROPS:
            continue
        try:
            value = getattr(item, key)
        except AttributeError:
            continue
        if prop.type == "POINTER":
            if isinstance(value, bpy.types.ID):
                out[key] = _id(value)
            elif value is not None and key in ("color_ramp", "mapping", "texture_mapping", "color_mapping"):
                out[key] = _nested(value)
        elif prop.type != "COLLECTION":
            out[key] = _value(value)
    return out


def _nested(struct):
    out = _struct(struct)
    for key in ("elements", "curves"):
        items = getattr(struct, key, None)
        if items is not None:
            out[key] = [_nested(i) if hasattr(i, "bl_rna") else _value(i) for i in items]
    points = getattr(struct, "points", None)
    if points is not None:
        out["points"] = [[_value(p.location), p.handle_type] for p in points]
    return out


def _tree(tree):
    nodes = []
    for node in sorted(tree.nodes, key=lambda n: n.name):
        inputs = [[s.identifier, _value(getattr(s, "default_value", None))]
                  for s in node.inputs if not s.is_linked]
        nodes.append([node.bl_idname, node.name, bool(node.mute), _struct(node), inputs])
    links = sorted([link.from_node.name, link.from_socket.identifier, link.to_node.name,
                    link.to_socket.identifier, bool(getattr(link, "is_muted", False))]
                   for link in tree.links)
    return [nodes, links]


def _faces(obj, indices):
    """Digest of the faces of ``obj`` that use the slots in ``indices``."""
    import numpy as np

    mesh = obj.data
    count = len(mesh.polygons)
    mats = np.empty(count, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", mats)
    smooth = np.empty(count, dtype=bool)
    mesh.polygons.foreach_get("use_smooth", smooth)
    starts = np.empty(count, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    totals = np.empty(count, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", totals)
    loops = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loops)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) @ np.array(obj.matrix_world, dtype=np.float32)[:3, :3].T \
        + np.array(obj.matrix_world.translation, dtype=np.float32)
    digest = hashlib.sha256()
    for face in np.flatnonzero(np.isin(mats, sorted(indices))):
        corners = loops[starts[face]:starts[face] + totals[face]]
        digest.update(np.round(co[corners], 5).tobytes())
        digest.update(bytes([int(smooth[face])]))
    digest.update(",".join(sorted(a.name for a in mesh.attributes)).encode())
    return digest.hexdigest()


def key(job, size, margin):
    """The cache key of one bake job, or None when it cannot be computed."""
    try:
        material = job["material"]
        payload = {
            "v": VERSION, "app": list(bpy.app.version), "plan": job["plan"], "size": size, "margin": margin,
            "material": _tree(material.node_tree),
            "faces": sorted(_faces(o, idx) for o, idx in job["slots"].items()),
        }
        raw = json.dumps(payload, sort_keys=True, default=repr).encode()
        return hashlib.sha256(raw).hexdigest()[:40]
    except Exception:  # noqa: BLE001 - no key means "bake it"
        return None


def load(entry_key, material_name, channels, suffix, srgb, created_images):
    """{channel: image} from the cache, or None on any miss. Each image is
    named as a fresh bake names it: the package's textures/ files and the
    file's image names come from it."""
    if not entry_key:
        return None
    folder = os.path.join(root(), entry_key)
    paths = {name: os.path.join(folder, f"{suffix[name]}.png") for name in channels}
    if not all(os.path.isfile(p) for p in paths.values()):
        return None
    images = {}
    try:
        for name, path in paths.items():
            image = bpy.data.images.load(path, check_existing=False)
            created_images.append(image)
            image.name = f"{material_name}_{suffix[name]}"
            if not srgb[name]:
                image.colorspace_settings.is_data = True
            image.pack()
            # Exporters name a file image after its path; the packed bytes are
            # what is written, and no local cache path stays on the image.
            image.filepath_raw = f"//{image.name}.png"
            images[name] = image
        os.utime(folder)
    except Exception:  # noqa: BLE001 - a broken entry is a miss
        return None
    return images


def store(entry_key, images, suffix):
    """Write ``images`` (freshly baked and packed) under ``entry_key``: their
    packed PNG bytes, so the images themselves are left as they are."""
    if not entry_key or not images:
        return
    base = root()
    staging = os.path.join(base, f".{entry_key}.{os.getpid()}.{time.monotonic_ns()}")
    try:
        os.makedirs(staging)
        for name, image in images.items():
            with open(os.path.join(staging, f"{suffix[name]}.png"), "wb") as handle:
                handle.write(bytes(image.packed_file.data))
        final = os.path.join(base, entry_key)
        shutil.rmtree(final, ignore_errors=True)
        os.replace(staging, final)
    except Exception:  # noqa: BLE001 - caching is best effort
        shutil.rmtree(staging, ignore_errors=True)
        return
    prune(base)


def prune(base, limit=MAX_BYTES):
    entries = []
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        size = sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path))
        entries.append((os.path.getmtime(path), size, path))
    total = sum(size for _, size, _ in entries)
    for _, size, path in sorted(entries):
        if total <= limit:
            break
        shutil.rmtree(path, ignore_errors=True)
        total -= size
