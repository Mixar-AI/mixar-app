# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local (this computer) branch of the AI Provider dialog.

Split out of byok_ops.py (500-line rule): the dialog form
(``byok_provider_settings_ui``) and the Save operator dispatch here when
the selected provider is ``local``. Drawing uses the sheet kit
(``common/sheet/kit``) so the branch matches the rest of the dialog. Data + save orchestration live in ``byok/core/local_provider.py``;
the managed download/start/stop operators live in
``modules/local_models/ui/operators/local_models_ops.py`` — this file
only draws and validates.
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_, n_, rpt_

from ...constants import LOCAL_MODE_ITEMS
from ...core import key_prompt, local_provider
from mixar.modules.common.sheet import kit as S
from .byok_state_ops import ensure_dialog_redraw_pump

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dialog-open preparation (called from MIXAR_BYOK_OT_open_dialog.invoke)
# ---------------------------------------------------------------------------

def prepare_dialog(wm) -> None:
    """Refresh caches + prefill the Local form from the saved registration."""
    local_provider.refresh_model_items()
    try:
        from mixar.modules.local_models.core import manifest, orchestrator
        reg = manifest.get_registered()
        if orchestrator.is_managed_registration(reg):
            wm.byok_form_local_mode = 'MANAGED'
            try:
                wm.byok_form_local_model = reg["model_id"]
            except TypeError:
                pass
        elif isinstance(reg, dict) and reg.get("base_url"):
            wm.byok_form_local_mode = 'CUSTOM'
            wm.byok_form_local_custom_base = reg.get("base_url", "")
            wm.byok_form_local_custom_model = reg.get("model_id", "") or ""
    except Exception as exc:
        logger.debug("Local dialog prefill failed: %s", exc)
    if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
        local_provider.refresh_detected_async()


# ---------------------------------------------------------------------------
# Status helpers (draw-time; cheap reads only)
# ---------------------------------------------------------------------------

def _model_downloaded(model_id: str) -> bool:
    try:
        from mixar.modules.local_models.core import runtime
        return runtime.model_files_present(model_id)
    except Exception:
        return False

def _selected_model_id(wm) -> str:
    model_id = getattr(wm, 'byok_form_local_model', 'NONE') or 'NONE'
    return "" if model_id == 'NONE' else model_id


def managed_status(wm):
    """(text, icon, is_error) for the managed status line."""
    if getattr(wm, 'mixar_local_dl_active', False):
        if getattr(wm, 'mixar_local_dl_file', '') == 'extract':
            return (n_("Unpacking the local AI runtime…"), 'SORTTIME', False)
        pct = getattr(wm, 'mixar_local_dl_pct', 0)
        return (iface_("Downloading — {percent}%").format(percent=pct), 'IMPORT', False)
    model_id = _selected_model_id(wm)
    if not model_id:
        return (n_("Choose a model"), 'INFO', False)
    if getattr(wm, 'mixar_local_server_model', '') == model_id:
        state = getattr(wm, 'mixar_local_server_state', '')
        if state == 'ready':
            return (n_("Running"), 'CHECKMARK', False)
        if state in ('spawning', 'waiting_health'):
            return (n_("Starting… (a big model can take a few minutes)"),
                    'SORTTIME', False)
        if state in ('crashed', 'failed'):
            error = getattr(wm, 'mixar_local_last_error', '')
            return (rpt_(error) if error else n_("The local server stopped"), 'ERROR', True)
    if _model_downloaded(model_id):
        return (n_("Downloaded — not running"), 'INFO', False)
    return (n_("Not downloaded"), 'INFO', False)


def _server_busy_with(wm, model_id: str) -> bool:
    return (
        getattr(wm, 'mixar_local_server_model', '') == model_id
        and getattr(wm, 'mixar_local_server_state', '')
        in ('spawning', 'waiting_health', 'ready')
    )


# ---------------------------------------------------------------------------
# Drawing (called from MIXAR_BYOK_OT_open_dialog._draw_form)
# ---------------------------------------------------------------------------

def _pill(line, operator_id, text, kind=S.SECONDARY):
    props = S.button(S.sized(line, S.text_width(line, kind, text) + 2 * S.BUTTON_PAD),
                     operator_id, text, kind)
    S.gap(line, S.GAP)
    return props


