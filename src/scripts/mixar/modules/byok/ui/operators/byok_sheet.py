# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider settings — the sheet kit the dialog's states are built with.

The designer's artboard is a 2x export: 1502 x 969 design px for a
751 x 484.5 UI-px dialog. Everything here is written in those design px
("dp") and converted to layout units in exactly two places — ``units()``
(fixed heights / widths, 40 dp per UI unit) and ``sep()`` (spacers, 12 dp
per separator factor) — so this layout and the C++ painters
(`interface_mixar_sheet.hh`, which keeps the same numbers) never disagree
about a measurement. The dialog itself is an ordinary props dialog opened
with no padding (`wm.mixar_invoke_modal_dialog(sheet=True)`: centred, in the
main window, the island and pill hidden while it is up), so the layout's
edges are the card's edges.

Every primitive degrades to a stock widget on a build whose C++ predates
the sheet painters (`hasattr`-guarded), so the dialog never loses
functionality — it just stops looking like the artboard.
"""

from mixar.modules.common.i18n import n_

# --- The artboard (design px) ---------------------------------------------
WIDTH = 1502
HEIGHT = 969
HEADER = 182            # title block; the divider is drawn at its foot
SIDEBAR = 442           # provider column width, divider at its right edge
FOOTER = 76             # the sidebar's LOCAL MODEL foot
UNIT_DP = 40.0          # one UI unit (20 px at 1x) is 40 design px
SEP_DP = 12.0           # one separator factor is 6 px at 1x

# Blender leaves `columnspace` (8 px = 16 dp) between split columns; the
# split factor puts the left column's edge on the sidebar divider, so the
# right column's layout starts 16 dp past it.
SPLIT_SPACE = 16
SPLIT_FACTOR = (SIDEBAR / 2) / (WIDTH / 2 - SPLIT_SPACE / 2)
RIGHT_X = SIDEBAR + SPLIT_SPACE
RIGHT_MARGIN = WIDTH - 1474.5            # the key field ends 27.5 dp from the edge

# Header: close square at the top right.
CLOSE = 100
CLOSE_TOP = 40
CLOSE_RIGHT = 42

# Captions sit 50 dp under the header divider ("PROVIDERS", "ALL SUPPORTED…").
CAPTION_TOP = 50
CAPTION_H = 48
LEFT_INSET = 66                          # sidebar text / pill edge
RIGHT_INSET = 501 - RIGHT_X              # chips and the right caption at x=501
PROMPT_INSET = 515 - RIGHT_X             # the key prompt at x=515

# Provider rows: 59 dp pills from x=66 to 379, starting 333 dp from the top.
ROW_H = 59
ROW_RIGHT = SIDEBAR - 379
ROW_TEXT_X = 28                          # the name sits 28 dp inside the pill
ROW_MIN_RIGHT = 16                       # a wide pill stops short of the divider
CAPTION_TO_ROWS = 333 - (HEADER + CAPTION_TOP + CAPTION_H)
ROWS_BOTTOM_GAP = 36

# Model chips: 49 dp pills butted in a row, rows 21.5 dp apart from y=334.
CHIP_H = 49
CHIP_PAD = 19
CHIP_GAP_Y = 21.5
CAPTION_TO_CHIPS = 334 - (HEADER + CAPTION_TOP + CAPTION_H)

# The key block at the foot of the right column.
PROMPT_H = 30
NOTE_H = 26
NOTE_TO_INPUT = 31.5
INPUT_H = 81
FIELD_H = 60             # secondary fields (OpenRouter slug, Local custom server)
BUTTON_H = 66
BUTTON_PAD = 36
SAVE_W = 262
DOCK_INSET = 8
BOTTOM = HEIGHT - 938.5  # below the key field
STRIP_H = 44             # one "in use" / error line above the prompt
GAP = 16

# Bright-span marker the caption painter understands (never drawn).
MARK = "\x1f"

# `layout.mixar_sheet*` kinds — values live in rna_ui_api.cc.
TITLE, CLOSE_KIND, CAPTION, PROVIDER_ROW, FOOTER_ROW, CHIP = (
    'TITLE', 'CLOSE', 'CAPTION', 'PROVIDER_ROW', 'FOOTER_ROW', 'CHIP')
PROMPT, NOTE, BODY, DANGER_TEXT = 'PROMPT', 'NOTE', 'BODY', 'DANGER_TEXT'
PRIMARY, SECONDARY, DANGER_BUTTON, INPUT, DROPDOWN = (
    'PRIMARY', 'SECONDARY', 'DANGER_BUTTON', 'INPUT', 'DROPDOWN')

# The active-default flag rides on the card-button restyle (it sets OR
# clears the flag); the sheet tag is applied afterwards and keeps the flag.
_FLAG_KIND = {PRIMARY: 'ACCENT', SECONDARY: 'CARD', DANGER_BUTTON: 'DANGER'}


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def units(dp):
    """Design px -> UI units (`ui_units_x` / `ui_units_y` / `scale_y`)."""
    return dp / UNIT_DP


def sep(column, dp):
    """A vertical spacer of ``dp`` design px in a column. (Blender's separator
    is square: never use it for a wide gap in a row, it makes the row tall.)"""
    if dp > 0:
        column.separator(factor=dp / SEP_DP)


def gap(row, dp):
    """A horizontal spacer of ``dp`` design px in a row: a fixed-width sub-row
    (so the row's height stays its items' height). Blender pins a sub-layout
    to its `ui_units_x` only when a labelled item lands in it while it is
    not expand-aligned — hence the one-space label."""
    if dp > 0:
        sub = row.row(align=True)
        sub.ui_units_x = units(dp)
        sub.alignment = 'LEFT'
        sub.label(text=" ")


def available(layout):
    """True on a build whose C++ paints the sheet."""
    return hasattr(layout, 'mixar_sheet_label')


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def tag(layout, kind, lit=False, extra=0.0):
    """Restyle the item just added to ``layout`` as a sheet element (and pin
    the layout to its `ui_units_x`, see `sized`)."""
    if hasattr(layout, 'mixar_sheet'):
        layout.mixar_sheet(kind=kind, lit=lit, extra=extra)


def label(layout, text, kind=BODY, lit=False, translate=True):
    """Text element. ``translate=False`` for text already built with
    ``iface_`` (formatted strings, catalog names)."""
    if available(layout):
        layout.mixar_sheet_label(text=text, kind=kind, lit=lit, translate=translate)
        return
    row = layout.row()
    if kind in (NOTE, PROMPT, CAPTION):
        row.enabled = False
    if kind == DANGER_TEXT:
        row.alert = True
    row.label(text=text.replace(MARK, ''), translate=translate)


def text_width(layout, kind, text):
    """Width of ``text`` in the painter's face, in design px."""
    if hasattr(layout, 'mixar_sheet_text_width'):
        return 2.0 * layout.mixar_sheet_text_width(kind=kind, text=text)
    return 14.0 * len(text)  # stock-widget fallback: a rough glyph average


