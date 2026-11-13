# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remote control of this app by Mixar Game Studio.

A cloud workstation runs this app in a sandbox while a person directs the work from a web page.
The studio's bridge (uploaded by the backend when the workstation starts) talks to the app through
``api``: the one supported surface for reading the conversation and acting on it from outside the
UI. Nothing here runs on its own, opens a port or registers a class; see README.md.
"""

API_VERSION = 1


def register():
    pass


def unregister():
    pass
