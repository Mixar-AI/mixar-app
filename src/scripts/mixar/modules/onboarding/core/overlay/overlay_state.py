# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Overlay State

Tiny module kept for compatibility with ``state.reset()``. The
info-only flow doesn't need any per-step latches — the renderer
reads everything it needs straight from the WindowManager step
ID. ``button_bounds`` and ``clear()`` exist as no-op shims.
"""

button_bounds: list = []


def is_active() -> bool:
    return False


def clear() -> None:
    button_bounds.clear()
