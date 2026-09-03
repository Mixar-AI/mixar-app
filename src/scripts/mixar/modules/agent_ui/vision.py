# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Screenshots for the agent — port of the QA harness ``qa_vision.py``.

``snap_steps`` is a generator (the pump steps it): tag every area for a
redraw, wait one tick, capture the target window with a window-only context
override, crop to an area / widget (+margin) or draw annotation boxes with a
legend, downscale to ``max_edge`` and return base64 bytes.

Widget rects (and wm events) are NATIVE pixels — the same space as the
screenshot framebuffer — so crops need no scaling. bpy pixel rows are
bottom-up, matching window coordinates.
"""

import base64
import os
import tempfile

import bpy
import numpy as np

from . import driver as drv
from .constants import (
    ERR_INVALID_PARAMS,
    ERR_NO_MATCH,
    SNAP_FRAMES,
    SNAP_JPEG_QUALITY,
    SNAP_MAX_EDGE_DEFAULT,
    SNAP_VIEWS,
)
from .errors import UIControlError

_COLORS = [(1.0, 0.25, 0.25), (0.25, 1.0, 0.4), (0.3, 0.55, 1.0),
           (1.0, 0.85, 0.2), (1.0, 0.35, 1.0), (0.3, 1.0, 1.0)]
_COLOR_NAMES = ["red", "green", "blue", "yellow", "magenta", "cyan"]
_BORDER = 4  # px at image scale


def _capture(win, path):
    # Agent Bubble / pill windows own temporary screens. Blender rejects an
    # explicit temporary-screen override, but a window-only override derives
    # the correct screen/area context and captures that window normally.
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=path)
    return path


def _load_pixels(path):
    img = bpy.data.images.load(path)
    try:
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    finally:
        bpy.data.images.remove(img)
    return px


def _save_png(px, path):
    h, w = px.shape[:2]
    name = "__agent_ui_snap"
    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, width=w, height=h, alpha=True)
    img.pixels[:] = px.ravel()
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)
    return path


def _rect_to_img(rect, w, h, margin=0):
    x0 = max(0, int(rect[0]) - margin)
    y0 = max(0, int(rect[1]) - margin)
    x1 = min(w, int(rect[2]) + margin)
    y1 = min(h, int(rect[3]) + margin)
    return x0, y0, x1, y1


def _draw_border(px, x0, y0, x1, y1, color):
    r, g, b = color
    b_ = _BORDER
    for ys, xs in ((slice(y0, y1), slice(x0, min(x0 + b_, x1))),
                   (slice(y0, y1), slice(max(x1 - b_, x0), x1)),
                   (slice(y0, min(y0 + b_, y1)), slice(x0, x1)),
                   (slice(max(y1 - b_, y0), y1), slice(x0, x1))):
        px[ys, xs, :3] = (r, g, b)
        px[ys, xs, 3] = 1.0


def _legend_name(w):
    for key in ("surface", "op", "prop", "panel"):
        if w.get(key):
            extra = f" '{w['text'][:28]}'" if w.get("text") else ""
            return f"{key}={w[key]}{extra}"
    return f"text='{(w.get('text') or '?')[:36]}'"


def encode_pixels(px, max_edge=SNAP_MAX_EDGE_DEFAULT):
    """RGBA float32 rows-bottom-up -> (base64, mime, width, height).

    JPEG via Pillow when available (downscaled to max_edge); otherwise a PNG
    written through bpy at native size.
    """
    h, w = px.shape[:2]
    try:
        from PIL import Image as PILImage
    except Exception:
        PILImage = None
    if PILImage is not None:
        rgb = np.clip(px[::-1, :, :3] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        image = PILImage.fromarray(np.ascontiguousarray(rgb), mode="RGB")
        edge = max(w, h)
        if max_edge and edge > max_edge:
            scale = max_edge / float(edge)
            image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        import io
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=SNAP_JPEG_QUALITY)
        return (base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg",
                image.width, image.height)
    fd, path = tempfile.mkstemp(prefix="agent_ui_snap_", suffix=".png")
    os.close(fd)
    try:
        _save_png(np.ascontiguousarray(px), path)
        with open(path, "rb") as fh:
            data = fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return base64.b64encode(data).decode("ascii"), "image/png", w, h


# View / framing keys pressed with the pointer in the 3D viewport (spec §11.3).
# (key, ctrl): ctrl flips a numpad view to its opposite side.
VIEW_KEYS = {
    "front": ("NUMPAD_1", False), "back": ("NUMPAD_1", True),
    "right": ("NUMPAD_3", False), "left": ("NUMPAD_3", True),
    "top": ("NUMPAD_7", False), "bottom": ("NUMPAD_7", True),
    "persp": ("NUMPAD_5", False),  # only pressed when the view is orthographic
}
FRAME_KEYS = {"selected": "NUMPAD_PERIOD", "all": "HOME"}


def view_keys(view, frame, is_perspective=True):
    """Ordered (key, ctrl) presses for ``view``/``frame``; validates names."""
    keys = []
    if frame and frame != "none":
        if frame not in SNAP_FRAMES:
            raise UIControlError(ERR_INVALID_PARAMS, f"frame must be one of {SNAP_FRAMES}")
        keys.append((FRAME_KEYS[frame], False))
    if view:
        if view not in SNAP_VIEWS:
            raise UIControlError(ERR_INVALID_PARAMS, f"view must be one of {SNAP_VIEWS}")
        key, ctrl = VIEW_KEYS[view]
        if view != "persp" or not is_perspective:
            keys.append((key, ctrl))
    return keys


def _is_perspective():
    try:
        from .geometry import view3d_region
        _win, _area, _region, rv3d = view3d_region()
        return bool(getattr(rv3d, "is_perspective", True))
    except Exception:
        return True


def _view_steps(view, frame):
    """Generator: press the view/frame keys in the viewport without smooth-view
    animation so the capture that follows shows the settled view."""
    keys = view_keys(view, frame, _is_perspective())
    if not keys:
        return
    yield from drv.focus_area_steps("VIEW_3D")
    win = drv.main_window()
    prefs = getattr(getattr(bpy.context, "preferences", None), "view", None)
    old_smooth = getattr(prefs, "smooth_view", None)
    try:
        if prefs is not None and old_smooth is not None:
            prefs.smooth_view = 0
        for key, ctrl in keys:
            drv.press(win, key, ctrl=ctrl)
            yield 0.05
        for _ in range(3):
            yield 0.05
    finally:
        if prefs is not None and old_smooth is not None:
            try:
                prefs.smooth_view = old_smooth
            except Exception:
                pass


def snap_steps(params):
    """Generator: {area?, query?, margin?, annotate?, max_edge?} -> result."""
    area_type = params.get("area")
    target_q = params.get("query")
    annotate_q = params.get("annotate")
    margin = int(params.get("margin", 40))
    max_edge = int(params.get("max_edge", SNAP_MAX_EDGE_DEFAULT))

    view = str(params.get("view") or "").lower() or None
    frame = str(params.get("frame") or "none").lower()
    # Pressing view/frame keys injects input: the service gates enablement
    # (spec §11.3) — validate names here so a bad request fails before input.
    view_keys(view, frame, True)
    if view or frame != "none":
        yield from _view_steps(view, frame)

    target_query = drv.query_of(target_q) if target_q else None
    widgets = drv.snapshot()
    if target_query:
        target = drv.find_one(widgets, **target_query)
        win = target["_win"]
    else:
        win = drv.main_window()

    # Temp windows are not guaranteed to repaint while another window owns
    # focus: force one main-loop redraw before reading the framebuffer.
    for w in drv._wm().windows:
        for area in w.screen.areas:
            area.tag_redraw()
    yield 0.1

    fd, path = tempfile.mkstemp(prefix="agent_ui_cap_", suffix=".png")
    os.close(fd)
    try:
        _capture(win, path)
        px = _load_pixels(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    # Capturing can complete a pending custom-surface layout; refresh
    # geometry so crops/annotations describe the captured pixels.
    widgets = drv.snapshot()
    target = None
    if target_query:
        target_query["window"] = win.as_pointer()
        target = drv.find_one(widgets, **target_query)

    result = {"window": win.as_pointer(), "view": view, "frame": frame}
    h, w = px.shape[:2]

    if annotate_q is not None:
        query = drv.query_of(annotate_q) if isinstance(annotate_q, dict) else {}
        hits = [x for x in drv.find(widgets, **query) if x["window"] == win.as_pointer()]
        legend = []
        for i, widget in enumerate(hits[:48]):
            color = _COLORS[i % len(_COLORS)]
            x0, y0, x1, y1 = _rect_to_img(widget["rect"], w, h)
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            _draw_border(px, x0, y0, x1, y1, color)
            legend.append({"color": _COLOR_NAMES[i % len(_COLORS)],
                           "what": _legend_name(widget),
                           "center": widget["center"]})
        result["legend"] = legend

    crop_rect = None
    if target is not None:
        crop_rect = _rect_to_img(target["rect"], w, h, margin)
        result["target"] = drv.public_widget(target)
    elif area_type:
        area = next((a for a in list(win.screen.areas) +
                     list(getattr(win, "global_areas", []))
                     if a.type == area_type), None)
        if area is None:
            raise UIControlError(ERR_NO_MATCH, f"no {area_type} area in captured window")
        crop_rect = _rect_to_img(
            [area.x, area.y, area.x + area.width, area.y + area.height], w, h)
    if crop_rect is not None:
        x0, y0, x1, y1 = crop_rect
        px = px[y0:y1, x0:x1]
        result["cropped_to"] = [x0, y0, x1, y1]

    b64, mime, width, height = encode_pixels(np.ascontiguousarray(px), max_edge)
    result.update({"image_b64": b64, "mime": mime, "width": width, "height": height})
    return result