def _flag(layout, kind, default):
    """Set or clear the dialog's active-default flag on the last button (the
    native OK/Cancel row stays suppressed while exactly one button holds it)."""
    if hasattr(layout, 'mixar_card_button'):
        layout.mixar_card_button(kind=_FLAG_KIND.get(kind, 'CARD'), active_default=default)


def button(layout, operator_id, text, kind=SECONDARY, default=False, docked=False,
           icon='NONE'):
    """Operator button drawn as a sheet pill. ``docked`` nests the pill in the
    field before it (8 dp breathing room). Returns the operator properties."""
    props = layout.operator(operator_id, text=text, icon=icon)
    _flag(layout, kind, default)
    tag(layout, kind, extra=1.0 if docked else 0.0)
    return props


def dismiss(layout, text, kind=SECONDARY, default=False, docked=False):
    """A button that only closes the dialog: a ``template_popup_confirm``
    cancel button, so closing runs the operator's ``cancel()`` secret wipe
    exactly like Esc. Nothing on a build without the template."""
    if not hasattr(layout, 'template_popup_confirm'):
        return
    layout.template_popup_confirm("", text="", cancel_text=text)
    _flag(layout, kind, default)
    tag(layout, kind, extra=1.0 if docked else 0.0)


def choice(layout, operator_id, text, kind, lit, provider="", model=""):
    """A pickable row / chip: `mixar_byok.pick` with the choice it makes."""
    props = layout.operator(operator_id, text=text)
    if provider:
        props.provider = provider
    if model:
        props.model = model
    tag(layout, kind, lit=lit)


def input_field(layout, data, prop, docked_w=0.0, activate=False):
    """The key field. ``docked_w`` (dp) is the width of the control that
    follows in the same row; the field's backdrop runs underneath it.
    ``activate`` starts it in edit mode when the dialog opens (the chat's
    key-missing card: the user types at once)."""
    if activate:
        layout.activate_init = True
    layout.prop(data, prop, text="")
    tag(layout, INPUT, extra=docked_w)


