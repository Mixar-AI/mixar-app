# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider Settings — the two-column form (IDLE / SAVING / ERROR).

Left column: the provider list (catalog providers, then OpenRouter and
Codex), with Local Model pinned to the foot. Right column: every model the
selected provider supports as a pickable chip, then the credential field
for that model and the one primary action. The recap and confirm states
stay in ``byok_dialog_ui``; this module only draws the form states.

Rows are native enum-item buttons bound to the existing form properties
(``byok_form_provider`` / ``byok_form_model``), restyled with the shared
Cinema popup row painter, so picking a provider runs the same update
callback the old dropdown did and Save reads the same fields.
"""

from mixar.modules.common.i18n import iface_, n_

from ...constants import LOCAL_PROVIDER_ID
from ...core import model_suggestions
from . import byok_dialog_ui as ui

# Left column share of the dialog width (design: 730 of 1502).
PROVIDER_COLUMN_FACTOR = 0.36
# Model chips per row in the right column.
MODEL_COLUMNS = 3
PROVIDER_ROW_SCALE_Y = 1.6

# Literal idname: byok_pick_ops is loaded by auto-discovery, not imported here.
OP_PICK = "mixar_byok.pick"
MODEL_ROW_SCALE_Y = 1.5


def _cinema_row(layout, active):
    """Graded pill for the current choice, plain text for the others."""
    if hasattr(layout, 'mixar_cinema_row'):
        layout.mixar_cinema_row(kind='ACTIVE' if active else 'OPTION')


def _choice(layout, text, active, scale_y, provider="", model="", icon='NONE'):
    """One pickable row: an operator button so the Cinema row painter
    (which styles plain buttons only) can draw it."""
    row = layout.row()
    row.scale_y = scale_y
    props = row.operator(OP_PICK, text=text, icon=icon)
    if provider:
        props.provider = provider
    if model:
        props.model = model
    _cinema_row(row, active)


def _sidebar_providers():
    """Provider rows for the left column; Local has its own footer button."""
    return [item for item in model_suggestions.get_provider_items()
            if not model_suggestions.is_local(item[0])]


def provider_label(provider_id):
    for pid, label, _desc in model_suggestions.get_provider_items():
        if pid == provider_id:
            return label
    return ui.lookup_provider_label(provider_id)


def model_label(provider_id, model_id):
    for mid, label, _desc in model_suggestions.get_model_items(provider_id):
        if mid == model_id:
            return label
    return ui.lookup_model_label(provider_id, model_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def draw_form(col, layout, wm, state):
    """Two-column body plus footer for the form states."""
    if wm.byok_is_active and state != 'ERROR':
        _draw_active_strip(col, wm, with_remove=(state == 'IDLE'))

    split = col.split(factor=PROVIDER_COLUMN_FACTOR)
    split.enabled = state != 'SAVING'
    _draw_provider_column(split.column(), wm)
    _draw_detail_column(split.column(), wm)

    if state == 'ERROR' and wm.byok_last_error:
        ui._draw_error(col, wm)

    if state == 'SAVING':
        ui._footer_busy(layout, n_("Validating with provider…"))
    else:
        _footer_save(layout, state)


def _draw_active_strip(col, wm, with_remove):
    """One line naming the key in use, with its Remove action beside it."""
    row = col.row()
    text = iface_("In use: {provider} · {model} · {key}").format(
        provider=ui.lookup_provider_label(wm.byok_current_provider),
        model=ui.lookup_model_label(wm.byok_current_provider, wm.byok_current_model),
        key=wm.byok_key_preview or iface_("key stored securely"),
    )
    ui.card_label(row, text, 'MUTED')
    if with_remove:
        sub = row.row()
        sub.scale_y = 1.2
        ui.op_button(sub, ui.OP_REQUEST_REMOVE, n_("Remove API Key…"), 'DANGER')
    col.separator(factor=0.6)


# ---------------------------------------------------------------------------
# Left column
# ---------------------------------------------------------------------------

def _draw_provider_column(col, wm):
    col.separator(factor=1.2)
    ui.section_title(col, n_("PROVIDERS"))
    col.separator(factor=1.4)
    current = wm.byok_form_provider
    for pid, label, _desc in _sidebar_providers():
        if pid == 'NONE':
            # Loading / empty sentinel: say so instead of offering a row.
            ui.card_label(col, label, 'MUTED')
            continue
        _choice(col, label.upper(), pid == current, PROVIDER_ROW_SCALE_Y, provider=pid)
    col.separator(factor=3.0)
    _choice(col, iface_("LOCAL MODEL"), model_suggestions.is_local(current),
            PROVIDER_ROW_SCALE_Y * 1.15, provider=LOCAL_PROVIDER_ID, icon='DESKTOP')


# ---------------------------------------------------------------------------
# Right column
# ---------------------------------------------------------------------------

def _draw_detail_column(col, wm):
    provider = wm.byok_form_provider
    col.separator(factor=1.2)
    if model_suggestions.is_local(provider):
        ui.section_title(col, n_("LOCAL MODEL ON THIS COMPUTER"))
        col.separator(factor=1.0)
        from . import byok_local_ops
        byok_local_ops.draw_local_fields(col, wm)
        return
    if model_suggestions.is_openrouter(provider):
        _draw_openrouter(col, wm)
        return
    if provider == 'NONE':
        # Catalog still loading (or empty): teach instead of a blank pane.
        ui.section_title(col, n_("MODELS"))
        col.separator(factor=1.0)
        ui.card_label(col, n_("Pick a provider on the left to see its models."), 'MUTED')
        return

    ui.section_title(
        col,
        iface_("ALL SUPPORTED {provider} MODELS").format(
            provider=provider_label(provider).upper()),
    )
    col.separator(factor=1.4)
    _draw_model_chips(col, wm, provider)
    col.separator(factor=3.0)

    if model_suggestions.is_codex(provider):
        _draw_codex(col, wm)
        return

    _key_prompt(col, iface_("Enter API key for {model} here.").format(
        model=model_label(provider, wm.byok_form_model)))
    ui.field_input(col, wm, 'byok_form_api_key')


def _draw_model_chips(col, wm, provider):
    items = [item for item in model_suggestions.get_model_items(provider)
             if item[0] != 'NONE']
    if not items:
        ui.card_label(col, n_("No models available for this provider yet."), 'MUTED')
        return
    current = wm.byok_form_model
    if hasattr(col, 'grid_flow'):
        grid = col.grid_flow(row_major=True, columns=MODEL_COLUMNS,
                             even_columns=True, align=False)
    else:
        grid = col.column()
    for mid, label, _desc in items:
        _choice(grid, label, mid == current, MODEL_ROW_SCALE_Y, model=mid)


def _key_prompt(col, heading):
    ui.card_label(col, heading, 'SECTION')
    ui.card_label(
        col,
        n_("Stored encrypted, used only for Mixar agent requests — only a "
           "masked preview is shown after saving."),
        'MUTED',
    )
    col.separator(factor=0.6)


def _draw_openrouter(col, wm):
    ui.section_title(col, n_("ANY OPENROUTER MODEL"))
    col.separator(factor=1.0)
    ui.field_input(col, wm, 'byok_form_openrouter_model')
    ui.card_label(
        col,
        n_("Any slug from openrouter.ai/models, e.g. anthropic/claude-opus-4.8."),
        'MUTED',
    )
    ui.card_label(
        col,
        n_("Pick a model that supports tool / function calling — the agent needs it."),
        'DANGER',
    )
    col.separator(factor=3.0)
    _key_prompt(col, iface_("Enter your OpenRouter API key here."))
    ui.field_input(col, wm, 'byok_form_api_key')


def _draw_codex(col, wm):
    _key_prompt(col, iface_("Connect your ChatGPT subscription."))
    load_row = col.row()
    load_row.scale_y = 1.4
    ui.op_button(load_row, ui.OP_CODEX_LOAD_FILE, n_("Load from ~/.codex/auth.json"), 'CARD')
    col.separator(factor=0.35)
    ui.field_label(col, n_("…or paste it manually"))
    paste_row = ui.field_input(col, wm, 'byok_form_codex_bundle')
    paste_row.operator(ui.OP_CODEX_PASTE, text="", icon='PASTEDOWN')
    n = len(wm.byok_form_codex_bundle or "")
    ui.card_label(
        col,
        iface_("{count} characters pasted").format(count=n) if n
        else n_("Run  codex login  in a terminal, then load or paste ~/.codex/auth.json."),
        'MUTED',
    )


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

def _footer_save(layout, state):
    """The one primary action; the header's close button dismisses."""
    layout.separator(factor=0.9)
    split = layout.split(factor=PROVIDER_COLUMN_FACTOR)
    split.label(text="")
    row = split.row()
    row.scale_y = ui.ACTION_SCALE_Y
    label = n_("Try Again") if state == 'ERROR' else n_("Save & Activate")
    ui.op_button(row, ui.OP_SAVE, label, 'ACCENT', default=True)


classes = ()
