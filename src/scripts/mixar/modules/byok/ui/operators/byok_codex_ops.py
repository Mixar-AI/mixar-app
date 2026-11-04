# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex (ChatGPT subscription) branch of the AI Provider dialog.

Split out of byok_ops.py (500-line rule), the way the Local branch is: the
dialog form (``byok_provider_settings_ui``) and the Save operator dispatch
here when the selected provider is ``codex``. The sheet draws the form;
this module supplies the sign-in status line (`path_status`), the field's
prefill on open (`prefill_path`) and the save.

The Codex CLI's sign-in file is the source of truth. The form takes a PATH
(empty = ``$CODEX_HOME/auth.json``, else ``~/.codex/auth.json``, prefilled
when that file exists and stored as empty; the field's own browse button
picks another file); on Save the
file is read HERE (`core/codex_auth.read_auth_file`), only the access token
(as ``api_key``) and the ChatGPT account id go to PUT /agent/byok, and this
device's credential store keeps the path — never the tokens, which stay in
the CLI's file and are renewed in place before a turn (`turn_credentials`).
"""

import os

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_, n_

from ...core import byok_client, codex_auth, model_suggestions
from .byok_state_ops import ensure_dialog_redraw_pump

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# The sign-in status line (drawn by byok_provider_settings_ui over the field)
# ---------------------------------------------------------------------------

def signed_in(path: str) -> bool:
    """The sign-in file at ``path`` (empty = the default) exists. Presence
    only — never its contents — so it is safe on the draw thread."""
    return os.path.isfile(codex_auth.resolve_auth_path(path))


def path_status(path: str) -> tuple:
    """``(text, found)`` for the status line over the path field: what to do
    next, so a signed-in user knows the field needs nothing from them."""
    if signed_in(path):
        return iface_("Codex sign-in found - just click Save & Activate"), True
    if not path.strip() or _is_default(path):
        return iface_("No Codex sign-in found - run  codex login  in your terminal"), False
    resolved = codex_auth.resolve_auth_path(path)
    return iface_("Not found: {path} — run  codex login").format(path=_short(resolved)), False


def prefill_path(wm) -> None:
    """Fill an empty path field with the default sign-in file when it exists,
    so the dialog shows the file Save will use (called on dialog open). The
    path is absolute: the field's browse button does not expand ``~``."""
    if (wm.byok_form_codex_path or "").strip():
        return
    default = codex_auth.default_auth_path()
    if os.path.isfile(default):
        wm.byok_form_codex_path = default


def _is_default(path: str) -> bool:
    return (os.path.normpath(codex_auth.resolve_auth_path(path))
            == os.path.normpath(codex_auth.default_auth_path()))


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


# ---------------------------------------------------------------------------
# Save (dispatched from MIXAR_BYOK_OT_save)
# ---------------------------------------------------------------------------

def execute_codex(op, wm, on_done):
    """Read the sign-in file, PUT access token + account id, keep the path.
    Returns the operator result set; validation problems land in ERROR."""
    model = wm.byok_form_model
    path = (wm.byok_form_codex_path or "").strip()
    # The prefilled default is stored as empty, so the reference keeps
    # following $CODEX_HOME the way the CLI does.
    if path and _is_default(path):
        path = ""
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
