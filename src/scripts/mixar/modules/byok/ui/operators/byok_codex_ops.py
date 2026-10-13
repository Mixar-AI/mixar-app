# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex (ChatGPT subscription) in AI Provider settings: fill the auth bundle
field from ~/.codex/auth.json or the clipboard. Split from byok_ops (500-line
rule); the Save path that sends the bundle stays there."""

import os

from bpy.types import Operator

from mixar.config.logging_config import get_logger

from .byok_state_ops import _redraw_mixie_chat_areas

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Codex — paste auth.json from clipboard
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_codex_load_file(Operator):
    """Read ~/.codex/auth.json from this machine into the field"""
    bl_idname = "mixar_byok.codex_load_file"
    bl_label = "Load from ~/.codex/auth.json"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        path = os.path.expanduser(os.path.join("~", ".codex", "auth.json"))
        if not os.path.exists(path):
            self.report({'WARNING'}, "~/.codex/auth.json not found — run `codex login` first")
            return {'CANCELLED'}
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("Codex auth.json read failed: %s", e)
            self.report({'ERROR'}, "Could not read ~/.codex/auth.json")
            return {'CANCELLED'}
        if not content:
            self.report({'WARNING'}, "~/.codex/auth.json is empty")
            return {'CANCELLED'}
        wm.byok_form_codex_bundle = content
        if len(wm.byok_form_codex_bundle) < len(content):
            # StringProperty maxlen truncates silently — a clipped bundle is
            # invalid JSON and the save fails with an error the user can't
            # connect to truncation.
            self.report(
                {'ERROR'},
                "auth.json is too large for this field and was truncated — "
                "it will not save correctly",
            )
            _wipe_form_secrets(wm)
            return {'CANCELLED'}
        _redraw_mixie_chat_areas()
        self.report({'INFO'}, "Loaded auth.json")
        return {'FINISHED'}


class MIXAR_BYOK_OT_codex_paste(Operator):
    """Paste your ~/.codex/auth.json from the clipboard into the field"""
    bl_idname = "mixar_byok.codex_paste"
    bl_label = "Paste auth.json"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        # Read the clipboard directly — this preserves the multi-line JSON that
        # a single-line prop field can't accept via a manual paste.
        clip = (wm.clipboard or "").strip()
        if not clip:
            self.report({'WARNING'}, "Clipboard is empty")
            return {'CANCELLED'}
        wm.byok_form_codex_bundle = clip
        if len(wm.byok_form_codex_bundle) < len(clip):
            self.report(
                {'ERROR'},
                "Pasted auth.json is too large for this field and was "
                "truncated — it will not save correctly",
            )
            _wipe_form_secrets(wm)
            return {'CANCELLED'}
        _redraw_mixie_chat_areas()
        return {'FINISHED'}


classes = (
    MIXAR_BYOK_OT_codex_load_file,
    MIXAR_BYOK_OT_codex_paste,
)
