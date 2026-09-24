# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bootstrap bridge that installs the deleted-camera shot sweep."""

from ..core import camera_sync


def register():
    camera_sync.register()


def unregister():
    camera_sync.unregister()
