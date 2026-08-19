# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local (this computer) branch of the AI Provider dialog.

Split out of byok_ops.py (500-line rule): the dialog's ``_draw_form`` /
Save operator dispatch here when the selected provider is ``local``.
Data + save orchestration live in ``byok/core/local_provider.py``; the
managed download/start/stop operators live in
``modules/local_models/ui/operators/local_models_ops.py`` — this file
only draws and validates.
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import local_provider

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

def draw_local_fields(dialog, box, col, wm) -> None:
    mode_row = col.row(align=True)
    mode_row.prop(wm, 'byok_form_local_mode', expand=True)
    col.separator(factor=0.45)

    if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
        _draw_custom(dialog, box, col, wm)
    else:
        _draw_managed(dialog, box, col, wm)

    box.separator(factor=0.55)
    note = box.column(align=True)
    note.enabled = False
    note.label(
        text="Runs entirely on this computer — your prompts never leave it",
        icon='LOCKED',
    )
    note.label(text="except through Mixar's agent orchestration.")


def _draw_managed(dialog, box, col, wm) -> None:
    dialog._draw_tall_prop(col, wm, 'byok_form_local_model', "Model")

    text, icon, is_error = managed_status(wm)
    status = col.row()
    status.alert = is_error
    status.label(text=text, icon=icon)
    col.separator(factor=0.35)

    model_id = _selected_model_id(wm)
    buttons = col.row(align=True)
    buttons.scale_y = 1.35
    if getattr(wm, 'mixar_local_dl_active', False):
        buttons.operator("mixar_local.cancel_download",
                         text="Cancel Download", icon='CANCEL')
    elif not model_id:
        buttons.enabled = False
        buttons.label(text="")
    elif not _model_downloaded(model_id):
        props = buttons.operator("mixar_local.download_model",
                                 text="Download", icon='IMPORT')
        props.model_id = model_id
    elif _server_busy_with(wm, model_id):
        buttons.operator("mixar_local.stop_server", text="Stop", icon='PAUSE')
    else:
        props = buttons.operator("mixar_local.start_server",
                                 text="Start", icon='PLAY')
        props.model_id = model_id
        remove = buttons.row(align=True)
        remove.alert = True
        props = remove.operator("mixar_local.remove_model",
                                text="", icon='TRASH')
        props.model_id = model_id


def _draw_custom(dialog, box, col, wm) -> None:
    label_row = col.row()
    label_row.enabled = False
    label_row.label(text="Detected local apps")
    detect_row = col.row(align=True)
    detect_row.scale_y = 1.45
    detect_row.prop(wm, 'byok_form_local_detected', text="")
    detect_row.operator(MIXAR_BYOK_OT_local_rescan.bl_idname,
                        text="", icon='FILE_REFRESH')
    col.separator(factor=0.45)

    dialog._draw_tall_prop(col, wm, 'byok_form_local_custom_base', "Base URL")
    dialog._draw_tall_prop(col, wm, 'byok_form_local_custom_model', "Model")
    dialog._draw_tall_prop(col, wm, 'byok_form_local_custom_key',
                           "API Key (optional)")

    hint = box.row()
    hint.enabled = False
    hint.label(
        text="Any OpenAI-compatible server on this computer — Ollama, "
             "LM Studio, llama.cpp…",
        icon='INFO',
    )


# ---------------------------------------------------------------------------
# Save (dispatched from MIXAR_BYOK_OT_save)
# ---------------------------------------------------------------------------

def poll_local(wm) -> bool:
    """Save is possible: managed → the selected model's server is healthy;
    custom → base URL + model filled in."""
    if getattr(wm, 'byok_form_local_mode', 'MANAGED') == 'CUSTOM':
        return bool(
            (getattr(wm, 'byok_form_local_custom_base', '') or '').strip()
            and (getattr(wm, 'byok_form_local_custom_model', '') or '').strip()
        )
    model_id = _selected_model_id(wm)
    if not model_id:
        return False
    try:
        from mixar.modules.local_models.core import server_supervisor
        current = server_supervisor.current()
        return bool(
            server_supervisor.is_healthy()
            and current and current.get("model_id") == model_id
        )
    except Exception:
        return False


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
