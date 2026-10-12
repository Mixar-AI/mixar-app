# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex (ChatGPT sub): load the Codex CLI login's sign-in tokens.

Only ``refresh_token``, ``access_token`` and ``account_id`` are read into the
transient form field (core/codex_cli_login.py); Save sends exactly those. The
rest of auth.json — id token, OPENAI_API_KEY, timestamps — never leaves this
computer, and nothing passes through the clipboard.
"""

from bpy.types import Operator

from mixar.modules.common.i18n import rpt_

from ...core import codex_cli_login
from .byok_state_ops import _redraw_mixie_chat_areas


class MIXAR_BYOK_OT_codex_use_cli(Operator):
    """Use the ChatGPT login of the Codex CLI on this computer. Only its sign-in tokens are sent"""
    bl_idname = "mixar_byok.codex_use_cli"
    bl_label = "Use my Codex CLI login"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        try:
            bundle = codex_cli_login.read_minimal_bundle()
        except ValueError as e:
            self.report({'WARNING'}, rpt_(str(e)))
            return {'CANCELLED'}
        wm.byok_form_codex_bundle = bundle
        if wm.byok_form_codex_bundle != bundle:
            # StringProperty maxlen truncates silently; a clipped bundle is
            # invalid JSON and would fail with an unrelated-looking error.
            wm.byok_form_codex_bundle = ''
            self.report({'ERROR'}, "Codex CLI login is too large to load")
            return {'CANCELLED'}
        _redraw_mixie_chat_areas()
        self.report({'INFO'}, "Loaded your Codex CLI login")
        return {'FINISHED'}


classes = (MIXAR_BYOK_OT_codex_use_cli,)
