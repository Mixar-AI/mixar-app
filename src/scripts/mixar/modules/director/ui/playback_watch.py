# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bootstrap bridge that installs the preview single-play stop."""

from ..core import playback


def register():
    playback.register()


def unregister():
    playback.unregister()
