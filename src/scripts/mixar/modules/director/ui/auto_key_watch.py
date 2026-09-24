# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bootstrap bridge for the two ways a camera move becomes a keyframe.

Auto Key watches a camera that STOPS (`core/auto_key.py`); recording writes a
camera that MOVES, one key per frame the timeline plays through
(`core/record.py`). Different handlers, different questions, one bridge.
"""

from ..core import auto_key, record


def register():
    auto_key.register()
    record.register()


def unregister():
    auto_key.unregister()
    record.unregister()
