# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Semantic UI driver — port of the QA harness ``qa_driver.py``.

Widgets come from ``WindowManager.mixar_qa_ui_dump`` (labels, operator
idnames, prop paths, window-space rects); actions are injected with
``Window.event_simulate`` so every interaction runs the real C++ UI path.

Functions that must span main-loop iterations are GENERATORS yielding a delay
in seconds; the pump (``pump.py``) steps them from a ``bpy.app.timers``
callback. Plain functions act instantly.

Mixed mode (the user's live app, no ``--enable-event-simulate``): before a
press the real OS pointer is warped to the click point (``Window.cursor_warp``)
so the user sees the pointer travel; the fork's mixed-mode C++ change accepts
the injected events while ``mixar_agent_input_enabled`` is set.
"""

import json
import time

import bpy

from .constants import (
    DENIED_KEY_COMBOS,
    DENIED_OP_SUFFIXES,
    DENIED_OPS,
    DRAG_STABLE_TICKS,
    ERR_DENIED,
    ERR_INVALID_PARAMS,
    ERR_NO_MATCH,
    ERR_TIMEOUT,
    FIND_RETRY_WINDOW_S,
    QUERY_KEYS,
    SECRET_PROP_RE,
)
from .errors import UIControlError


def _wm():
    return bpy.data.window_managers[0]


def event_simulate_mode() -> bool:
    """True only under a real ``--enable-event-simulate`` launch."""
    return getattr(bpy.app, "use_event_simulate", False) is True


# ---------------------------------------------------------------- dump / find

def query_of(args) -> dict:
    """Keep only recognised query keys (spec §3 widget query)."""
    if not isinstance(args, dict):
        raise UIControlError(ERR_INVALID_PARAMS, "query must be an object")
    return {k: v for k, v in args.items() if k in QUERY_KEYS}


def snapshot():
    """Parse mixar_qa_ui_dump and annotate widgets with bpy-side names.

    Adds: _win (bpy Window), window (ptr), area_type, region_type,
    center [x, y]. Popup widgets get area_type 'POPUP'. Labels of
    secret-bearing fields are blanked.
    """
    wm = _wm()
    raw = json.loads(wm.mixar_qa_ui_dump)
    win_by_ptr, area_by_ptr, region_by_ptr = {}, {}, {}
    for win in wm.windows:
        win_by_ptr[win.as_pointer()] = win
        areas = list(win.screen.areas) + list(getattr(win, "global_areas", []))
        for area in areas:
            area_by_ptr[area.as_pointer()] = area
            for region in area.regions:
                region_by_ptr[region.as_pointer()] = region

    widgets = []
    for w in raw["widgets"]:
        win = win_by_ptr.get(w["w"])
        if win is None:
            continue  # window died between serialize and parse
        w["_win"] = win
        w["window"] = w.pop("w")
        area = area_by_ptr.get(w.pop("a"), None)
        w["_area"] = area
        w["area_type"] = ("POPUP" if w.get("popup") else
                          (area.type if area is not None else f"SPACE_{w['at']}"))
        region = region_by_ptr.get(w.pop("r"), None)
        w["region_type"] = region.type if region is not None else f"RGN_{w['rt']}"
        x0, y0, x1, y1 = w["rect"]
        w["center"] = [int((x0 + x1) / 2), int((y0 + y1) / 2)]
        prop = w.get("prop") or ""
        if prop and SECRET_PROP_RE.search(prop):
            w["text"] = ""
            if "value" in w:
                w["value"] = ""
        widgets.append(w)
    return widgets


def pick_click_point(widget):
    """A point inside the widget's rect that overlapping sibling regions
    (sidebar/tools/header float OVER the canvas and receive events first)
    do not cover. Falls back to the center when fully occluded."""
    x0, y0, x1, y1 = widget["rect"]
    cx, cy = widget["center"]
    area = widget.get("_area")
    if area is None or widget.get("region_type") != "WINDOW":
        return cx, cy
    occluders = [r for r in area.regions
                 if r.type != 'WINDOW' and r.width > 1 and r.height > 1]
    if not occluders:
        return cx, cy

    def free(px, py):
        return not any(r.x <= px < r.x + r.width and r.y <= py < r.y + r.height
                       for r in occluders)

    candidates = [(cx, cy)]
    for fx in (0.5, 0.2, 0.8, 0.06, 0.94):
        for fy in (0.5, 0.25, 0.75):
            candidates.append((x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy))
    for px, py in candidates:
        if x0 <= px <= x1 and y0 <= py <= y1 and free(px, py):
            return int(px), int(py)
    return cx, cy


def _matches(w, text=None, contains=False, op=None, prop=None, prop_owner=None,
             panel=None, area_type=None, region_type=None, but_type=None,
             popup=None, enabled=None, window=None, surface=None, value=None,
             detail=None, index=None):
    if surface is not None and w.get("surface") != surface:
        return False
    if value is not None and w.get("value") != value:
        return False
    if detail is not None and w.get("detail") != detail:
        return False
    if index is not None and w.get("index") != index:
        return False
    if op is not None and w.get("op") != op:
        return False
    if prop is not None and w.get("prop") != prop:
        return False
    if prop_owner is not None and w.get("prop_owner") != prop_owner:
        return False
    if panel is not None and w.get("panel") != panel:
        return False
    if area_type is not None and w.get("area_type") != area_type:
        return False
    if region_type is not None and w.get("region_type") != region_type:
        return False
    if but_type is not None and w.get("type") != but_type:
        return False
    if popup is not None and bool(w.get("popup")) != bool(popup):
        return False
    if enabled is not None and w.get("enabled") != enabled:
        return False
    if window is not None and w.get("window") != window:
        return False
    if text is not None:
        hay = (w.get("text") or "") + "\x00" + (w.get("tip") or "")
        if contains:
            if text.lower() not in hay.lower():
                return False
        else:
            if text.lower() not in (
                (w.get("text") or "").lower(), (w.get("tip") or "").lower()
            ):
                return False
    return True


def find(widgets=None, **query):
    if widgets is None:
        widgets = snapshot()
    return [w for w in widgets if _matches(w, **query)]


def find_one(widgets=None, **query):
    hits = find(widgets, **query)
    if not hits:
        raise UIControlError(ERR_NO_MATCH, f"no widget matches {query}")
    # Prefer enabled widgets and larger hit areas on ambiguity.
    hits.sort(key=lambda w: (not w.get("enabled", True),
                             -(w["rect"][2] - w["rect"][0]) *
                             (w["rect"][3] - w["rect"][1])))
    return hits[0]


def public_widget(w):
    """JSON-serializable copy for wire transport."""
    return {k: v for k, v in w.items() if not k.startswith("_")}


def find_one_steps(query, timeout=None):
    """Generator find_one with a short retry window: a prop edit or tab
    switch tags a re-layout, and for a beat the region's blocks are being
    rebuilt — a single-shot find during that beat misses widgets that are
    genuinely there. Actions resolve through this, not bare find_one."""
    if timeout is None:
        timeout = FIND_RETRY_WINDOW_S
    end = time.monotonic() + timeout
    while True:
        try:
            return find_one(**query)
        except UIControlError as exc:
            if exc.code != ERR_NO_MATCH or time.monotonic() >= end:
                raise
            yield 0.15


# ---------------------------------------------------------------- denylist

def op_denied(op) -> bool:
    if not op:
        return False
    if op in DENIED_OPS:
        return True
    return any(op.endswith(suffix) for suffix in DENIED_OP_SUFFIXES)


def check_widget_allowed(widget):
    if op_denied(widget.get("op")):
        raise UIControlError(ERR_DENIED, f"operator {widget.get('op')!r} is not allowed")
    return widget


def check_key_allowed(key, shift=False, ctrl=False, alt=False, oskey=False):
    k = str(key or "").upper()
    for mod_name, mod_on in (("ctrl", ctrl), ("alt", alt), ("oskey", oskey)):
        if mod_on and (k, mod_name) in DENIED_KEY_COMBOS:
            raise UIControlError(ERR_DENIED, f"{mod_name}+{k} is not allowed")


# ---------------------------------------------------------------- raw events

# Last simulated pointer position per window ptr. event_simulate writes its
# x/y args into the event unconditionally (default 0,0), so KEY events must
# carry the pointer position too or position-routed hotkeys land at the
# window's bottom-left corner.
_last_xy = {}


def reset_runtime_state():
    """Forget input state tied to windows destroyed by a file reload."""
    _last_xy.clear()


def _pointer_xy(win):
    return _last_xy.get(win.as_pointer(), (win.width // 2, win.height // 2))


def _sim(win, **kw):
    if "x" not in kw:
        kw["x"], kw["y"] = _pointer_xy(win)
    return win.event_simulate(**kw)


def warp_pointer(win, x, y):
    """Mixed mode only: move the REAL OS pointer so the user sees it travel
    and so real-cursor readers agree with the injected event position."""
    if event_simulate_mode():
        return
    try:
        win.cursor_warp(int(x), int(y))
    except Exception:
        pass  # cosmetic; the injected event carries its own position


def move_to(win, x, y):
    _last_xy[win.as_pointer()] = (int(x), int(y))
    _sim(win, type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))


def click_xy_steps(win, x, y, double=False, shift=False, ctrl=False, alt=False):
    """Generator click: move, press and release land on SEPARATE main-loop
    iterations, like real input. Queueing them in one tick makes the first
    click into a freshly-entered area vanish (hover/active-region state and
    the press resolve in the same event burst). ``shift``/``ctrl``/``alt``
    ride on both the press and the release (Shift+click = toggle-select in
    the 3D viewport)."""
    x, y = int(x), int(y)
    mods = {"shift": bool(shift), "ctrl": bool(ctrl), "alt": bool(alt)}
    # Approach from an offset first so two sequential targeted clicks are
    # never mistaken for a double-click on the same spot.
    warp_pointer(win, x - 4, y)
    move_to(win, x - 4, y)
    yield 0.05
    warp_pointer(win, x, y)
    move_to(win, x, y)
    _last_xy[win.as_pointer()] = (x, y)
    yield 0.05
    reps = 2 if double else 1
    for _ in range(reps):
        _sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y, **mods)
        yield 0.03
        _sim(win, type='LEFTMOUSE', value='RELEASE', x=x, y=y, **mods)
        yield 0.03


def click_steps(widget, double=False):
    check_widget_allowed(widget)
    x, y = pick_click_point(widget)
    yield from click_xy_steps(widget["_win"], x, y, double)
    return widget


def drag_xy_steps(win, x0, y0, x1, y1, steps=10, shift=False,
                  button='LEFTMOUSE'):
    """Generator drag: press at (x0,y0), interpolated moves (each on its own
    main-loop tick so drag thresholds and modal move handlers see real
    motion), release at (x1,y1). button='MIDDLEMOUSE' pans View2D canvases."""
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    warp_pointer(win, x0, y0)
    move_to(win, x0, y0)
    yield 0.06
    _sim(win, type=button, value='PRESS', x=x0, y=y0, shift=shift)
    yield 0.05
    steps = max(2, int(steps))
    for i in range(1, steps + 1):
        mx = x0 + (x1 - x0) * i // steps
        my = y0 + (y1 - y0) * i // steps
        warp_pointer(win, mx, my)
        move_to(win, mx, my)
        yield 0.03
    _sim(win, type=button, value='RELEASE', x=x1, y=y1, shift=shift)
    _last_xy[win.as_pointer()] = (x1, y1)
    yield 0.05


def drop_file(win, x, y, filepath):
    """Simulated OS file drop (Window.mixar_qa_drop_file)."""
    warp_pointer(win, x, y)
    win.mixar_qa_drop_file(filepath=filepath, x=int(x), y=int(y))


_SHIFTED = {'!': 'ONE', '@': 'TWO', '#': 'THREE', '$': 'FOUR', '%': 'FIVE',
            '^': 'SIX', '&': 'SEVEN', '*': 'EIGHT', '(': 'NINE', ')': 'ZERO',
            '_': 'MINUS', '+': 'EQUAL', '?': 'SLASH', ':': 'SEMI_COLON',
            '"': 'QUOTE', '<': 'COMMA', '>': 'PERIOD'}
_PLAIN = {' ': 'SPACE', '-': 'MINUS', '=': 'EQUAL', '/': 'SLASH',
          ';': 'SEMI_COLON', "'": 'QUOTE', ',': 'COMMA', '.': 'PERIOD',
          '[': 'LEFT_BRACKET', ']': 'RIGHT_BRACKET', '`': 'ACCENT_GRAVE',
          '\\': 'BACK_SLASH'}
_DIGITS = {'0': 'ZERO', '1': 'ONE', '2': 'TWO', '3': 'THREE', '4': 'FOUR',
           '5': 'FIVE', '6': 'SIX', '7': 'SEVEN', '8': 'EIGHT', '9': 'NINE'}


def key_for_char(ch):
    """(event type, shift) for one typeable ASCII character."""
    if ch.isalpha() and ch.isascii():
        return ch.upper(), ch.isupper()
    if ch in _DIGITS:
        return _DIGITS[ch], False
    if ch in _PLAIN:
        return _PLAIN[ch], False
    if ch in _SHIFTED:
        return _SHIFTED[ch], True
    raise UIControlError(ERR_INVALID_PARAMS, f"no key mapping for {ch!r} (ASCII only)")


def type_char(win, ch):
    etype, shift = key_for_char(ch)
    _sim(win, type=etype, value='PRESS', unicode=ch, shift=shift)
    _sim(win, type=etype, value='RELEASE', shift=shift)


def type_text(win, text):
    for ch in text:
        key_for_char(ch)  # validate the whole string before typing any of it
    for ch in text:
        type_char(win, ch)


def press(win, key, shift=False, ctrl=False, alt=False, oskey=False):
    check_key_allowed(key, shift=shift, ctrl=ctrl, alt=alt, oskey=oskey)
    _sim(win, type=key, value='PRESS', shift=shift, ctrl=ctrl, alt=alt, oskey=oskey)
    _sim(win, type=key, value='RELEASE', shift=shift, ctrl=ctrl, alt=alt, oskey=oskey)


def main_window():
    return max(_wm().windows, key=lambda w: len(w.screen.areas))


def focus_area_steps(area_type, region_type="WINDOW"):
    """Generator: move the pointer (warping the real cursor in mixed mode) into
    the largest editor area of ``area_type`` in the main window, at a point of
    its ``region_type`` region not covered by overlapping sibling regions
    (sidebar/tool/header regions float over the WINDOW region and would steal
    hotkeys). Blender routes keystrokes by pointer position, so this is what
    makes Shift+A / Tab / E / G / R / S reach the 3D viewport. No click."""
    win = main_window()
    areas = [a for a in win.screen.areas if a.type == area_type]
    if not areas:
        raise UIControlError(ERR_NO_MATCH, f"no {area_type} area in the main window")
    area = max(areas, key=lambda a: a.width * a.height)
    region = next((r for r in area.regions if r.type == region_type and r.width > 1), None)
    if region is None:
        raise UIControlError(ERR_NO_MATCH, f"{area_type} has no {region_type} region")
    x0, y0 = region.x, region.y
    x1, y1 = region.x + region.width, region.y + region.height
    occluders = [r for r in area.regions
                 if r.type != region_type and r.width > 1 and r.height > 1]

    def free(px, py):
        return not any(r.x <= px < r.x + r.width and r.y <= py < r.y + r.height
                       for r in occluders)

    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    candidates = [(cx, cy)]
    for fx in (0.5, 0.35, 0.65, 0.2, 0.8):
        for fy in (0.5, 0.35, 0.65, 0.25, 0.75):
            candidates.append((int(x0 + (x1 - x0) * fx), int(y0 + (y1 - y0) * fy)))
    px, py = next(((a, b) for a, b in candidates if free(a, b)), (cx, cy))
    warp_pointer(win, px, py)
    move_to(win, px, py)
    yield 0.05
    return {"area_type": area_type, "region_type": region_type,
            "rect": [x0, y0, x1, y1], "point": [px, py],
            "window": win.as_pointer()}


def window_for(args):
    ptr = (args or {}).get("window")
    if ptr:
        for win in _wm().windows:
            if win.as_pointer() == ptr:
                return win
        raise UIControlError(ERR_NO_MATCH, f"no window with ptr {ptr}")
    return main_window()


# ---------------------------------------------------------------- generators

def wait_expr(pred, timeout, what="condition", interval=0.15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except Exception:
            pass
        yield interval
    raise UIControlError(ERR_TIMEOUT, f"timeout ({timeout}s) waiting for {what}")


def choose(query, item_text, contains=False):
    """Generator: open a dropdown (enum/menu widget matching `query`), wait
    for its popup, click the item labelled `item_text`. The N-panel staple:
    choose({'prop': 'p_aspect_ratio'}, '16:9')."""
    widget = yield from find_one_steps(query)
    yield from click_steps(widget)
    yield from wait_expr(
        lambda: bool(find(popup=True, text=item_text, contains=contains)),
        4, f"dropdown item {item_text!r}", interval=0.1)
    item = find_one(popup=True, text=item_text, contains=contains)
    yield from click_steps(item)
    yield 0.15
    return {"chose": item_text, "widget": public_widget(widget)}


def set_text(query, text, enter=True):
    """Generator: click a text/number field, select-all, retype. `enter`
    commits with RET (fields with Enter-submit semantics may act on it —
    pass enter=False and click elsewhere to just blur-commit)."""
    for ch in text:
        key_for_char(ch)
    widget = yield from find_one_steps(query)
    win = widget["_win"]
    yield from click_steps(widget)
    yield 0.2
    press(win, 'A', ctrl=True)
    press(win, 'BACK_SPACE')
    yield 0.1
    type_text(win, text)
    yield 0.15
    if enter:
        press(win, 'RET')
        yield 0.1
    return {"typed": text, "widget": public_widget(widget)}


def _chat_state():
    scene = main_window().scene
    return getattr(scene, "mixie_chat_state", "?")


def wait_until(until, timeout):
    """Generator: the ``ui.wait`` DSL — no arbitrary code.

    until: {"widget_present": query} | {"widget_absent": query}
         | {"widget_sel": {"query": query, "sel": bool}} | {"chat_state": str}
    """
    if not isinstance(until, dict) or len(until) != 1:
        raise UIControlError(ERR_INVALID_PARAMS, "until must hold exactly one condition")
    (kind, spec), = until.items()
    if kind == "widget_present":
        q = query_of(spec)
        pred, what = (lambda: bool(find(**q))), f"widget {q}"
    elif kind == "widget_absent":
        q = query_of(spec)
        pred, what = (lambda: not find(**q)), f"absence of widget {q}"
    elif kind == "widget_sel":
        if not isinstance(spec, dict):
            raise UIControlError(ERR_INVALID_PARAMS, "widget_sel needs {query, sel}")
        q = query_of(spec.get("query"))
        want = bool(spec.get("sel", True))
        pred = lambda: any(bool(w.get("sel")) == want for w in find(**q))  # noqa: E731
        what = f"widget {q} sel={want}"
    elif kind == "chat_state":
        target = str(spec).upper()
        pred, what = (lambda: _chat_state() == target), f"chat state {target}"
    else:
        raise UIControlError(ERR_INVALID_PARAMS, f"unknown wait condition {kind!r}")
    t0 = time.monotonic()
    yield from wait_expr(pred, float(timeout), what)
    return {"seconds": round(time.monotonic() - t0, 2)}


def _resolve_endpoint(spec, widgets, origin=None):
    if spec is None:
        raise UIControlError(ERR_INVALID_PARAMS, "drag needs 'from' and 'to'")
    if isinstance(spec, dict) and "dx" in spec and "dy" in spec:
        if origin is None:
            raise UIControlError(ERR_INVALID_PARAMS, "relative endpoint only valid for 'to'")
        win, x, y = origin
        return win, int(x + int(spec["dx"])), int(y + int(spec["dy"])), None
    w = find_one(widgets=widgets, **query_of(spec))
    x, y = pick_click_point(w)
    return w["_win"], x, y, w


def drag(from_spec, to_spec, steps=10, shift=False, button='LEFTMOUSE'):
    """Generator: resolve both endpoints from ONE dump, require the
    coordinates to survive two UI ticks (a redraw can rebuild custom-surface
    targets mid-flight), then drag."""
    if button not in ('LEFTMOUSE', 'MIDDLEMOUSE'):
        raise UIControlError(ERR_INVALID_PARAMS, "button must be LEFTMOUSE or MIDDLEMOUSE")
    deadline = time.monotonic() + 3.0
    previous = None
    stable = 0
    while True:
        try:
            widgets = snapshot()
            src = _resolve_endpoint(from_spec, widgets)
            dst = _resolve_endpoint(to_spec, widgets, origin=src[:3])
        except UIControlError as exc:
            if exc.code != ERR_NO_MATCH or time.monotonic() >= deadline:
                raise
            yield 0.15
            continue
        signature = (src[0].as_pointer(), src[1], src[2], dst[0].as_pointer(), dst[1], dst[2])
        if signature == previous:
            stable += 1
            if stable >= DRAG_STABLE_TICKS:
                break
        else:
            stable = 0
            previous = signature
        if time.monotonic() >= deadline:
            raise UIControlError(ERR_TIMEOUT, "drag endpoints did not settle")
        yield 0.1
    if src[0].as_pointer() != dst[0].as_pointer():
        raise UIControlError(ERR_INVALID_PARAMS, "drag endpoints must share a window")
    if src[3] is not None:
        check_widget_allowed(src[3])
    if dst[3] is not None:
        check_widget_allowed(dst[3])
    yield from drag_xy_steps(src[0], src[1], src[2], dst[1], dst[2],
                             steps=steps, shift=shift, button=button)
    return {"from_widget": public_widget(src[3]) if src[3] else None,
            "to_widget": public_widget(dst[3]) if dst[3] else None,
            "from": [src[1], src[2]], "to": [dst[1], dst[2]]}


def popup_summary(limit=3):
    """(count, first labels) of open popup widgets — for ui.state and hygiene."""
    pops = find(popup=True)
    labels = [(w.get("text") or "") for w in pops if (w.get("text") or "").strip()][:limit]
    return len(pops), labels


def dismiss_foreign_popups_steps(max_rounds=3):
    """Generator: Esc until no popup is open. A stale menu, Mixar's mode-chooser
    splash or an F9 panel left open holds keyboard focus and silently eats every
    key routed to the viewport (a whole live run was lost that way). Actions
    call this BEFORE their first input; callers that intend to click INSIDE a
    popup (ui.click with popup=true, choose) must not."""
    dismissed = 0
    for _ in range(max_rounds):
        count, _labels = popup_summary()
        if not count:
            break
        press(main_window(), 'ESC')
        dismissed += 1
        yield 0.06
        yield 0.06
    return dismissed
