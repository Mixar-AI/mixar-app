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
}
DESCRIPTIONS = {
    "mixar_ui_context": "Read UI readiness and current/bound scene. Explicitly select an instance or bind its current session after changing documents. Can release your input ownership.",
    "mixar_ui_observe": "Inspect visible Mixar controls and regions. Returns fresh opaque context/target handles; optionally a screenshot. Inspect before each action.",
    "mixar_ui_act": "Drive one observed Mixar control or region through native events. User input cancels control. Gesture points are normalized bottom-left region coordinates. Never blindly retry an uncertain action.",
    "mixar_ui_wait": "Wait for matching visible controls to appear/disappear, with a bounded deadline. No Python expressions.",
    "mixar_ui_call_status": "Recover a local UI action's durable receipt without executing it again.",
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
             "annotations": {"readOnlyHint": name in {
                 "mixar_ui_observe", "mixar_ui_wait", "mixar_ui_call_status"}},
             "_meta": {"mixar/billing": {"invocation_credits": 0, "surface": "local_ui"}}}
            for name, schema in SCHEMAS.items()]
