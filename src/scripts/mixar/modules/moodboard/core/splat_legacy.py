# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Convert splats saved by the retired KIRI 3DGS Render addon to built-in splats.

Files saved before Blender 5.3 hold a splat as KIRI objects: a point mesh
carrying the raw 3DGS PLY fields (``f_dc_*``, ``f_rest_*``, ``opacity``,
``scale_*``, ``rot_*``) behind KIRI geometry-nodes modifiers, often a second
copy of that mesh, and a proxy Empty that drew the splat through KIRI's own
GPU handler. Without the addon none of them shows anything, so each world is
rebuilt as one built-in splat object in the same place, and the KIRI objects
are removed.

Only objects that are KIRI's (a ``KIRI_3DGS`` modifier, KIRI's proxy keys) or
that a Mixar splat importer stamped (``wl_role``) are touched. Must run on the
main thread; it is a one-off per old file.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.splat_native import SPLAT_TYPE

logger = get_logger(__name__)

_KIRI_PREFIX = "KIRI_3DGS"
_PROXY_KEYS = ("is_gaussian_splat", "gaussian_data")
_REQUIRED = (
    "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
    "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
)
# Coefficients per colour channel for spherical-harmonic degrees 1..4.
_SH_DIMENSIONS = (3, 8, 15, 24)


def _is_kiri_mesh(obj) -> bool:
    if obj.type != "MESH":
        return False
    if "3DGS_Mesh_Type" in obj.keys():
        return True
    for mod in obj.modifiers:
        group = getattr(mod, "node_group", None)
        if group is not None and group.name.startswith(_KIRI_PREFIX):
            return True
    return False


def _is_kiri_proxy(obj) -> bool:
    if obj.type != "EMPTY":
        return False
    keys = obj.keys()
    return obj.get("wl_role") == "proxy" or any(k in keys for k in _PROXY_KEYS)


def _has_raw_fields(obj) -> bool:
    attributes = obj.data.attributes
    return all(name in attributes for name in _REQUIRED)


def _home(obj):
    """The collection a world lives in (its first one), or None."""
    collections = obj.users_collection
    return collections[0] if collections else None


def find_kiri_worlds() -> list:
    """Group KIRI objects into worlds: ``[(source_mesh, [objects_to_remove])]``.

    Per collection, every KIRI mesh with the raw fields is converted. A plain
    ``wl_role == 'splat'`` mesh is KIRI's duplicate source when a KIRI mesh of
    the same size sits beside it, otherwise it is converted itself. Proxies
    go with their collection's worlds.
    """
    by_home = {}
    for obj in bpy.data.objects:
        if _is_kiri_proxy(obj):
            by_home.setdefault(_home(obj), {"meshes": [], "plain": [], "proxies": []})[
                "proxies"].append(obj)
        elif obj.type == "MESH" and (_is_kiri_mesh(obj) or obj.get("wl_role") == "splat"):
            if not _has_raw_fields(obj):
                continue
            kind = "meshes" if _is_kiri_mesh(obj) else "plain"
            by_home.setdefault(_home(obj), {"meshes": [], "plain": [], "proxies": []})[
                kind].append(obj)

    worlds = []
    for group in by_home.values():
        sizes = {len(m.data.vertices) for m in group["meshes"]}
        sources = list(group["meshes"])
        duplicates = []
        for mesh in group["plain"]:
            (duplicates if len(mesh.data.vertices) in sizes else sources).append(mesh)
        if not sources:
            continue  # a lone proxy: nothing to rebuild from, leave it alone
        extras = duplicates + group["proxies"]
        for index, source in enumerate(sources):
            worlds.append((source, extras if index == 0 else []))
    return worlds


def _read(attributes, name, count, np, key="value"):
    out = np.empty(count, dtype=np.float32)
    attributes[name].data.foreach_get(key, out)
    return out


