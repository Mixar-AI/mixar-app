# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Notification System Constants

Defines notification types, layout parameters, and theme-aware color
resolution for the toast overlay rendering system.
"""

from enum import Enum

import bpy


class NotificationType(Enum):
    """Notification severity levels.

    info, warning, update — from the backend API.
    error, success       — available for local/client-side use.
    """
    INFO = "info"
    WARNING = "warning"
    UPDATE = "update"
    ERROR = "error"
    SUCCESS = "success"


# Priority -> TTL mapping (ms). 0 = sticky (manual dismiss only).
PRIORITY_TTL_MS = {
    "low": 0,
    "normal": 0,
    "high": 0,
    "critical": 0,
}
DEFAULT_TTL_MS = 0

# -- Layout ----------------------------------------------------------------
MAX_VISIBLE_TOASTS = 5
TOAST_WIDTH = 520
TOAST_PADDING_X = 28
TOAST_PADDING_Y = 24
TOAST_MARGIN = 14
TOAST_CORNER_OFFSET_X = 28
TOAST_CORNER_OFFSET_Y = 28
TOAST_CORNER_RADIUS = 14

# -- Typography -------------------------------------------------------------
TITLE_FONT_SIZE = 18
BODY_FONT_SIZE = 15
ACTION_URL_FONT_SIZE = 14

# -- Close button -----------------------------------------------------------
CLOSE_BUTTON_SIZE = 30
CLOSE_BUTTON_RADIUS = 15

# -- Badge dot --------------------------------------------------------------
BADGE_RADIUS = 6

# -- Action buttons ---------------------------------------------------------
BUTTON_HEIGHT = 38
BUTTON_PADDING_X = 20
BUTTON_GAP = 10
BUTTON_CORNER_RADIUS = 8
BUTTON_FONT_SIZE = 15

# -- Animation --------------------------------------------------------------
FADE_DURATION_MS = 300
TIMER_INTERVAL = 0.2

# -- REST -------------------------------------------------------------------
NOTIFICATIONS_REST_PATH = "/api/v1/notifications"


# -- Theme-aware colors -----------------------------------------------------

def _rgba(color, alpha_override=None):
    """Normalize a Blender theme color to an RGBA tuple.

    Theme colors can be RGB (3) or RGBA (4). This ensures a consistent
    4-tuple, optionally overriding the alpha channel.
    """
    r, g, b = color[0], color[1], color[2]
    a = color[3] if len(color) > 3 else 1.0
    if alpha_override is not None:
        a = alpha_override
    return (r, g, b, a)


def get_toast_colors(ntype: NotificationType) -> dict:
    """Resolve toast colors from the active Blender theme.

    Returns a dict with keys:
        bg, text, dim_text, badge,
        close_bg, close_icon,
        button_primary, button_secondary, button_danger
    Each value is an RGBA tuple.
    """
    theme = bpy.context.preferences.themes[0]
    ui = theme.user_interface
    tooltip = ui.wcol_tooltip

    # -- Base from tooltip widget --
    bg = _rgba(tooltip.inner, alpha_override=0.94)
    text = _rgba(tooltip.text, alpha_override=1.0)
    dim_text = (*text[:3], 0.55)

    # -- Badge from semantic state colors --
    state = ui.wcol_state
    _badge_map = {
        NotificationType.INFO: state.info,
        NotificationType.WARNING: state.warning,
        NotificationType.ERROR: state.error,
        NotificationType.SUCCESS: state.success,
        NotificationType.UPDATE: state.info,
    }
    badge = _rgba(_badge_map[ntype])

    # -- Close button --
    close_bg = _rgba(tooltip.inner, alpha_override=0.25)
    close_icon = (*text[:3], 0.9)

    # -- Action buttons --
    chat = theme.mixie_chat
    primary_bg = _rgba(chat.chat_prompt_button)
    primary_text = _rgba(chat.chat_button_text)
    secondary_bg = _rgba(tooltip.inner, alpha_override=0.3)
    secondary_text = text
    danger_bg = _rgba(state.error, alpha_override=1.0)
    danger_text = (1.0, 1.0, 1.0, 1.0)

    return {
        "bg": bg,
        "text": text,
        "dim_text": dim_text,
        "badge": badge,
        "close_bg": close_bg,
        "close_icon": close_icon,
        "button_primary": {"bg": primary_bg, "text": primary_text},
        "button_secondary": {"bg": secondary_bg, "text": secondary_text},
        "button_danger": {"bg": danger_bg, "text": danger_text},
    }
