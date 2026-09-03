# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Wire constants for agent UI control (must match the backend byte for byte:
mixar-backend/modules/agent/ui_control_protocol.py)."""

import re

PROTOCOL_VERSION = 1
CAPABILITY = "ui_control_v1"
RPC_PREFIX = "ui."

RPC_STATE = "ui.state"
RPC_DUMP = "ui.dump"
RPC_FIND = "ui.find"
RPC_CLICK = "ui.click"
RPC_TYPE = "ui.type"
RPC_PRESS = "ui.press"
RPC_CHOOSE = "ui.choose"
RPC_SET_TEXT = "ui.set_text"
RPC_DRAG = "ui.drag"
RPC_DROP_FILE = "ui.drop_file"
RPC_WAIT = "ui.wait"
RPC_SNAP = "ui.snap"
RPC_FOCUS_AREA = "ui.focus_area"

RPC_METHODS = frozenset({
    RPC_STATE, RPC_DUMP, RPC_FIND, RPC_CLICK, RPC_TYPE, RPC_PRESS, RPC_CHOOSE,
    RPC_SET_TEXT, RPC_DRAG, RPC_DROP_FILE, RPC_WAIT, RPC_SNAP, RPC_FOCUS_AREA,
})

# Methods that inject input — they need agent input enabled (mixed mode) or
# an event-simulate launch. Read-only methods work in every build.
ACTION_METHODS = frozenset({
    RPC_CLICK, RPC_TYPE, RPC_PRESS, RPC_CHOOSE, RPC_SET_TEXT, RPC_DRAG,
    RPC_DROP_FILE, RPC_FOCUS_AREA,
})

# Closed error-code set (spec §3).
ERR_UNSUPPORTED_PROTOCOL = "unsupported_protocol"
ERR_UNKNOWN_METHOD = "unknown_method"
ERR_INVALID_PARAMS = "invalid_params"
ERR_NOT_ENABLED = "not_enabled"
ERR_BUSY = "busy"
ERR_NO_MATCH = "no_match"
ERR_TIMEOUT = "timeout"
ERR_INTERRUPTED = "interrupted"
ERR_DENIED = "denied"
ERR_INTERNAL = "internal"

QUERY_KEYS = frozenset({
    "text", "contains", "op", "prop", "prop_owner", "panel", "area_type",
    "region_type", "but_type", "popup", "enabled", "window", "surface",
    "value", "detail", "index",
})

# Widget labels of secret-bearing fields are blanked in every dump (spec §3).
SECRET_PROP_RE = re.compile(r"password|secret|token|api_key|apikey", re.IGNORECASE)

# Operator denylist (both sides enforce it).
DENIED_OPS = frozenset({
    "wm.quit_blender", "wm.save_mainfile", "wm.save_as_mainfile",
    "wm.open_mainfile", "wm.revert_mainfile", "wm.read_homefile",
    "wm.read_factory_settings", "wm.save_userpref", "wm.window_close",
    "wm.recover_last_session", "wm.recover_auto_save", "mixie_chat.logout",
    # Introspection exports operator idnames in class form too.
    "WM_OT_quit_blender", "WM_OT_save_mainfile", "WM_OT_save_as_mainfile",
    "WM_OT_open_mainfile", "WM_OT_revert_mainfile", "WM_OT_read_homefile",
    "WM_OT_read_factory_settings", "WM_OT_save_userpref", "WM_OT_window_close",
    "WM_OT_recover_last_session", "WM_OT_recover_auto_save",
    "MIXIE_CHAT_OT_logout",
})
DENIED_OP_SUFFIXES = ("delete_all",)
# (key, modifier) combinations that close or quit the app.
DENIED_KEY_COMBOS = frozenset({("Q", "ctrl"), ("Q", "oskey"), ("F4", "alt")})

DUMP_LIMIT_DEFAULT = 200
DUMP_LIMIT_MAX = 400
FIND_LIMIT_DEFAULT = 25
WAIT_TIMEOUT_DEFAULT = 30.0
WAIT_TIMEOUT_MAX = 300.0
ACTION_TIMEOUT_S = 60.0
SNAP_MAX_EDGE_DEFAULT = 1568
SNAP_JPEG_QUALITY = 80
FIND_RETRY_WINDOW_S = 2.0
# Widget geometry must survive this many UI ticks before a drag starts.
DRAG_STABLE_TICKS = 2

STATUS_TEXT = "Mixar is working — press Esc to take over"

WM_PROP_INPUT_ENABLED = "mixar_agent_input_enabled"
WM_PROP_ACTION_ACTIVE = "mixar_agent_action_active"
WM_PROP_INTERRUPT = "mixar_agent_interrupt_requested"
