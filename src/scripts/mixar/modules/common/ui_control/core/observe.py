# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read built UI geometry. Handles are scoped to a short-lived observation."""

import base64
import io
import json
from pathlib import Path
import secrets
import tempfile
import time

import bpy

from ..constants import CONTEXT_TTL, MAX_CONTEXTS, MAX_IMAGE_BYTES, UIError

_contexts = {}


def main_window():
    windows = [w for w in bpy.context.window_manager.windows if not w.screen.is_temporary]
    if not windows:
        raise UIError("not_ready", "Mixar has no document window")
    return max(windows, key=lambda w: w.width * w.height)


def signature():
    win = main_window()
    scene = win.scene
    active = win.view_layer.objects.active
    return (win.as_pointer(), scene.as_pointer(), scene.mixie_session_id,
            bpy.context.window_manager.mixar_ui_generation(),
            active.as_pointer() if active else 0, active.mode if active else "OBJECT",
            tuple(v for row in active.matrix_world for v in row) if active else (),
            tuple((w.as_pointer(), w.screen.as_pointer(), w.width, w.height,
                   w.scene.as_pointer()) for w in bpy.context.window_manager.windows))


def widgets():
    wm = bpy.context.window_manager
    raw = json.loads(wm.mixar_qa_ui_dump)
    wins = {w.as_pointer(): w for w in wm.windows}
    areas, regions = {}, {}
    for win in wins.values():
        for area in [*win.screen.areas, *win.global_areas]:
            areas[area.as_pointer()] = area
            for region in area.regions:
                regions[region.as_pointer()] = region
    result = []
    for item in raw["widgets"]:
        win = wins.get(item["w"])
        if win is None:
            continue
        area, region = areas.get(item["a"]), regions.get(item["r"])
        result.append({**item, "area_type": "POPUP" if item.get("popup") else getattr(area, "type", ""),
                       "region_type": getattr(region, "type", ""),
                       "_win": win, "_area": area, "_region": region})
    return result


def matches(item, query):
    return all(str(item.get(k, "")).casefold() == v.casefold() for k, v in query.items())


def fingerprint(item):
    return tuple(json.dumps(item.get(k), sort_keys=True) for k in (
        "w", "a", "r", "rect", "op", "prop", "prop_owner", "surface", "value", "detail",
        "index", "text", "enabled", "sel", "popup", "type"))


def region_identity(win, area, region):
    view = getattr(area.spaces.active, "region_3d", None)
    matrix = tuple(v for row in view.view_matrix for v in row) if view else ()
    return (win.as_pointer(), area.as_pointer(), region.as_pointer(),
            (region.x, region.y, region.width, region.height), matrix)


def public(item):
    return {key: value for key, value in item.items() if key in {
        "text", "tip", "op", "prop", "prop_owner", "surface", "value", "detail", "index",
        "rect", "enabled", "sel", "popup", "type", "area_type", "region_type"}}


def image(win, items):
    from mixar.modules.common.render_coordinator.core import busy
    if (bpy.context.window_manager.mixar_window_resizing or bpy.app.is_job_running('RENDER')
            or busy()):
        raise UIError("capture_busy", "Wait for rendering or window resize to finish")
    from PIL import Image, ImageDraw
    with tempfile.TemporaryDirectory(prefix="mixar-ui-") as directory:
        path = Path(directory) / "frame.png"
        with bpy.context.temp_override(window=win):
            if not win.mixar_ui_capture(filepath=str(path)):
                raise UIError("capture_unavailable", "Window frame is not ready")
        with Image.open(path) as source:
            frame = source.convert("RGB")
        sx, sy = frame.width / win.width, frame.height / win.height
        draw = ImageDraw.Draw(frame)
        for item in items:
            if item.get("secret") and item["w"] == win.as_pointer():
                x0, y0, x1, y1 = item["rect"]
                draw.rectangle((int(x0*sx), int(frame.height-y1*sy),
                                int(x1*sx), int(frame.height-y0*sy)), fill="black")
        frame.thumbnail((2048, 2048))
        out = io.BytesIO()
        frame.save(out, format="PNG")
    raw = out.getvalue()
    if len(raw) > MAX_IMAGE_BYTES:
        raise UIError("capture_too_large", "Window image exceeds the local image budget")
    return {"type": "image", "mimeType": "image/png", "data": base64.b64encode(raw).decode()}, {
        "width": frame.width, "height": frame.height, "window_width": win.width,
        "window_height": win.height, "origin": "bottom_left"}


