# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actions yield to Blender between event phases and never dispatch operators."""

import sys
import time

import bpy

from ..constants import UIError
from . import observe, ownership


def occlusion_rects(item):
    # Popup regions intercept events before ordinary area regions.
    if not item.get("popup"):
        for other in observe.widgets():
            if other.get("popup") and other["w"] == item["_win"].as_pointer():
                raise UIError("popup_active", "Close or act on the current popup first")
    occluders = []
    if item.get("region_type") == "WINDOW" and item.get("_area"):
        area = item["_area"]
        for region in area.regions:
            if region.type == "WINDOW" or region.width < 2 or region.height < 2:
                continue
            # Zen's transparent TOOL_HEADER spans the viewport. Its native
            # handlers intercept drawn controls, not that whole rectangle.
            if (area.type == "VIEW_3D" and region.type == "TOOL_HEADER"
                    and region.height > area.height / 2):
                occluders.extend(w["rect"] for w in observe.widgets()
                                 if w.get("r") == region.as_pointer())
            else:
                occluders.append((region.x, region.y, region.x+region.width, region.y+region.height))
    return occluders


def point(item):
    x0, y0, x1, y1 = item["rect"]
    if x1 <= x0 or y1 <= y0:
        raise UIError("target_hidden", "The target has no visible geometry")
    occluders = occlusion_rects(item)
    for fx, fy in [(0.5, 0.5), (0.2, 0.5), (0.8, 0.5), (0.5, 0.2), (0.5, 0.8)]:
        x, y = int(x0 + (x1-x0)*fx), int(y0 + (y1-y0)*fy)
        if not any(left <= x < right and bottom <= y < top for left, bottom, right, top in occluders):
            return x, y
    raise UIError("target_occluded", "Reveal this control before acting")


def event(owner, item, key, value, xy, mods=None, text=""):
    ownership.check(owner)
    pointer = item["_win"].as_pointer()
    wins = [w for w in bpy.context.window_manager.windows if w.as_pointer() == pointer]
    if len(wins) != 1:
        raise UIError("context_changed", "The recipient window closed")
    win = wins[0]
    if win.scene != observe.main_window().scene:
        raise UIError("context_changed", "Target window belongs to another scene")
    with bpy.context.temp_override(window=win):
        if not win.mixar_ui_event(owner=owner, type=key, value=value, text=text,
                                  x=xy[0], y=xy[1], **(mods or {})):
            raise UIError("control_revoked", "Native input refused the action")


def keypress(owner, item, key, xy, mods=None, text=""):
    event(owner, item, key, "PRESS", xy, mods, text)
    yield 0.025
    event(owner, item, key, "RELEASE", xy, mods)
    yield 0.025


def click(owner, item, xy, mods=None):
    # Custom hit-tests use the actual cursor outside QA simulation mode.
    item["_win"].cursor_warp(*xy)
    event(owner, item, "MOUSEMOVE", "NOTHING", xy)
    yield 0.04
    yield from keypress(owner, item, "LEFTMOUSE", xy, mods)


