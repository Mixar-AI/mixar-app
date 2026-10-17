# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider Settings dialog — card-styled rendering.

Draws the BYOK dialog with the profile menu's design language: the
account-card text/pill/divider painters (``layout.mixar_card_label``),
its action-button variants (``layout.mixar_card_button``) and the
``mixar_section`` / ``mixar_dropdown`` / ``mixar_input`` widget family.
Every primitive degrades to stock Blender widgets on a build whose C++
predates them, so the dialog never loses functionality.

The one-action contract (the fix for the redundant Save + OK buttons):
the dialog draws its own footer and always marks exactly one button as
the active default. ``wm_block_dialog_create`` only appends its
automatic OK/Cancel pair when the block has no active-default button,
so the native row disappears and Return triggers the primary action.
Dialog-closing buttons (Cancel / Done) are ``template_popup_confirm``
cancel buttons: closing through them runs the dialog operator's
``cancel()``, which wipes transient secrets — same as Esc.

State machine lives on WindowManager (see ui/properties/byok_props.py);
operators and async flow live in byok_ops.py. This module only draws.
"""

from mixar.modules.common.i18n import iface_, n_, rpt_

from ...core import catalog_labels, key_prompt, model_suggestions
from .byok_dialog_chrome import (  # re-exported: callers use byok_dialog_ui.<name>
    ACTION_SCALE_Y,
    DIVIDER_SCALE_Y,
    ERROR_WRAP_CHARS,
    FIELD_SCALE_Y,
    HEADER_SCALE_Y,
    lookup_model_label,
    lookup_provider_label,
    _wrap,
    card_divider,
    card_label,
    dismiss_button,
    field_dropdown,
    field_input,
    field_label,
    op_button,
    section,
    section_title,
    style_last_button,
)

# Operator idnames as literals — byok_ops imports this module for its
# draw() body, so importing the classes back would be circular.
# The in-app help button opens the BYOK section of the published docs
# (mixie-frontend src/pages/docsByok.ts, section id "your-own-provider").
BYOK_GUIDE_URL = "https://www.mixar.app/docs#your-own-provider"

OP_SAVE = "mixar_byok.save"
OP_USE_KEY = "mixar_byok.use_key"
OP_FORGET_KEY = "mixar_byok.forget_stored_key"
OP_REQUEST_REMOVE = "mixar_byok.request_remove"
OP_CANCEL_REMOVE = "mixar_byok.cancel_remove"
OP_CONFIRM_REMOVE = "mixar_byok.confirm_remove"
# The Codex browse operator lives in byok_codex_ops (with the branch's
# drawing), the Local ones in byok_local_ops.


# ---------------------------------------------------------------------------

def draw_dialog(layout, wm):
    """Entry point — byok_ops.MIXAR_BYOK_OT_open_dialog.draw() delegates here."""
    layout.use_property_split = False
    layout.use_property_decorate = False
    state = wm.byok_dialog_state

    col = layout.column()
    _draw_header(col, wm, state)

    if state == 'CONFIRM_REMOVE':
        _draw_current_config(col, wm, with_remove=False)
        col.separator(factor=0.6)
        _draw_remove_warning(col)
        _footer_confirm_remove(layout)
        return

    if state == 'REMOVING':
        _draw_current_config(col, wm, with_remove=False)
        _footer_busy(layout, n_("Removing your key…"))
        return

    if state == 'SAVED':
        _draw_saved_body(col, wm)
        _footer_done(layout)
        return

    if state == 'REMOVED':
        _draw_removed_body(col)
        _footer_done(layout)
        return

    # IDLE / SAVING / ERROR — the form states. A failed save or remove
    # leaves the stored key in place, so the active config stays visible.
    key_missing = _device_key_missing(wm)
    if wm.byok_is_active:
        _draw_current_config(col, wm, with_remove=(state == 'IDLE'))
        col.separator(factor=0.6)
    if key_missing:
        # Active for the account, but this device holds no key (the server
        # keeps metadata only): ask for the key, keep provider/model as saved.
        _draw_device_key_notice(col, wm)
        col.separator(factor=0.6)
    elif _key_paused(wm):
        # The island's Mixie half paused the key: the server holds nothing,
        # this computer holds the key. Name it; saving below replaces it.
        _draw_paused_notice(col, wm, with_actions=(state == 'IDLE'))
        col.separator(factor=0.6)
    _draw_form(col, wm, disabled=(state == 'SAVING'), key_only=key_missing)
    if state == 'ERROR' and wm.byok_last_error:
        _draw_error(col, wm)

    if state == 'SAVING':
        # Validation is one network round-trip to the provider (a Codex probe
        # can take several seconds), so set the expectation rather than let the
        # pill look stuck.
        card_label(col, n_("This can take a few seconds."), 'MUTED')
        _footer_busy(layout, n_("Validating with your provider…"))
    else:
        _footer_save(layout, state)


def _draw_header(col, wm, state):
    row = col.row()
    heading = row.row()
    heading.scale_y = HEADER_SCALE_Y
    card_label(heading, n_("AI Provider Settings"), 'HEADING')

    pill = row.row()
    pill.scale_y = HEADER_SCALE_Y
    active = wm.byok_is_active and state != 'REMOVED'
    if active and _device_key_missing(wm):
        pill_text = n_("Key needed on this device")
    elif not active and state != 'REMOVED' and _key_paused(wm):
        pill_text = n_("Paused")
    else:
        pill_text = n_("Active") if active else n_("Not configured")
    card_label(pill, pill_text, 'PILL')

    # Help: open the published BYOK guide in the browser.
    guide = row.row()
    guide.scale_y = HEADER_SCALE_Y
    guide.alignment = 'RIGHT'
    guide.operator("wm.url_open", text=n_("Guide"), icon='HELP',
                   emboss=False).url = BYOK_GUIDE_URL

    card_label(
        col,
        n_("Use your own AI provider. While it is on, Agent chats do not use "
           "Mixar credits."),
        'MUTED',
    )
    card_divider(col)


def _draw_current_config(col, wm, with_remove):
    box = section(col)
    bcol = box.column()
    section_title(bcol, n_("Current Configuration"))
    bcol.separator(factor=0.4)

    provider_label = lookup_provider_label(wm.byok_current_provider)
    model_label = lookup_model_label(wm.byok_current_provider, wm.byok_current_model)
    _value_row(bcol, n_("Provider"), provider_label)
    _value_row(bcol, n_("Model"), model_label)
    if model_suggestions.is_codex(wm.byok_current_provider):
        _value_row(bcol, n_("Account"), wm.byok_key_preview or n_("ChatGPT subscription"))
    else:
        _value_row(bcol, n_("API Key"), wm.byok_key_preview or n_("Stored securely"))

    if not wm.byok_current_supports_vision:
        bcol.separator(factor=0.3)
        card_label(
            bcol,
            n_("Text-only model — chat works; 3D tasks run without visual feedback."),
            'MUTED',
        )

    if with_remove:
        # The destructive action lives beside the thing it removes, not
        # in the footer where it competed with Save.
        bcol.separator(factor=0.55)
        rrow = bcol.row()
        rrow.scale_y = 1.4
        op_button(rrow, OP_REQUEST_REMOVE, n_("Remove key…"), 'DANGER')


def _value_row(col, label, value):
    row = col.split(factor=0.28)
    row.scale_y = 1.1
    card_label(row, label, 'MUTED')
    row.label(text=value)


def _device_key_missing(wm) -> bool:
    """Active server-side, but this device holds no usable key (the server
    keeps metadata only — see core/key_store). Absent on older mirrors.
    A dialog opened from the chat's key-missing card is in this state by
    definition (`core/key_prompt`): the server just refused a keyless turn."""
    if key_prompt.is_open():
        return True
    return bool(wm.byok_is_active and getattr(wm, 'byok_device_key_missing', False))


def _key_paused(wm) -> bool:
    """Inactive for the account, but this computer still holds the key the
    island's Mixie half paused (`credential_state.byok_key_resumable`)."""
    return bool(not wm.byok_is_active and getattr(wm, 'byok_key_resumable', False))