def dropdown(layout, data, prop):
    layout.prop(data, prop, text="")
    tag(layout, DROPDOWN)


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def row(parent, h_dp, left=0.0, right=0.0, packed=False, align=None):
    """A row ``h_dp`` tall with ``left`` / ``right`` dp of margin. ``packed``
    keeps the items at their own widths, left-aligned (chips); ``align``
    ('RIGHT') packs them at the other end."""
    outer = parent.row(align=True)
    outer.scale_y = units(h_dp)
    gap(outer, left)
    inner = outer.row(align=True)
    if packed:
        inner.alignment = 'LEFT'
    elif align:
        inner.alignment = align
    gap(outer, right)
    return inner


def row_right(layout, text):
    """The right margin of a provider pill: the artboard's 63 dp, shrunk
    until a long name keeps the same 28 dp of pill on both sides, but never
    closer than 16 dp to the divider (then the painter ellipsises)."""
    need = text_width(layout, PROVIDER_ROW, text) + 2 * ROW_TEXT_X
    return min(ROW_RIGHT, max(ROW_MIN_RIGHT, SIDEBAR - LEFT_INSET - need))


def fixed(parent, h_dp):
    """A column of exactly ``h_dp`` design px, so what follows it lands on
    the artboard's line whatever is drawn inside."""
    col = parent.column(align=True)
    col.ui_units_y = units(h_dp)
    return col


def sized(parent, w_dp):
    """A sub-row of exactly ``w_dp`` design px for one item (a chip, a pill).
    Add the item through a primitive here (`choice`, `button`, `dismiss`,
    `input_field`): Blender only pins a sub-layout to its `ui_units_x` when a
    labelled item lands in it while it is not expand-aligned, so the
    `mixar_sheet` tag pins the layout itself (rna_ui_api.cc)."""
    sub = parent.row(align=True)
    sub.ui_units_x = units(w_dp)
    return sub


def caption(parent, text, left):
    label(row(parent, CAPTION_H, left=left), text, CAPTION)


def bright(text):
    """Mark ``text`` as the bright span of a caption."""
    return MARK + text + MARK


def chip_rows(layout, items, avail_dp):
    """Wrap ``(id, label)`` chips into rows of the artboard's butted pills."""
    rows, current, used = [], [], 0.0
    for item_id, item_label in items:
        w = text_width(layout, CHIP, item_label) + 2 * CHIP_PAD
        if current and used + w > avail_dp:
            rows.append(current)
            current, used = [], 0.0
        current.append((item_id, item_label, w))
        used += w
    if current:
        rows.append(current)
    return rows


def chips_height(n_rows):
    return n_rows * CHIP_H + max(0, n_rows - 1) * CHIP_GAP_Y


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

class Geometry:
    """Column heights for one draw. The sheet is the artboard's 969 dp unless
    the sidebar's rows or the right column's content need more; both columns
    always end on the same line, so the key field sits at the bottom and the
    Local Model foot hugs the card's corner."""

    def __init__(self, n_rows, chips_need, bottom):
        # Sidebar: caption, rows, breathing room, then the foot.
        rows_need = CAPTION_TOP + CAPTION_H + CAPTION_TO_ROWS + n_rows * ROW_H + ROWS_BOTTOM_GAP
        left_body = max(HEIGHT - HEADER - FOOTER, rows_need)
        # Right column: caption, the flexible area, the key block.
        self.fixed_top = CAPTION_TOP + CAPTION_H + CAPTION_TO_CHIPS
        right_need = self.fixed_top + chips_need + bottom
        body = max(left_body + FOOTER, HEIGHT - HEADER, right_need)
        self.left_body = body - FOOTER
        self.right = body
        self.area = body - self.fixed_top - bottom
        self.bottom = bottom
        self.height = HEADER + body


def key_block_height(extra_rows_dp=0.0):
    """Height of the prompt + note + field block at the foot of the column."""
    return PROMPT_H + NOTE_H + extra_rows_dp + NOTE_TO_INPUT + INPUT_H + BOTTOM


def action_block_height():
    """Height of a bare action row at the foot (recap states, Local)."""
    return NOTE_TO_INPUT + INPUT_H + BOTTOM


# Translators: the hidden close button's label (the painter draws a cross).
CLOSE_GLYPH = "✕"
DONE_TEXT = n_("Done")
