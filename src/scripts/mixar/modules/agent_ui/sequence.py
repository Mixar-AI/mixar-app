# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Batched input, menus and operators for the agent (spec §11.1 / §11.2).

``ui.sequence`` runs a planned list of steps in ONE request with the same
tick separation the single primitives use; the model spends one tool call on
a whole keystroke phrase (``S, Z, 0.1, RET``) instead of four.

``ui.open_menu`` opens a Blender menu by idname as a popup at the pointer
(``wm.call_menu`` under the largest VIEW_3D WINDOW override), because Mixar's
default viewport header carries no Blender menus and F3 is bound to
onboarding. ``ui.run_operator`` invokes ``wm.search_menu`` (falling back to
``wm.search_operator``), types the label, runs the top match with Enter, then presses F9 and reads/sets the
redo ("Adjust Last Operation") popup. Search results are NOT exported
widgets (only the SearchMenu box is), so the F9 label check is what proves
the intended operator ran.
"""

import re

import bpy

from mixar.config.logging_config import get_logger

from . import driver as drv
from .constants import (
    ERR_DENIED,
    ERR_INTERNAL,
    ERR_INVALID_PARAMS,
    ERR_NO_MATCH,
    ERR_OPERATOR_MISMATCH,
    MENU_IDNAME_RE,
    SEQUENCE_MAX_STEPS,
    SEQUENCE_STEP_KINDS,
    SEQUENCE_WAIT_TICKS_MAX,
)
from .errors import UIControlError

logger = get_logger(__name__)

_MODS = ("shift", "ctrl", "alt", "oskey")
_TICK = 0.05


# ------------------------------------------------------------------ sequence

def _step_kind(step):
    """The ONE recognised key of a step object (spec §11.1)."""
    if not isinstance(step, dict) or len(step) != 1:
        raise UIControlError(ERR_INVALID_PARAMS,
                             "each step must be an object with exactly one key")
    kind = next(iter(step))
    if kind not in SEQUENCE_STEP_KINDS:
        raise UIControlError(ERR_INVALID_PARAMS, f"unknown step kind {kind!r}")
    return kind, step[kind]


def validate_steps(steps):
    """Validate EVERY step before any input is injected. Returns a list of
    ``(kind, normalised_payload)``; raises ``invalid_params`` / ``denied``."""
    if not isinstance(steps, list) or not steps:
        raise UIControlError(ERR_INVALID_PARAMS, "steps must be a non-empty list")
    if len(steps) > SEQUENCE_MAX_STEPS:
        raise UIControlError(ERR_INVALID_PARAMS,
                             f"at most {SEQUENCE_MAX_STEPS} steps per sequence")
    plan = []
    for i, step in enumerate(steps):
        kind, body = _step_kind(step)
        if kind == "press":
            if not isinstance(body, dict) or not isinstance(body.get("key"), str) or not body["key"]:
                raise UIControlError(ERR_INVALID_PARAMS, f"step {i}: press needs a key")
            mods = {m: bool(body.get(m)) for m in _MODS}
            drv.check_key_allowed(body["key"], **mods)  # denied
            plan.append((kind, {"key": body["key"], **mods}))
        elif kind == "type":
            if not isinstance(body, str) or not body:
                raise UIControlError(ERR_INVALID_PARAMS, f"step {i}: type needs a non-empty string")
            for ch in body:
                drv.key_for_char(ch)  # ASCII only
            plan.append((kind, body))
        elif kind == "focus_area":
            area = body if isinstance(body, str) and body else "VIEW_3D"
            plan.append((kind, area.upper()))
        elif kind == "click":
            query = drv.query_of(body)
            if not query:
                raise UIControlError(ERR_INVALID_PARAMS,
                                     f"step {i}: click needs at least one widget filter")
            if drv.op_denied(query.get("op")):
                raise UIControlError(ERR_DENIED,
                                     f"step {i}: operator {query.get('op')!r} is not allowed")
            plan.append((kind, query))
        elif kind == "click_geometry":
            if not isinstance(body, dict) or not body.get("object"):
                raise UIControlError(ERR_INVALID_PARAMS,
                                     f"step {i}: click_geometry needs object/element/index")
            plan.append((kind, dict(body)))
        elif kind == "wait_ticks":
            try:
                n = int(body)
            except (TypeError, ValueError):
                raise UIControlError(ERR_INVALID_PARAMS, f"step {i}: wait_ticks must be an integer")
            if n < 1 or n > SEQUENCE_WAIT_TICKS_MAX:
                raise UIControlError(ERR_INVALID_PARAMS,
                                     f"step {i}: wait_ticks must be 1..{SEQUENCE_WAIT_TICKS_MAX}")
            plan.append((kind, n))
        elif kind == "expect_popup":
            query = drv.query_of(body) if body else {}
            plan.append((kind, query))
    return plan


def _run_step(kind, body):
    """Generator executing one validated step with the primitives' helpers."""
    # Pacing: a key that switches mode (Tab), starts a modal (S/E/I) or opens
    # a popup needs a redraw before the NEXT key is routed, and a pointer move
    # needs a tick before the region under it becomes active. Callers should
    # not have to know this, so every step settles on its own.
    if kind == "press":
        win = drv.main_window()
        key = body["key"]
        drv.press(win, key, **{m: body[m] for m in _MODS})
        for _ in range(3):
            yield _TICK
    elif kind == "type":
        drv.type_text(drv.main_window(), body)
        for _ in range(2):
            yield _TICK
    elif kind == "focus_area":
        yield from drv.focus_area_steps(body)
        for _ in range(2):
            yield _TICK
    elif kind == "click":
        w = yield from drv.find_one_steps(body)
        yield from drv.click_steps(w)
    elif kind == "click_geometry":
        from . import geometry
        yield from geometry.click_geometry_steps(body)
    elif kind == "wait_ticks":
        for _ in range(body):
            yield _TICK
    elif kind == "expect_popup":
        if not drv.find(popup=True, **body):
            raise UIControlError(ERR_NO_MATCH, f"no popup widget matches {body}")
        yield _TICK


