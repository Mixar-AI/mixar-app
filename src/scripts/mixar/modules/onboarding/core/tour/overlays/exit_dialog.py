# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the "Leave the tour?" confirmation.

A centred dialog over a dim film with two pill buttons: *Continue tour*
(accent filled) and *Leave* (outlined). Layout is arithmetic over
``config`` so the tests can pin it; drawing is ``gpu``/``blf`` only.
"""

from dataclasses import dataclass, field
from typing import Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_rect,
    draw_rounded_rect,
    draw_rounded_rect_outline,
)

from .. import config
from .text import draw_text, draw_text_centered, text_width

logger = get_logger(__name__)

DIALOG_W = 380.0              # logical px
DIALOG_H = 150.0
DIALOG_RADIUS = 16.0
DIALOG_PAD = 22.0
TITLE_PX = 17
BODY_PX = 13
BUTTON_H = 32.0
BUTTON_PAD_X = 16.0
BUTTON_GAP = 10.0
BUTTON_ORDER = ("continue", "exit")
DIALOG_BG = (0.11, 0.11, 0.13, 0.98)
DIALOG_BORDER = (1.0, 1.0, 1.0, 0.12)
TITLE_COLOR = (0.97, 0.97, 0.98, 1.0)
BODY_COLOR = (0.72, 0.73, 0.76, 1.0)
CONTINUE_TEXT = (0.12, 0.10, 0.04, 1.0)
EXIT_TEXT = (0.92, 0.92, 0.94, 1.0)
EXIT_BORDER = (1.0, 1.0, 1.0, 0.35)
HOVER_LIFT = 0.10


@dataclass
class ExitConfirmLayout:
    dialog: tuple
    buttons: dict = field(default_factory=dict)
    host: tuple = (0.0, 0.0, 0.0, 0.0)


def _lift(color: tuple, amount: float) -> tuple:
    return (min(1.0, color[0] + amount), min(1.0, color[1] + amount),
            min(1.0, color[2] + amount), color[3])


def compute_exit_confirm_layout(host_rect: tuple, ui_scale: float) -> ExitConfirmLayout:
    """Centred ``DIALOG_W`` x ``DIALOG_H`` dialog with its two buttons."""
    s = max(0.1, float(ui_scale))
    hxmin, hymin, hxmax, hymax = host_rect
    w = min(DIALOG_W * s, max(0.0, hxmax - hxmin))
    h = min(DIALOG_H * s, max(0.0, hymax - hymin))
    xmin = (hxmin + hxmax) * 0.5 - w * 0.5
    ymin = (hymin + hymax) * 0.5 - h * 0.5
    dialog = (xmin, ymin, xmin + w, ymin + h)

    pad = DIALOG_PAD * s
    bh = BUTTON_H * s
    bpad = BUTTON_PAD_X * s
    gap = BUTTON_GAP * s
    px = BODY_PX * s
    by0 = ymin + pad * 0.8
    by1 = by0 + bh
    right = xmin + w - pad
    buttons = {}
    exit_w = text_width(config.EXIT_CONFIRM_QUIT, px) + 2 * bpad
    buttons["exit"] = (right - exit_w, by0, right, by1)
    right -= exit_w + gap
    cont_w = text_width(config.EXIT_CONFIRM_CONTINUE, px) + 2 * bpad
    buttons["continue"] = (right - cont_w, by0, right, by1)
    return ExitConfirmLayout(dialog=dialog, buttons=buttons, host=tuple(host_rect))


def draw_exit_confirm(layout: ExitConfirmLayout, ui_scale: float = 1.0,
                      hover: Optional[str] = None) -> None:
    """Dim film over the host, then the dialog and its buttons."""
    try:
        s = max(0.1, float(ui_scale))
        hxmin, hymin, hxmax, hymax = layout.host
        if hxmax > hxmin and hymax > hymin:
            draw_rect(hxmin, hymin, hxmax - hxmin, hymax - hymin, config.HERO_DIM)

        xmin, ymin, xmax, ymax = layout.dialog
        w, h = xmax - xmin, ymax - ymin
        radius = DIALOG_RADIUS * s
        draw_rounded_rect(xmin, ymin, w, h, radius, DIALOG_BG)
        draw_rounded_rect_outline(xmin, ymin, w, h, radius, DIALOG_BORDER, width=1.0)

        pad = DIALOG_PAD * s
        title_px = TITLE_PX * s
        body_px = BODY_PX * s
        draw_text(xmin + pad, ymax - pad - title_px * 0.8,
                  config.EXIT_CONFIRM_TITLE, title_px, TITLE_COLOR)
        draw_text(xmin + pad, ymax - pad - title_px * 0.8 - body_px * 1.7,
                  config.EXIT_CONFIRM_BODY, body_px, BODY_COLOR)

        cont = layout.buttons.get("continue")
        if cont is not None:
            bw, bh = cont[2] - cont[0], cont[3] - cont[1]
            fill = _lift(config.ACCENT, HOVER_LIFT) if hover == "continue" else config.ACCENT
            draw_rounded_rect(cont[0], cont[1], bw, bh, bh * 0.5, fill)
            draw_text_centered(cont, config.EXIT_CONFIRM_CONTINUE, body_px, CONTINUE_TEXT)
        quit_ = layout.buttons.get("exit")
        if quit_ is not None:
            bw, bh = quit_[2] - quit_[0], quit_[3] - quit_[1]
            border = _lift(EXIT_BORDER, 0.3) if hover == "exit" else EXIT_BORDER
            draw_rounded_rect_outline(quit_[0], quit_[1], bw, bh, bh * 0.5, border, width=1.0)
            draw_text_centered(quit_, config.EXIT_CONFIRM_QUIT, body_px, EXIT_TEXT)
    except Exception as exc:
        logger.debug("Tour exit dialog draw failed: %s", exc)


def _inside(rect: tuple, x: float, y: float) -> bool:
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


def hit_test_exit_confirm(layout: ExitConfirmLayout, x: float, y: float) -> Optional[str]:
    """``"continue"``, ``"exit"``, ``"dialog"`` or None."""
    for name in BUTTON_ORDER:
        rect = layout.buttons.get(name)
        if rect is not None and _inside(rect, x, y):
            return name
    if _inside(layout.dialog, x, y):
        return "dialog"
    return None
