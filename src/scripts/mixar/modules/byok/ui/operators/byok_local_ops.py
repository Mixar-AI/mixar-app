# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local (this computer) branch of the AI Provider dialog.

Split out of byok_ops.py (500-line rule): the dialog form
(``byok_dialog_ui._draw_form``) and the Save operator dispatch here when
the selected provider is ``local``. Drawing uses the shared card
primitives from ``byok_dialog_ui`` so the branch matches the rest of the
dialog. Data + save orchestration live in ``byok/core/local_provider.py``;
the managed download/start/stop operators live in
``modules/local_models/ui/operators/local_models_ops.py`` — this file
only draws and validates.
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import local_provider
from . import byok_dialog_ui

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
            return ("Unpacking the local AI runtime…", 'SORTTIME', False)
        pct = getattr(wm, 'mixar_local_dl_pct', 0)
        return (f"Downloading — {pct}%", 'IMPORT', False)
    model_id = _selected_model_id(wm)
    if not model_id:
        return ("Choose a model", 'INFO', False)
    if getattr(wm, 'mixar_local_server_model', '') == model_id:
        state = getattr(wm, 'mixar_local_server_state', '')
        if state == 'ready':
            return ("Running", 'CHECKMARK', False)
        if state in ('spawning', 'waiting_health'):
            return ("Starting… (a big model can take a few minutes)",
                    'SORTTIME', False)
        if state in ('crashed', 'failed'):
            error = getattr(wm, 'mixar_local_last_error', '')
            return (error or "The local server stopped", 'ERROR', True)
    if _model_downloaded(model_id):
        return ("Downloaded — not running", 'INFO', False)
    return ("Not downloaded", 'INFO', False)


def _server_busy_with(wm, model_id: str) -> bool:
    return (
        getattr(wm, 'mixar_local_server_model', '') == model_id
        and getattr(wm, 'mixar_local_server_state', '')
        in ('spawning', 'waiting_health', 'ready')
    )


# ---------------------------------------------------------------------------
# Drawing (called from MIXAR_BYOK_OT_open_dialog._draw_form)
# ---------------------------------------------------------------------------

def draw_local_fields(body, wm) -> None:
    """Local branch of the dialog form. ``body`` is the card section's
    inner column from ``byok_dialog_ui._draw_form``."""
    mode_row = body.row(align=True)
    mode_row.prop(wm, 'byok_form_local_mode', expand=True)
    body.separator(factor=0.45)

    if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
        _draw_custom(body, wm)
    else:
        _draw_managed(body, wm)

    body.separator(factor=0.5)
    byok_dialog_ui.card_label(
        body,
        "Runs entirely on this computer — your prompts never leave it "
        "except through Mixar's agent orchestration.",
        'MUTED',
    )


def _draw_managed(body, wm) -> None:
    byok_dialog_ui.field_label(body, "Model")
    byok_dialog_ui.field_dropdown(body, wm, 'byok_form_local_model')

    text, _icon, is_error = managed_status(wm)
    byok_dialog_ui.card_label(body, text, 'DANGER' if is_error else 'MUTED')
    body.separator(factor=0.35)

    model_id = _selected_model_id(wm)
    buttons = body.row(align=True)
    buttons.scale_y = 1.4
    if getattr(wm, 'mixar_local_dl_active', False):
        byok_dialog_ui.op_button(
            buttons, "mixar_local.cancel_download", "Cancel Download", 'CARD')
    elif not model_id:
        buttons.enabled = False
        buttons.label(text="")
    elif not _model_downloaded(model_id):
        props = byok_dialog_ui.op_button(
            buttons, "mixar_local.download_model", "Download", 'CARD')
        props.model_id = model_id
    elif _server_busy_with(wm, model_id):
        byok_dialog_ui.op_button(buttons, "mixar_local.stop_server", "Stop", 'CARD')
    else:
        props = byok_dialog_ui.op_button(
            buttons, "mixar_local.start_server", "Start", 'CARD')
        props.model_id = model_id
        props = byok_dialog_ui.op_button(
            buttons, "mixar_local.remove_model", "Delete Download", 'DANGER')
        props.model_id = model_id


def _draw_custom(body, wm) -> None:
    byok_dialog_ui.field_label(body, "Detected local apps")
    detect_row = byok_dialog_ui.field_dropdown(body, wm, 'byok_form_local_detected')
    detect_row.operator(MIXAR_BYOK_OT_local_rescan.bl_idname,
                        text="", icon='FILE_REFRESH')
    body.separator(factor=0.45)

    byok_dialog_ui.field_label(body, "Base URL")
    byok_dialog_ui.field_input(body, wm, 'byok_form_local_custom_base')
    body.separator(factor=0.45)
    byok_dialog_ui.field_label(body, "Model")
    byok_dialog_ui.field_input(body, wm, 'byok_form_local_custom_model')
    body.separator(factor=0.45)
    byok_dialog_ui.field_label(body, "API Key (optional)")
    byok_dialog_ui.field_input(body, wm, 'byok_form_local_custom_key')
    body.separator(factor=0.5)

    byok_dialog_ui.card_label(
        body,
        "Any OpenAI-compatible server on this computer — Ollama, "
        "LM Studio, llama.cpp…",
        'MUTED',
    )


# ---------------------------------------------------------------------------
# Save (dispatched from MIXAR_BYOK_OT_save)
# ---------------------------------------------------------------------------
# There is deliberately no poll-side gating any more: save_managed /
# save_custom_async validate everything themselves and return a message
# the ERROR state shows verbatim ("Start the local model first…"), which
# beats a silently disabled Save button.

def execute_local(op, wm, on_done):
    """Run the Local save path. Returns the operator result set."""
    if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
        started, err = local_provider.save_custom_async(wm, on_done)
    else:
        started, err = local_provider.save_managed(wm, on_done)
    if not started:
        wm.byok_dialog_state = 'ERROR'
        wm.byok_last_error = err or "Could not save the local provider."
        return {'CANCELLED'}
    wm.byok_dialog_state = 'SAVING'
    wm.byok_last_error = ''
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
