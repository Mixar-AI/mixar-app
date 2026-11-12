# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional startup module for the local UAT6 Claude Dev bundle only.

Install in that bundle's scripts/startup/ directory. No embedded credentials;
uses the existing build-gated Dev bypass and ordinary worker-thread login.
Never installed by the product build or copied into production bundles.
"""
import time

import bpy

_deadline = 0.0


def _sign_in():
    if time.monotonic() >= _deadline:
        print('[UAT6 dev login] Startup did not become ready.', flush=True)
        return None
    from mixar.config.config import get_dev_bypass_credentials, get_server_url
    username, password = get_dev_bypass_credentials()
    if (get_server_url().rstrip('/') != 'https://uat6.mixar.app'
            or not username or not password):
        return None
    wm = bpy.context.window_manager
    if not hasattr(wm, 'mixie_chat_is_logged_in') or not wm.mixie_chat_is_logged_in:
        return 0.5  # Let the ordinary credential restore / guest bootstrap settle.
    if not getattr(wm, 'mixie_chat_is_guest', False):
        print('[UAT6 dev login] Account is signed in.', flush=True)
        return None
    print('[UAT6 dev login] Invoking configured Dev sign-in.', flush=True)
    bpy.ops.mixie_chat.login()
    return None  # One attempt; normal login UI owns errors and retry.


def register():
    global _deadline
    if bpy.app.background:
        return
    _deadline = time.monotonic() + 90
    bpy.app.timers.register(_sign_in, first_interval=1.0)


def unregister():
    if bpy.app.timers.is_registered(_sign_in):
        bpy.app.timers.unregister(_sign_in)