def draw_local_fields(area, wm) -> None:
    """Local branch of the form, inside the right column's flexible area
    (`byok_provider_settings_ui.LOCAL_FIELDS_HEIGHT` reserves its room)."""
    modes = S.row(area, S.CHIP_H, left=S.RIGHT_INSET, packed=True)
    for ident, name, _desc in LOCAL_MODE_ITEMS:
        label = iface_(name)
        chip = S.sized(modes, S.text_width(modes, S.CHIP, label) + 2 * S.CHIP_PAD)
        chip.prop_enum(wm, 'byok_form_local_mode', ident, text=label)
        S.tag(chip, S.CHIP, lit=getattr(wm, 'byok_form_local_mode', 'MANAGED') == ident)
    S.sep(area, S.GAP)

    if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
        _draw_custom(area, wm)
    else:
        _draw_managed(area, wm)

    S.sep(area, S.GAP)
    for line in (n_("Runs entirely on this computer."),
                 n_("Your prompts leave it only through Mixar's agent orchestration.")):
        S.label(S.row(area, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), line, S.NOTE)


def _draw_managed(area, wm) -> None:
    S.label(S.row(area, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), n_("Model"), S.NOTE)
    S.dropdown(S.row(area, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN),
               wm, 'byok_form_local_model')

    text, _icon, is_error = managed_status(wm)
    S.label(S.row(area, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), text,
            S.DANGER_TEXT if is_error else S.NOTE, translate=False)
    S.sep(area, S.GAP)

    model_id = _selected_model_id(wm)
    buttons = S.row(area, S.BUTTON_H, left=S.RIGHT_INSET, packed=True)
    if getattr(wm, 'mixar_local_dl_active', False):
        _pill(buttons, "mixar_local.cancel_download", iface_("Cancel Download"))
    elif not model_id:
        buttons.enabled = False
        S.label(buttons, n_("Choose a model"), S.NOTE)
    elif not _model_downloaded(model_id):
        _pill(buttons, "mixar_local.download_model", iface_("Download")).model_id = model_id
    elif _server_busy_with(wm, model_id):
        _pill(buttons, "mixar_local.stop_server", iface_("Stop"))
    else:
        _pill(buttons, "mixar_local.start_server", iface_("Start")).model_id = model_id
        _pill(buttons, "mixar_local.remove_model", iface_("Delete Download"),
              S.DANGER_BUTTON).model_id = model_id


def _draw_custom(area, wm) -> None:
    S.label(S.row(area, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), n_("Detected local apps"), S.NOTE)
    detect = S.row(area, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
    S.dropdown(detect, wm, 'byok_form_local_detected')
    S.gap(detect, S.GAP)
    rescan = S.sized(detect, S.FIELD_H)
    S.button(rescan, MIXAR_BYOK_OT_local_rescan.bl_idname, "", S.SECONDARY, icon='FILE_REFRESH')

    for text, prop in ((n_("Base URL"), 'byok_form_local_custom_base'),
                       (n_("Model"), 'byok_form_local_custom_model'),
                       (n_("API Key (optional)"), 'byok_form_local_custom_key')):
        S.label(S.row(area, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), text, S.NOTE)
        S.input_field(S.row(area, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), wm, prop,
                      activate=(prop == 'byok_form_local_custom_key'
                                and key_prompt.focus_is(key_prompt.FOCUS_LOCAL_KEY)))


def execute_local(op, wm, on_done):
    """Run the Local save path. Returns the operator result set.

    SAVING is set BEFORE the request starts: a request whose worker cannot
    start answers synchronously (byok_client._run_worker), and its ERROR must
    not be overwritten by a SAVING with nothing in flight."""
    wm.byok_dialog_state = 'SAVING'
    wm.byok_last_error = ''
    ensure_dialog_redraw_pump()
    if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
        started, err = local_provider.save_custom_async(wm, on_done)
    else:
        started, err = local_provider.save_managed(wm, on_done)
    if not started:
        wm.byok_dialog_state = 'ERROR'
        wm.byok_last_error = err or n_("Could not save the local provider.")
        return {'CANCELLED'}
    return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_local_rescan(Operator):
    """Rescan this computer for running local AI apps"""
    bl_idname = "mixar_byok.local_rescan"
    bl_label = "Rescan Local Apps"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        local_provider.refresh_detected_async()
        return {'FINISHED'}


classes = (
    MIXAR_BYOK_OT_local_rescan,
)
