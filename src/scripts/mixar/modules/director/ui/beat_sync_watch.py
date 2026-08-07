# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bootstrap bridge that installs the Director beat/keyframe reconciler."""

from ..core import beat_sync


def register():
    beat_sync.register()


def unregister():
    beat_sync.unregister()
