# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""WindowManager state of the Connect MCP sheet (`mixar.connect_ai`).

The state machine (`constants.CONNECT_STATE_ITEMS`, driven by
`core/connect_state.py`), the app the sidebar has selected (an
`app_configs.SIDEBAR` key, or OTHER for the foot), the Other app's format
(`app_configs.FORMATS`), and the last add's outcome for the recap / error.
Runtime-only: nothing here is written into a .blend.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from ...constants import CONNECT_STATE_ITEMS, OTHER_APP, PRODUCT_NAMES
from ...core import app_configs

_APP_ITEMS = ([(key, app_configs.label(key), "") for key in app_configs.SIDEBAR]
              + [(OTHER_APP, "Other app", "")])
_FORMAT_ITEMS = [(key, app_configs.label(key), "") for key in app_configs.FORMATS]

_WM_ATTRS = (
    'mixar_mcp_dialog_state',
    'mixar_mcp_dialog_app',
    'mixar_mcp_dialog_format',
    'mixar_mcp_last_error',
    'mixar_mcp_result_app',
    'mixar_mcp_result_status',
)


def register():
    WM = bpy.types.WindowManager
    WM.mixar_mcp_dialog_state = EnumProperty(
        name="Connect Dialog State", items=CONNECT_STATE_ITEMS, default='IDLE',
        options={'SKIP_SAVE'})
    WM.mixar_mcp_dialog_app = EnumProperty(
        name="App", items=_APP_ITEMS, default=app_configs.SIDEBAR[0],
        translation_context=PRODUCT_NAMES, options={'SKIP_SAVE'})
    WM.mixar_mcp_dialog_format = EnumProperty(
        name="Format", items=_FORMAT_ITEMS, default=app_configs.FORMATS[0],
        translation_context=PRODUCT_NAMES, options={'SKIP_SAVE'})
    WM.mixar_mcp_last_error = StringProperty(default='', options={'SKIP_SAVE'})
    WM.mixar_mcp_result_app = StringProperty(default='', options={'SKIP_SAVE'})
    WM.mixar_mcp_result_status = StringProperty(default='', options={'SKIP_SAVE'})


def unregister():
    WM = bpy.types.WindowManager
    for attr in _WM_ATTRS:
        try:
            delattr(WM, attr)
        except AttributeError:
            pass
