# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Commit the live viewport ink before Send snapshots the scene's drafts.

Main-thread only. Keep the operator, not RNA area/region references; resolve
the owning window afresh so sends from the floating chat use the right scene.
"""

import time

_operator = None


def bind(operator):
    global _operator
    _operator = operator


def clear():
    global _operator
    _operator = None


def flush(context):
    from .freeze_session import resolve

    operator = _operator
    if operator is None or operator._ink is None or operator._ink.empty:
        return False
    window, area, region = resolve(context, operator._area_ptr, operator._region_ptr)
    if window is None or area is None or region is None:
        return False
    # Resizing invalidates the pixels. Never project old ink through a new view.
    if not operator._session.matches(region):
        return False
    if window.scene != context.scene:
        return False
    with context.temp_override(window=window, area=area, region=region):
        operator._ink.end(time.monotonic())
        operator._commit_pending(context)
    return True
