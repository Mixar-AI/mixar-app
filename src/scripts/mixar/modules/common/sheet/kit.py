# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sheet kit: the framed two-column card dialog AI Provider settings
(`byok`) and Connect MCP (`mcp_bridge`) are built with.

Measured in design px (2x: a 1440 dp sheet is 720 UI px wide), from the
designer's artboard tightened to the Agent island's proportions; its text
follows Mixar's text roles in the C++ painter, not artboard px. Everything here is written in those design px
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

import textwrap

from mixar.modules.common.i18n import n_

# --- The artboard (design px) ---------------------------------------------
WIDTH = 1440
HEIGHT = 700
HEADER = 140            # title block; the divider is drawn at its foot
SIDEBAR = 400           # provider column width, divider at its right edge
FOOTER = 64             # the sidebar's Local model row and its bottom margin
UNIT_DP = 40.0          # one UI unit (20 px at 1x) is 40 design px
SEP_DP = 12.0           # one separator factor is 6 px at 1x

# Blender leaves `columnspace` (8 px = 16 dp) between split columns; the
# split factor puts the left column's edge on the sidebar divider, so the
# right column's layout starts 16 dp past it.
SPLIT_SPACE = 16
SPLIT_FACTOR = (SIDEBAR / 2) / (WIDTH / 2 - SPLIT_SPACE / 2)
RIGHT_X = SIDEBAR + SPLIT_SPACE
RIGHT_MARGIN = 28                        # the key field ends 28 dp from the edge

# Header: close square at the top right.
CLOSE = 60
CLOSE_TOP = 38
CLOSE_RIGHT = 38

# Captions sit CAPTION_TOP dp under the header divider ("PROVIDERS", "ALL SUPPORTED…").
CAPTION_TOP = 36
CAPTION_H = 34
LEFT_INSET = 66                          # sidebar text / pill edge
RIGHT_INSET = 43                         # chips and the right caption, from the column edge
PROMPT_INSET = 57                        # the key prompt, from the column edge

# Provider rows: ROW_H dp plates from x=LEFT_INSET to ROW_RIGHT short of the divider.
ROW_H = 46
ROW_RIGHT = 60                           # a plate stops 60 dp short of the divider
ROW_TEXT_X = 20                          # the name sits 20 dp inside the plate
ROW_MIN_RIGHT = 16                       # a wide pill stops short of the divider
CAPTION_TO_ROWS = 14
ROWS_BOTTOM_GAP = 28

# Model chips: CHIP_H dp pills butted in a row, rows CHIP_GAP_Y dp apart.
CHIP_H = 40
CHIP_PAD = 16
CHIP_GAP_Y = 12
CAPTION_TO_CHIPS = 14

# The key block at the foot of the right column.
PROMPT_H = 34
NOTE_H = 30
NOTE_TO_INPUT = 20
INPUT_H = 64
FIELD_H = 52             # secondary fields (OpenRouter slug, Local custom server)
BUTTON_H = 52
BUTTON_PAD = 32
SAVE_W = 230
DOCK_INSET = 6
BOTTOM = 30              # below the key field
STRIP_H = 40             # one "in use" / error line above the prompt
GAP = 14

# Snippet: a monospace code block on the key field's backdrop.
SNIPPET_LINE_H = 28
SNIPPET_PAD_X = 22
SNIPPET_PAD_Y = 18
SNIPPET_COLUMNS = 72     # wrap width on a build without the painters
# Switch: a track and knob, its label after SWITCH_GAP.
SWITCH_W = 45
SWITCH_GAP = 16
# Status dot: a STATUS_DOT dp disc, the line's text STATUS_GAP after it.
STATUS_DOT = 11
STATUS_GAP = 16

# Bright-span marker the caption painter understands (never drawn).
MARK = "\x1f"

# `layout.mixar_sheet*` kinds — values live in rna_ui_api.cc.
TITLE, CLOSE_KIND, CAPTION, PROVIDER_ROW, FOOTER_ROW, CHIP = (
    'TITLE', 'CLOSE', 'CAPTION', 'PROVIDER_ROW', 'FOOTER_ROW', 'CHIP')
PROMPT, NOTE, BODY, DANGER_TEXT = 'PROMPT', 'NOTE', 'BODY', 'DANGER_TEXT'
PRIMARY, SECONDARY, DANGER_BUTTON, INPUT, DROPDOWN = (
    'PRIMARY', 'SECONDARY', 'DANGER_BUTTON', 'INPUT', 'DROPDOWN')