def sequence_steps(params, on_progress=None):
    """Generator: run all steps, stop at the first failure (rest ``skipped``).

    ``on_progress(results)`` is called after every step so the service can
    keep the partial results if the pump interrupts the generator.
    """
    plan = validate_steps(params.get("steps"))
    results = []
    failed = False
    for i, (kind, body) in enumerate(plan):
        if failed:
            results.append({"step": i, "kind": kind, "ok": False, "skipped": True})
            if on_progress:
                on_progress(results)
            continue
        try:
            yield from _run_step(kind, body)
            results.append({"step": i, "kind": kind, "ok": True})
        except UIControlError as exc:
            results.append({"step": i, "kind": kind, "ok": False,
                            "error": {"code": exc.code, "message": exc.message}})
            failed = True
        except GeneratorExit:
            raise
        except Exception as exc:  # a helper blew up: report, never crash the pump
            logger.error("agent_ui sequence step %d (%s) failed: %r", i, kind, exc)
            results.append({"step": i, "kind": kind, "ok": False,
                            "error": {"code": ERR_INTERNAL, "message": "step failed in the client"}})
            failed = True
        if on_progress:
            on_progress(results)
        yield _TICK
    completed = sum(1 for r in results if r["ok"])
    return {"completed": completed, "results": results, "interrupted": False,
            "ok": not failed}


# ----------------------------------------------------------------- open_menu

def _view3d_override():
    """(win, area, region) of the largest VIEW_3D WINDOW region."""
    win = drv.main_window()
    areas = [a for a in win.screen.areas if a.type == "VIEW_3D"]
    if not areas:
        raise UIControlError(ERR_NO_MATCH, "no VIEW_3D area in the main window")
    area = max(areas, key=lambda a: a.width * a.height)
    region = next((r for r in area.regions if r.type == "WINDOW" and r.width > 1), None)
    if region is None:
        raise UIControlError(ERR_NO_MATCH, "VIEW_3D has no WINDOW region")
    return win, area, region


def split_hotkey(text):
    """Menu item labels carry the shortcut after a '|' ("Inset Faces|I")."""
    text = (text or "").strip()
    if "|" in text:
        label, hotkey = text.split("|", 1)
        return label.strip(), hotkey.strip()
    return text, ""


