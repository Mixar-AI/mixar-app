# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bootstrap bridge that installs the Auto Key camera watcher."""

from ..core import auto_key


def register():
    auto_key.register()


def unregister():
    auto_key.unregister()
