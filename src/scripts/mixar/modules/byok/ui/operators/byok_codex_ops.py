# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex (ChatGPT subscription) branch of the AI Provider dialog.

Split out of byok_ops.py (500-line rule), the way the Local branch is: the
dialog form (``byok_dialog_ui._draw_form``) and the Save operator dispatch
here when the selected provider is ``codex``. Drawing uses the shared card
primitives from ``byok_dialog_ui``.

The Codex CLI's sign-in file is the source of truth. The form takes a PATH
(empty = ``$CODEX_HOME/auth.json``, else ``~/.codex/auth.json``; the field's own
browse button picks another file); on Save the
file is read HERE (`core/codex_auth.read_auth_file`), only the access token
(as ``api_key``) and the ChatGPT account id go to PUT /agent/byok, and this
device's credential store keeps the path — never the tokens, which stay in
the CLI's file and are renewed in place before a turn (`turn_credentials`).
"""

import os

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_, n_

from ...core import byok_client, codex_auth, key_prompt, model_suggestions
from . import byok_dialog_ui
from .byok_state_ops import ensure_dialog_redraw_pump

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Drawing (called from byok_dialog_ui._draw_form)
# ---------------------------------------------------------------------------

def _path_status(path: str) -> tuple:
    """``(text, kind)`` for the hint under the path field. Reads the file's
    presence only — never its contents — on the draw thread."""
    resolved = codex_auth.resolve_auth_path(path)
    if os.path.isfile(resolved):
        return iface_("Sign-in found: {path}").format(path=_short(resolved)), 'MUTED'
    return iface_("Not found: {path} — run  codex login").format(path=_short(resolved)), 'DANGER'


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def draw_codex_fields(body, wm, key_only=False) -> None:
    """Codex branch of the form. ``key_only`` is the "Key needed on this
    device" state: the model stays as the server has it."""
    model_row = body.column()
    model_row.enabled = not key_only
    byok_dialog_ui.field_label(model_row, n_("Model"))
    byok_dialog_ui.field_dropdown(model_row, wm, 'byok_form_model')
    body.separator(factor=0.45)

    byok_dialog_ui.field_label(body, n_("Codex sign-in file (empty = default)"))
    # FILE_PATH subtype: Blender draws the browse button itself.
    byok_dialog_ui.field_input(body, wm, 'byok_form_codex_path',
                               activate=key_prompt.focus_is(key_prompt.FOCUS_CODEX_PATH))
    text, kind = _path_status(wm.byok_form_codex_path or "")
    byok_dialog_ui.card_label(body, text, kind)
    body.separator(factor=0.5)
    for line in (
        n_("Run  codex login  in your terminal; Mixar uses that sign-in in place."),
        n_("Only the access token leaves this computer, with each agent request;"),
        n_("the sign-in file is never copied, and renewed tokens are written back to it."),
        n_("Uses your ChatGPT subscription — Mixar credits are not charged."),
    ):
        byok_dialog_ui.card_label(body, line, 'MUTED')


# ---------------------------------------------------------------------------
# Save (dispatched from MIXAR_BYOK_OT_save)
# ---------------------------------------------------------------------------

def execute_codex(op, wm, on_done):
    """Read the sign-in file, PUT access token + account id, keep the path.
    Returns the operator result set; validation problems land in ERROR."""
    model = wm.byok_form_model
    path = (wm.byok_form_codex_path or "").strip()
    if not model_suggestions.is_valid_model('codex', model):
        wm.byok_dialog_state = 'ERROR'
        wm.byok_last_error = n_("Choose a Codex model.")
        return {'CANCELLED'}
    try:
        creds = codex_auth.read_auth_file(path)
    except codex_auth.CodexBundleError as exc:
        wm.byok_dialog_state = 'ERROR'
        wm.byok_last_error = exc.message
        return {'CANCELLED'}

    wm.byok_dialog_state = 'SAVING'
    wm.byok_last_error = ''
    ensure_dialog_redraw_pump()

    byok_client.save_credentials(
        provider='codex',
        model=model,
        api_key=creds.access_token,
        account_id=creds.account_id,
        codex_auth_path=path,
        on_done=on_done,
    )
    return {'FINISHED'}


classes = ()