def _popup_items(widgets):
    items = []
    for w in widgets:
        raw = (w.get("text") or "").strip()
        if not raw and not w.get("op"):
            continue
        text, hotkey = split_hotkey(raw)
        submenu = w.get("type") in ("Pulldown", "Menu") or text.endswith(("▸", "▶"))
        items.append({"text": text, "hotkey": hotkey, "op": w.get("op"),
                      "submenu": bool(submenu), "type": w.get("type")})
    return items


def menu_idname_ok(menu) -> bool:
    return isinstance(menu, str) and bool(MENU_IDNAME_RE.match(menu))


def open_menu_steps(params):
    menu = params.get("menu")
    if not menu_idname_ok(menu):
        raise UIControlError(ERR_INVALID_PARAMS,
                             "menu must be a Blender menu idname like VIEW3D_MT_edit_mesh_faces")
    if getattr(bpy.types, menu, None) is None:
        raise UIControlError(ERR_NO_MATCH, f"no menu named {menu!r} is registered")
    area_type = str(params.get("area_type") or "VIEW_3D").upper()
    yield from drv.focus_area_steps(area_type)
    win, area, region = _view3d_override() if area_type == "VIEW_3D" else _area_override(area_type)
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.wm.call_menu(name=menu)
    except Exception as exc:
        raise UIControlError(ERR_NO_MATCH, f"menu {menu!r} could not be opened: {exc}")
    yield _TICK
    yield _TICK
    widgets = drv.find(popup=True)
    if not widgets:
        raise UIControlError(ERR_NO_MATCH, f"menu {menu!r} opened no popup")
    return {"menu": menu, "items": _popup_items(widgets)}


def _area_override(area_type):
    win = drv.main_window()
    areas = [a for a in win.screen.areas if a.type == area_type]
    if not areas:
        raise UIControlError(ERR_NO_MATCH, f"no {area_type} area in the main window")
    area = max(areas, key=lambda a: a.width * a.height)
    region = next((r for r in area.regions if r.type == "WINDOW" and r.width > 1), None)
    if region is None:
        raise UIControlError(ERR_NO_MATCH, f"{area_type} has no WINDOW region")
    return win, area, region


# -------------------------------------------------------------- run_operator

def _modal_operators():
    """Idnames of modal operators running in any window (empty when none)."""
    names = []
    try:
        for win in drv._wm().windows:
            for m in getattr(win, "modal_operators", []) or []:
                names.append(getattr(m, "bl_idname", str(m)))
    except Exception:
        pass
    return names


def _norm_label(text) -> str:
    text, _hotkey = split_hotkey(text)
    text = re.sub(r"\.\.\.$|…$", "", text).strip()
    return re.sub(r"\s+", " ", text).lower()


def _redo_fields(widgets):
    fields = []
    for w in widgets:
        if w.get("prop"):
            fields.append({"prop": w["prop"], "type": w.get("type"),
                           "text": w.get("text") or "", "sel": w.get("sel")})
    return fields


def _validate_settings(settings):
    if settings is None:
        return []
    if not isinstance(settings, list):
        raise UIControlError(ERR_INVALID_PARAMS, "settings must be a list of {prop, value}")
    out = []
    for i, s in enumerate(settings):
        if not isinstance(s, dict) or not isinstance(s.get("prop"), str) or not s["prop"]:
            raise UIControlError(ERR_INVALID_PARAMS, f"settings[{i}] needs a prop name")
        value = s.get("value")
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif value is None:
            raise UIControlError(ERR_INVALID_PARAMS, f"settings[{i}] needs a value")
        else:
            value = str(value)
        out.append({"prop": s["prop"], "value": value})
    return out


def _widget_point(w):
    """(window, (x, y)) to click for a dump widget; tolerant of records that
    lack the snapshot annotations (``_win``/``center``)."""
    win = w.get("_win") or drv.main_window()
    if "center" in w and "_area" in w:
        return win, drv.pick_click_point(w)
    x0, y0, x1, y1 = w["rect"]
    return win, (int((x0 + x1) / 2), int((y0 + y1) / 2))


