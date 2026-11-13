# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Save the local Claude Code provider without accepting any credentials."""
from mixar.modules.common.i18n import n_
from ...core import byok_client, model_suggestions
from .byok_state_ops import ensure_dialog_redraw_pump


def execute_claude(wm, on_done):
    if not model_suggestions.is_valid_model("claude_code", wm.byok_form_model):
        wm.byok_dialog_state, wm.byok_last_error = "ERROR", n_("Pick a model.")
        return {"CANCELLED"}
    wm.byok_dialog_state, wm.byok_last_error = "SAVING", ""
    ensure_dialog_redraw_pump()
    byok_client.save_credentials(provider="claude_code", model=wm.byok_form_model,
                                 api_key=None, on_done=on_done)
    return {"FINISHED"}


classes = ()
