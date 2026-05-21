# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Text measurement and word-wrapping utilities for the onboarding card.
"""

import blf

FONT_ID = 0


def measure_text_h(font_size: int, sample: str = "Ag") -> int:
    blf.size(FONT_ID, font_size)
    _, h = blf.dimensions(FONT_ID, sample)
    return max(int(h), font_size)


def measure_text_w(font_size: int, text: str) -> int:
    blf.size(FONT_ID, font_size)
    w, _ = blf.dimensions(FONT_ID, text)
    return int(w)


def wrap_line(font_size: int, max_w: int, text: str) -> list:
    """Word-wrap a single line to fit within ``max_w`` pixels."""
    blf.size(FONT_ID, font_size)
    if not text:
        return [""]
    words = text.split(" ")
    if not words:
        return [text]
    lines = []
    current = words[0]
    for word in words[1:]:
        test = (current + " " + word) if current else word
        w, _ = blf.dimensions(FONT_ID, test)
        if w <= max_w:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines
