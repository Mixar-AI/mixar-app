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

from ...core import model_suggestions

# Row heights (uiLayout.scale_y), mirroring the profile card's rhythm
# (`ROW_*` in interface_mixar_profile_card.cc).
HEADER_SCALE_Y = 1.6
FIELD_SCALE_Y = 1.45
ACTION_SCALE_Y = 1.7
DIVIDER_SCALE_Y = 0.6

# Word-wrap width for inline error text (Blender labels don't wrap).
ERROR_WRAP_CHARS = 72

# Operator idnames as literals — byok_ops imports this module for its
# draw() body, so importing the classes back would be circular.
OP_SAVE = "mixar_byok.save"
OP_REQUEST_REMOVE = "mixar_byok.request_remove"
OP_CANCEL_REMOVE = "mixar_byok.cancel_remove"
OP_CONFIRM_REMOVE = "mixar_byok.confirm_remove"
OP_CODEX_LOAD_FILE = "mixar_byok.codex_load_file"
OP_CODEX_PASTE = "mixar_byok.codex_paste"


# ---------------------------------------------------------------------------
# Primitives (profile-card painters, with stock fallbacks)
# ---------------------------------------------------------------------------

def card_label(layout, text, kind='MUTED'):
    """Card-painted text element; falls back to a themed stock label."""
    if hasattr(layout, 'mixar_card_label'):
        layout.mixar_card_label(text=text, kind=kind)
        return
    if kind == 'DIVIDER':
        layout.separator()
        return
    row = layout.row()
    if kind in ('MUTED', 'SECTION', 'META'):
        row.enabled = False
    if kind in ('META', 'PILL'):
        row.alignment = 'RIGHT'
    if kind == 'DANGER':
        row.alert = True
    row.label(text=text)


def card_divider(layout):
    row = layout.row()
    row.scale_y = DIVIDER_SCALE_Y
    card_label(row, "", 'DIVIDER')


def section(layout):
    """Accent-bordered card section; stock box when unavailable."""
    if hasattr(layout, 'mixar_section'):
        return layout.mixar_section()
    return layout.box()


def section_title(col, text):
    card_label(col, text, 'SECTION')


def field_label(col, text):
    row = col.row()
    row.scale_y = 0.9
    card_label(row, text, 'MUTED')


def field_input(col, data, prop):
    """Tall styled text input row. Returns the row for trailing buttons."""
    row = col.row(align=True)
    row.scale_y = FIELD_SCALE_Y
    if hasattr(row, 'mixar_input'):
        row.mixar_input(data, prop, text="")
    else:
        row.prop(data, prop, text="")
    return row


def field_dropdown(col, data, prop):
    """Tall styled enum dropdown row. Returns the row for trailing buttons."""
    row = col.row(align=True)
    row.scale_y = FIELD_SCALE_Y
    if hasattr(row, 'mixar_dropdown'):
        row.mixar_dropdown(data, prop, text="")
    else:
        row.prop(data, prop, text="")
    return row


def style_last_button(layout, kind='CARD', default=False):
    """Restyle the button just added to *layout* as a card action button.

    ``default=True`` also makes it the dialog's default button, which is
    what keeps the native OK/Cancel row suppressed — every rendered
    state must pass it on exactly one button.
    """
    if hasattr(layout, 'mixar_card_button'):
        layout.mixar_card_button(kind=kind, active_default=default)


def op_button(layout, operator_id, text, kind='CARD', default=False):
    """Operator button drawn as a card action button."""
    props = layout.operator(operator_id, text=text)
    style_last_button(layout, kind, default)
    return props


def dismiss_button(layout, text="Cancel", kind='GHOST', default=False):
    """One button that just closes the dialog.

    Built on ``template_popup_confirm`` with no confirm operator: the
    button closes the popup through the dialog's cancel path, so the
    operator's ``cancel()`` wipes transient secrets exactly like Esc.
    ``template_popup_confirm`` hands its button the active-default flag
    when nothing holds it yet; ``style_last_button`` then sets or
    *clears* it to match ``default``, so a later primary action can own
    Return. On builds without the card styling the template's flag is
    left in place — the native OK/Cancel row stays suppressed either way.
    """
    if not hasattr(layout, 'template_popup_confirm'):
        return
    layout.template_popup_confirm("", text="", cancel_text=text)
    style_last_button(layout, kind, default)