def _draw_paused_notice(col, wm, with_actions):
    from ...core import credential_state

    provider, model = credential_state.resume_target()
    box = section(col)
    bcol = box.column()
    card_label(bcol, n_("Your key is paused — Mixie is answering"), 'SECTION')
    bcol.separator(factor=0.25)
    card_label(
        bcol,
        iface_("Saved on this computer: {provider} · {model}").format(
            provider=lookup_provider_label(provider),
            model=lookup_model_label(provider, model)),
        'MUTED',
    )
    card_label(bcol, n_("Pick one of its models from the model chip in the chat bar to switch back. Saving a key below replaces it."),
               'MUTED')
    if with_actions:
        bcol.separator(factor=0.55)
        row = bcol.row(align=True)
        row.scale_y = 1.4
        op_button(row, OP_USE_KEY, n_("Use my key"), 'CARD')
        op_button(row, OP_FORGET_KEY, n_("Forget saved key"), 'DANGER')


def _draw_device_key_notice(col, wm):
    box = section(col)
    bcol = box.column()
    if model_suggestions.is_codex(wm.byok_current_provider):
        card_label(bcol, n_("Codex sign-in needed on this device"), 'DANGER')
        bcol.separator(factor=0.25)
        card_label(bcol, n_("Run  codex login  on this computer, then save below."), 'MUTED')
    else:
        card_label(bcol, n_("Enter your API key to continue"), 'DANGER')
        bcol.separator(factor=0.25)
        card_label(bcol, n_("Your provider and model are already set — just paste the key."), 'MUTED')
    card_label(
        bcol,
        n_("Your key is stored only on this computer. Mixar never keeps it."),
        'MUTED',
    )