def _apply_setting(setting):
    """Generator: apply ONE {prop, value} through the redo popup widgets.
    Returns (applied_record | None, failed_record | None)."""
    prop, value = setting["prop"], setting["value"]
    hits = drv.find(popup=True, prop=prop)
    if not hits:
        return None, {"prop": prop, "reason": "no popup widget with that prop"}
    wtype = hits[0].get("type")
    query = {"popup": True, "prop": prop}
    if wtype in ("Num", "NumSlider", "Text", "SearchMenu"):
        for ch in value:
            drv.key_for_char(ch)
        # Live fact: a redo-popup number field enters text edit only on a
        # DOUBLE-click (a single click + retype — the sidebar set_text
        # gesture — does nothing here). After Enter the popup stays open and
        # the operator re-executes with the new value.
        w = hits[0]
        win, (x, y) = _widget_point(w)
        yield from drv.click_xy_steps(win, x, y, double=True)
        yield 0.15
        drv.press(win, "A", ctrl=True)
        drv.press(win, "BACK_SPACE")
        yield 0.1
        drv.type_text(win, value)
        yield 0.1
        drv.press(win, "RET")
        yield 0.15
    elif wtype == "Menu":
        yield from drv.choose(query, value)
    elif wtype == "Row":
        target = next((h for h in hits
                       if split_hotkey(h.get("text"))[0].lower() == value.lower()), None)
        if target is None:
            return None, {"prop": prop, "reason": f"no option labelled {value!r}"}
        yield from drv.click_steps(target)
    elif wtype in ("Checkbox", "Toggle", "IconToggle", "CheckboxN"):
        want = value.strip().lower() in ("true", "1", "yes", "on")
        if bool(hits[0].get("sel")) != want:
            yield from drv.click_steps(hits[0])
    else:
        return None, {"prop": prop, "reason": f"unsupported widget type {wtype!r}"}
    yield _TICK
    after = drv.find(popup=True, prop=prop)
    text_after = (after[0].get("text") or "") if after else ""
    return {"prop": prop, "text_after": text_after, "type": wtype}, None



def _op_history():
    """(count, last idname, last name) of the window-manager operator history."""
    try:
        ops = bpy.context.window_manager.operators
        n = len(ops)
        last = ops[-1] if n else None
        return n, (getattr(last, "bl_idname", "") if last else ""), (getattr(last, "name", "") if last else "")
    except Exception:
        return 0, "", ""


def _label_matches(found, label, op_name=""):
    """Lenient title check: menu labels are longer than operator names
    ('Bevel Edges' -> redo title 'Bevel'); either containment or the operator
    history name counts."""
    f, l, o = _norm_label(found), _norm_label(label), _norm_label(op_name)
    if not f and not o:
        return False
    return bool(f) and (f == l or f in l or l in f) or bool(o) and (o == l or o in l or l in o)


