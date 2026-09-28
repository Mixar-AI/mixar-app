# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import a glTF / GLB file into the CURRENT scene only.

Blender's glTF importer creates a new Blender scene for every scene in the
file that is not the file's default one (``io_scene_gltf2/blender/imp/vnode.py``:
``bpy.data.scenes.new(name=scene.name)``). A file that carries several scenes
therefore spawns scene tabs named after those scenes — ``<name>.001`` when a
tab of that name already exists — and each one is empty, because the nodes go
into the active scene's collections. Nodes that are in no scene at all are
imported as well (the importer's "orphan" collection).

Such files are real: the glTF exporter writes EVERY Blender scene unless
``use_active_scene`` is set (client 4.1.1 exported job uploads without it), and
services like Tripo echo the scene list of the upload back in their result. One
mesh job then turned every open tab into a phantom copy, and the next job
copied the copies (``Scene 4.002``).

Every glTF import in the app goes through :func:`import_gltf`:

1. :func:`keep_default_scene` rewrites the file so it holds one scene, the
   default one, and only what that scene reaches: nodes, their meshes, skins
   and animation channels of anything else are pruned, with every index
   reference remapped (a ``.glb`` or a ``.gltf``; materials, accessors and
   buffers are left alone, unreferenced entries there are valid glTF).
2. The import runs; any scene it still created is removed, after its objects
   were linked into the active scene so nothing generated is lost.
3. Both are reported as ``[SCENES] event=import.scenes_stripped``.

The pure part (no ``bpy``) mirrors ``core/gltf_scenes.py`` in mixar-backend,
which applies the same rewrite to job uploads before a provider sees them.
"""

from __future__ import annotations

import json
import os
import struct
from typing import Any, NamedTuple

from mixar.config.logging_config import get_logger

from .scenes_log import slog

logger = get_logger(__name__)

_GLB_MAGIC = 0x46546C67          # b"glTF"
_CHUNK_JSON = 0x4E4F534A         # b"JSON"


class Stripped(NamedTuple):
    scenes: list      # names of the scenes dropped ("" for an unnamed one)
    nodes: list       # names of the nodes dropped (not reachable from the kept scene)

    def __bool__(self) -> bool:
        return bool(self.scenes or self.nodes)


_NOTHING = Stripped([], [])


# =============================================================================
# File sanitising (no bpy)
# =============================================================================

def _index(value, size: int):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < size else None


def _replace_list(doc: dict, key: str, values: list) -> None:
    """glTF arrays, when present, must not be empty."""
    if values:
        doc[key] = values
    else:
        doc.pop(key, None)


def strip_gltf_json(doc: dict) -> Stripped:
    """Keep only the document's default scene and what it reaches. Mutates
    ``doc``; returns what was dropped. A document with one scene and no
    orphan nodes is left untouched."""
    scenes = doc.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return _NOTHING
    default = _index(doc.get("scene"), len(scenes))
    if default is None:
        default = 0
    kept_scene = scenes[default] if isinstance(scenes[default], dict) else {}
    dropped_scenes = [str(s.get("name", "") if isinstance(s, dict) else "")
                      for i, s in enumerate(scenes) if i != default]

    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    roots = [i for i in (kept_scene.get("nodes") or []) if _index(i, len(nodes)) is not None]
    reachable = set()
    stack = list(roots)
    while stack:
        i = stack.pop()
        if i in reachable:
            continue
        reachable.add(i)
        node = nodes[i] if isinstance(nodes[i], dict) else {}
        stack.extend(c for c in (node.get("children") or []) if _index(c, len(nodes)) is not None)
    if len(scenes) == 1 and len(reachable) == len(nodes):
        return _NOTHING

    keep = sorted(reachable)
    node_map = {old: new for new, old in enumerate(keep)}
    dropped_nodes = [str((nodes[i].get("name", "") if isinstance(nodes[i], dict) else ""))
                     for i in range(len(nodes)) if i not in reachable]
    new_nodes = []
    for old in keep:
        node = dict(nodes[old]) if isinstance(nodes[old], dict) else {}
        children = [node_map[c] for c in (node.get("children") or []) if c in node_map]
        if children:
            node["children"] = children
        else:
            node.pop("children", None)
        new_nodes.append(node)

    meshes = doc.get("meshes") if isinstance(doc.get("meshes"), list) else []
    used_meshes = sorted({n["mesh"] for n in new_nodes if _index(n.get("mesh"), len(meshes)) is not None})
    mesh_map = {old: new for new, old in enumerate(used_meshes)}
    for node in new_nodes:
        if "mesh" in node:
            new_mesh = mesh_map.get(node["mesh"]) if isinstance(node["mesh"], int) else None
            if new_mesh is None:
                node.pop("mesh", None)
            else:
                node["mesh"] = new_mesh
    _replace_list(doc, "meshes", [meshes[i] for i in used_meshes])

    skins = doc.get("skins") if isinstance(doc.get("skins"), list) else []
    used_skins = sorted({n["skin"] for n in new_nodes if _index(n.get("skin"), len(skins)) is not None})
    new_skins, skin_map = [], {}
    for old in used_skins:
        skin = dict(skins[old]) if isinstance(skins[old], dict) else {}
        joints = [node_map[j] for j in (skin.get("joints") or []) if j in node_map]
        if not joints:
            continue
        skin["joints"] = joints
        skeleton = skin.get("skeleton")
        if skeleton in node_map:
            skin["skeleton"] = node_map[skeleton]
        else:
            skin.pop("skeleton", None)
        skin_map[old] = len(new_skins)
        new_skins.append(skin)
    for node in new_nodes:
        if "skin" in node:
            new_skin = skin_map.get(node["skin"]) if isinstance(node["skin"], int) else None
            if new_skin is None:
                node.pop("skin", None)
            else:
                node["skin"] = new_skin
    _replace_list(doc, "skins", new_skins)

    animations = doc.get("animations") if isinstance(doc.get("animations"), list) else []
    new_animations = []
    for animation in animations:
        if not isinstance(animation, dict):
            continue
        channels = []
        for channel in animation.get("channels") or []:
            target = channel.get("target") if isinstance(channel, dict) else None
            if not isinstance(target, dict):
                continue
            node_index = target.get("node")
            if node_index is None:
                channels.append(channel)
            elif node_index in node_map:
                channel = dict(channel)
                channel["target"] = dict(target, node=node_map[node_index])
                channels.append(channel)
        if channels:
            animation = dict(animation)
            animation["channels"] = channels
            new_animations.append(animation)
    _replace_list(doc, "animations", new_animations)

    kept_scene = dict(kept_scene)
    scene_nodes = [node_map[i] for i in roots if i in node_map]
    if scene_nodes:
        kept_scene["nodes"] = scene_nodes
    else:
        kept_scene.pop("nodes", None)
    doc["scenes"] = [kept_scene]
    doc["scene"] = 0
    _replace_list(doc, "nodes", new_nodes)
    return Stripped(dropped_scenes, dropped_nodes)


def _read_glb(data: bytes):
    """(header_version, json_doc, remaining_chunks_bytes) or None if not a GLB."""
    if len(data) < 20:
        return None
    magic, version, _length = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC:
        return None
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != _CHUNK_JSON or 20 + chunk_len > len(data):
        return None
    doc = json.loads(data[20:20 + chunk_len].decode("utf-8"))
    return version, doc, data[20 + chunk_len:]


def _write_glb(version: int, doc: dict, rest: bytes) -> bytes:
    payload = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    payload += b" " * (-len(payload) % 4)          # JSON chunks pad with spaces
    body = struct.pack("<II", len(payload), _CHUNK_JSON) + payload + rest
    return struct.pack("<III", _GLB_MAGIC, version, 12 + len(body)) + body


def keep_default_scene(filepath: str) -> Stripped:
    """Rewrite ``filepath`` (``.glb`` or ``.gltf``) in place so it holds only its
    default scene and what it reaches. Returns what was dropped; nothing when
    the file was already clean or could not be parsed (the import then proceeds
    unchanged and the post-import guard still applies)."""
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except OSError as error:
        logger.debug("gltf import guard: cannot read %s: %s", filepath, error)
        return _NOTHING
    try:
        glb = _read_glb(data)
        if glb is not None:
            version, doc, rest = glb
            if not isinstance(doc, dict):
                return _NOTHING
            stripped = strip_gltf_json(doc)
            if stripped:
                out = _write_glb(version, doc, rest)
        else:
            doc = json.loads(data.decode("utf-8"))
            if not isinstance(doc, dict):
                return _NOTHING
            stripped = strip_gltf_json(doc)
            if stripped:
                out = json.dumps(doc).encode("utf-8")
        if not stripped:
            return _NOTHING
        tmp = filepath + ".tmp"
        with open(tmp, "wb") as f:
            f.write(out)
        os.replace(tmp, filepath)
        return stripped
    except (ValueError, struct.error, OSError, UnicodeDecodeError, TypeError, AttributeError) as error:
        logger.debug("gltf import guard: %s left unchanged: %s", filepath, error)
        return _NOTHING


# =============================================================================
# Import (main thread, bpy)
# =============================================================================

def _scene_keys(bpy) -> set:
    return {s.as_pointer() for s in bpy.data.scenes}


def _remove_new_scenes(bpy, before: set, active) -> list:
    """Drop every scene not in ``before``. Objects only they hold are linked
    into ``active`` first, so a generated object is never lost."""
    removed = []
    for scene in [s for s in bpy.data.scenes if s.as_pointer() not in before]:
        if scene is active:
            continue
        for obj in list(scene.objects):
            if active is not None and obj.name not in active.objects:
                try:
                    active.collection.objects.link(obj)
                except RuntimeError:
                    pass
        name = scene.name
        try:
            bpy.data.scenes.remove(scene, do_unlink=True)
            removed.append(name)
        except Exception as error:  # noqa: BLE001 — never fail the import over cleanup
            logger.warning("gltf import guard: could not remove scene %r: %s", name, error)
    return removed


def import_gltf(filepath: str, **kwargs: Any):
    """``bpy.ops.import_scene.gltf`` confined to the current scene. Returns the
    operator's result set. ``kwargs`` go to the operator unchanged."""
    import bpy  # noqa: PLC0415 — main-thread only, keeps the module importable in tests

    stripped = keep_default_scene(filepath)
    active = bpy.context.scene
    before = _scene_keys(bpy)
    try:
        return bpy.ops.import_scene.gltf(filepath=filepath, **kwargs)
    finally:
        removed = _remove_new_scenes(bpy, before, active)
        if stripped or removed:
            slog("import.scenes_stripped", active, file=os.path.basename(filepath),
                 in_file=stripped.scenes, orphan_nodes=stripped.nodes, created=removed)
            logger.warning(
                "glTF import confined to scene %r: %s dropped %d extra scene(s) and %d orphan node(s); "
                "%d scene(s) the importer created removed: %s",
                getattr(active, "name", "?"), os.path.basename(filepath), len(stripped.scenes),
                len(stripped.nodes), len(removed), removed or stripped.scenes or stripped.nodes,
            )