def _draw_form(col, wm, disabled, key_only=False):
    box = section(col)
    bcol = box.column()
    section_title(bcol, n_("Provider Setup"))

    body = bcol.column()
    body.enabled = not disabled
    body.separator(factor=0.45)

    provider_col = body.column()
    provider_col.enabled = not key_only
    field_label(provider_col, n_("Provider"))
    field_dropdown(provider_col, wm, 'byok_form_provider')
    body.separator(factor=0.45)

    if model_suggestions.is_openrouter(wm.byok_form_provider):
        _draw_openrouter_fields(body, wm, key_only)
    elif model_suggestions.is_codex(wm.byok_form_provider):
        from . import byok_codex_ops
        byok_codex_ops.draw_codex_fields(body, wm, key_only)
    elif model_suggestions.is_local(wm.byok_form_provider):
        from . import byok_local_ops
        byok_local_ops.draw_local_fields(body, wm)
    else:
        _draw_cloud_fields(body, wm, key_only)


def _model_column(body, key_only):
    """The model row — locked in the key-only state (kept as saved)."""
    col = body.column()
    col.enabled = not key_only
    return col


def _draw_cloud_fields(body, wm, key_only=False):
    model_col = _model_column(body, key_only)
    field_label(model_col, n_("Model"))
    field_dropdown(model_col, wm, 'byok_form_model')
    body.separator(factor=0.45)
    field_label(body, n_("API Key"))
    field_input(body, wm, 'byok_form_api_key', activate=key_prompt.focus_is(key_prompt.FOCUS_KEY))
    body.separator(factor=0.5)
    card_label(
        body,
        n_("Stored only on this computer. Mixar never keeps a copy. You will see "
           "a masked preview after saving."),
        'MUTED',
    )