SNIPPET, SWITCH, STATUS_DOT_KIND = 'SNIPPET', 'SWITCH', 'STATUS_DOT'

# FOOTER_ROW glyphs (the tag's ``extra``): Local model's monitor, a terminal.
FOOT_MONITOR, FOOT_TERMINAL = 0.0, 1.0
# Status dot colours: lit green, danger, dim.
STATUS_ON, STATUS_DANGER, STATUS_DIM = 'ON', 'DANGER', 'DIM'
# A pill's docked payload: inside the field before it (full height), or in
# the top-right corner of a taller block (a snippet), at its own height.
DOCK_FIELD, DOCK_CORNER = 1.0, 2.0

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


# Blender truncates every sized slot to whole px; a measured label gets this
# much room on top so the painter never ellipsises it by a rounding pixel.
TEXT_SLACK = 4.0


def text_width(layout, kind, text):
    """Width of ``text`` in the painter's face, in design px."""
    if hasattr(layout, 'mixar_sheet_text_width'):
        return 2.0 * layout.mixar_sheet_text_width(kind=kind, text=text) + TEXT_SLACK
    return 14.0 * len(text)  # stock-widget fallback: a rough glyph average


def _flag(layout, kind, default):
    """Set or clear the dialog's active-default flag on the last button (the
    native OK/Cancel row stays suppressed while exactly one button holds it)."""
    if hasattr(layout, 'mixar_card_button'):
        layout.mixar_card_button(kind=_FLAG_KIND.get(kind, 'CARD'), active_default=default)


def button(layout, operator_id, text, kind=SECONDARY, default=False, docked=False,
           icon='NONE'):
    """Operator button drawn as a sheet pill. ``docked`` nests the pill in the
    field before it (DOCK_INSET dp breathing room). ``text`` is already translated
    (``iface_``), so Blender must not translate it again. Returns the operator
    properties."""
    props = layout.operator(operator_id, text=text, icon=icon, translate=False)
    _flag(layout, kind, default)
    tag(layout, kind, extra=DOCK_FIELD if docked else 0.0)
    return props


def dismiss(layout, text, kind=SECONDARY, default=False, docked=False):
    """A button that only closes the dialog: a ``template_popup_confirm``
    cancel button, so closing runs the operator's ``cancel()`` secret wipe
    exactly like Esc. Nothing on a build without the template."""
    if not hasattr(layout, 'template_popup_confirm'):
        return
    layout.template_popup_confirm("", text="", cancel_text=text, translate=False)
    _flag(layout, kind, default)
    tag(layout, kind, extra=DOCK_FIELD if docked else 0.0)


def choice(layout, operator_id, text, kind, lit, extra=0.0, **choice_props):
    """A pickable row / chip: a pick operator with the choice it makes
    (``provider=`` / ``model=`` for `mixar_byok.pick`; empty values are left
    unset). ``extra`` is the kind's payload (FOOTER_ROW: FOOT_MONITOR /
    FOOT_TERMINAL). ``text`` is a catalog name or already-translated text:
    never translated here."""
    props = layout.operator(operator_id, text=text, translate=False)
    for name, value in choice_props.items():
        if value:
            setattr(props, name, value)
    tag(layout, kind, lit=lit, extra=extra)


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


