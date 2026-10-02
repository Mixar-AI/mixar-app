# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One schema authority for local relay, MCP, and QA callers."""

from ..constants import UIError


def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}


TOKEN = {"type": "string", "minLength": 1, "maxLength": 128}
TEXT = {"type": "string", "maxLength": 4096, "pattern": r"^[^\x00-\x09\x0b-\x1f\x7f\ud800-\udfff]*$"}
BOOL = {"type": "boolean"}
QUERY = obj({key: TEXT for key in (
    "text", "op", "prop", "surface", "area_type", "region_type", "panel", "value")})
POINT = {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
         "minItems": 2, "maxItems": 2}
MODS = obj({key: BOOL for key in ("shift", "ctrl", "alt", "oskey")})
_base = {"context": TOKEN, "target": TOKEN}


def action(name, props=None, required=()):
    return obj({**_base, "action": {"const": name}, **(props or {})},
               ("context", "target", "action", *required))


SCHEMAS = {
    "mixar_ui_context": obj({"release": BOOL, "instance": TOKEN, "session": TOKEN}),
    "mixar_ui_observe": obj({"query": QUERY, "image": BOOL, "window": TOKEN,
                             "limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
    "mixar_ui_act": {"type": "object", "oneOf": [
        action("click", {"double": BOOL, "modifiers": MODS}),
        action("set_text", {"text": TEXT, "enter": BOOL}, ("text",)),
        action("choose", {"item": TEXT}, ("item",)),
        action("press", {"key": {"type": "string", "pattern": "^[A-Z][A-Z_0-9]{0,31}$"},
                         "modifiers": MODS}, ("key",)),
        action("scroll", {"steps": {"type": "integer", "minimum": -20, "maximum": 20}}, ("steps",)),
        action("gesture", {"points": {"type": "array", "items": POINT,
                                       "minItems": 2, "maxItems": 256},
                           "button": {"enum": ["LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE"]},
                           "modifiers": MODS,
                           "duration": {"type": "number", "minimum": 0.05, "maximum": 5}}, ("points",)),
    ]},
    "mixar_ui_wait": obj({"query": QUERY, "present": BOOL,
                           "timeout": {"type": "number", "minimum": 0, "maximum": 30}}, ("query",)),
    "mixar_ui_call_status": obj({"call_id": TOKEN}, ("call_id",)),
    "mixar_scenes": obj({}),
    "mixar_scene_new": obj({"name": {"type": "string", "minLength": 1, "maxLength": 63,
                                     "pattern": r"^[^\x00-\x1f\x7f]*$"}}),
    "mixar_scene_switch": obj({"session": TOKEN}, ("session",)),
    "mixar_projects": obj({}),
    "mixar_project_open": obj({"project": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
                               "unsaved": {"enum": ["refuse", "save", "discard"], "default": "refuse"}},
                              ("project",)),
}
READ_ONLY = {"mixar_ui_observe", "mixar_ui_wait", "mixar_ui_call_status", "mixar_scenes", "mixar_projects"}
#: Native interface input: offered only while the user has opted in.
UI_INPUT = {"mixar_ui_observe", "mixar_ui_act", "mixar_ui_wait"}
#: Replaces the open document (its unsaved changes only with explicit consent).
DESTRUCTIVE = {"mixar_project_open"}
DOMAINS = {name: ("scenes" if name.startswith(("mixar_scene", "mixar_project")) else "ui") for name in SCHEMAS}
DESCRIPTIONS = {
    "mixar_ui_context": "Read UI readiness and current/bound scene. Explicitly select an instance or bind its current session after changing documents. Can release your input ownership.",
    "mixar_ui_observe": "Inspect visible Mixar controls and regions. Returns fresh opaque context/target handles; optionally a screenshot. Inspect before each action.",
    "mixar_ui_act": "Drive one observed Mixar control or region through native events. User input cancels control. Gesture points are normalized bottom-left region coordinates. Never blindly retry an uncertain action.",
    "mixar_ui_wait": "Wait for matching visible controls to appear/disappear, with a bounded deadline. No Python expressions.",
    "mixar_ui_call_status": "Recover a local UI action's durable receipt without executing it again.",
    "mixar_scenes": "List the open Mixar scene tabs: name, session id, state and which one is shown. Free.",
    "mixar_scene_new": "Create a new Mixar scene tab exactly like the app's + New scene (camera, light, the current tab's render/unit/colour settings), show it, and pin this connection to it so later scene and UI tools target it. Use this instead of bpy.data.scenes.new in a script. Free.",
    "mixar_scene_switch": "Pin this connection to an existing scene tab by its session id from mixar_scenes and show it in the app. Free.",
    "mixar_projects": "List the user's recent Mixar project files (name, folder, last modified, which is open) and whether the open file has unsaved changes. Use when the user asks to continue earlier work. Free.",
    "mixar_project_open": "Open a recent project by its id from mixar_projects, replacing the open file, and pin this connection to its shown scene tab so later tools target it. Refused while the open file is still working (an agent task, a render or running generation jobs). If the open file has unsaved changes it is refused unless unsaved is 'save' or 'discard': ask the user which first, never choose for them. Free.",
}


def validate(name, args):
    import json
    from jsonschema import Draft202012Validator
    if name not in SCHEMAS:
        raise UIError("unknown_tool", "Unknown UI tool")
    try:
        json.dumps(args, allow_nan=False)
    except (ValueError, TypeError):
        raise UIError("invalid_arguments", "UI arguments must be finite JSON values") from None
    if next(Draft202012Validator(SCHEMAS[name]).iter_errors(args), None):
        raise UIError("invalid_arguments", "Arguments do not match the UI tool schema")


def tools():
    return [{"name": name, "description": DESCRIPTIONS[name], "inputSchema": schema,
             "annotations": {"readOnlyHint": name in READ_ONLY, "destructiveHint": name in DESTRUCTIVE},
             "_meta": {"mixar/billing": {"invocation_credits": 0, "surface": "local_ui"},
                       "mixar/domain": DOMAINS[name]}}
            for name, schema in SCHEMAS.items()]