def observe(owner, args):
    now = time.monotonic()
    for key in list(_contexts):
        if _contexts[key]["expires"] <= now:
            del _contexts[key]
    if len(_contexts) >= MAX_CONTEXTS:
        del _contexts[next(iter(_contexts))]
    win = main_window()
    items = widgets()
    token = secrets.token_urlsafe(24)
    entry = {"owner": owner, "signature": signature(), "expires": now + CONTEXT_TTL, "targets": {}}
    all_windows = list(bpy.context.window_manager.windows)
    window_ids = {w.as_pointer(): "w%d" % i for i, w in enumerate(all_windows)}
    if args.get("window"):
        candidates = [w for w in all_windows if window_ids[w.as_pointer()] == args["window"]]
        if len(candidates) != 1:
            raise UIError("window_unavailable", "Observe available windows before selecting one")
        win = candidates[0]
    found = [item for item in items if not item.get("secret") and matches(item, args.get("query", {}))]
    targets = []
    for i, item in enumerate(found[:args.get("limit", 100)]):
        handle = "t%d" % i
        entry["targets"][handle] = ("widget", fingerprint(item))
        targets.append({**public(item), "target": handle, "window": window_ids[item["w"]]})
    regions = []
    for window in all_windows:
        for area in window.screen.areas:
            for region in area.regions:
                if region.width < 2 or region.height < 2:
                    continue
                handle = "r%d" % len(regions)
                entry["targets"][handle] = ("region", region_identity(window, area, region))
                regions.append({"target": handle, "window": window_ids[window.as_pointer()],
                                "area_type": area.type, "region_type": region.type,
                                "rect": [region.x, region.y, region.x+region.width, region.y+region.height]})
    _contexts[token] = entry
    result = {"context": token, "session_id": main_window().scene.mixie_session_id,
              "scene_name": main_window().scene.name, "targets": targets,
              "total_targets": len(found), "regions": regions,
              "windows": [{"window": window_ids[w.as_pointer()], "width": w.width, "height": w.height,
                           "scene_name": w.scene.name} for w in all_windows]}
    blocks = []
    if args.get("image"):
        block, result["frame"] = image(win, items)
        blocks.append(block)
    return result, blocks


def resolve(owner, context, target):
    entry = _contexts.get(context)
    if (entry is None or entry["owner"] != owner or entry["expires"] < time.monotonic()
            or entry["signature"] != signature()):
        raise UIError("context_changed", "Observe the current UI before acting")
    spec = entry["targets"].get(target)
    if spec is None:
        raise UIError("target_unavailable", "Target does not belong to this observation")
    kind, identity = spec
    if kind == "widget":
        found = [item for item in widgets() if fingerprint(item) == identity]
        if len(found) != 1 or not found[0].get("enabled", True):
            raise UIError("target_changed", "Control moved, became ambiguous, or is disabled; observe again")
        return found[0]
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            for region in area.regions:
                if region_identity(win, area, region) == identity:
                    return {"_win": win, "_area": area, "_region": region, "_kind": "region",
                            "rect": [region.x, region.y, region.x+region.width, region.y+region.height],
                            "region_type": region.type, "area_type": area.type}
    raise UIError("target_changed", "Editor region changed; observe again")


def invalidate():
    _contexts.clear()
