# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Leaf UI-chrome for the AI Provider Settings dialog.

The profile-card painters (``layout.mixar_card_label`` / ``mixar_card_button`` /
``mixar_section`` / ``mixar_dropdown`` / ``mixar_input``) and the inline word-wrap,
each degrading to a stock Blender widget on a build whose C++ predates them.
Split out of ``byok_dialog_ui`` to keep that file under the 500-line limit; it
re-exports these names, so callers still reach them as ``byok_dialog_ui.<name>``.
This module holds no dialog state or logic — only drawing primitives.
"""

from mixar.modules.common.ui.constants import (
    CARD_ROW_CTA,
    CARD_ROW_DIVIDER,
    CARD_ROW_FIELD,
    CARD_ROW_HEADING,
)
from mixar.modules.common.i18n import n_

from ...core import catalog_labels

# Row heights (uiLayout.scale_y). Match chrome ``card_row_*``.
HEADER_SCALE_Y = CARD_ROW_HEADING
FIELD_SCALE_Y = CARD_ROW_FIELD
ACTION_SCALE_Y = CARD_ROW_CTA
DIVIDER_SCALE_Y = CARD_ROW_DIVIDER

# Word-wrap width for inline error text (Blender labels don't wrap).
ERROR_WRAP_CHARS = 72

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


def field_input(col, data, prop, activate=False):
    """Tall styled text input row. Returns the row for trailing buttons.
    ``activate`` starts the field in edit mode when the dialog opens (the
    key-missing card's "Enter key": the user types at once)."""
    row = col.row(align=True)
    row.scale_y = FIELD_SCALE_Y
    if activate:
        row.activate_init = True
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