def build_splat_from_mesh(mesh_obj, np):
    """A built-in splat point cloud decoded from a mesh's raw 3DGS PLY fields.

    Mirrors Blender's own PLY importer: opacity through a sigmoid, scale
    through exp, rotation (w, x, y, z) normalised, and channel-major
    ``f_rest_*`` regrouped into ``radiance:sh_<n>`` colour vectors.
    """
    mesh = mesh_obj.data
    count = len(mesh.vertices)
    attributes = mesh.attributes
    positions = np.empty(count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)

    def raw(name):
        return _read(attributes, name, count, np)

    radiance = np.stack([raw("f_dc_0"), raw("f_dc_1"), raw("f_dc_2"),
                         np.clip(1.0 / (1.0 + np.exp(-raw("opacity"))), 0.0, 1.0)], axis=1)
    scale = np.exp(np.stack([raw("scale_0"), raw("scale_1"), raw("scale_2")], axis=1))
    rotation = np.stack([raw(f"rot_{i}") for i in range(4)], axis=1)
    norms = np.linalg.norm(rotation, axis=1, keepdims=True)
    rotation = np.where(norms > 1e-12, rotation / np.maximum(norms, 1e-12),
                        np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))

    rest = 0
    while f"f_rest_{rest}" in attributes:
        rest += 1
    per_channel = rest // 3 if rest % 3 == 0 else 0
    dimensions = max((d for d in _SH_DIMENSIONS if d <= per_channel), default=0)

    cloud = bpy.data.pointclouds.new(mesh_obj.name)
    try:
        cloud.resize(count)
        cloud.type = SPLAT_TYPE
        cloud.attributes["position"].data.foreach_set("vector", positions)
        _write(cloud, "radiance:base", "FLOAT4", radiance)
        _write(cloud, "scale", "FLOAT_VECTOR", scale)
        _write(cloud, "rotation", "QUATERNION", rotation)
        for d in range(dimensions):
            sh = np.stack([raw(f"f_rest_{d + c * per_channel}") for c in range(3)], axis=1)
            _write(cloud, f"radiance:sh_{d}", "FLOAT_VECTOR", sh)
    except Exception:
        bpy.data.pointclouds.remove(cloud)
        raise
    return cloud


# The RNA element property each attribute type stores its value under.
_VALUE_KEY = {"FLOAT_VECTOR": "vector", "FLOAT4": "vector", "QUATERNION": "value"}


def _write(cloud, name, data_type, values) -> None:
    attribute = cloud.attributes.get(name) or cloud.attributes.new(name, data_type, "POINT")
    attribute.data.foreach_set(_VALUE_KEY[data_type],
                               values.astype("float32", copy=False).ravel())


def _visible_world(source, extras) -> tuple:
    """(hidden in viewport, hidden in render) the converted splat should take.

    The proxy was the world's only visible handle: its meshes stayed hidden
    behind it in the viewport, and their render flag only followed the proxy
    when Mixar's reconciler had run. So the proxy decides both when there is one.
    """
    proxies = [o for o in extras if o.type == "EMPTY"]
    handle = proxies[0] if proxies else source
    try:
        hidden = bool(handle.hide_get())
    except RuntimeError:  # not in the active view layer
        hidden = False
    if not proxies:
        return hidden, bool(source.hide_render)
    return hidden, bool(handle.hide_render or hidden or handle.hide_viewport)


def _replace(source, extras, np):
    cloud = build_splat_from_mesh(source, np)
    name = source.name
    splat = bpy.data.objects.new(name + ".native", cloud)
    for collection in source.users_collection:
        collection.objects.link(splat)
    splat.parent = source.parent
    splat.matrix_world = source.matrix_world.copy()
    splat["wl_role"] = "splat"
    hidden, render_hidden = _visible_world(source, extras)
    splat.hide_render = render_hidden

    for obj in [source] + list(extras):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0 and isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
    splat.name = name
    cloud.name = name
    try:
        splat.hide_set(hidden)
    except RuntimeError:
        pass
    return splat


def _remove_unused_kiri_data() -> None:
    """Drop KIRI node groups and materials nothing uses any more."""
    for collection in (bpy.data.node_groups, bpy.data.materials):
        for block in list(collection):
            if block.name.startswith(_KIRI_PREFIX) and block.users == 0:
                collection.remove(block)


def convert_kiri_splats() -> list:
    """Rebuild every KIRI splat in the open file as a built-in splat.

    Returns the converted objects. Safe to call on any file: without KIRI
    objects it does nothing.
    """
    worlds = find_kiri_worlds()
    if not worlds:
        return []
    import numpy as np

    converted = []
    for source, extras in worlds:
        name = source.name
        try:
            converted.append(_replace(source, extras, np))
        except Exception:  # noqa: BLE001 - one bad world must not strand the rest
            logger.warning("[SplatLegacy] could not convert '%s'", name, exc_info=True)
    _remove_unused_kiri_data()
    _release_lock_interface(converted)
    logger.info("[SplatLegacy] converted %d KIRI splat(s) to built-in splats",
                len(converted))
    return converted


def _release_lock_interface(splats: list) -> None:
    """Undo the Lock Interface Mixar forced on every KIRI splat scene.

    KIRI's render path wrote camera matrices into modifier sockets from a
    frame handler, so splat scenes rendered with the interface locked.
    Built-in splats need nothing of the kind, and a locked interface freezes
    the app for the whole F12 render.
    """
    for scene in {scene for obj in splats for scene in obj.users_scene}:
        if scene.render.use_lock_interface:
            scene.render.use_lock_interface = False
