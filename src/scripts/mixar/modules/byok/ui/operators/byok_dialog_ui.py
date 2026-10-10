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

from mixar.modules.common.ui.constants import (
    CARD_ROW_CTA,
    CARD_ROW_DIVIDER,
    CARD_ROW_FIELD,
    CARD_ROW_HEADING,
)

from mixar.modules.common.i18n import iface_, n_, rpt_

from ...core import catalog_labels, model_suggestions

# Row heights (uiLayout.scale_y). Match chrome ``card_row_*``.
# Footer actions use the CTA recipe (1.7), not the profile action rows (1.9).
HEADER_SCALE_Y = CARD_ROW_HEADING
FIELD_SCALE_Y = CARD_ROW_FIELD
ACTION_SCALE_Y = CARD_ROW_CTA
DIVIDER_SCALE_Y = CARD_ROW_DIVIDER

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

# Header close button (U+2715): dismisses through the cancel path.
CLOSE_GLYPH = "\u2715"


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


def dismiss_button(layout, text=n_("Cancel"), kind='GHOST', default=False):
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
# Catalog label lookups (raw IDs only as a fallback) — shared with the picker
# menu's BYOK note, so they live bpy-free in `core/catalog_labels`.
# ---------------------------------------------------------------------------

lookup_provider_label = catalog_labels.lookup_provider_label
lookup_model_label = catalog_labels.lookup_model_label


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

    # IDLE / SAVING / ERROR — the two-column provider form.
    from . import byok_provider_settings_ui
    byok_provider_settings_ui.draw_form(col, layout, wm, state)


def _draw_header(col, wm, state):
    row = col.row()
    heading = row.row()
    heading.scale_y = HEADER_SCALE_Y
    card_label(heading, n_("AI Provider settings"), 'HEADING')
    if state not in ('SAVING', 'REMOVING'):
        # The close button: a cancel-path dismiss, so Esc and this both
        # wipe transient secrets. Busy states keep the dialog until the
        # request lands.
        close = row.row()
        close.alignment = 'RIGHT'
        close.scale_x = 1.4
        close.scale_y = HEADER_SCALE_Y
        dismiss_button(close, CLOSE_GLYPH, 'DANGER')

    card_label(
        col,
        n_("Use Mixar with your own provider — you won't be charged Mixar credits."),
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
        op_button(rrow, OP_REQUEST_REMOVE, n_("Remove API Key…"), 'DANGER')


def _value_row(col, label, value):
    row = col.split(factor=0.28)
    row.scale_y = 1.1
    card_label(row, label, 'MUTED')
    row.label(text=value)


def _draw_error(col, wm):
    col.separator(factor=0.55)
    box = section(col)
    bcol = box.column()
    card_label(bcol, n_("Couldn't apply your changes"), 'DANGER')
    bcol.separator(factor=0.25)
    # Static messages are stored as msgids; formatted ones arrive translated.
    for line in _wrap(rpt_(wm.byok_last_error), ERROR_WRAP_CHARS):
        card_label(bcol, line, 'MUTED')


def _draw_remove_warning(col):
    box = section(col)
    bcol = box.column()
    card_label(bcol, n_("Switch back to Mixie?"), 'DANGER')
    bcol.separator(factor=0.25)
    card_label(bcol, n_("This removes your saved API key; the agent runs on Mixie again."), 'MUTED')
    card_label(bcol, n_("Mixar credits will be charged for future agent requests."), 'MUTED')


def _draw_saved_body(col, wm):
    box = section(col)
    bcol = box.column()
    section_title(bcol, n_("Saved"))
    bcol.separator(factor=0.25)
    card_label(
        bcol,
        n_("The Mixar agent now runs on your provider — Mixar credits are "
           "not charged."),
        'MUTED',
    )
    col.separator(factor=0.6)
    _draw_current_config(col, wm, with_remove=False)


def _draw_removed_body(col):
    box = section(col)
    bcol = box.column()
    section_title(bcol, n_("API key removed"))
    bcol.separator(factor=0.25)
    card_label(bcol, n_("The agent is back on Mixie, Mixar's hosted models."), 'MUTED')
    card_label(bcol, n_("Mixar credits are charged for agent requests again."), 'MUTED')


# ---------------------------------------------------------------------------
# Footers — every state renders exactly one primary (active-default) action
# ---------------------------------------------------------------------------

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
    op_button(row, OP_CANCEL_REMOVE, n_("Keep My Key"), 'CARD', default=True)
    op_button(row, OP_CONFIRM_REMOVE, n_("Remove API Key"), 'DANGER')


def _footer_done(layout):
    layout.separator(factor=0.9)
    row = layout.row()
    row.scale_y = ACTION_SCALE_Y
    dismiss_button(row, n_("Done"), 'ACCENT', default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