# ---------------------------------------------------------------------------
# Catalog label lookups (raw IDs only as a fallback)
# ---------------------------------------------------------------------------

def lookup_provider_label(provider_id):
    for pid, plabel, _desc in model_suggestions.get_provider_items():
        if pid == provider_id:
            return plabel
    return provider_id


def lookup_model_label(provider_id, model_id):
    for mid, mlabel, _desc in model_suggestions.get_model_items(provider_id):
        if mid == model_id:
            return mlabel
    return model_id


def _wrap(text, width):
    """Dumb word-wrap for error rendering (labels don't wrap on their own)."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            if current:
                lines.append(current)
            current = word if len(word) <= width else word[:width]
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


# ---------------------------------------------------------------------------
# Dialog composition
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
        _footer_busy(layout, "Removing your key…")
        return

    if state == 'SAVED':
        _draw_saved_body(col, wm)
        _footer_done(layout)
        return

    if state == 'REMOVED':
        _draw_removed_body(col)
        _footer_done(layout)
        return

    # IDLE / SAVING / ERROR — the form states.
    if wm.byok_is_active and state != 'ERROR':
        _draw_current_config(col, wm, with_remove=(state == 'IDLE'))
        col.separator(factor=0.6)
    _draw_form(col, wm, disabled=(state == 'SAVING'))
    if state == 'ERROR' and wm.byok_last_error:
        _draw_error(col, wm)

    if state == 'SAVING':
        _footer_busy(layout, "Validating with provider…")
    else:
        _footer_save(layout, state)


def _draw_header(col, wm, state):
    row = col.row()
    heading = row.row()
    heading.scale_y = HEADER_SCALE_Y
    card_label(heading, "AI Provider Settings", 'HEADING')

    pill = row.row()
    pill.scale_y = HEADER_SCALE_Y
    active = wm.byok_is_active and state != 'REMOVED'
    card_label(pill, "Active" if active else "Not configured", 'PILL')

    card_label(
        col,
        "Run the Mixar agent on your own provider — Mixar credits are "
        "not charged while active.",
        'MUTED',
    )
    card_divider(col)


def _draw_current_config(col, wm, with_remove):
    box = section(col)
    bcol = box.column()
    section_title(bcol, "Current Configuration")
    bcol.separator(factor=0.4)

    provider_label = lookup_provider_label(wm.byok_current_provider)
    model_label = lookup_model_label(wm.byok_current_provider, wm.byok_current_model)
    _value_row(bcol, "Provider", provider_label)
    _value_row(bcol, "Model", model_label)
    if model_suggestions.is_codex(wm.byok_current_provider):
        _value_row(bcol, "Account", wm.byok_key_preview or "ChatGPT subscription")
    else:
        _value_row(bcol, "API Key", wm.byok_key_preview or "Stored securely")

    if not wm.byok_current_supports_vision:
        bcol.separator(factor=0.3)
        card_label(
            bcol,
            "Text-only model — chat works; 3D tasks run without visual feedback.",
            'MUTED',
        )

    if with_remove:
        # The destructive action lives beside the thing it removes, not
        # in the footer where it competed with Save.
        bcol.separator(factor=0.55)
        rrow = bcol.row()
        rrow.scale_y = 1.4
        op_button(rrow, OP_REQUEST_REMOVE, "Remove API Key…", 'DANGER')


def _value_row(col, label, value):
    row = col.split(factor=0.28)
    row.scale_y = 1.1
    card_label(row, label, 'MUTED')
    row.label(text=value)


def _draw_form(col, wm, disabled):
    box = section(col)
    bcol = box.column()
    section_title(bcol, "Provider Setup")

    body = bcol.column()
    body.enabled = not disabled
    body.separator(factor=0.45)

    field_label(body, "Provider")
    field_dropdown(body, wm, 'byok_form_provider')
    body.separator(factor=0.45)

    if model_suggestions.is_openrouter(wm.byok_form_provider):
        _draw_openrouter_fields(body, wm)
    elif model_suggestions.is_codex(wm.byok_form_provider):
        _draw_codex_fields(body, wm)
    elif model_suggestions.is_local(wm.byok_form_provider):
        from . import byok_local_ops
        byok_local_ops.draw_local_fields(body, wm)
    else:
        _draw_cloud_fields(body, wm)


def _draw_cloud_fields(body, wm):
    field_label(body, "Model")
    field_dropdown(body, wm, 'byok_form_model')
    body.separator(factor=0.45)
    field_label(body, "API Key")
    field_input(body, wm, 'byok_form_api_key')
    body.separator(factor=0.5)
    card_label(
        body,
        "Stored encrypted, used only for Mixar agent requests — only a "
        "masked preview is shown after saving.",
        'MUTED',
    )


def _draw_openrouter_fields(body, wm):
    field_label(body, "Model")
    field_input(body, wm, 'byok_form_openrouter_model')
    body.separator(factor=0.45)
    field_label(body, "API Key")
    field_input(body, wm, 'byok_form_api_key')
    body.separator(factor=0.5)
    card_label(
        body,
        "Pick a model that supports tool / function calling — the agent needs it.",
        'DANGER',
    )
    card_label(
        body,
        "Any slug from openrouter.ai/models, e.g. anthropic/claude-opus-4.8.",
        'MUTED',
    )


def _draw_codex_fields(body, wm):
    field_label(body, "Model")
    field_input(body, wm, 'byok_form_codex_model')
    body.separator(factor=0.45)

    load_row = body.row()
    load_row.scale_y = 1.4
    op_button(load_row, OP_CODEX_LOAD_FILE, "Load from ~/.codex/auth.json", 'CARD')
    body.separator(factor=0.35)

    field_label(body, "…or paste it manually")
    paste_row = field_input(body, wm, 'byok_form_codex_bundle')
    paste_row.operator(OP_CODEX_PASTE, text="", icon='PASTEDOWN')

    n = len(wm.byok_form_codex_bundle or "")
    card_label(
        body,
        f"{n} characters pasted" if n else "Empty — paste your auth.json",
        'MUTED',
    )
    body.separator(factor=0.5)
    for line in (
        "Run  codex login  in your terminal, then load or paste the full",
        "contents of ~/.codex/auth.json (the paste button reads your clipboard).",
        "Uses your ChatGPT subscription — Mixar credits are not charged.",
    ):
        card_label(body, line, 'MUTED')


def _draw_error(col, wm):
    col.separator(factor=0.55)
    box = section(col)
    bcol = box.column()
    card_label(bcol, "Couldn't apply your changes", 'DANGER')
    bcol.separator(factor=0.25)
    for line in _wrap(wm.byok_last_error, ERROR_WRAP_CHARS):
        card_label(bcol, line, 'MUTED')


def _draw_remove_warning(col):
    box = section(col)
    bcol = box.column()
    card_label(bcol, "Remove your API key?", 'DANGER')
    bcol.separator(factor=0.25)
    card_label(bcol, "The agent will use Mixar's default provider again.", 'MUTED')
    card_label(bcol, "Mixar credits will be charged for future agent requests.", 'MUTED')


def _draw_saved_body(col, wm):
    box = section(col)
    bcol = box.column()
    section_title(bcol, "Saved")
    bcol.separator(factor=0.25)
    card_label(
        bcol,
        "The Mixar agent now runs on your provider — Mixar credits are "
        "not charged.",
        'MUTED',
    )
    col.separator(factor=0.6)
    _draw_current_config(col, wm, with_remove=False)


def _draw_removed_body(col):
    box = section(col)
    bcol = box.column()
    section_title(bcol, "API key removed")
    bcol.separator(factor=0.25)
    card_label(bcol, "The agent is back on Mixar's default provider.", 'MUTED')
    card_label(bcol, "Mixar credits are charged for agent requests again.", 'MUTED')


# ---------------------------------------------------------------------------
# Footers — every state renders exactly one primary (active-default) action
# ---------------------------------------------------------------------------

def _footer_save(layout, state):
    layout.separator(factor=0.9)
    row = layout.row(align=True)
    row.scale_y = ACTION_SCALE_Y
    dismiss_button(row, "Cancel", 'GHOST')
    label = "Try Again" if state == 'ERROR' else "Save & Activate"
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
    op_button(row, OP_CANCEL_REMOVE, "Keep My Key", 'CARD', default=True)
    op_button(row, OP_CONFIRM_REMOVE, "Remove API Key", 'DANGER')


def _footer_done(layout):
    layout.separator(factor=0.9)
    row = layout.row()
    row.scale_y = ACTION_SCALE_Y
    dismiss_button(row, "Done", 'ACCENT', default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
