# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the shortcut panel.

A dark box with a title and one row per shortcut: keycaps on the left, what
the key does on the right. Each row carries the video ms at which the
narration names it: before that it waits dimmed, when it is named it lights
in the accent colour for ``KEY_LIT_MS``, then it settles to full white. So
the panel reads as a reference card that fills in with the voice.

Layout is pure math (``keys_layout``) so tests pin it without a GPU.
"""

import sys

from mixar.config.logging_config import get_logger
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_rounded_rect,
    draw_rounded_rect_outline,
)

from .. import config
from .text import draw_text, text_height, text_width

logger = get_logger(__name__)

PAD = 16.0
ROW_H = 30.0
TITLE_GAP = 10.0
CAP_PAD_X = 7.0
CAP_H = 22.0
CAP_GAP = 4.0
LABEL_GAP = 14.0
KEY_LIT_MS = 1400        # accent glow after a key is named
DIM_ALPHA = 0.32         # rows not yet named

MOD_KEY = "Cmd" if sys.platform == "darwin" else "Ctrl"
ALT_KEY = "Option" if sys.platform == "darwin" else "Alt"
_PLATFORM_KEYS = {"Mod": MOD_KEY, "Opt": ALT_KEY}


def _with_alpha(color: tuple, alpha: float) -> tuple:
    return (color[0], color[1], color[2], color[3] * alpha)


def _caps(keys: str) -> list:
    """``"Shift+A"`` → ``["Shift", "A"]``; ``"Mod"`` becomes Cmd / Ctrl and
    ``"Opt"`` Option / Alt, per platform."""
    return [_PLATFORM_KEYS.get(k, k) for k in keys.split("+") if k]


def keys_layout(title: str, rows: tuple, center: tuple, bounds: tuple,
                ui_scale: float = 1.0) -> dict:
    """Box rect and per-row geometry for ``rows`` of ``(keys, label, ms)``,
    centred on ``center`` and clamped into ``bounds``."""
    s = ui_scale
    cap_px, label_px, title_px = (config.KEYS_CAP_PX * s, config.KEYS_LABEL_PX * s,
                                  config.KEYS_TITLE_PX * s)
    caps_w = []
    for keys, _label, _ms in rows:
        w = sum(text_width(c, cap_px) + 2 * CAP_PAD_X * s for c in _caps(keys))
        caps_w.append(w + CAP_GAP * s * max(0, len(_caps(keys)) - 1))
    col = max(caps_w or [0.0])
    labels_w = max([text_width(r[1], label_px) for r in rows] or [0.0])
    w = max(text_width(title, title_px), col + LABEL_GAP * s + labels_w) + 2 * PAD * s
    h = 2 * PAD * s + text_height(title_px) + TITLE_GAP * s + len(rows) * ROW_H * s
    cx, cy = center
    xmin, ymin = cx - w * 0.5, cy - h * 0.5
    bxmin, bymin, bxmax, bymax = bounds
    margin = 12 * s
    xmin = max(bxmin + margin, min(xmin, bxmax - margin - w))
    ymin = max(bymin + margin, min(ymin, bymax - margin - h))
    return {"rect": (xmin, ymin, xmin + w, ymin + h), "caps_col": col,
            "caps_w": caps_w}


def row_state(named_ms: int, ms: int) -> str:
    """``"waiting"`` before the row is named, ``"lit"`` right after,
    ``"done"`` once it has settled."""
    if ms < named_ms:
        return "waiting"
    if ms < named_ms + KEY_LIT_MS:
        return "lit"
    return "done"


def draw_keys(title: str, rows: tuple, center: tuple, bounds: tuple, ms: int,
              ui_scale: float = 1.0, alpha: float = 1.0) -> tuple:
    lay = keys_layout(title, rows, center, bounds, ui_scale)
    if alpha <= 0.0:
        return lay["rect"]
    s = ui_scale
    try:
        xmin, ymin, xmax, ymax = lay["rect"]
        draw_rounded_rect(xmin, ymin, xmax - xmin, ymax - ymin, 10 * s,
                          _with_alpha(config.CALLOUT_BG, alpha))
        title_px = config.KEYS_TITLE_PX * s
        y = ymax - PAD * s - title_px * 0.82
        draw_text(xmin + PAD * s, y, title, title_px,
                  _with_alpha(config.CONTROL_TEXT_DIM, alpha))
        y = ymax - PAD * s - text_height(title_px) - TITLE_GAP * s
        cap_px, label_px = config.KEYS_CAP_PX * s, config.KEYS_LABEL_PX * s
        for (keys, label, named_ms) in rows:
            state = row_state(named_ms, ms)
            row_a = alpha * (DIM_ALPHA if state == "waiting" else 1.0)
            lit = state == "lit"
            cy = y - ROW_H * s * 0.5
            x = xmin + PAD * s
            for cap in _caps(keys):
                cw = text_width(cap, cap_px) + 2 * CAP_PAD_X * s
                ch = CAP_H * s
                draw_rounded_rect(x, cy - ch * 0.5, cw, ch, 5 * s,
                                  _with_alpha(config.KEYS_CAP_BG, row_a))
                edge = config.ACCENT if lit else config.KEYS_CAP_EDGE
                draw_rounded_rect_outline(x, cy - ch * 0.5, cw, ch, 5 * s,
                                          _with_alpha(edge, row_a), width=1.2 * s)
                draw_text(x + CAP_PAD_X * s, cy - cap_px * 0.35, cap, cap_px,
                          _with_alpha(config.ACCENT if lit else config.HINT_TEXT, row_a))
                x += cw + CAP_GAP * s
            lx = xmin + PAD * s + lay["caps_col"] + LABEL_GAP * s
            draw_text(lx, cy - label_px * 0.35, label, label_px,
                      _with_alpha(config.ACCENT if lit else config.HINT_TEXT, row_a))
            y -= ROW_H * s
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tour keys draw failed: %s", exc)
    return lay["rect"]