def run(owner, args):
    item = observe.resolve(owner, args["context"], args["target"])
    action, mods = args["action"], args.get("modifiers", {})
    if action == "gesture" and item.get("_kind") != "region":
        raise UIError("invalid_target", "Gestures require an observed editor region")
    xy = point(item)
    ownership.begin(owner)
    if action == "click":
        yield from click(owner, item, xy, mods)
        if args.get("double"):
            event(owner, item, "LEFTMOUSE", "DOUBLE_CLICK", xy, mods)
            yield 0.025
            event(owner, item, "LEFTMOUSE", "RELEASE", xy, mods)
            yield 0.025
    elif action == "press":
        allowed = bpy.types.Event.bl_rna.properties["type"].enum_items.keys()
        if args["key"] not in allowed or not keyboard_key(args["key"]):
            raise UIError("invalid_key", "Use a supported Blender keyboard event")
        item["_win"].cursor_warp(*xy)
        yield from keypress(owner, item, args["key"], xy, mods,
                            keyboard_text(args["key"], mods))
    elif action == "set_text":
        if item.get("type") not in {"Text", "SearchMenu", "Num", "NumSlider"}:
            raise UIError("invalid_target", "Text replacement requires an observed editable field")
        yield from click(owner, item, xy)
        select = {"oskey": True} if sys.platform == "darwin" else {"ctrl": True}
        yield from keypress(owner, item, "A", xy, select)
        yield from keypress(owner, item, "BACK_SPACE", xy)
        for index, char in enumerate(args["text"]):
            if char == "\n":
                yield from keypress(owner, item, "RET", xy, {"shift": True})
            else:
                event(owner, item, "A", "PRESS", xy, text=char)
                event(owner, item, "A", "RELEASE", xy)
                if index % 16 == 15:
                    yield 0.025
        yield 0.04
        if args.get("enter", True):
            yield from keypress(owner, item, "RET", xy)
    elif action == "choose":
        yield from click(owner, item, xy)
        deadline = time.monotonic()+2
        while True:
            hits = [w for w in observe.widgets() if w.get("popup") and
                    w["w"] == item["_win"].as_pointer() and
                    w.get("enabled", True) and w.get("text", "").casefold() == args["item"].casefold()]
            if len(hits) == 1:
                yield from click(owner, hits[0], point(hits[0]))
                break
            if len(hits) > 1 or time.monotonic() >= deadline:
                raise UIError("choice_unavailable", "Choose an unambiguous visible popup item")
            yield 0.05
    elif action == "scroll":
        item["_win"].cursor_warp(*xy)
        for _ in range(abs(args["steps"])):
            event(owner, item, "WHEELUPMOUSE" if args["steps"] > 0 else "WHEELDOWNMOUSE", "PRESS", xy)
            yield 0.04
    elif action == "gesture":
        x0, y0, x1, y1 = item["rect"]
        points = [(int(x0+p[0]*(x1-x0-1)), int(y0+p[1]*(y1-y0-1))) for p in args["points"]]
        obstacles = occlusion_rects(item)
        if any(segment_intersects(a, b, rect) for a, b in zip(points, points[1:]) for rect in obstacles):
            raise UIError("target_occluded", "The gesture crosses an overlapping control or panel")
        button = args.get("button", "LEFTMOUSE")
        item["_win"].cursor_warp(*points[0])
        event(owner, item, "MOUSEMOVE", "NOTHING", points[0], mods)
        yield 0.04
        event(owner, item, button, "PRESS", points[0], mods)
        yield 0.04
        for point_ in points[1:]:
            item["_win"].cursor_warp(*point_)
            event(owner, item, "MOUSEMOVE", "NOTHING", point_, mods)
            yield args.get("duration", 0.5) / len(points)
        event(owner, item, button, "RELEASE", points[-1], mods)
        yield 0.04
    while bpy.context.window_manager.mixar_ui_pending():
        ownership.check(owner)
        yield 0.025
    return {"input_delivered": True, "postcondition_verified": False,
            "note": "Inspect the current state and screenshot to verify the intended result."}


def keyboard_text(key, mods):
    """Match the text accompanying ordinary OS keys (numeric input needs it)."""
    if any(mods.get(modifier) for modifier in ("ctrl", "alt", "oskey")):
        return ""
    shift = mods.get("shift", False)
    if len(key) == 1 and "A" <= key <= "Z":
        return key if shift else key.lower()
    pairs = dict(zip(
        ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"),
        zip("0123456789", ")!@#$%^&*(")))
    pairs.update({"MINUS": ("-", "_"), "EQUAL": ("=", "+"), "PERIOD": (".", ">"),
                  "COMMA": (",", "<"), "SLASH": ("/", "?"), "SPACE": (" ", " "),
                  "SEMI_COLON": (";", ":"), "QUOTE": ("'", '"'),
                  "LEFT_BRACKET": ("[", "{"), "RIGHT_BRACKET": ("]", "}"),
                  "BACK_SLASH": ("\\", "|"), "ACCENT_GRAVE": ("`", "~")})
    if key.startswith("NUMPAD_") and key[-1:].isdigit():
        return key[-1]
    return pairs.get(key, ("", ""))[bool(shift)]


def keyboard_key(key):
    """Only keyboard input, never timers, window drops, or mouse pseudo-events."""
    return (len(key) == 1 and "A" <= key <= "Z") or key in {
        "ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
        "ESC", "TAB", "RET", "SPACE", "BACK_SPACE", "DEL", "INSERT", "HOME", "END",
        "PAGE_UP", "PAGE_DOWN", "LEFT_ARROW", "RIGHT_ARROW", "UP_ARROW", "DOWN_ARROW",
        "ACCENT_GRAVE", "MINUS", "EQUAL", "LEFT_BRACKET", "RIGHT_BRACKET", "BACK_SLASH",
        "SEMI_COLON", "QUOTE", "COMMA", "PERIOD", "SLASH", "PAUSE",
        "NUMPAD_PERIOD", "NUMPAD_SLASH", "NUMPAD_ASTERIX", "NUMPAD_MINUS", "NUMPAD_PLUS",
        "NUMPAD_ENTER", *{"NUMPAD_%d" % i for i in range(10)},
        *{"F%d" % i for i in range(1, 25)},
    }


def segment_intersects(start, end, rect):
    lower, upper = 0.0, 1.0
    for a, b, minimum, maximum in zip(start, end, rect[:2], rect[2:]):
        delta = b-a
        if delta == 0:
            if not minimum <= a <= maximum:
                return False
        else:
            entry, leave = sorted(((minimum-a)/delta, (maximum-a)/delta))
            lower, upper = max(lower, entry), min(upper, leave)
            if lower > upper:
                return False
    return True