def _draw_openrouter_fields(body, wm, key_only=False):
    model_col = _model_column(body, key_only)
    field_label(model_col, n_("Model"))
    field_input(model_col, wm, 'byok_form_openrouter_model')
    body.separator(factor=0.45)
    field_label(body, n_("API Key"))
    field_input(body, wm, 'byok_form_api_key', activate=key_prompt.focus_is(key_prompt.FOCUS_KEY))
    body.separator(factor=0.5)
    card_label(
        body,
        n_("Pick a model that can use tools — the agent needs it. Most current "
           "models can."),
        'DANGER',
    )
    card_label(
        body,
        n_("Any slug from openrouter.ai/models, e.g. anthropic/claude-opus-4.8."),
        'MUTED',
    )


def _draw_error(col, wm):
    col.separator(factor=0.55)
    box = section(col)
    bcol = box.column()
    card_label(bcol, n_("Couldn't save"), 'DANGER')
    bcol.separator(factor=0.25)
    # Static messages are stored as msgids; formatted ones arrive translated.
    for line in _wrap(rpt_(wm.byok_last_error), ERROR_WRAP_CHARS):
        card_label(bcol, line, 'MUTED')


def _draw_remove_warning(col):
    box = section(col)
    bcol = box.column()
    card_label(bcol, n_("Remove your key?"), 'DANGER')
    bcol.separator(factor=0.25)
    card_label(bcol, n_("The agent will use Mixar's models again."), 'MUTED')
    card_label(bcol, n_("Agent chats will use Mixar credits again."), 'MUTED')


def _draw_saved_body(col, wm):
    box = section(col)
    bcol = box.column()
    section_title(bcol, n_("Saved"))
    bcol.separator(factor=0.25)
    card_label(
        bcol,
        n_("You are set. Agent chats now run on your own provider."),
        'MUTED',
    )
    col.separator(factor=0.6)
    _draw_current_config(col, wm, with_remove=False)


def _draw_removed_body(col):
    box = section(col)
    bcol = box.column()
    section_title(bcol, n_("Key removed"))
    bcol.separator(factor=0.25)
    card_label(bcol, n_("The agent uses Mixar's models again."), 'MUTED')
    card_label(bcol, n_("Agent chats use Mixar credits again."), 'MUTED')


# ---------------------------------------------------------------------------
# Footers — every state renders exactly one primary (active-default) action
# ---------------------------------------------------------------------------

def _footer_save(layout, state):
    layout.separator(factor=0.9)
    row = layout.row(align=True)
    row.scale_y = ACTION_SCALE_Y
    dismiss_button(row, n_("Cancel"), 'GHOST')
    label = n_("Try Again") if state == 'ERROR' else n_("Save")
    op_button(row, OP_SAVE, label, 'ACCENT', default=True)


def _footer_busy(layout, text):
    layout.separator(factor=0.9)
    row = layout.row()
    row.scale_y = ACTION_SCALE_Y
    sub = row.row()
    sub.enabled = False
    # A disabled button-as-progress-pill: it keeps the primary-action
    # slot (and the active-default flag that suppresses the native OK
    # row) while the async request runs; Return does nothing on it.
    op_button(sub, OP_SAVE, text, 'ACCENT', default=True)


def _footer_confirm_remove(layout):
    layout.separator(factor=0.9)
    row = layout.row(align=True)
    row.scale_y = ACTION_SCALE_Y
    # Keeping the key is the safe default — Return backs out.
    op_button(row, OP_CANCEL_REMOVE, n_("Keep my key"), 'CARD', default=True)
    op_button(row, OP_CONFIRM_REMOVE, n_("Remove key"), 'DANGER')


def _footer_done(layout):
    layout.separator(factor=0.9)
    row = layout.row()
    row.scale_y = ACTION_SCALE_Y
    dismiss_button(row, n_("Done"), 'ACCENT', default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