def run_operator_steps(params):
    label = params.get("label")
    if not isinstance(label, str) or not label.strip():
        raise UIControlError(ERR_INVALID_PARAMS, "label must be a non-empty string")
    for ch in label:
        drv.key_for_char(ch)
    settings = _validate_settings(params.get("settings"))

    yield from drv.focus_area_steps("VIEW_3D")
    win, area, region = _view3d_override()
    # Menu search first (labels a user sees: "Bevel Edges"); the operator
    # search ("Bevel") is the fallback when the menu search ran nothing.
    search_ops = ["search_menu", "search_operator"]
    history_before = _op_history()
    search_op = search_ops[0]
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            getattr(bpy.ops.wm, search_op)("INVOKE_DEFAULT")
    except Exception as exc:
        raise UIControlError(ERR_INTERNAL, f"operator search could not be opened: {exc}")
    # The search box takes several redraws to appear AND take keyboard focus;
    # characters typed before that are dropped and Enter then runs nothing
    # (a live run "ran" the previous operator's redo panel that way). Wait for
    # the box, give it time to focus, type, then wait until the box echoes the
    # typed label before pressing Enter.
    for _ in range(20):
        if drv.find(popup=True, but_type="SearchMenu"):
            break
        yield _TICK
    else:
        raise UIControlError(ERR_INTERNAL, "search popup did not open")
    for _ in range(8):
        yield _TICK
    # Modals that were ALREADY running (Mixar keeps e.g. MIXIE_OT_train_asset_model
    # alive as a background modal) must not be mistaken for the operator's own.
    modal_baseline = set(_modal_operators())
    drv.type_text(win, label)
    # The search box's text is NOT exported by the inspector, so the only
    # safe pacing is time: let the results list rebuild before Enter.
    for _ in range(14):
        yield _TICK
    drv.press(win, "RET")
    for _ in range(6):
        yield _TICK
    if drv.find(popup=True, but_type="SearchMenu"):
        # Enter did not run anything: nothing matched the label.
        drv.press(win, "ESC")
        yield _TICK
        raise UIControlError(ERR_NO_MATCH, f"no operator matches {label!r}")

    # Many mesh operators START a modal from the search (Inset, Bevel, Loop
    # Cut...) instead of applying: confirm it with default values, then tune
    # through the redo popup like a user would.
    modal_confirmed = False
    modal_before = [m for m in _modal_operators() if m not in modal_baseline]
    # Registered operators append to wm.operators; a modal shows up in the
    # window's modal list. Neither -> the search matched nothing (Blender closes
    # "No results found" silently on Enter).
    nothing_ran = not modal_before and _op_history() == history_before
    if nothing_ran and search_op == "search_menu":
        # "No results found" + Enter closes the menu search silently. Retry
        # once with the operator-name search ("Bevel Edges" -> "Bevel").
        search_op = "search_operator"
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.wm.search_operator("INVOKE_DEFAULT")
        except Exception as exc:
            raise UIControlError(ERR_INTERNAL, f"operator search could not be opened: {exc}")
        for _ in range(10):
            yield _TICK
        drv.type_text(win, label.split()[0])
        for _ in range(10):
            yield _TICK
        drv.press(win, "RET")
        for _ in range(6):
            yield _TICK
        if drv.find(popup=True, but_type="SearchMenu"):
            drv.press(win, "ESC")
            yield _TICK
            raise UIControlError(ERR_NO_MATCH, f"no operator matches {label!r}")
        modal_before = [m for m in _modal_operators() if m not in modal_baseline]
        if not modal_before and _op_history() == history_before:
            raise UIControlError(ERR_NO_MATCH, f"no operator ran for {label!r}")
    if modal_before:
        drv.press(win, "RET")
        for _ in range(3):
            yield _TICK
        modal_confirmed = True

    drv.press(win, "F9")
    for _ in range(3):
        yield _TICK
    popup = drv.find(popup=True)
    if not popup:
        return {"operator": label, "applied": [], "failed": [], "redo_fields": [],
                "redo_panel": False, "popup_closed": True,
                "modal_confirmed": modal_confirmed, "modal": modal_before}
    found = next(((w.get("text") or "") for w in popup if w.get("type") == "Label"), "")
    _n, _idname, op_name = _op_history()
    if not _label_matches(found, label, op_name):
        drv.press(win, "ESC")
        yield _TICK
        yield from drv.focus_area_steps("VIEW_3D")
        drv.press(win, "Z", ctrl=True)
        yield _TICK
        raise UIControlError(ERR_OPERATOR_MISMATCH,
                             f"ran {found.strip()!r} not {label!r} (undone with Ctrl+Z)")

    applied, failed = [], []
    for setting in settings:
        # Typing a value + Enter applies it AND closes the popup: re-open the
        # redo panel before every subsequent setting.
        if not drv.find(popup=True):
            yield from _reopen_redo(win)
        ok, bad = yield from _apply_setting(setting)
        if ok:
            applied.append(ok)
        if bad:
            failed.append(bad)
    if not drv.find(popup=True):
        yield from _reopen_redo(win)
    fields = _redo_fields(drv.find(popup=True))
    # Leave the viewport clean for the next action: Esc dismisses the redo
    # popup without reverting the values (verified live).
    popup_closed = False
    if drv.find(popup=True):
        drv.press(win, "ESC")
        yield _TICK
        popup_closed = not drv.find(popup=True)
    return {"operator": found.strip() or label, "applied": applied, "failed": failed,
            "redo_fields": fields, "redo_panel": True, "popup_closed": popup_closed,
            "modal_confirmed": modal_confirmed, "modal": modal_before}


def _reopen_redo(win):
    yield from drv.focus_area_steps("VIEW_3D")
    drv.press(win, "F9")
    for _ in range(3):
        yield _TICK