def switch(layout, operator_id, text, on):
    """A toggle drawn as a switch: track and knob (green while ``on``) with
    ``text`` (already translated) after it; the whole slot is the button.
    Returns the operator properties. Stock fallback: a checkbox glyph."""
    if not available(layout):
        return layout.operator(operator_id, text=text, translate=False, emboss=False,
                               icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT')
    slot = sized(layout, SWITCH_W + SWITCH_GAP + text_width(layout, SWITCH, text))
    props = slot.operator(operator_id, text=text, translate=False)
    tag(slot, SWITCH, lit=on)
    return props


def status_dot(layout, state):
    """The disc leading a status line: STATUS_ON (green), STATUS_DANGER or
    STATUS_DIM; the line's text follows STATUS_GAP after it. Stock
    fallback: the matching icon."""
    if not available(layout):
        icons = {STATUS_ON: 'CHECKMARK', STATUS_DANGER: 'ERROR'}
        layout.label(text="", icon=icons.get(state, 'TIME'))
        return
    slot = sized(layout, STATUS_DOT + STATUS_GAP)
    slot.mixar_sheet_label(text="", kind=STATUS_DOT_KIND, lit=state == STATUS_ON,
                           extra=1.0 if state == STATUS_DANGER else 0.0, translate=False)


# ---------------------------------------------------------------------------
# Snippet (code block)
# ---------------------------------------------------------------------------

def snippet_columns(layout, width_dp):
    """Characters per line that fit ``width_dp`` of snippet text room: the
    monospace face's measured advance (SNIPPET_COLUMNS without the painters)."""
    if not hasattr(layout, 'mixar_sheet_text_width'):
        return SNIPPET_COLUMNS
    sample = "0" * 32
    advance = max(1.0, (text_width(layout, SNIPPET, sample) - TEXT_SLACK) / len(sample))
    # One column of headroom for the painter's whole-px rounding.
    return max(16, int(width_dp / advance) - 1)


def wrap_code(text, columns):
    """Hard-wrap code at ``columns``: a continuation is indented four past its
    line's own indent, and a long token (a path) breaks anywhere."""
    lines = []
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        lines += textwrap.wrap(line, columns, subsequent_indent=" " * (indent + 4),
                               break_long_words=True, break_on_hyphens=False) or [""]
    return lines


def snippet_height(n_lines):
    """The code block's height: its lines and padding, never under a field's."""
    return max(INPUT_H, 2 * SNIPPET_PAD_Y + n_lines * SNIPPET_LINE_H)


def snippet_dock_width(layout, text):
    """Width of the corner-docked pill's slot: label, padding, inset. A plain
    label like every other sheet pill — a stock glyph ahead of it outgrew
    the measured slot and ellipsised "Copy" to "C…"."""
    return text_width(layout, SECONDARY, text) + BUTTON_PAD + DOCK_INSET


def snippet(parent, lines, left=0.0, right=0.0, dock=None):
    """A code block of ``lines`` (see `wrap_code`) in the monospace face on
    the key field's backdrop, `snippet_height` tall. ``dock`` =
    ``(operator_id, text)`` docks a secondary pill in the box's
    top-right corner — DOCK_INSET in from its top and right edges and
    BUTTON_H tall however many lines the box holds; the box's text stops
    short of it. Returns that pill's operator properties (None without a
    dock). Stock fallback: a box of labels and a plain button under it."""
    if not available(parent):
        box = parent.box().column(align=True)
        for line in lines:
            box.label(text=line, translate=False)
        if dock is None:
            return None
        return parent.row().operator(dock[0], text=dock[1], translate=False, icon='COPYDOWN')
    height = snippet_height(len(lines))
    line = row(parent, height, left=left, right=right)
    dock_w = snippet_dock_width(line, dock[1]) if dock is not None else 0.0
    # The backdrop runs under the docked column (the tag's payload).
    line.mixar_sheet_label(text="\n".join(lines), kind=SNIPPET, extra=dock_w, translate=False)
    if dock is None:
        return None
    side = line.column(align=True)
    side.ui_units_x = units(dock_w)
    top = side.row(align=True)
    # Row scales multiply through nested layouts: relative to the block's.
    top.scale_y = (DOCK_INSET + BUTTON_H) / height
    props = top.operator(dock[0], text=dock[1], translate=False)
    _flag(top, SECONDARY, False)
    tag(side, SECONDARY, extra=DOCK_CORNER)   # also pins the column to its width
    return props


def wrap(layout, kind, text, width_dp):
    """Word-wrap ``text`` into lines that fit ``width_dp`` in ``kind``'s face
    (labels never wrap on their own). One line on a build without the
    painters: nothing measures there, and a stock label clips by itself."""
    if not hasattr(layout, 'mixar_sheet_text_width'):
        return [text] if text else []
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and text_width(layout, kind, candidate) > width_dp:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


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
    """The right margin of a provider pill: the artboard's ROW_RIGHT, shrunk
    until a long name keeps ROW_TEXT_X of pill on both sides, but never
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


def caption(parent, text, left, translate=True):
    """A right-column caption; it stops RIGHT_MARGIN short of the card's edge,
    where the painter ellipsises a long translation."""
    label(row(parent, CAPTION_H, left=left, right=RIGHT_MARGIN), text, CAPTION,
          translate=translate)


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
    """Column heights for one draw. The sheet is the artboard's HEIGHT unless
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
