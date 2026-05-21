# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
File Select Utilities

Guard against Blender's file browser double-click event propagation.
When a user double-clicks a file in the browser, the second click can
propagate to the UI button underneath after the browser closes, triggering
a fresh invoke() call.  The helpers here let operators detect and suppress
that spurious re-invocation.
"""

import time

# Operator bl_idname -> monotonic timestamp of last execute() completion.
_last_execute_times: dict[str, float] = {}

_GUARD_INTERVAL = 0.5  # seconds


def file_select_guard(operator, context):
    """Call from invoke() *before* fileselect_add.

    Returns True if the file browser should be opened normally.
    Returns False if this invocation is a spurious double-click propagation
    and should be silently suppressed.
    """
    last = _last_execute_times.get(operator.bl_idname, 0)
    if time.monotonic() - last < _GUARD_INTERVAL:
        return False
    return True


def mark_file_select_executed(operator):
    """Call from execute() when the operator finishes successfully."""
    _last_execute_times[operator.bl_idname] = time.monotonic()
