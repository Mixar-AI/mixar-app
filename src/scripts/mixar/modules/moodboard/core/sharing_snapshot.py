# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Portable board content. Only explicit canvas data leaves the project."""
import base64
import copy
import json
import io
import uuid

import bpy
from PIL import Image

from . import clipboard_snapshot as clipboard
from . import node_duplicate
from .node_graph import ensure_media_node_ids
from mixar.modules.common.utils.image_utils import image_to_png_bytes, load_image_from_base64

FRAME_FIELDS = ("name", "position_x", "position_y", "width", "height", "palette_index",
                "use_custom_color", "custom_color", "locked", "collapsed")


def capture(scene):
    """Snapshot the whole board, without changing the user's selection."""
    ensure_media_node_ids(scene)
    nodes = [n for n in scene.mixie_moodboard_action_nodes
             if n.action_type not in node_duplicate.UNCOPYABLE_ACTION_TYPES]
    node_ids = {n.node_id for n in nodes}
    media = [m for m in scene.mixie_moodboard_images if m.image and m.embedded_node_id not in node_ids]
    if any(m.image.source == 'MOVIE' for m in scene.mixie_moodboard_images if m.image):
        raise ValueError("Video sharing is not available yet. Share a board with still images instead")
    if scene.mixie_moodboard_asset_nodes:
        raise ValueError("Mesh cards stay in your project. Remove them from this board before sharing")
    payload = {
        "version": 1,
        "media": [clipboard._serialize_media(m) for m in media],
        "textboxes": [clipboard._serialize_textbox(t) for t in scene.mixie_moodboard_textboxes],
        "nodes": [node_duplicate.serialize_node(scene, n) for n in nodes],
        "links": clipboard._serialize_links(scene, node_ids, node_ids | {m.node_id for m in media}),
        "frames": [dict(frame_id=f.frame_id, **{k: clipboard._plain(getattr(f, k)) for k in FRAME_FIELDS})
                   for f in scene.mixie_moodboard_frames],
        "annotations": clipboard._serialize_annotations(type("Board", (), {"annotations": scene.mixie_moodboard_annotations})()),
    }
    payload["links"] = [link for link in payload["links"] if link["internal"]]
    for key, originals in (("media", media), ("textboxes", scene.mixie_moodboard_textboxes), ("nodes", nodes)):
        for data, original in zip(payload[key], originals):
            data["frame_id"] = getattr(original, "frame_id", "")
    for node in payload["nodes"]:
        if node["result"]:
            # Provider errors and local result names do not belong to a share.
            node["result"]["error"] = ""
            node["result"]["result_names"] = ""
    names = clipboard.referenced_image_names(payload)
    remap = {name: f"a{i}" for i, name in enumerate(names)}
    assets, total, pixels = [], 0, 0
    for name in names:
        image = bpy.data.images.get(name)
        if image is None:
            raise ValueError("A board image is missing. Restore it before sharing")
        count = image.size[0] * image.size[1]
        pixels += count
        if count > 32_000_000 or pixels > 64_000_000:
            raise ValueError("Use images below 32 megapixels each and 64 megapixels total")
        raw = image_to_png_bytes(image)
        total += len(raw)
        if len(raw) > 16 * 1024 * 1024 or total > 32 * 1024 * 1024 or len(names) > 100:
            raise ValueError("Use up to 100 images, 16 MB each and 32 MB total")
        assets.append({"id": remap[name], "data": base64.b64encode(raw).decode()})
    for media_data in payload["media"]:
        media_data["image_name"] = remap[media_data["image_name"]]
    for data, item in zip(payload['media'], media):
        if item.scene_node:
            data['scene_title'] = item.source_scene.name if item.source_scene else item.scene_title
    for node in payload["nodes"]:
        result = node.get("result")
        if result:
            result["preview_image_name"] = remap[result["preview_image_name"]]
            for media_data in result["media"]:
                media_data["image_name"] = remap[media_data["image_name"]]
    return {"snapshot": payload, "assets": assets}


def validate_bundle(bundle):
    """Check before allocating datablocks; unknown versions fail closed."""
    snapshot = bundle.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
        raise ValueError("Update Mixar to open this moodboard")
    if len(json.dumps(snapshot, allow_nan=False)) > 2 * 1024 * 1024:
        raise ValueError("Moodboard layout is too large")
    assets = bundle.get("assets", [])
    if len(assets) > 100 or len({a["id"] for a in assets}) != len(assets):
        raise ValueError("Invalid moodboard images")
    names = set(clipboard.referenced_image_names(snapshot))
    if names != {a["id"] for a in assets}:
        raise ValueError("This moodboard has missing images")
    return snapshot


def restore(bundle):
    """Build an independent scene transactionally; never touch the active board."""
    snapshot = validate_bundle(bundle)
    scene = bpy.data.scenes.new(bundle.get("title", "Shared Moodboard")[:120])
    loaded = {}
    try:
        total, pixels = 0, 0
        for asset in bundle.get("assets", []):
            if len(asset['data']) > 24 * 1024 * 1024:
                raise ValueError("Moodboard image is too large")
            raw = base64.b64decode(asset["data"], validate=True)
            total += len(raw)
            if len(raw) > 16 * 1024 * 1024 or total > 32 * 1024 * 1024:
                raise ValueError("Moodboard images are too large")
            with Image.open(io.BytesIO(raw)) as info:
                count = info.width * info.height
                pixels += count
                if info.format not in {'PNG', 'JPEG', 'WEBP'} or count > 32_000_000 or pixels > 64_000_000:
                    raise ValueError("Moodboard image dimensions are too large")
                info.verify()
            loaded[asset["id"]] = load_image_from_base64(asset["data"], "Shared reference")
        id_map, made_nodes = {}, []
        frames = {}
        for data in snapshot.get("frames", []):
            frame = scene.mixie_moodboard_frames.add()
            frame.frame_id = uuid.uuid4().hex
            frames[data["frame_id"]] = frame.frame_id
            clipboard._apply_fields(frame, data, FRAME_FIELDS)
        for data in snapshot.get("nodes", []):
            node = node_duplicate.materialize_node(scene, copy.deepcopy(data), (0, 0), loaded.get)
            node.frame_id = frames.get(data.get("frame_id"), "")
            id_map[data["node_id"]] = node.node_id
            made_nodes.append(node)
        for i, data in enumerate(snapshot.get("media", [])):
            item = clipboard._materialize_media(scene, data, loaded[data["image_name"]], (0, 0), i)
            item.frame_id = frames.get(data.get("frame_id"), "")
            id_map[data["node_id"]] = item.node_id
            if data.get('scene_title'):
                item.scene_node, item.scene_title = True, data['scene_title']
                item.image.name = 'Scene · ' + item.scene_title
        for i, data in enumerate(snapshot.get("textboxes", [])):
            item = clipboard._materialize_textbox(scene, data, (0, 0), i)
            item.frame_id = frames.get(data.get("frame_id"), "")
        clipboard._recreate_links(scene, snapshot, id_map, made_nodes)
        for data in snapshot.get("annotations", []):
            stroke = scene.mixie_moodboard_annotations.add()
            stroke.color, stroke.width = data["color"], data["width"]
            for x, y in data["points"]:
                point = stroke.points.add()
                point.x, point.y = x, y
        scene["_mixie_moodboard_started"] = True
        scene["_moodboard_source_author"] = bundle.get("author", "")
        scene["_moodboard_source_title"] = bundle.get("title", "")
        return scene
    except Exception:
        bpy.data.scenes.remove(scene)
        for image in loaded.values():
            if image.users == 0:
                bpy.data.images.remove(image)
        raise
